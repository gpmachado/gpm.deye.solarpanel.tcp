#!/usr/bin/env bash
set -euo pipefail

echo
echo " ============================================"
echo "  Deye String Local Scan for macOS"
echo " ============================================"
echo

PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo " [ERROR] python3 not found"
  exit 1
fi

DEFAULT_HOST="${1:-192.168.1.199}"
DEFAULT_SERIAL="${2:-1782317166}"

printf " Logger IP Address [%s]: " "$DEFAULT_HOST"
read -r HOST
HOST="${HOST:-$DEFAULT_HOST}"

printf " Logger Serial Number [%s]: " "$DEFAULT_SERIAL"
read -r SERIAL
SERIAL="${SERIAL:-$DEFAULT_SERIAL}"

if ! [[ "$SERIAL" =~ ^[0-9]+$ ]]; then
  echo " [ERROR] Serial must be numeric"
  exit 1
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
OUTFILE="${HOME}/Desktop/deye_string_scan_${HOST}_${STAMP}.txt"

echo
echo " Running local scan for ${HOST} serial=${SERIAL}"
echo " Output will be saved to: ${OUTFILE}"
echo

"$PYTHON_BIN" - "$HOST" "$SERIAL" "$OUTFILE" <<'PY'
import asyncio
import datetime as _dt
import os
import socket
import struct
import sys
import time


HOST = sys.argv[1]
SERIAL = int(sys.argv[2])
OUTFILE = sys.argv[3]

PORT = 8899
SLAVE = 1
TIMEOUT = 8.0
RETRIES = 3

REQUESTS = [
    {"start": 1, "end": 125, "fc": 3},
    {"start": 198, "end": 210, "fc": 3},
]

SENSORS = [
    {"name": "PV1 Voltage", "uom": "V", "scale": 0.1, "rule": 1, "registers": [109]},
    {"name": "PV1 Current", "uom": "A", "scale": 0.1, "rule": 1, "registers": [110]},
    {"name": "PV2 Voltage", "uom": "V", "scale": 0.1, "rule": 1, "registers": [111]},
    {"name": "PV2 Current", "uom": "A", "scale": 0.1, "rule": 1, "registers": [112]},
    {"name": "PV3 Voltage", "uom": "V", "scale": 0.1, "rule": 1, "registers": [113]},
    {"name": "PV3 Current", "uom": "A", "scale": 0.1, "rule": 1, "registers": [114]},
    {"name": "PV4 Voltage", "uom": "V", "scale": 0.1, "rule": 1, "registers": [115]},
    {"name": "PV4 Current", "uom": "A", "scale": 0.1, "rule": 1, "registers": [116]},
    {"name": "Today Production", "uom": "kWh", "scale": 0.1, "rule": 1, "registers": [60]},
    {"name": "Total Production", "uom": "kWh", "scale": 0.1, "rule": 3, "registers": [63, 64]},
    {"name": "Grid L1 Voltage", "uom": "V", "scale": 0.1, "rule": 1, "registers": [73]},
    {"name": "Grid L2 Voltage", "uom": "V", "scale": 0.1, "rule": 1, "registers": [74]},
    {"name": "Grid L3 Voltage", "uom": "V", "scale": 0.1, "rule": 1, "registers": [75]},
    {"name": "Grid L1 Current", "uom": "A", "scale": 0.1, "rule": 2, "registers": [76]},
    {"name": "Grid L2 Current", "uom": "A", "scale": 0.1, "rule": 2, "registers": [77]},
    {"name": "Grid L3 Current", "uom": "A", "scale": 0.1, "rule": 2, "registers": [78]},
    {"name": "Grid Frequency", "uom": "Hz", "scale": 0.01, "rule": 1, "registers": [79]},
    {"name": "Output AC Power", "uom": "W", "scale": 0.1, "rule": 3, "registers": [80, 81]},
    {"name": "Input Power", "uom": "W", "scale": 0.1, "rule": 3, "registers": [82, 83]},
    {"name": "Output Apparent Power", "uom": "VA", "scale": 0.1, "rule": 3, "registers": [84, 85]},
    {"name": "AC Output Power", "uom": "W", "scale": 0.1, "rule": 3, "registers": [86, 87]},
    {"name": "Output Reactive Power", "uom": "var", "scale": 0.1, "rule": 3, "registers": [88, 89]},
    {"name": "DC Temperature", "uom": "C", "scale": 0.1, "rule": 2, "offset": 1000, "registers": [90]},
    {"name": "Radiator Temperature", "uom": "C", "scale": 0.1, "rule": 2, "offset": 1000, "registers": [91]},
    {"name": "Load Power", "uom": "W", "scale": 0.1, "rule": 1, "registers": [198, 199]},
    {"name": "Grid Power", "uom": "W", "scale": 0.1, "rule": 2, "registers": [203, 204]},
    {"name": "Today Load Consumption", "uom": "kWh", "scale": 0.01, "rule": 1, "registers": [200]},
    {"name": "Total Load Consumption", "uom": "kWh", "scale": 0.1, "rule": 3, "registers": [201, 202]},
    {"name": "Today Energy Export", "uom": "kWh", "scale": 0.01, "rule": 1, "registers": [205]},
    {"name": "Total Energy Export", "uom": "kWh", "scale": 0.1, "rule": 3, "registers": [206, 207]},
    {"name": "Today Energy Import", "uom": "kWh", "scale": 0.01, "rule": 1, "registers": [208]},
    {"name": "Total Energy Import", "uom": "kWh", "scale": 0.1, "rule": 1, "registers": [209, 210]},
    {"name": "Running Status", "uom": "", "scale": 1, "rule": 1, "registers": [59], "lookup": {
        0: "Standby", 1: "Self-test", 2: "Normal", 3: "Alarm", 4: "Fault"
    }},
]

V5_START = 0xA5
V5_END = 0x15
V5_CTRL_REQ = struct.pack("<H", 0x4510)
V5_CTRL_RESP = struct.pack("<H", 0x1510)


class Tee:
    def __init__(self, path):
        self._file = open(path, "w", encoding="utf-8")

    def write(self, text=""):
        print(text)
        self._file.write(text + "\n")
        self._file.flush()

    def close(self):
        self._file.close()


def crc16_modbus(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def v5_checksum(frame):
    return sum(frame[i] & 0xFF for i in range(1, len(frame) - 2)) & 0xFF


def build_modbus_request(slave, fc, start, count):
    msg = struct.pack(">BBHH", slave, fc, start, count)
    return msg + struct.pack("<H", crc16_modbus(msg))


def build_v5_frame(serial, seq, modbus_payload):
    payload = bytearray(
        bytes([0x02])
        + bytes(2)
        + bytes(4)
        + bytes(4)
        + bytes(4)
        + modbus_payload
    )
    header = bytearray(
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
        raise ValueError("V5 response too short: %d bytes" % len(frame))
    if frame[0] != V5_START:
        raise ValueError("V5 start mismatch: 0x%02x" % frame[0])
    if frame[-1] != V5_END:
        raise ValueError("V5 end mismatch: 0x%02x" % frame[-1])
    if frame[3:5] != V5_CTRL_RESP:
        raise ValueError("V5 unexpected control code: %s" % frame[3:5].hex())
    if frame[5] != (expected_seq & 0xFF):
        raise ValueError("V5 sequence mismatch: got %d expected %d" % (frame[5], expected_seq))
    if frame[-2] != v5_checksum(frame):
        raise ValueError("V5 checksum mismatch: got %02x expected %02x" % (frame[-2], v5_checksum(frame)))
    modbus = frame[25:-2]
    if len(modbus) < 5:
        raise ValueError("Modbus payload too short: %d bytes" % len(modbus))
    return bytes(modbus)


def parse_modbus_registers(data, count):
    if len(data) < 5:
        raise ValueError("Modbus response too short: %d bytes" % len(data))
    if data[1] & 0x80:
        raise ValueError("Modbus exception, code 0x%02x" % data[2])
    byte_count = data[2]
    available = byte_count // 2
    values = []
    for i in range(min(count, available)):
        values.append(struct.unpack(">H", data[3 + i * 2:5 + i * 2])[0])
    if len(values) != count:
        raise ValueError("Short Modbus response: got %d/%d registers" % (len(values), count))
    return values


class V5Transport:
    def __init__(self, host, serial, port=8899, slave=1, timeout=8.0):
        self.host = host
        self.serial = serial
        self.port = port
        self.slave = slave
        self.timeout = timeout
        self.seq = 0
        self.reader = None
        self.writer = None

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
        self.reader = None
        self.writer = None

    def next_seq(self):
        self.seq = (self.seq + 1) & 0xFF
        return self.seq

    async def read_registers(self, fc, start, count):
        seq = self.next_seq()
        req = build_modbus_request(self.slave, fc, start, count)
        frame = build_v5_frame(self.serial, seq, req)
        self.writer.write(frame)
        await self.writer.drain()
        response = await self.read_v5_frame()
        modbus = parse_v5_response(response, seq)
        return parse_modbus_registers(modbus, count)

    async def read_v5_frame(self):
        for _ in range(5):
            header = await asyncio.wait_for(self.reader.readexactly(11), timeout=self.timeout)
            if header[0] != V5_START:
                raise ValueError("Unexpected V5 start byte: 0x%02x" % header[0])
            payload_len = struct.unpack("<H", header[1:3])[0]
            rest = await asyncio.wait_for(self.reader.readexactly(payload_len + 2), timeout=self.timeout)
            frame = header + rest
            if frame[3:5] == V5_CTRL_RESP:
                return frame
        raise TimeoutError("No V5 data response received")


def signed_word(value, bits):
    maxint = (1 << bits) - 1
    if value > maxint / 2:
        return value - maxint
    return value


def parse_value(defn, registers):
    raw = 0
    bits = 0
    shift = 0
    raw_parts = []
    for reg in defn["registers"]:
        if reg not in registers:
            return None, None
        part = registers[reg] & 0xFFFF
        raw_parts.append(part)
        raw += part << shift
        shift += 16
        bits += 16

    if "lookup" in defn:
        return raw, defn["lookup"].get(raw, raw)

    value = raw
    if "offset" in defn:
        value -= defn["offset"]
    if defn["rule"] in (2, 4):
        value = signed_word(value, bits)
    value *= defn.get("scale", 1)
    if abs(value - int(value)) < 0.0000001:
        value = int(value)
    return raw, value


async def read_block(req, log):
    start = req["start"]
    end = req["end"]
    count = end - start + 1
    fc = req["fc"]
    label = "0x%x-0x%x" % (start, end)
    last_error = None

    for attempt in range(1, RETRIES + 1):
        transport = V5Transport(HOST, SERIAL, PORT, SLAVE, TIMEOUT)
        try:
            await transport.connect()
            values = await transport.read_registers(fc, start, count)
            await transport.disconnect()
            if attempt > 1:
                log.write("  OK after retry %d: [%s]" % (attempt, label))
            return values
        except Exception as exc:
            last_error = exc
            log.write("  Query [%s] attempt %d/%d failed: %s: %s" % (
                label, attempt, RETRIES, exc.__class__.__name__, str(exc)
            ))
            await transport.disconnect()
            await asyncio.sleep(0.8 * attempt)

    raise last_error


def fmt(value, uom=""):
    if value is None:
        return "--"
    if isinstance(value, str):
        return value
    if isinstance(value, float):
        text = ("%.2f" % value).rstrip("0").rstrip(".")
    else:
        text = str(value)
    return (text + (" " + uom if uom else "")).strip()


def get(results, name):
    item = results.get(name)
    return item["value"] if item else None


def add_derived(results, name, value, uom, note):
    results[name] = {"raw": None, "value": value, "uom": uom, "registers": [], "note": note}


async def main():
    os.makedirs(os.path.dirname(OUTFILE), exist_ok=True)
    log = Tee(OUTFILE)
    started = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        log.write("Deye String Local Scan - %s" % started)
        log.write("Host: %s  Serial: %s  Model: deye_string" % (HOST, SERIAL))
        log.write("Transport: embedded Solarman V5 TCP, no pysolarmanv5")
        log.write("=" * 72)
        log.write("")

        all_registers = {}
        for req in REQUESTS:
            start = req["start"]
            end = req["end"]
            count = end - start + 1
            log.write("Reading fc=%d registers [%d-%d]..." % (req["fc"], start, end))
            values = await read_block(req, log)
            for offset, value in enumerate(values):
                all_registers[start + offset] = value
            log.write("  OK: %d registers" % count)
            time.sleep(0.5)

        log.write("")
        log.write("Raw registers (non-zero):")
        for reg in sorted(all_registers):
            value = all_registers[reg]
            if value:
                log.write("  reg %4d (0x%04X) = %6d  (0x%04X)" % (reg, reg, value, value))

        results = {}
        for sensor in SENSORS:
            raw, value = parse_value(sensor, all_registers)
            if value is not None:
                results[sensor["name"]] = {
                    "raw": raw,
                    "value": value,
                    "uom": sensor.get("uom", ""),
                    "registers": sensor["registers"],
                    "note": "",
                }

        pv1_v = get(results, "PV1 Voltage")
        pv1_a = get(results, "PV1 Current")
        pv2_v = get(results, "PV2 Voltage")
        pv2_a = get(results, "PV2 Current")
        pv3_v = get(results, "PV3 Voltage")
        pv3_a = get(results, "PV3 Current")
        pv4_v = get(results, "PV4 Voltage")
        pv4_a = get(results, "PV4 Current")

        pv1_w = pv1_v * pv1_a if pv1_v is not None and pv1_a is not None else None
        pv2_w = pv2_v * pv2_a if pv2_v is not None and pv2_a is not None else None
        pv3_w = pv3_v * pv3_a if pv3_v is not None and pv3_a is not None else None
        pv4_w = pv4_v * pv4_a if pv4_v is not None and pv4_a is not None else None
        pv_total = sum(v for v in (pv1_w, pv2_w, pv3_w, pv4_w) if v is not None)

        add_derived(results, "PV1 Power", pv1_w, "W", "derived: PV1 Voltage * PV1 Current")
        add_derived(results, "PV2 Power", pv2_w, "W", "derived: PV2 Voltage * PV2 Current")
        add_derived(results, "PV3 Power", pv3_w, "W", "derived: PV3 Voltage * PV3 Current")
        add_derived(results, "PV4 Power", pv4_w, "W", "derived: PV4 Voltage * PV4 Current")
        add_derived(results, "PV Power", pv_total, "W", "derived: PV1+PV2+PV3+PV4 Power")

        input_power = get(results, "Input Power")
        output_ac = get(results, "Output AC Power")
        ac_power = get(results, "AC Output Power")
        if input_power is not None and output_ac is not None:
            add_derived(results, "Power losses", input_power - output_ac, "W", "derived: Input Power - Output AC Power")
        if input_power is not None and ac_power is not None:
            add_derived(results, "Power losses vs AC Output Power", input_power - ac_power, "W", "derived: Input Power - AC Output Power")

        today_prod = get(results, "Today Production")
        today_load = get(results, "Today Load Consumption")
        total_prod = get(results, "Total Production")
        total_load = get(results, "Total Load Consumption")
        if today_prod is not None and today_load is not None:
            add_derived(results, "Today Losses", today_prod - today_load, "kWh", "derived: Today Production - Today Load Consumption")
        if total_prod is not None and total_load is not None:
            add_derived(results, "Total Losses", total_prod - total_load, "kWh", "derived: Total Production - Total Load Consumption")

        order = [
            "Running Status",
            "PV1 Voltage", "PV1 Current", "PV1 Power",
            "PV2 Voltage", "PV2 Current", "PV2 Power",
            "PV3 Voltage", "PV3 Current", "PV3 Power",
            "PV4 Voltage", "PV4 Current", "PV4 Power",
            "PV Power",
            "Grid Frequency",
            "Grid L1 Voltage", "Grid L2 Voltage", "Grid L3 Voltage",
            "Grid L1 Current", "Grid L2 Current", "Grid L3 Current", "Grid Power",
            "Input Power", "Load Power", "Output AC Power", "Output Apparent Power",
            "Output Reactive Power", "AC Output Power", "Power losses", "Power losses vs AC Output Power",
            "DC Temperature", "Radiator Temperature",
            "Today Energy Export", "Today Energy Import", "Today Load Consumption",
            "Today Losses", "Today Production",
            "Total Energy Export", "Total Energy Import", "Total Load Consumption",
            "Total Losses", "Total Production",
        ]

        log.write("")
        log.write("Parsed values (HA comparison order):")
        for name in order:
            if name not in results:
                continue
            item = results[name]
            regs = ",".join(str(r) for r in item["registers"]) if item["registers"] else "derived"
            raw = "--" if item["raw"] is None else str(item["raw"])
            value = fmt(item["value"], item["uom"])
            note = "  # %s" % item["note"] if item["note"] else ""
            log.write("  %-34s %-14s raw=%-10s regs=%s%s" % (name + ":", value, raw, regs, note))

        log.write("")
        log.write("Homey/HA notes:")
        log.write("  - PV1/PV2/PV Power are derived here because deye_string has voltage/current registers, not direct PV power registers.")
        log.write("  - Input Power is the direct DC input register pair 82+83.")
        log.write("  - Output AC Power uses registers 80+81; AC Output Power uses 86+87. Keep both visible for comparison.")
        log.write("  - Radiator Temperature = -100 C normally means raw register 91 is 0, so it should be treated as unavailable.")
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
        print("ERROR: %s: %s" % (exc.__class__.__name__, str(exc)))
        sys.exit(1)
PY

echo
echo " ============================================"
echo "  Done. File saved to:"
echo "  ${OUTFILE}"
echo " ============================================"
echo
