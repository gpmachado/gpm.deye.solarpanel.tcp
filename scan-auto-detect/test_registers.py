"""
Quick diagnostic: reads all registers for a given model and prints raw values and parsed results.
Run from the project root.

Usage:
    python test_registers.py <host> <serial> [model]

Models: any file in inverter_definitions/ (default deye_string)

Examples:
    python test_registers.py 192.168.1.50 2304123456
    python test_registers.py 192.168.1.50  2304123456 deye_hybrid
"""

import asyncio
import json
import sys
import os

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "lib"))

from pysolarmanv5 import PySolarmanV5Async
from parser import ParameterParser  # the app's own decoder — same rules as on Homey


async def main(host: str, serial: int, model: str):
    definition_path = os.path.join(_PROJECT_ROOT, "inverter_definitions", f"{model}.json")
    if not os.path.exists(definition_path):
        print(f"ERROR: model '{model}' not found at {definition_path}")
        print("Available models:", ", ".join(sorted(
            f[:-5] for f in os.listdir(os.path.dirname(definition_path)) if f.endswith(".json"))))
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
    params = ParameterParser(definition)
    for req in definition["requests"]:
        start, end = req["start"], req["end"]
        if all(r in all_raw for r in range(start, end + 1)):
            params.parse([all_raw[r] for r in range(start, end + 1)], start, end - start + 1)
    values = params.get_result()
    for group in definition["parameters"]:
        for item in group["items"]:
            name = item["name"]
            if name not in values:
                print(f"  {name:<44s} — not read / out of range")
                continue
            raw = [all_raw.get(r) for r in item["registers"]]
            print(f"  {name:<44s} raw={raw}  → {values[name]} {item.get('uom', '')}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_registers.py <host> <serial> [model]")
        print("Example: python test_registers.py 192.168.1.50 2304123456")
        print("Example: python test_registers.py 192.168.1.50  2304123456 deye_hybrid")
        sys.exit(1)

    host   = sys.argv[1]
    serial = int(sys.argv[2])
    model  = sys.argv[3] if len(sys.argv) > 3 else "deye_string"
    asyncio.run(main(host, serial, model))
