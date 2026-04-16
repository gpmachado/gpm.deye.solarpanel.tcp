#!/bin/bash
# Deye Inverter Diagnostic — Mac / Linux
# Usage: bash deye_diagnostic.sh

set -e

echo ""
echo " ============================================"
echo "  Deye Inverter Diagnostic Tool"
echo " ============================================"
echo ""

# ── Check Python 3 ─────────────────────────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VERSION=$("$cmd" --version 2>&1)
        MAJOR=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null)
        if [ "$MAJOR" = "3" ]; then
            PYTHON="$cmd"
            echo " [OK] $VERSION found"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo " [ERROR] Python 3 not found."
    echo ""
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo " Install with Homebrew:  brew install python3"
        echo " Or download from:       https://www.python.org/downloads/"
    else
        echo " Install with:  sudo apt install python3 python3-pip   (Debian/Ubuntu)"
        echo " Or:            sudo dnf install python3               (Fedora/RHEL)"
    fi
    echo ""
    exit 1
fi

# ── Install pysolarmanv5 ───────────────────────────────────────────────────
echo " [..] Checking pysolarmanv5..."
if ! "$PYTHON" -c "import pysolarmanv5" &>/dev/null; then
    echo " [..] Installing pysolarmanv5..."
    "$PYTHON" -m pip install pysolarmanv5 --quiet --break-system-packages 2>/dev/null \
        || "$PYTHON" -m pip install pysolarmanv5 --quiet
fi
echo " [OK] pysolarmanv5 ready"
echo ""

# ── Connection details ─────────────────────────────────────────────────────
echo " Enter the details from Homey > Deye Inverter > Settings:"
echo ""
read -p "  Logger IP Address   : " HOST
read -p "  Logger Serial Number: " SERIAL
echo ""

if [ -z "$HOST" ] || [ -z "$SERIAL" ]; then
    echo " [ERROR] IP and serial are required."
    exit 1
fi

# ── Embedded Python diagnostic ────────────────────────────────────────────
TMPSCRIPT=$(mktemp /tmp/deye_diag_XXXXXX.py)

cat > "$TMPSCRIPT" << 'PYEOF'
import asyncio, sys
from pysolarmanv5 import PySolarmanV5Async

HOST   = sys.argv[1]
SERIAL = int(sys.argv[2])

REQUESTS = [
    {"start":   3, "end": 116, "fc": 3},
    {"start": 150, "end": 249, "fc": 3},
    {"start": 250, "end": 279, "fc": 3},
]

SENSORS = [
    {"name": "PV1 Power",               "reg": [  11],      "rule": 1, "scale": 1,    "off": 0},
    {"name": "PV1 Voltage",             "reg": [  13],      "rule": 1, "scale": 0.1,  "off": 0},
    {"name": "PV1 Current",             "reg": [  14],      "rule": 1, "scale": 0.1,  "off": 0},
    {"name": "PV2 Power",               "reg": [  16],      "rule": 1, "scale": 1,    "off": 0},
    {"name": "PV2 Voltage",             "reg": [  17],      "rule": 1, "scale": 0.1,  "off": 0},
    {"name": "PV2 Current",             "reg": [  18],      "rule": 1, "scale": 0.1,  "off": 0},
    {"name": "Battery Power",           "reg": [ 190],      "rule": 2, "scale": 1,    "off": 0},
    {"name": "Battery Voltage",         "reg": [ 183],      "rule": 1, "scale": 0.01, "off": 0},
    {"name": "Battery Current",         "reg": [ 191],      "rule": 2, "scale": 0.01, "off": 0},
    {"name": "Battery SOC",             "reg": [ 184],      "rule": 1, "scale": 1,    "off": 0},
    {"name": "Battery Temperature",     "reg": [ 182],      "rule": 2, "scale": 0.1,  "off": 1000},
    {"name": "Grid L1 Voltage",         "reg": [  76],      "rule": 1, "scale": 0.1,  "off": 0},
    {"name": "Grid L1 Current",         "reg": [  78],      "rule": 2, "scale": 0.01, "off": 0},
    {"name": "Grid Frequency",          "reg": [  79],      "rule": 1, "scale": 0.01, "off": 0},
    {"name": "Grid Power",              "reg": [ 169],      "rule": 2, "scale": 1,    "off": 0},
    {"name": "Load Power",              "reg": [ 178],      "rule": 1, "scale": 1,    "off": 0},
    {"name": "AC Output Power",         "reg": [ 175],      "rule": 1, "scale": 1,    "off": 0},
    {"name": "DC Temperature",          "reg": [  90],      "rule": 2, "scale": 0.1,  "off": 1000},
    {"name": "Radiator Temperature",    "reg": [  91],      "rule": 2, "scale": 0.1,  "off": 1000},
    {"name": "Today Production",        "reg": [  60],      "rule": 1, "scale": 0.1,  "off": 0},
    {"name": "Total Production",        "reg": [  63,  64], "rule": 3, "scale": 0.1,  "off": 0},
    {"name": "Today Battery Charge",    "reg": [ 166],      "rule": 1, "scale": 0.1,  "off": 0},
    {"name": "Today Battery Discharge", "reg": [ 167],      "rule": 1, "scale": 0.1,  "off": 0},
    {"name": "Today Energy Import",     "reg": [ 250],      "rule": 1, "scale": 0.1,  "off": 0},
    {"name": "Today Energy Export",     "reg": [ 251],      "rule": 1, "scale": 0.1,  "off": 0},
    {"name": "Total Energy Import",     "reg": [ 252, 253], "rule": 3, "scale": 0.1,  "off": 0},
    {"name": "Total Energy Export",     "reg": [ 254, 255], "rule": 3, "scale": 0.1,  "off": 0},
]

async def main():
    print(f"\n  Connecting to {HOST}:8899  serial={SERIAL}...")
    m = PySolarmanV5Async(
        HOST, SERIAL, port=8899, mb_slave_id=1,
        auto_reconnect=False, socket_timeout=15,
    )
    await m.connect()
    print("  Connected OK\n")

    raw = {}
    for req in REQUESTS:
        s, e, fc = req["start"], req["end"], req["fc"]
        n = e - s + 1
        print(f"  Reading [0x{s:X}–0x{e:X}] fc={fc}...")
        try:
            if fc == 3:
                data = await m.read_holding_registers(register_addr=s, quantity=n)
            else:
                data = await m.read_input_registers(register_addr=s, quantity=n)
            for i, v in enumerate(data):
                raw[s + i] = v
        except Exception as ex:
            print(f"    ERROR: {ex}")

    await m.disconnect()

    print("\n  Raw registers (non-zero):")
    for reg in sorted(raw):
        v = raw[reg]
        if v:
            print(f"    reg {reg:4d} (0x{reg:04X}) = {v:6d}  (0x{v:04X})")

    print("\n  Parsed values:")
    for s in SENSORS:
        regs = s["reg"]
        if not all(r in raw for r in regs):
            print(f"  {s['name']:<36s} -- not read")
            continue
        if s["rule"] == 3 and len(regs) >= 2:
            rv = raw[regs[0]] + raw.get(regs[1], 0) * 65536
        else:
            rv = raw[regs[0]]
            if s["rule"] == 2 and rv > 32767:
                rv -= 65536  # signed interpretation for rule 2 when needed
        val = (rv - s["off"]) * s["scale"]
        unit_map = {1: "W", 0.1: "W", 0.01: "A"}
        print(f"  {s['name']:<36s} {val:.2f}")

asyncio.run(main())
PYEOF

# ── Run and save ───────────────────────────────────────────────────────────
OUTFILE="$HOME/Desktop/deye_diagnostic_${HOST}.txt"
# fallback if Desktop doesn't exist (Linux without GUI)
[ -d "$HOME/Desktop" ] || OUTFILE="$HOME/deye_diagnostic_${HOST}.txt"

echo " Running diagnostic for $HOST (serial: $SERIAL)..."
echo " Output will be saved to: $OUTFILE"
echo ""

{
    echo "Deye Diagnostic — $(date)"
    echo "Host: $HOST   Serial: $SERIAL   Model: deye_hybrid"
    echo "================================================================"
    "$PYTHON" "$TMPSCRIPT" "$HOST" "$SERIAL"
} 2>&1 | tee "$OUTFILE"

rm -f "$TMPSCRIPT"

echo ""
echo " ============================================"
echo "  Done! File saved to:"
echo "  $OUTFILE"
echo "  Please send this file."
echo " ============================================"
echo ""
