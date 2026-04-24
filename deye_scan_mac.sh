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
  echo " [ERROR] python3 not found"; exit 1
fi

echo
echo " ============================================"
echo "  Deye Universal Local Scan"
echo "  String · Hybrid · Micro · SG04LP3"
echo " ============================================"
echo

# ── Step 1: resolve logger IP + serial ───────────────────────────────────────

printf " Logger IP Address (leave blank to auto-scan): "
read -r HOST

if [ -z "$HOST" ]; then
  echo " Scanning network for Solarman loggers (UDP broadcast)..."

  # UDP discovery via a tiny synchronous Python snippet (no heredoc — stdin is terminal)
  DISCOVERY=$("$PYTHON_BIN" - <<'PYEOF'
import socket, sys, time
results = []
seen = set()
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(0.3)
    s.bind(("", 0))
    for payload in [b"WIFIKIT-214028-READ", b"HF-A11ASSISTHREAD"]:
        try:
            s.sendto(payload, ("<broadcast>", 48899))
        except Exception:
            pass
    deadline = time.time() + 3.0
    while time.time() < deadline:
        try:
            data, addr = s.recvfrom(256)
            parts = data.decode("latin-1").strip().split(",")
            if len(parts) >= 3 and parts[2].strip().isdigit() and addr[0] not in seen:
                seen.add(addr[0])
                results.append("%s %s %s" % (parts[0].strip(), parts[1].strip(), parts[2].strip()))
        except socket.timeout:
            pass
    s.close()
except Exception as e:
    print("ERROR: %s" % e, file=sys.stderr)
for r in results:
    print(r)
PYEOF
  )

  if [ -z "$DISCOVERY" ]; then
    echo " [ERROR] No Solarman loggers found on network."
    echo "         Make sure you are on the same Wi-Fi as the inverter logger."
    echo "         Or enter the IP address manually and re-run."
    exit 1
  fi

  # Count found loggers
  LOGGER_COUNT=$(echo "$DISCOVERY" | wc -l | tr -d ' ')

  if [ "$LOGGER_COUNT" -eq 1 ]; then
    read -r IP MAC SERIAL <<< "$DISCOVERY"
    HOST="$IP"
    echo " Found: $HOST  MAC:$MAC  Serial:$SERIAL"
  else
    echo " Found $LOGGER_COUNT logger(s):"
    I=1
    while IFS= read -r line; do
      read -r IP MAC SN <<< "$line"
      echo "   [$I] $IP  MAC:$MAC  Serial:$SN"
      I=$((I+1))
    done <<< "$DISCOVERY"
    printf " Choice [1-%d, default=1]: " "$LOGGER_COUNT"
    read -r CHOICE
    CHOICE="${CHOICE:-1}"
    SELECTED=$(echo "$DISCOVERY" | sed -n "${CHOICE}p")
    if [ -z "$SELECTED" ]; then
      echo " [ERROR] Invalid choice"; exit 1
    fi
    read -r HOST MAC SERIAL <<< "$SELECTED"
    echo " Selected: $HOST  Serial:$SERIAL"
  fi

else
  # Manual IP — validate and ask for serial
  if ! echo "$HOST" | grep -qE '^([0-9]{1,3}\.){3}[0-9]{1,3}$'; then
    echo " [ERROR] Invalid IP address: $HOST"; exit 1
  fi
  printf " Logger Serial Number: "
  read -r SERIAL
  if ! echo "$SERIAL" | grep -qE '^[0-9]+$'; then
    echo " [ERROR] Serial must be numeric"; exit 1
  fi
fi

# ── Step 2: model selection ───────────────────────────────────────────────────

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

# ── Step 3: run scan ──────────────────────────────────────────────────────────

STAMP="$(date +%Y%m%d_%H%M%S)"
if [ "$MODEL" = "auto" ]; then
  OUTFILE="${HOME}/Desktop/deye_scan_${HOST}_${STAMP}.txt"
else
  OUTFILE="${HOME}/Desktop/${MODEL}_scan_${HOST}_${STAMP}.txt"
fi

echo
echo " Scanning $HOST  serial=$SERIAL  model=$MODEL"
echo " Output:  $OUTFILE"
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

HOST     = sys.argv[1]
SERIAL   = int(sys.argv[2])
MODEL    = sys.argv[3]
OUTFILE  = sys.argv[4]
DEFS_DIR = sys.argv[5]

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

# ── Tee ───────────────────────────────────────────────────────────────────────

class Tee:
    def __init__(self, path):
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
            timeout=TIMEOUT)

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
        shift += 16; bits += 16
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

async def detect_model(log):
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
                    read_block(HOST, SERIAL, fc, start, end), timeout=10.0)
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
        log.write(" ⚠  No live data (night/offline) — defaulting to deye_string")
    else:
        log.write(" ✓  Detected: %s (score=%d)" % (best_model, best_score))
    log.write("")
    return best_model

# ── Output helper ─────────────────────────────────────────────────────────────

def fmt(value, uom=""):
    if value is None: return "--"
    if isinstance(value, str): return value
    text = ("%.3f" % value).rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
    return (text + (" " + uom if uom else "")).strip()

def add_derived(results, name, value, uom, note):
    results[name] = {"raw": None, "value": value, "uom": uom,
                     "registers": [], "note": note}

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    log     = Tee(OUTFILE)
    started = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        model_id = MODEL
        if model_id == "auto":
            log.write("Deye Universal Scan - %s" % started)
            log.write("Host: %s  Serial: %s" % (HOST, SERIAL))
            log.write("Transport: embedded Solarman V5 TCP, no pysolarmanv5")
            log.write("=" * 72)
            log.write("")
            model_id = await detect_model(log)

        defn       = load_definition(model_id)
        model_name = MODELS.get(model_id, model_id)

        log.write("Deye Universal Scan - %s" % started)
        log.write("Host: %s  Serial: %s  Model: %s" % (HOST, SERIAL, model_id))
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
                values = await read_block(HOST, SERIAL, fc, start, end, log)
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
            pv_total = 0.0
            for idx in (1, 2, 3, 4):
                v_val = results.get("PV%d Voltage" % idx, {}).get("value")
                a_val = results.get("PV%d Current" % idx, {}).get("value")
                if v_val is not None and a_val is not None:
                    pwr = round(float(v_val) * float(a_val), 1)
                    add_derived(results, "PV%d Power" % idx, pwr, "W",
                                "derived: PV%d Voltage × PV%d Current" % (idx, idx))
                    pv_total += pwr
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
                direction = ("discharging" if float(batt_pwr) > 0
                             else "charging" if float(batt_pwr) < 0 else "standby")
                log.write("  - Battery Power = %.1f W (%s)." % (float(batt_pwr), direction))
        log.write("  - Radiator Temperature = -100 C means register 0 (sensor absent).")
        log.write("")
        log.write("Done. File saved to: %s" % OUTFILE)
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
