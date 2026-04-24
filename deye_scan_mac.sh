#!/usr/bin/env bash
# deye_scan_mac.sh — Universal Deye inverter scan (macOS / Linux)
# Supports: deye_string · deye_hybrid · deye_micro · deye_sg04lp3
# Transport: embedded Solarman V5 TCP — no pysolarmanv5 needed
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
echo "  Deye Universal Local Scan for macOS"
echo " ============================================"
echo

DEFAULT_HOST="${1:-192.168.1.199}"
DEFAULT_SERIAL="${2:-1782317166}"

printf " Logger IP Address    [%s]: " "$DEFAULT_HOST"
read -r HOST
HOST="${HOST:-$DEFAULT_HOST}"

printf " Logger Serial Number [%s]: " "$DEFAULT_SERIAL"
read -r SERIAL
SERIAL="${SERIAL:-$DEFAULT_SERIAL}"

if ! [[ "$SERIAL" =~ ^[0-9]+$ ]]; then
  echo " [ERROR] Serial must be numeric"
  exit 1
fi

echo
echo " Select model:"
echo "   [1] deye_string   — String Inverter (2/4 MPPT)"
echo "   [2] deye_hybrid   — Hybrid (Battery + 2 MPPT)"
echo "   [3] deye_micro    — Microinverter (4 MPPT)"
echo "   [4] deye_sg04lp3  — Hybrid 3-phase SG04LP3"
echo "   [5] auto-detect   (probe inverter to determine model)"
echo
printf " Choice [1-5, default=1]: "
read -r MODEL_CHOICE
MODEL_CHOICE="${MODEL_CHOICE:-1}"

case "$MODEL_CHOICE" in
  1) MODEL="deye_string"  ;;
  2) MODEL="deye_hybrid"  ;;
  3) MODEL="deye_micro"   ;;
  4) MODEL="deye_sg04lp3" ;;
  5) MODEL="auto"         ;;
  *) echo " [ERROR] Invalid choice"; exit 1 ;;
esac

STAMP="$(date +%Y%m%d_%H%M%S)"
if [ "$MODEL" = "auto" ]; then
  OUTFILE="${HOME}/Desktop/deye_scan_${HOST}_${STAMP}.txt"
else
  OUTFILE="${HOME}/Desktop/${MODEL}_scan_${HOST}_${STAMP}.txt"
fi

echo
echo " Scanning ${HOST} serial=${SERIAL} model=${MODEL}"
echo " Output: ${OUTFILE}"
echo

"$PYTHON_BIN" - "$HOST" "$SERIAL" "$MODEL" "$OUTFILE" "$DEFS_DIR" <<'PY'
import asyncio
import datetime as _dt
import json
import os
import socket
import struct
import sys
import time

HOST   = sys.argv[1]
SERIAL = int(sys.argv[2])
MODEL  = sys.argv[3]      # model id or "auto"
OUTFILE = sys.argv[4]
DEFS_DIR = sys.argv[5]

PORT    = 8899
SLAVE   = 1
TIMEOUT = 8.0
RETRIES = 3

MODELS = {
    "deye_string":  "Deye String Inverter (2/4 MPPT)",
    "deye_hybrid":  "Deye Hybrid (Battery + 2 MPPT)",
    "deye_micro":   "Deye Microinverter (4 MPPT) — SUN-M/SUN2000G3",
    "deye_sg04lp3": "Deye Hybrid 3-phase — SG04LP3",
}

# ── Tee output to file + stdout ───────────────────────────────────────────────

class Tee:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._file = open(path, "w", encoding="utf-8")

    def write(self, text=""):
        print(text)
        self._file.write(text + "\n")
        self._file.flush()

    def close(self):
        self._file.close()

# ── SolarmanV5 TCP transport (embedded — no pysolarmanv5) ────────────────────

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


def build_modbus_request(slave, fc, start, count):
    msg = struct.pack(">BBHH", slave, fc, start, count)
    return msg + struct.pack("<H", crc16_modbus(msg))


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


def parse_v5_response(frame, expected_seq):
    if len(frame) < 29:
        raise ValueError("V5 frame too short: %d bytes" % len(frame))
    if frame[0] != V5_START or frame[-1] != V5_END:
        raise ValueError("V5 start/end mismatch")
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
    def __init__(self, host, serial, port=8899, slave=1, timeout=8.0):
        self.host = host; self.serial = serial
        self.port = port; self.slave = slave; self.timeout = timeout
        self.seq = 0; self.reader = self.writer = None

    async def connect(self):
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port, family=socket.AF_INET),
            timeout=self.timeout,
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
        seq = self._next_seq()
        req   = build_modbus_request(self.slave, fc, start, count)
        frame = build_v5_frame(self.serial, seq, req)
        self.writer.write(frame)
        await self.writer.drain()
        resp   = await self._read_v5_frame()
        modbus = parse_v5_response(resp, seq)
        return parse_modbus_registers(modbus, count)

    async def _read_v5_frame(self):
        for _ in range(5):
            header = await asyncio.wait_for(
                self.reader.readexactly(11), timeout=self.timeout)
            if header[0] != V5_START:
                raise ValueError("Unexpected V5 start: 0x%02x" % header[0])
            payload_len = struct.unpack("<H", header[1:3])[0]
            rest  = await asyncio.wait_for(
                self.reader.readexactly(payload_len + 2), timeout=self.timeout)
            frame = header + rest
            if frame[3:5] == V5_CTRL_RESP:
                return frame
        raise TimeoutError("No V5 data response after 5 frames")


async def read_block(host, serial, fc, start, end, log=None):
    count = end - start + 1
    label = "fc=%d [%d-%d]" % (fc, start, end)
    last_err = None
    for attempt in range(1, RETRIES + 1):
        t = V5Transport(host, serial, PORT, SLAVE, TIMEOUT)
        try:
            await t.connect()
            values = await t.read_registers(fc, start, count)
            await t.disconnect()
            return values
        except Exception as exc:
            last_err = exc
            if log:
                log.write("  %s attempt %d/%d failed: %s: %s"
                          % (label, attempt, RETRIES, type(exc).__name__, exc))
            await t.disconnect()
            await asyncio.sleep(0.8 * attempt)
    raise last_err


# ── JSON definition loader ────────────────────────────────────────────────────

def load_definition(model_id):
    path = os.path.join(DEFS_DIR, model_id + ".json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── Parameter parser (adapted from ha-solarman) ───────────────────────────────

def lookup_value(value, options):
    for o in options:
        if o["key"] == value:
            return o["value"]
    return str(value)


def parse_sensor(defn, all_regs):
    """Parse one sensor definition against a {addr: raw_value} dict.
    Returns (raw_combined, parsed_value) or (None, None) if registers missing."""
    rule  = defn.get("rule", 1)
    regs  = defn["registers"]
    scale = defn.get("scale", 1)

    # Check all registers are present
    for r in regs:
        if r not in all_regs:
            return None, None

    # Combine register words
    raw   = 0
    shift = 0
    bits  = 0
    for r in regs:
        raw  += (all_regs[r] & 0xFFFF) << shift
        shift += 16
        bits  += 16

    # Lookup table
    if "lookup" in defn:
        return raw, lookup_value(raw, defn["lookup"])

    value = raw

    # Offset (e.g. temperature: subtract 1000)
    if "offset" in defn:
        value -= defn["offset"]

    # Signed (rules 2 and 4)
    if rule in (2, 4):
        maxint = (1 << bits) - 1
        if value > maxint // 2:
            value -= (maxint + 1)

    value = value * scale

    # Validation
    if "validation" in defn:
        v = defn["validation"]
        if "min" in v and value < v["min"]:
            return raw, None
        if "max" in v and value > v["max"]:
            return raw, None

    # Round nicely
    if isinstance(value, float) and value == int(value):
        value = int(value)
    elif isinstance(value, float):
        value = round(value, 3)

    return raw, value


# ── Auto-detection ────────────────────────────────────────────────────────────

async def detect_model(log):
    """Score each model by reading its registers and counting non-zero sensor hits."""
    log.write(" Auto-detecting model — probing each type...")
    log.write("")

    best_model = "deye_string"
    best_score = 0

    for model_id in MODELS:
        try:
            defn = load_definition(model_id)
        except FileNotFoundError:
            log.write("  [%s] definition not found — skipped" % model_id)
            continue

        score = 0
        all_regs = {}

        for req in defn["requests"]:
            start, end, fc = req["start"], req["end"], req["mb_functioncode"]
            count = end - start + 1
            try:
                values = await asyncio.wait_for(
                    read_block(HOST, SERIAL, fc, start, end), timeout=10.0
                )
                for i, v in enumerate(values):
                    all_regs[start + i] = v
            except Exception as e:
                pass   # register group not supported by this inverter → skip

        # Score sensors
        for group in defn["parameters"]:
            for sensor in group["items"]:
                raw, value = parse_sensor(sensor, all_regs)
                if value is None or value == 0:
                    continue
                uom = sensor.get("uom", "")
                if uom in ("W", "kWh", "kW"):
                    score += 2
                else:
                    score += 1

        log.write("  [%s] score=%d" % (model_id, score))
        if score > best_score:
            best_score = score
            best_model = model_id

        await asyncio.sleep(1.5)   # let logger close TCP slot

    log.write("")
    if best_score == 0:
        log.write(" ⚠ No live data found (night / offline) — defaulting to deye_string")
    else:
        log.write(" ✓ Detected: %s (score=%d)" % (best_model, best_score))
    log.write("")
    return best_model


# ── Formatted output ──────────────────────────────────────────────────────────

def fmt(value, uom=""):
    if value is None:
        return "--"
    if isinstance(value, str):
        return value
    if isinstance(value, float):
        text = ("%.3f" % value).rstrip("0").rstrip(".")
    else:
        text = str(value)
    return (text + (" " + uom if uom else "")).strip()


def add_derived(results, name, value, uom, note):
    results[name] = {"raw": None, "value": value, "uom": uom,
                     "registers": [], "note": note}


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    log = Tee(OUTFILE)
    started = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        # ── Auto-detect if requested ──────────────────────────────────────────
        model_id = MODEL
        if model_id == "auto":
            log.write("Deye Universal Scan - %s" % started)
            log.write("Host: %s  Serial: %s" % (HOST, SERIAL))
            log.write("Transport: embedded Solarman V5 TCP, no pysolarmanv5")
            log.write("=" * 72)
            log.write("")
            model_id = await detect_model(log)

        defn = load_definition(model_id)
        model_name = MODELS.get(model_id, model_id)

        log.write("Deye Universal Scan - %s" % started)
        log.write("Host: %s  Serial: %s  Model: %s" % (HOST, SERIAL, model_id))
        log.write("Description: %s" % model_name)
        log.write("Transport: embedded Solarman V5 TCP, no pysolarmanv5")
        log.write("=" * 72)
        log.write("")

        # ── Read all register groups ──────────────────────────────────────────
        all_registers = {}
        for req in defn["requests"]:
            start = req["start"]
            end   = req["end"]
            fc    = req["mb_functioncode"]
            count = end - start + 1
            log.write("Reading fc=%d registers [%d-%d]..." % (fc, start, end))
            try:
                values = await read_block(HOST, SERIAL, fc, start, end, log)
                for i, v in enumerate(values):
                    all_registers[start + i] = v
                log.write("  OK: %d registers" % count)
            except Exception as exc:
                log.write("  FAILED after %d retries: %s" % (RETRIES, exc))
            await asyncio.sleep(0.3)

        # ── Raw non-zero registers ────────────────────────────────────────────
        log.write("")
        log.write("Raw registers (non-zero):")
        for reg in sorted(all_registers):
            v = all_registers[reg]
            if v:
                log.write("  reg %5d (0x%04X) = %7d  (0x%04X)" % (reg, reg, v, v))

        # ── Parse all sensors ─────────────────────────────────────────────────
        results = {}   # name → {raw, value, uom, registers, note, group}
        group_order = []
        for group_def in defn["parameters"]:
            gname = group_def.get("group", "")
            if gname not in group_order:
                group_order.append(gname)
            for sensor in group_def["items"]:
                sname = sensor["name"]
                raw, value = parse_sensor(sensor, all_registers)
                if value is not None:
                    results[sname] = {
                        "raw": raw,
                        "value": value,
                        "uom": sensor.get("uom", ""),
                        "registers": sensor["registers"],
                        "note": "",
                        "group": gname,
                    }

        # ── Derived PV power for string/micro (no direct PV-power registers) ─
        if model_id in ("deye_string", "deye_micro"):
            pv_channels = {}
            for idx in (1, 2, 3, 4):
                vname = "PV%d Voltage" % idx
                aname = "PV%d Current" % idx
                v_val = results.get(vname, {}).get("value")
                a_val = results.get(aname, {}).get("value")
                if v_val is not None and a_val is not None:
                    pwr = round(float(v_val) * float(a_val), 1)
                    pv_channels[idx] = pwr
                    add_derived(results, "PV%d Power" % idx, pwr, "W",
                                "derived: PV%d Voltage × PV%d Current" % (idx, idx))
            if pv_channels:
                total = round(sum(pv_channels.values()), 1)
                add_derived(results, "PV Power Total", total, "W",
                            "derived: sum of PV1..PV4 Power")

        # ── Display parsed values by group ────────────────────────────────────
        log.write("")
        log.write("Parsed values by group:")
        log.write("")

        # Gather all sensor names in their definition order
        ordered_names = []
        for group_def in defn["parameters"]:
            gname = group_def.get("group", "")
            group_sensors = [s["name"] for s in group_def["items"]]
            # inject derived PV power after each PVx Voltage/Current pair
            expanded = []
            for sname in group_sensors:
                expanded.append(sname)
                for idx in (1, 2, 3, 4):
                    if sname == ("PV%d Current" % idx):
                        pwr_name = "PV%d Power" % idx
                        if pwr_name in results:
                            expanded.append(pwr_name)
            ordered_names.append((gname, expanded))
        # add PV Power Total at end of solar group
        for gname_exp in ordered_names:
            if gname_exp[0].lower() in ("solar", "pv", ""):
                if "PV Power Total" in results and "PV Power Total" not in gname_exp[1]:
                    gname_exp[1].append("PV Power Total")
                break

        for gname, sensor_names in ordered_names:
            printed_header = False
            for sname in sensor_names:
                if sname not in results:
                    continue
                if not printed_header:
                    log.write("  [%s]" % gname)
                    printed_header = True
                item = results[sname]
                regs_str = (",".join(str(r) for r in item["registers"])
                            if item["registers"] else "derived")
                raw_str  = "--" if item["raw"] is None else str(item["raw"])
                val_str  = fmt(item["value"], item["uom"])
                note     = "  # %s" % item["note"] if item["note"] else ""
                log.write("    %-38s %-16s raw=%-10s regs=%s%s"
                          % (sname + ":", val_str, raw_str, regs_str, note))
            if printed_header:
                log.write("")

        # ── Model-specific notes ──────────────────────────────────────────────
        log.write("Notes:")
        if model_id in ("deye_string", "deye_micro"):
            log.write("  - PV Power is derived (Voltage × Current) — no direct PV power register.")
            input_pwr = results.get("Input Power", {}).get("value")
            if input_pwr is not None:
                log.write("  - Input Power (Solar DC) = %.1f W (register 82+83)." % input_pwr)
        if model_id in ("deye_hybrid", "deye_sg04lp3"):
            batt_soc = results.get("Battery SOC", {}).get("value")
            if batt_soc is not None:
                log.write("  - Battery SOC = %s%%." % batt_soc)
            batt_pwr = results.get("Battery Power", {}).get("value")
            if batt_pwr is not None:
                direction = "discharging" if float(batt_pwr) > 0 else "charging" if float(batt_pwr) < 0 else "standby"
                log.write("  - Battery Power = %.1f W (%s)." % (float(batt_pwr), direction))
        log.write("  - Radiator Temperature = -100 C means register is 0 (sensor absent).")
        log.write("")
        log.write("Done. File saved to: %s" % OUTFILE)

    finally:
        log.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted.")
        sys.exit(130)
    except Exception as exc:
        print("ERROR: %s: %s" % (type(exc).__name__, exc))
        sys.exit(1)
PY

echo
echo " ============================================"
echo "  Done. File saved to:"
echo "  ${OUTFILE}"
echo " ============================================"
echo
