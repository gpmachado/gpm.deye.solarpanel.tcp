#!/usr/bin/env bash
# deye_scan_mac.sh — Universal Deye inverter scan (macOS / Linux)
# Supports: deye_string · deye_hybrid · deye_micro · deye_sg04lp3
# Transport: embedded Solarman V5 TCP — no pysolarmanv5 needed
# Auto-discovery: UDP broadcast on port 48899 (leave IP blank to scan)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFS_DIR="$SCRIPT_DIR/inverter_definitions"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo " [ERROR] python3 not found"
  exit 1
fi

echo
echo " ============================================"
echo "  Deye Universal Local Scan"
echo "  String · Hybrid · Micro · SG04LP3"
echo " ============================================"
echo

"$PYTHON_BIN" - "$DEFS_DIR" <<'PY'
import asyncio
import datetime as _dt
import json
import os
import socket
import struct
import sys
import time

DEFS_DIR = sys.argv[1]

PORT    = 8899
SLAVE   = 1
TIMEOUT = 8.0
RETRIES = 3

MODELS = {
    "deye_string":  "String Inverter (2/4 MPPT)",
    "deye_hybrid":  "Hybrid (Battery + 2 MPPT)",
    "deye_micro":   "Microinverter (4 MPPT) — SUN-M/SUN2000G3",
    "deye_sg04lp3": "Hybrid 3-phase — SG04LP3",
}

# ── UDP logger discovery ───────────────────────────────────────────────────────

async def discover_loggers(timeout: float = 3.0) -> list[dict]:
    """Broadcast Solarman discovery payloads, collect IP/MAC/serial replies."""
    DISCOVERY_PORT     = 48899
    DISCOVERY_PAYLOADS = [b"WIFIKIT-214028-READ", b"HF-A11ASSISTHREAD"]
    found: list[dict] = []
    seen:  set[str]   = set()

    loop = asyncio.get_event_loop()

    class _Protocol(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr):
            try:
                parts = data.decode("latin-1").strip().split(",")
                if len(parts) < 3:
                    return
                ip, mac, sn = parts[0].strip(), parts[1].strip(), parts[2].strip()
                if not ip or ip in seen or not sn.isdigit():
                    return
                seen.add(ip)
                found.append({"ip": ip, "mac": mac, "serial": int(sn)})
            except Exception:
                pass
        def error_received(self, exc): pass
        def connection_lost(self, exc):  pass

    try:
        transport, _ = await loop.create_datagram_endpoint(
            _Protocol, local_addr=("0.0.0.0", 0), allow_broadcast=True,
        )
        for payload in DISCOVERY_PAYLOADS:
            transport.sendto(payload, ("<broadcast>", DISCOVERY_PORT))
            await asyncio.sleep(0.1)
        await asyncio.sleep(timeout)
        transport.close()
    except Exception as e:
        print(f" [WARNING] UDP scan error: {e}")

    return found

# ── Tee output ────────────────────────────────────────────────────────────────

class Tee:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._file = open(path, "w", encoding="utf-8")

    def write(self, text=""):
        print(text)
        self._file.write(text + "\n")
        self._file.flush()

    def close(self):
        self._file.close()

# ── SolarmanV5 TCP transport ──────────────────────────────────────────────────

V5_START     = 0xA5
V5_END       = 0x15
V5_CTRL_REQ  = struct.pack("<H", 0x4510)
V5_CTRL_RESP = struct.pack("<H", 0x1510)


def crc16_modbus(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else crc >> 1
    return crc


def v5_checksum(frame):
    return sum(frame[i] & 0xFF for i in range(1, len(frame) - 2)) & 0xFF


def build_v5_frame(serial, seq, modbus_payload):
    payload = bytearray(bytes([0x02]) + bytes(14) + modbus_payload)
    header  = bytearray(
        bytes([V5_START])
        + struct.pack("<H", len(payload))
        + V5_CTRL_REQ
        + struct.pack("<H", seq)
        + struct.pack("<I", serial)
    )
    frame = header + payload + bytearray(2)
    frame[-2] = v5_checksum(frame)
    frame[-1] = V5_END
    return frame


def build_modbus_request(slave, fc, start, count):
    msg = struct.pack(">BBHH", slave, fc, start, count)
    return msg + struct.pack("<H", crc16_modbus(msg))


def parse_v5_response(frame):
    if len(frame) < 29 or frame[0] != V5_START or frame[-1] != V5_END:
        raise ValueError("Invalid V5 frame (%d bytes)" % len(frame))
    modbus = frame[25:-2]
    if len(modbus) < 5:
        raise ValueError("Modbus payload too short: %d bytes" % len(modbus))
    return bytes(modbus)


def parse_modbus_registers(data, count):
    if len(data) < 5:
        raise ValueError("Modbus response too short: %d bytes" % len(data))
    if data[1] & 0x80:
        raise ValueError("Modbus exception code 0x%02x" % data[2])
    byte_count = data[2]
    n = min(count, byte_count // 2)
    if n < count:
        raise ValueError("Short response: got %d/%d registers" % (n, count))
    return [struct.unpack(">H", data[3 + i*2: 5 + i*2])[0] for i in range(n)]


class V5Transport:
    def __init__(self, host, serial):
        self.host = host; self.serial = serial
        self.seq = 0; self.reader = self.writer = None

    async def connect(self):
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, PORT, family=socket.AF_INET),
            timeout=TIMEOUT,
        )

    async def disconnect(self):
        if self.writer:
            try:
                self.writer.close()
                await asyncio.wait_for(self.writer.wait_closed(), timeout=2.0)
            except Exception:
                pass
        self.reader = self.writer = None

    def _next_seq(self):
        self.seq = (self.seq + 1) & 0xFF
        return self.seq

    async def read_registers(self, fc, start, count):
        seq   = self._next_seq()
        req   = build_modbus_request(SLAVE, fc, start, count)
        frame = build_v5_frame(self.serial, seq, req)
        self.writer.write(frame)
        await self.writer.drain()
        resp   = await self._read_v5_frame()
        modbus = parse_v5_response(resp)
        return parse_modbus_registers(modbus, count)

    async def _read_v5_frame(self):
        for _ in range(5):
            header = await asyncio.wait_for(
                self.reader.readexactly(11), timeout=TIMEOUT)
            if header[0] != V5_START:
                raise ValueError("Unexpected V5 start: 0x%02x" % header[0])
            payload_len = struct.unpack("<H", header[1:3])[0]
            rest  = await asyncio.wait_for(
                self.reader.readexactly(payload_len + 2), timeout=TIMEOUT)
            frame = header + rest
            if frame[3:5] == V5_CTRL_RESP:
                return frame
        raise TimeoutError("No V5 data response after 5 frames")


async def read_block(host, serial, fc, start, end, log=None):
    count = end - start + 1
    label = "fc=%d [%d-%d]" % (fc, start, end)
    last_err = None
    for attempt in range(1, RETRIES + 1):
        t = V5Transport(host, serial)
        try:
            await t.connect()
            values = await t.read_registers(fc, start, count)
            await t.disconnect()
            return values
        except Exception as exc:
            last_err = exc
            if log:
                log.write("  %s attempt %d/%d: %s: %s"
                          % (label, attempt, RETRIES, type(exc).__name__, exc))
            await t.disconnect()
            await asyncio.sleep(0.8 * attempt)
    raise last_err

# ── JSON / parser ─────────────────────────────────────────────────────────────

def load_definition(model_id):
    path = os.path.join(DEFS_DIR, model_id + ".json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def lookup_value(value, options):
    for o in options:
        if o["key"] == value:
            return o["value"]
    return str(value)


def parse_sensor(defn, all_regs):
    regs  = defn["registers"]
    rule  = defn.get("rule", 1)
    scale = defn.get("scale", 1)
    for r in regs:
        if r not in all_regs:
            return None, None
    raw = shift = bits = 0
    for r in regs:
        raw  += (all_regs[r] & 0xFFFF) << shift
        shift += 16
        bits  += 16
    if "lookup" in defn:
        return raw, lookup_value(raw, defn["lookup"])
    value = raw
    if "offset" in defn:
        value -= defn["offset"]
    if rule in (2, 4):
        maxint = (1 << bits) - 1
        if value > maxint // 2:
            value -= (maxint + 1)
    value = value * scale
    if "validation" in defn:
        v = defn["validation"]
        if "min" in v and value < v["min"]:
            return raw, None
        if "max" in v and value > v["max"]:
            return raw, None
    if isinstance(value, float) and value == int(value):
        value = int(value)
    elif isinstance(value, float):
        value = round(value, 3)
    return raw, value

# ── Auto-detect model ─────────────────────────────────────────────────────────

async def detect_model(host, serial, log):
    log.write(" Auto-detecting model — probing each type...")
    log.write("")
    best_model, best_score = "deye_string", 0
    for model_id in MODELS:
        try:
            defn = load_definition(model_id)
        except FileNotFoundError:
            continue
        all_regs = {}
        for req in defn["requests"]:
            start, end, fc = req["start"], req["end"], req["mb_functioncode"]
            try:
                values = await asyncio.wait_for(
                    read_block(host, serial, fc, start, end), timeout=10.0)
                for i, v in enumerate(values):
                    all_regs[start + i] = v
            except Exception:
                pass
        score = 0
        for group in defn["parameters"]:
            for sensor in group["items"]:
                _, value = parse_sensor(sensor, all_regs)
                if value is None or value == 0:
                    continue
                score += 2 if sensor.get("uom", "") in ("W", "kWh", "kW") else 1
        log.write("  [%s] score=%d" % (model_id, score))
        if score > best_score:
            best_score = score
            best_model = model_id
        await asyncio.sleep(1.5)
    log.write("")
    if best_score == 0:
        log.write(" ⚠ No live data (night/offline) — defaulting to deye_string")
    else:
        log.write(" ✓ Detected: %s (score=%d)" % (best_model, best_score))
    log.write("")
    return best_model

# ── Output helper ─────────────────────────────────────────────────────────────

def fmt(value, uom=""):
    if value is None:
        return "--"
    if isinstance(value, str):
        return value
    text = ("%.3f" % value).rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
    return (text + (" " + uom if uom else "")).strip()


def add_derived(results, name, value, uom, note):
    results[name] = {"raw": None, "value": value, "uom": uom,
                     "registers": [], "note": note}

# ── Interactive prompts ───────────────────────────────────────────────────────

async def prompt_logger() -> tuple[str, int]:
    """Ask for IP+serial, offering UDP auto-discovery when IP is left blank."""
    print(" Logger IP Address (leave blank to auto-scan): ", end="", flush=True)
    host = input().strip()

    if not host:
        print(" Scanning network for Solarman loggers (UDP broadcast)...", flush=True)
        loggers = await discover_loggers(timeout=3.0)
        if not loggers:
            print(" [ERROR] No loggers found. Enter IP manually.")
            sys.exit(1)
        if len(loggers) == 1:
            lg = loggers[0]
            print(f" Found: {lg['ip']}  MAC:{lg['mac']}  Serial:{lg['serial']}")
            return lg["ip"], lg["serial"]
        # Multiple loggers — let user pick
        print(f" Found {len(loggers)} logger(s):")
        for i, lg in enumerate(loggers, 1):
            print(f"   [{i}] {lg['ip']}  MAC:{lg['mac']}  Serial:{lg['serial']}")
        print(f" Choice [1-{len(loggers)}, default=1]: ", end="", flush=True)
        choice = input().strip() or "1"
        try:
            lg = loggers[int(choice) - 1]
        except (IndexError, ValueError):
            print(" [ERROR] Invalid choice")
            sys.exit(1)
        return lg["ip"], lg["serial"]

    # Manual IP entered — ask for serial
    parts = host.split(".")
    if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        print(f" [ERROR] Invalid IP: {host}")
        sys.exit(1)
    print(" Logger Serial Number: ", end="", flush=True)
    sn_str = input().strip()
    if not sn_str.isdigit():
        print(" [ERROR] Serial must be numeric")
        sys.exit(1)
    return host, int(sn_str)


def prompt_model() -> str:
    print()
    print(" Select model:")
    for i, (mid, mname) in enumerate(MODELS.items(), 1):
        print(f"   [{i}] {mid:<14} — {mname}")
    print(f"   [5] auto-detect   (probe inverter to determine model)")
    print()
    print(" Choice [1-5, default=1]: ", end="", flush=True)
    choice = input().strip() or "1"
    keys = list(MODELS.keys())
    if choice == "5":
        return "auto"
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(keys):
            return keys[idx]
    except ValueError:
        pass
    print(" [ERROR] Invalid choice")
    sys.exit(1)

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    host, serial = await prompt_logger()
    model        = prompt_model()

    stamp   = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_pfx = model if model != "auto" else "deye"
    outfile = os.path.join(os.path.expanduser("~"), "Desktop",
                           f"{out_pfx}_scan_{host}_{stamp}.txt")

    print()
    print(f" Scanning {host}  serial={serial}  model={model}")
    print(f" Output:  {outfile}")
    print()

    log = Tee(outfile)
    started = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        model_id = model
        if model_id == "auto":
            log.write("Deye Universal Scan - %s" % started)
            log.write("Host: %s  Serial: %s" % (host, serial))
            log.write("Transport: embedded Solarman V5 TCP, no pysolarmanv5")
            log.write("=" * 72)
            log.write("")
            model_id = await detect_model(host, serial, log)

        defn       = load_definition(model_id)
        model_name = MODELS.get(model_id, model_id)

        log.write("Deye Universal Scan - %s" % started)
        log.write("Host: %s  Serial: %s  Model: %s" % (host, serial, model_id))
        log.write("Description: %s" % model_name)
        log.write("Transport: embedded Solarman V5 TCP, no pysolarmanv5")
        log.write("=" * 72)
        log.write("")

        # Read all register groups
        all_registers = {}
        for req in defn["requests"]:
            start, end, fc = req["start"], req["end"], req["mb_functioncode"]
            count = end - start + 1
            log.write("Reading fc=%d registers [%d-%d]..." % (fc, start, end))
            try:
                values = await read_block(host, serial, fc, start, end, log)
                for i, v in enumerate(values):
                    all_registers[start + i] = v
                log.write("  OK: %d registers" % count)
            except Exception as exc:
                log.write("  FAILED: %s" % exc)
            await asyncio.sleep(0.3)

        # Raw non-zero registers
        log.write("")
        log.write("Raw registers (non-zero):")
        for reg in sorted(all_registers):
            v = all_registers[reg]
            if v:
                log.write("  reg %5d (0x%04X) = %7d  (0x%04X)" % (reg, reg, v, v))

        # Parse sensors
        results = {}
        for group_def in defn["parameters"]:
            gname = group_def.get("group", "")
            for sensor in group_def["items"]:
                sname = sensor["name"]
                raw, value = parse_sensor(sensor, all_registers)
                if value is not None:
                    results[sname] = {
                        "raw": raw, "value": value,
                        "uom": sensor.get("uom", ""),
                        "registers": sensor["registers"],
                        "note": "", "group": gname,
                    }

        # Derived PV power for string/micro
        if model_id in ("deye_string", "deye_micro"):
            for idx in (1, 2, 3, 4):
                v_val = results.get("PV%d Voltage" % idx, {}).get("value")
                a_val = results.get("PV%d Current" % idx, {}).get("value")
                if v_val is not None and a_val is not None:
                    pwr = round(float(v_val) * float(a_val), 1)
                    add_derived(results, "PV%d Power" % idx, pwr, "W",
                                "derived: PV%d Voltage × PV%d Current" % (idx, idx))
            pv_total = sum(
                results["PV%d Power" % i]["value"]
                for i in (1, 2, 3, 4) if ("PV%d Power" % i) in results
            )
            if pv_total:
                add_derived(results, "PV Power Total", pv_total, "W",
                            "derived: sum of PV1..PV4 Power")

        # Display by group
        log.write("")
        log.write("Parsed values by group:")
        log.write("")
        ordered_names = []
        for group_def in defn["parameters"]:
            gname = group_def.get("group", "")
            expanded = []
            for sensor in group_def["items"]:
                sname = sensor["name"]
                expanded.append(sname)
                for idx in (1, 2, 3, 4):
                    if sname == ("PV%d Current" % idx):
                        pname = "PV%d Power" % idx
                        if pname in results:
                            expanded.append(pname)
            ordered_names.append((gname, expanded))
        for gname_exp in ordered_names:
            if gname_exp[0].lower() in ("solar", "pv", ""):
                if "PV Power Total" in results and "PV Power Total" not in gname_exp[1]:
                    gname_exp[1].append("PV Power Total")
                break

        for gname, sensor_names in ordered_names:
            printed = False
            for sname in sensor_names:
                if sname not in results:
                    continue
                if not printed:
                    log.write("  [%s]" % gname)
                    printed = True
                item = results[sname]
                regs_str = (",".join(str(r) for r in item["registers"])
                            if item["registers"] else "derived")
                raw_str  = "--" if item["raw"] is None else str(item["raw"])
                note     = "  # %s" % item["note"] if item["note"] else ""
                log.write("    %-38s %-16s raw=%-10s regs=%s%s"
                          % (sname + ":", fmt(item["value"], item["uom"]),
                             raw_str, regs_str, note))
            if printed:
                log.write("")

        # Notes
        log.write("Notes:")
        if model_id in ("deye_string", "deye_micro"):
            log.write("  - PV Power is derived (Voltage × Current) — no direct PV power register.")
        if model_id in ("deye_hybrid", "deye_sg04lp3"):
            batt_soc = results.get("Battery SOC", {}).get("value")
            batt_pwr = results.get("Battery Power", {}).get("value")
            if batt_soc is not None:
                log.write("  - Battery SOC = %s%%." % batt_soc)
            if batt_pwr is not None:
                direction = "discharging" if float(batt_pwr) > 0 else "charging" if float(batt_pwr) < 0 else "standby"
                log.write("  - Battery Power = %.1f W (%s)." % (float(batt_pwr), direction))
        log.write("  - Radiator Temperature = -100 C means register 0 (sensor absent).")
        log.write("")
        log.write("Done. File saved to: %s" % outfile)

    finally:
        log.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception as exc:
        print("ERROR: %s: %s" % (type(exc).__name__, exc))
        sys.exit(1)
PY

echo
echo " ============================================"
echo "  Done."
echo " ============================================"
echo
