#!/usr/bin/env python3
"""
SOFAR G3 hybrid register dump (ESI-T1 / HYD 5-20KTL-3PH / ZCS Azzurro 3PH).

READ-ONLY: only Modbus function 0x03 (read holding registers). Nothing is written.

Reads the SOFAR G3 register blocks through a Solarman LSW3 logger and prints,
for every register: address, raw value, signed value and — where known — the
decoded value using the community register map (ha-solarman sofar_g3hyd.yaml).
The output is also saved to a .txt file you can attach to the forum thread.

Requirements:
    pip install pysolarmanv5

Usage:
    python3 sofar_register_dump.py <logger_ip> <logger_serial> [label]

Examples:
    python3 sofar_register_dump.py 192.168.1.50 2712345678 charging
    python3 sofar_register_dump.py 192.168.1.50 2712345678 discharging

Tip: run it once while the battery is charging and once while it is
discharging, and note what the SOFAR app / inverter display shows at the
same moment (SOC, battery W, grid W, PV W, load W, today's kWh).
"""

import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from pysolarmanv5 import PySolarmanV5
except ImportError:
    print("pysolarmanv5 is required:  pip install pysolarmanv5")
    sys.exit(1)

PORT = 8899
SLAVE = 1
MAX_CHUNK = 40  # LSW3 loggers can reject long Modbus reads

# (start, end, description)
BLOCKS = [
    (0x0404, 0x042B, "Inverter status, faults, temperatures"),
    (0x0445, 0x0465, "Serial number, hardware/software versions"),
    (0x0484, 0x04AF, "On-grid: frequency, output, PCC (grid meter), L1/L2/L3"),
    (0x0504, 0x051F, "Off-grid / EPS"),
    (0x0584, 0x058F, "PV strings 1-4"),
    (0x05C4, 0x05C4, "PV total power"),
    (0x0600, 0x0670, "Battery packs + battery totals"),
    (0x0684, 0x069B, "Energy counters (daily / total)"),
]

# Known 16-bit registers: address -> (name, scale, signed, unit)
# scale None = not confirmed yet, please compare with the SOFAR app.
KNOWN = {
    0x0404: ("Inverter status", 1, False, ""),
    0x0418: ("Ambient temperature 1", 1, True, "°C"),
    0x041A: ("Radiator temperature 1", 1, True, "°C"),
    0x0420: ("Module temperature 1", 1, True, "°C"),
    0x0484: ("Grid frequency", 0.01, False, "Hz"),
    0x0485: ("Active power output total", 10, True, "W"),
    0x0486: ("Reactive power output total", 10, True, "var"),
    0x0487: ("Apparent power output total", 10, True, "VA"),
    0x0488: ("Active power PCC total (grid)", 10, True, "W"),
    0x048D: ("Voltage phase R (L1)", 0.1, False, "V"),
    0x048E: ("Current output R (L1)", 0.01, False, "A"),
    0x048F: ("Active power output R (L1)", 10, True, "W"),
    0x0493: ("Active power PCC R (L1)", 10, True, "W"),
    0x0498: ("Voltage phase S (L2)", 0.1, False, "V"),
    0x0499: ("Current output S (L2)", 0.01, False, "A"),
    0x049A: ("Active power output S (L2)", 10, True, "W"),
    0x049E: ("Active power PCC S (L2)", 10, True, "W"),
    0x04A3: ("Voltage phase T (L3)", 0.1, False, "V"),
    0x04A4: ("Current output T (L3)", 0.01, False, "A"),
    0x04A5: ("Active power output T (L3)", 10, True, "W"),
    0x04A9: ("Active power PCC T (L3)", 10, True, "W"),
    0x04AE: ("Active power PV external", 10, False, "W"),
    0x04AF: ("Active power load system", 10, True, "W"),
    0x0504: ("Active power load total EPS", 10, True, "W"),
    0x0584: ("PV1 voltage", 0.1, False, "V"),
    0x0585: ("PV1 current", 0.01, False, "A"),
    0x0586: ("PV1 power", 10, False, "W"),
    0x0587: ("PV2 voltage", 0.1, False, "V"),
    0x0588: ("PV2 current", 0.01, False, "A"),
    0x0589: ("PV2 power", 10, False, "W"),
    0x058A: ("PV3 voltage", 0.1, False, "V"),
    0x058B: ("PV3 current", 0.01, False, "A"),
    0x058C: ("PV3 power", 10, False, "W"),
    0x058D: ("PV4 voltage", 0.1, False, "V"),
    0x058E: ("PV4 current", 0.01, False, "A"),
    0x058F: ("PV4 power", 10, False, "W"),
    0x05C4: ("PV total power", 100, False, "W"),
    0x0604: ("Battery 1 voltage", 0.1, False, "V"),
    0x0605: ("Battery 1 current", 0.01, True, "A"),
    0x0606: ("Battery 1 power", 10, True, "W"),
    0x0607: ("Battery 1 temperature", 1, True, "°C"),
    0x0608: ("Battery 1 SOC", 1, False, "%"),
    0x0609: ("Battery 1 SOH", 1, False, "%"),
    0x060A: ("Battery 1 cycles", 1, False, ""),
    # SOFAR doc: I16, 0.1 kW, positive = charging, negative = discharging
    0x0667: ("Battery total power (+charge/-discharge)", 100, True, "W"),
    0x0668: ("Battery total SOC", 1, False, "%"),
}

# Known 32-bit counters: (high_register, low_register) -> (name, scale, unit)
KNOWN_32 = {
    (0x0684, 0x0685): ("Daily PV generation", 0.01, "kWh"),
    (0x0686, 0x0687): ("Total PV generation", 0.1, "kWh"),
    (0x0688, 0x0689): ("Daily load consumption", 0.01, "kWh"),
    (0x068A, 0x068B): ("Total load consumption", 0.1, "kWh"),
    (0x068C, 0x068D): ("Daily energy bought (import)", 0.01, "kWh"),
    (0x068E, 0x068F): ("Total energy bought (import)", 0.1, "kWh"),
    (0x0690, 0x0691): ("Daily energy sold (export)", 0.01, "kWh"),
    (0x0692, 0x0693): ("Total energy sold (export)", 0.1, "kWh"),
    (0x0694, 0x0695): ("Daily battery charge", 0.01, "kWh"),
    (0x0696, 0x0697): ("Total battery charge", 0.1, "kWh"),
    (0x0698, 0x0699): ("Daily battery discharge", 0.01, "kWh"),
    (0x069A, 0x069B): ("Total battery discharge", 0.1, "kWh"),
}


def signed16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


def fmt_num(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".")


def read_block(m: PySolarmanV5, start: int, end: int) -> dict[int, int] | str:
    regs: dict[int, int] = {}
    addr = start
    while addr <= end:
        count = min(MAX_CHUNK, end - addr + 1)
        last_err = None
        for _ in range(3):
            try:
                values = m.read_holding_registers(register_addr=addr, quantity=count)
                regs.update({addr + i: v for i, v in enumerate(values)})
                last_err = None
                break
            except Exception as e:  # noqa: BLE001 - report any transport/Modbus error
                last_err = e
                time.sleep(1)
        if last_err is not None:
            return f"ERROR reading 0x{addr:04X}-0x{addr + count - 1:04X}: {last_err}"
        addr += count
    return regs


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    host = sys.argv[1]
    serial = int(sys.argv[2])
    label = sys.argv[3] if len(sys.argv) > 3 else "snapshot"

    lines: list[str] = []

    def out(text: str = "") -> None:
        print(text)
        lines.append(text)

    out(f"SOFAR G3 register dump — {datetime.now():%Y-%m-%d %H:%M:%S} — {label}")
    out(f"Logger {host}:{PORT}  serial={serial}  slave={SLAVE}")

    m = PySolarmanV5(host, serial, port=PORT, mb_slave_id=SLAVE, socket_timeout=10)
    all_regs: dict[int, int] = {}
    try:
        for start, end, desc in BLOCKS:
            out()
            out(f"── 0x{start:04X}-0x{end:04X}  {desc} ──")
            result = read_block(m, start, end)
            if isinstance(result, str):
                out(f"  {result}")
                continue
            all_regs.update(result)
            for reg in range(start, end + 1):
                raw = result[reg]
                line = f"  0x{reg:04X} ({reg:5d})  raw={raw:5d}  signed={signed16(raw):6d}"
                if reg in KNOWN:
                    name, scale, is_signed, unit = KNOWN[reg]
                    base = signed16(raw) if is_signed else raw
                    if scale is None:
                        line += f"  {name}: {base} (scale unknown)"
                    else:
                        line += f"  {name}: {fmt_num(base * scale)} {unit}".rstrip()
                out(line)
    finally:
        try:
            m.disconnect()
        except Exception:  # noqa: BLE001
            pass

    out()
    out("── 32-bit energy counters ──")
    for (hi, lo), (name, scale, unit) in KNOWN_32.items():
        if hi in all_regs and lo in all_regs:
            value = ((all_regs[hi] << 16) | all_regs[lo]) * scale
            out(f"  {name:<32s} {fmt_num(value)} {unit}")
        else:
            out(f"  {name:<32s} (not read)")

    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
    out_dir = Path.home() / "Desktop"
    if not out_dir.is_dir():
        out_dir = Path.home()
    path = out_dir / f"sofar_dump_{safe_label}_{datetime.now():%Y%m%d_%H%M%S}.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nSaved to {path}")


if __name__ == "__main__":
    main()
