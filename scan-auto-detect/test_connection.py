#!/usr/bin/env python3
"""
Terminal test script for Deye/Solarman logger connection.
Run: python3 test_connection.py
"""

import asyncio
import json
import os
import sys

HOST   = "192.168.1.199"
SERIAL = 1782317166       # from UDP discovery
PORT   = 8899
SLAVE  = 1
MODEL  = "deye_string"    # change to your model


async def test():
    try:
        from pysolarmanv5 import PySolarmanV5Async
    except ImportError:
        print("Installing pysolarmanv5...")
        os.system(f"{sys.executable} -m pip install pysolarmanv5 -q")
        from pysolarmanv5 import PySolarmanV5Async

    print(f"Connecting to {HOST}:{PORT}  serial={SERIAL}")
    m = PySolarmanV5Async(
        HOST, SERIAL,
        port=PORT,
        mb_slave_id=SLAVE,
        auto_reconnect=False,
        socket_timeout=10,
    )

    try:
        await m.connect()
        print("Connected OK")

        r = await m.read_holding_registers(register_addr=0x0003, quantity=1)
        print(f"Register 0x0003 = {r}")

        # Read all registers from the YAML/JSON definition
        project_root = os.path.dirname(os.path.dirname(__file__))
        yaml_path = os.path.join(project_root, "inverter_definitions", f"{MODEL}.json")
        if os.path.exists(yaml_path):
            sys.path.insert(0, project_root)
            from lib.parser import ParameterParser
            with open(yaml_path) as f:
                definition = json.load(f)

            MAX_CHUNK = 50  # some inverters cap at ~58 registers per Modbus query
            params = ParameterParser(definition)
            for req in definition["requests"]:
                start, end, fc = req["start"], req["end"], req["mb_functioncode"]
                addr = start
                while addr <= end:
                    chunk = min(MAX_CHUNK, end - addr + 1)
                    print(f"  Reading [{addr:#x}–{addr+chunk-1:#x}] ({chunk} regs) fc={fc}...")
                    try:
                        if fc == 3:
                            data = await m.read_holding_registers(register_addr=addr, quantity=chunk)
                        else:
                            data = await m.read_input_registers(register_addr=addr, quantity=chunk)
                        params.parse(data, addr, chunk)
                    except Exception as chunk_err:
                        print(f"  ERROR: {chunk_err}")
                    addr += chunk

            result = params.get_result()
            print(f"\nParsed {len(result)} values:")
            for k, v in sorted(result.items()):
                print(f"  {k}: {v}")
        else:
            print(f"Definition file not found: {yaml_path}")

    finally:
        await m.disconnect()
        print("\nDisconnected.")


asyncio.run(test())
