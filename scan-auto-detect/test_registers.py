"""
Quick diagnostic: reads all registers for a given model and prints raw values and parsed results.
Run from the project root.

Usage:
    python test_registers.py <host> <serial> [model]

Models: deye_string (default), deye_micro, deye_hybrid, deye_sg04lp3

Examples:
    python test_registers.py 192.168.1.199 1782317166
    python test_registers.py 192.168.1.50  2304123456 deye_hybrid
"""

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from pysolarmanv5 import PySolarmanV5Async


async def main(host: str, serial: int, model: str):
    definition_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "inverter_definitions", f"{model}.json"
    )
    if not os.path.exists(definition_path):
        print(f"ERROR: model '{model}' not found at {definition_path}")
        print("Available models: deye_string, deye_micro, deye_hybrid, deye_sg04lp3")
        sys.exit(1)

    with open(definition_path) as f:
        definition = json.load(f)

    print(f"Model: {model}  |  Host: {host}  |  Serial: {serial}")

    m = PySolarmanV5Async(
        host, serial, port=8899, mb_slave_id=1,
        auto_reconnect=False, socket_timeout=15,
    )
    await m.connect()

    all_raw: dict[int, int] = {}

    for req in definition["requests"]:
        start = req["start"]
        end = req["end"]
        fc = req.get("mb_functioncode", 3)
        length = end - start + 1
        print(f"\n── Request fc={fc}: registers [{start}–{end}] ({length} regs) ──")
        try:
            if fc == 3:
                data = await m.read_holding_registers(register_addr=start, quantity=length)
            else:
                data = await m.read_input_registers(register_addr=start, quantity=length)
            for i, val in enumerate(data):
                reg = start + i
                all_raw[reg] = val
                if val != 0:
                    print(f"  reg {reg:4d} (0x{reg:04X}) = {val:6d}  (0x{val:04X})")
        except Exception as e:
            print(f"  ERROR: {e}")

    await m.disconnect()

    print("\n\n── Parsed results ──")
    for group in definition["parameters"]:
        for item in group["items"]:
            name = item["name"]
            regs = item["registers"]
            scale = item.get("scale", 1)
            offset = item.get("offset", 0)
            rule = item.get("rule", 1)

            if not all(r in all_raw for r in regs):
                print(f"  {name:<44s} — registers not read")
                continue

            raw = all_raw[regs[0]]

            if "lookup" in item:
                match = next((l["value"] for l in item["lookup"] if l.get("key") == raw), raw)
                print(f"  {name:<44s} raw={raw:6d}  → {match}")
            elif rule == 3 and len(regs) >= 2:
                # 32-bit little-endian: low word + high word * 65536
                raw32 = all_raw[regs[0]] + all_raw.get(regs[1], 0) * 65536
                value = (raw32 - offset) * scale
                unit = item.get("uom", "")
                print(f"  {name:<44s} raw={raw32:10d}  → {value:.2f} {unit}")
            else:
                value = (raw - offset) * scale
                unit = item.get("uom", "")
                print(f"  {name:<44s} raw={raw:6d}  → {value:.2f} {unit}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_registers.py <host> <serial> [model]")
        print("Example: python test_registers.py 192.168.1.199 1782317166")
        print("Example: python test_registers.py 192.168.1.50  2304123456 deye_hybrid")
        sys.exit(1)

    host   = sys.argv[1]
    serial = int(sys.argv[2])
    model  = sys.argv[3] if len(sys.argv) > 3 else "deye_string"
    asyncio.run(main(host, serial, model))
