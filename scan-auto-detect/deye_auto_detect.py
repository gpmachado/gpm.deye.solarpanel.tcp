#!/usr/bin/env python3
"""
Robust terminal-side Deye auto-detection tool.

Shared launcher target for macOS/Linux and Windows.
Uses the same local inverter definition JSON files as the Homey app.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import socket
import struct
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DEFS_DIR = PROJECT_DIR / "inverter_definitions"

PORT = 8899
SLAVE = 1
TIMEOUT = 8.0
RETRIES = 3

MODELS = {
    "deye_string": "String Inverter (2/4 MPPT)",
    "deye_hybrid": "Hybrid (Battery + 2 MPPT)",
    "deye_micro": "Microinverter (4 MPPT) - SUN-M/SUN2000G3",
    "deye_sg04lp3": "Hybrid 3-phase - SG04LP3",
}

DISCOVERY_PAYLOADS = (b"WIFIKIT-214028-READ", b"HF-A11ASSISTHREAD")

V5_START = 0xA5
V5_END = 0x15
V5_CTRL_REQ = struct.pack("<H", 0x4510)
V5_CTRL_RESP = struct.pack("<H", 0x1510)


class Tee:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("w", encoding="utf-8")

    def write(self, text: str = "") -> None:
        print(text)
        self._file.write(text + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else crc >> 1
    return crc


def v5_checksum(frame: bytes) -> int:
    return sum(frame[i] & 0xFF for i in range(1, len(frame) - 2)) & 0xFF


def build_modbus_request(slave: int, fc: int, start: int, count: int) -> bytes:
    msg = struct.pack(">BBHH", slave, fc, start, count)
    return msg + struct.pack("<H", crc16_modbus(msg))


def build_v5_frame(serial: int, seq: int, modbus_payload: bytes) -> bytearray:
    payload = bytearray(bytes([0x02]) + bytes(14) + modbus_payload)
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


def parse_v5_response(frame: bytes) -> bytes:
    if len(frame) < 29 or frame[0] != V5_START or frame[-1] != V5_END:
        raise ValueError(f"Invalid V5 frame ({len(frame)} bytes)")
    modbus = frame[25:-2]
    if len(modbus) < 5:
        raise ValueError(f"Modbus payload too short: {len(modbus)} bytes")
    return bytes(modbus)


def parse_modbus_registers(data: bytes, count: int) -> list[int]:
    if len(data) < 5:
        raise ValueError(f"Modbus response too short: {len(data)} bytes")
    if data[1] & 0x80:
        raise ValueError(f"Modbus exception code 0x{data[2]:02x}")
    byte_count = data[2]
    register_count = min(count, byte_count // 2)
    if register_count < count:
        raise ValueError(f"Short response: got {register_count}/{count} registers")
    return [
        struct.unpack(">H", data[3 + i * 2: 5 + i * 2])[0]
        for i in range(register_count)
    ]


class V5Transport:
    def __init__(self, host: str, serial: int):
        self.host = host
        self.serial = serial
        self.seq = 0
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, PORT, family=socket.AF_INET),
            timeout=TIMEOUT,
        )

    async def disconnect(self) -> None:
        if self.writer:
            try:
                self.writer.close()
                await asyncio.wait_for(self.writer.wait_closed(), timeout=2.0)
            except Exception:
                pass
        self.reader = None
        self.writer = None

    def _next_seq(self) -> int:
        self.seq = (self.seq + 1) & 0xFF
        return self.seq

    async def read_registers(self, fc: int, start: int, count: int) -> list[int]:
        if not self.writer:
            raise ConnectionError("Not connected")
        seq = self._next_seq()
        request = build_modbus_request(SLAVE, fc, start, count)
        frame = build_v5_frame(self.serial, seq, request)
        self.writer.write(frame)
        await self.writer.drain()
        response = await self._read_v5_frame()
        modbus = parse_v5_response(response)
        return parse_modbus_registers(modbus, count)

    async def _read_v5_frame(self) -> bytes:
        if not self.reader:
            raise ConnectionError("Not connected")
        for _ in range(5):
            header = await asyncio.wait_for(self.reader.readexactly(11), timeout=TIMEOUT)
            if header[0] != V5_START:
                raise ValueError(f"Unexpected V5 start: 0x{header[0]:02x}")
            payload_len = struct.unpack("<H", header[1:3])[0]
            rest = await asyncio.wait_for(
                self.reader.readexactly(payload_len + 2), timeout=TIMEOUT,
            )
            frame = header + rest
            if frame[3:5] == V5_CTRL_RESP:
                return frame
        raise TimeoutError("No V5 data response after 5 frames")


async def read_block(
    host: str, serial: int, fc: int, start: int, end: int, log: Tee | None = None,
) -> list[int]:
    count = end - start + 1
    label = f"fc={fc} [{start}-{end}]"
    last_err: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        transport = V5Transport(host, serial)
        try:
            await transport.connect()
            values = await transport.read_registers(fc, start, count)
            await transport.disconnect()
            return values
        except Exception as exc:
            last_err = exc
            if log:
                log.write(f"  {label} attempt {attempt}/{RETRIES}: {type(exc).__name__}: {exc}")
            await transport.disconnect()
            await asyncio.sleep(0.8 * attempt)
    assert last_err is not None
    raise last_err


def load_definition(model_id: str) -> dict:
    path = DEFS_DIR / f"{model_id}.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def lookup_value(value: int, options: list[dict]) -> str:
    for option in options:
        if option["key"] == value:
            return option["value"]
    return str(value)


def parse_sensor(defn: dict, all_regs: dict[int, int]) -> tuple[int | None, object | None]:
    regs = defn["registers"]
    rule = defn.get("rule", 1)
    scale = defn.get("scale", 1)
    for reg in regs:
        if reg not in all_regs:
            return None, None

    raw = 0
    shift = 0
    bits = 0
    for reg in regs:
        raw += (all_regs[reg] & 0xFFFF) << shift
        shift += 16
        bits += 16

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
        validation = defn["validation"]
        if "min" in validation and value < validation["min"]:
            return raw, None
        if "max" in validation and value > validation["max"]:
            return raw, None

    if isinstance(value, float) and value == int(value):
        value = int(value)
    elif isinstance(value, float):
        value = round(value, 3)
    return raw, value


def num(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def between(value: object, low: float, high: float) -> bool:
    v = num(value)
    return v is not None and low <= v <= high


def abs_between(value: object, low: float, high: float) -> bool:
    v = num(value)
    return v is not None and low <= abs(v) <= high


def first_value(results: dict, *names: str):
    for name in names:
        if name in results:
            return results[name]["value"]
    return None


def fmt(value: object, uom: str = "") -> str:
    if value is None:
        return "--"
    if isinstance(value, str):
        return value
    if isinstance(value, float):
        text = f"{value:.3f}".rstrip("0").rstrip(".")
    else:
        text = str(value)
    return f"{text} {uom}".strip()


def add_derived(results: dict, name: str, value: object, uom: str, note: str) -> None:
    results[name] = {
        "raw": None,
        "value": value,
        "uom": uom,
        "registers": [],
        "note": note,
    }


def is_valid_ipv4(host: str) -> bool:
    parts = host.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


async def discover_loggers(timeout: float = 3.0) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()
    loop = asyncio.get_event_loop()

    class _Protocol(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr):
            try:
                parts = data.decode("latin-1").strip().split(",")
                if len(parts) < 3:
                    return
                ip = parts[0].strip()
                mac = parts[1].strip()
                serial = parts[2].strip()
                if not ip or ip in seen or not serial.isdigit():
                    return
                seen.add(ip)
                found.append({"ip": ip, "mac": mac, "serial": int(serial)})
            except Exception:
                pass

        def error_received(self, exc): pass
        def connection_lost(self, exc): pass

    try:
        transport, _ = await loop.create_datagram_endpoint(
            _Protocol, local_addr=("0.0.0.0", 0), allow_broadcast=True,
        )
        for payload in DISCOVERY_PAYLOADS:
            transport.sendto(payload, ("<broadcast>", 48899))
            await asyncio.sleep(0.1)
        await asyncio.sleep(timeout)
        transport.close()
    except Exception as exc:
        print(f" [WARNING] UDP scan error: {exc}")
    return found


async def fetch_logger_info(host: str) -> dict:
    result = {"serial": None, "mac": "", "ssid": "", "rssi": ""}
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, 80), timeout=5.0,
        )
        request = (
            f"GET /status.html HTTP/1.0\r\n"
            f"Host: {host}\r\n"
            f"Authorization: Basic YWRtaW46YWRtaW4=\r\n"
            f"\r\n"
        )
        writer.write(request.encode())
        await writer.drain()
        data = b""
        try:
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                data += chunk
        except asyncio.TimeoutError:
            pass
        writer.close()
        await writer.wait_closed()

        text = data.decode("latin-1", errors="replace")

        def _var(name: str) -> str:
            match = re.search(rf'{name}\s*=\s*["\']?([^"\';\s]+)', text)
            return match.group(1) if match else ""

        serial = _var("webdata_sn")
        result["serial"] = int(serial) if serial.isdigit() else None
        result["mac"] = _var("cover_sta_mac")
        result["ssid"] = _var("cover_sta_ssid")
        rssi_raw = _var("cover_sta_rssi")
        if rssi_raw.startswith("0x"):
            try:
                rssi_int = int(rssi_raw, 16)
                result["rssi"] = f"{rssi_int - 256} dBm" if rssi_int > 127 else f"{rssi_int} dBm"
            except ValueError:
                result["rssi"] = rssi_raw
        elif rssi_raw:
            result["rssi"] = f"{rssi_raw} dBm"
    except Exception:
        pass
    return result


async def fetch_logger_serial_udp(host: str, timeout: float = 2.0) -> int | None:
    found_serial: list[int | None] = [None]
    loop = asyncio.get_event_loop()

    class _Protocol(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr):
            try:
                parts = data.decode("latin-1").strip().split(",")
                if len(parts) >= 3 and parts[2].strip().isdigit():
                    found_serial[0] = int(parts[2].strip())
            except Exception:
                pass

        def error_received(self, exc): pass
        def connection_lost(self, exc): pass

    try:
        transport, _ = await loop.create_datagram_endpoint(
            _Protocol, local_addr=("0.0.0.0", 0),
        )
        for payload in DISCOVERY_PAYLOADS:
            transport.sendto(payload, (host, 48899))
            await asyncio.sleep(0.1)
        await asyncio.sleep(timeout)
        transport.close()
    except Exception:
        pass
    return found_serial[0]


def score_detected_model(model_id: str, results: dict) -> tuple[int, list[str], list[str]]:
    score = 0
    reasons: list[str] = []
    penalties: list[str] = []

    def add(points: int, reason: str) -> None:
        nonlocal score
        score += points
        reasons.append(f"+{points} {reason}")

    def penalize(points: int, reason: str) -> None:
        nonlocal score
        score -= points
        penalties.append(f"-{points} {reason}")

    status = first_value(results, "Running Status", "Status")
    if isinstance(status, str):
        add(3, f"status={status}")

    frequency = first_value(results, "Grid Frequency", "Frequency", "Output Frequency")
    if between(frequency, 45, 65):
        add(4, f"frequency plausible ({frequency})")

    daily_prod = first_value(results, "Today Production", "Daily Production")
    if between(daily_prod, 0, 250):
        add(4, f"daily production plausible ({daily_prod})")

    total_prod = first_value(results, "Total Production")
    if between(total_prod, 0.1, 10_000_000):
        add(4, f"total production plausible ({total_prod})")

    pv_voltage_count = 0
    pv_current_count = 0
    for idx in (1, 2, 3, 4):
        if between(first_value(results, f"PV{idx} Voltage"), 20, 700):
            pv_voltage_count += 1
        if between(first_value(results, f"PV{idx} Current"), 0, 80):
            pv_current_count += 1
    if pv_voltage_count:
        add(pv_voltage_count * 2, f"{pv_voltage_count} PV voltages plausible")
    if pv_current_count:
        add(pv_current_count, f"{pv_current_count} PV currents plausible")

    grid_voltages = sum(
        1 for name in ("Grid Voltage", "Grid L1 Voltage", "Grid L2 Voltage", "Grid L3 Voltage")
        if between(first_value(results, name), 80, 300)
    )
    if grid_voltages:
        add(min(grid_voltages, 3) * 2, f"{grid_voltages} grid voltages plausible")

    temp_hits = sum(
        1 for name in ("DC Temperature", "Radiator Temperature", "Battery Temperature")
        if between(first_value(results, name), -30, 120)
    )
    if temp_hits:
        add(temp_hits, f"{temp_hits} temperatures plausible")

    input_power = first_value(results, "Input Power")
    output_ac = first_value(results, "Output AC Power", "AC Output Power")
    if between(input_power, 0, 200_000):
        add(4, f"input power plausible ({input_power})")
    if between(output_ac, 0, 200_000):
        add(4, f"output power plausible ({output_ac})")

    if model_id == "deye_string":
        pv_total = 0.0
        active = 0
        for idx in (1, 2, 3, 4):
            pv_v = first_value(results, f"PV{idx} Voltage")
            pv_a = first_value(results, f"PV{idx} Current")
            if between(pv_v, 20, 700) and between(pv_a, 0, 80):
                pv_total += float(pv_v) * float(pv_a)
                active += 1
        if active:
            add(8 + active, f"PV VxI signature across {active} strings")
        if between(pv_total, 20, 200_000):
            add(6, f"derived PV total plausible ({round(pv_total, 1)} W)")
        if between(input_power, 20, 200_000) and between(output_ac, 0, 200_000):
            add(6, "string-style DC input and AC output present")

    elif model_id == "deye_micro":
        micro_power = first_value(results, "Micro-inverter Power")
        if between(micro_power, 1, 5_000):
            add(12, f"micro-inverter power present ({micro_power})")
        if between(output_ac, 1, 5_000):
            add(6, f"micro-sized AC output ({output_ac})")
        if between(first_value(results, "Grid Voltage"), 80, 300):
            add(4, "single-phase grid voltage present")

    elif model_id == "deye_hybrid":
        battery_v = first_value(results, "Battery Voltage")
        battery_soc = first_value(results, "Battery SOC")
        battery_a = first_value(results, "Battery Current")
        battery_w = first_value(results, "Battery Power")
        direct_pv = sum(
            1 for idx in (1, 2, 3, 4)
            if between(first_value(results, f"PV{idx} Power"), 1, 50_000)
        )
        if direct_pv:
            add(direct_pv * 4, f"{direct_pv} direct PV power registers plausible")
        if between(battery_v, 35, 65):
            add(10, f"battery voltage plausible ({battery_v})")
        if between(battery_soc, 1, 100):
            add(8, f"battery SOC plausible ({battery_soc})")
        if abs_between(battery_a, 0.05, 600):
            add(5, f"battery current plausible ({battery_a})")
        if abs_between(battery_w, 20, 80_000):
            add(7, f"battery power plausible ({battery_w})")

        pv2_v = first_value(results, "PV2 Voltage")
        pv2_a = first_value(results, "PV2 Current")
        pv2_w = first_value(results, "PV2 Power")
        if between(pv2_v, 0, 5) and between(pv2_a, 0.5, 80) and between(pv2_w, 500, 80_000):
            penalize(12, "PV2 direct-power signature is inconsistent with near-zero voltage")

        grid_v = first_value(results, "Grid L1 Voltage")
        grid_a = first_value(results, "Grid L1 Current")
        if between(grid_v, 0, 10) and abs_between(grid_a, 1, 500):
            penalize(10, "hybrid grid voltage/current pair looks implausible")

    elif model_id == "deye_sg04lp3":
        battery_v = first_value(results, "Battery Voltage")
        battery_soc = first_value(results, "Battery SOC")
        if between(battery_v, 35, 800):
            add(8, f"battery voltage plausible ({battery_v})")
        if between(battery_soc, 1, 100):
            add(6, f"battery SOC plausible ({battery_soc})")
        phases = sum(
            1 for name in ("Grid L1 Voltage", "Grid L2 Voltage", "Grid L3 Voltage")
            if between(first_value(results, name), 80, 300)
        )
        if phases >= 2:
            add(10, f"{phases} phase voltages present")

    return score, reasons, penalties


async def probe_model(host: str, serial: int, model_id: str, log: Tee | None = None):
    definition = load_definition(model_id)
    all_regs: dict[int, int] = {}
    for req in definition["requests"]:
        start, end, fc = req["start"], req["end"], req["mb_functioncode"]
        try:
            values = await asyncio.wait_for(
                read_block(host, serial, fc, start, end), timeout=10.0,
            )
            for i, value in enumerate(values):
                all_regs[start + i] = value
        except Exception as exc:
            if log:
                log.write(f"    request [{start}-{end}] skipped: {type(exc).__name__}: {exc}")

    results = {}
    for group in definition["parameters"]:
        for sensor in group["items"]:
            raw, value = parse_sensor(sensor, all_regs)
            if value is not None:
                results[sensor["name"]] = {
                    "raw": raw,
                    "value": value,
                    "uom": sensor.get("uom", ""),
                    "registers": sensor["registers"],
                    "note": "",
                    "group": group.get("group", ""),
                }
    return definition, all_regs, results


async def detect_model(host: str, serial: int, log: Tee) -> str:
    log.write(" Auto-detecting model - probing each type...")
    log.write("")
    best_model = "deye_string"
    best_score = -999
    for model_id in MODELS:
        _, _, results = await probe_model(host, serial, model_id, log)
        score, reasons, penalties = score_detected_model(model_id, results)
        log.write(f"  [{model_id}] score={score}")
        for reason in reasons[:6]:
            log.write("    " + reason)
        for penalty in penalties[:4]:
            log.write("    " + penalty)
        if score > best_score:
            best_score = score
            best_model = model_id
        await asyncio.sleep(1.5)

    log.write("")
    if best_score <= 0:
        log.write(" Warning: weak or night-time data - defaulting to deye_string")
        best_model = "deye_string"
    else:
        log.write(f" Detected: {best_model} (score={best_score})")
    log.write("")
    return best_model


async def test_connection(host: str, serial: int) -> None:
    await asyncio.wait_for(read_block(host, serial, 3, 3, 3), timeout=10.0)


async def prompt_logger() -> tuple[str, int]:
    print(" Logger IP Address (leave blank to auto-scan): ", end="", flush=True)
    host = input().strip()

    if not host:
        print(" Scanning network for Solarman loggers (UDP broadcast)...", flush=True)
        loggers = await discover_loggers(timeout=3.0)
        if not loggers:
            print(" [ERROR] No loggers found. Enter IP manually.")
            raise SystemExit(1)
        if len(loggers) == 1:
            logger = loggers[0]
            print(f" Found: {logger['ip']}  MAC:{logger['mac']}  Serial:{logger['serial']}")
            return logger["ip"], logger["serial"]

        print(f" Found {len(loggers)} logger(s):")
        for idx, logger in enumerate(loggers, 1):
            print(f"   [{idx}] {logger['ip']}  MAC:{logger['mac']}  Serial:{logger['serial']}")
        print(f" Choice [1-{len(loggers)}, default=1]: ", end="", flush=True)
        choice = input().strip() or "1"
        try:
            logger = loggers[int(choice) - 1]
        except (IndexError, ValueError):
            print(" [ERROR] Invalid choice")
            raise SystemExit(1)
        return logger["ip"], logger["serial"]

    if not is_valid_ipv4(host):
        print(f" [ERROR] Invalid IP: {host}")
        raise SystemExit(1)

    print(" Logger Serial Number (optional): ", end="", flush=True)
    serial_str = input().strip()
    if serial_str:
        if not serial_str.isdigit():
            print(" [ERROR] Serial must be numeric")
            raise SystemExit(1)
        return host, int(serial_str)

    print(f" Trying UDP unicast serial detection on {host}...", flush=True)
    serial = await fetch_logger_serial_udp(host, timeout=2.0)
    if serial:
        print(f" Found logger serial via UDP: {serial}")
        return host, serial

    print(" UDP unicast returned nothing - trying HTTP status page...", flush=True)
    info = await fetch_logger_info(host)
    if info["serial"] is not None:
        print(f" Found serial via HTTP: {info['serial']}")
        return host, int(info["serial"])

    print(" [ERROR] Could not auto-detect the logger serial for that IP.")
    raise SystemExit(1)


def prompt_model() -> str:
    print()
    print(" Select model:")
    for idx, (model_id, label) in enumerate(MODELS.items(), 1):
        print(f"   [{idx}] {model_id:<14} - {label}")
    print("   [5] auto-detect   - probe inverter to determine model")
    print()
    print(" Choice [1-5, default=5]: ", end="", flush=True)
    choice = input().strip() or "5"
    keys = list(MODELS.keys())
    if choice == "5":
        return "auto"
    try:
        index = int(choice) - 1
        if 0 <= index < len(keys):
            return keys[index]
    except ValueError:
        pass
    print(" [ERROR] Invalid choice")
    raise SystemExit(1)


def get_output_path(prefix: str, host: str) -> Path:
    home = Path.home()
    desktop = home / "Desktop"
    out_dir = desktop if desktop.is_dir() else home
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return out_dir / f"{prefix}_scan_{host}_{stamp}.txt"


async def run_scan() -> int:
    host, serial = await prompt_logger()
    model = prompt_model()
    output_prefix = model if model != "auto" else "deye"
    outfile = get_output_path(output_prefix, host)

    print()
    print(f" Testing connection to {host}:8899  serial={serial} ...")
    try:
        await test_connection(host, serial)
        print(" Connection OK")
    except Exception as exc:
        print(f" [ERROR] Connection test failed: {type(exc).__name__}: {exc}")
        return 1

    print()
    print(f" Scanning {host}  serial={serial}  model={model}")
    print(f" Output:  {outfile}")
    print()

    log = Tee(outfile)
    started = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        model_id = model
        if model_id == "auto":
            log.write(f"Deye Universal Scan - {started}")
            log.write(f"Host: {host}  Serial: {serial}")
            log.write("Transport: embedded Solarman V5 TCP, no pysolarmanv5")
            log.write("=" * 72)
            log.write("")
            model_id = await detect_model(host, serial, log)

        definition, all_registers, results = await probe_model(host, serial, model_id)
        model_name = MODELS.get(model_id, model_id)

        log.write(f"Deye Universal Scan - {started}")
        log.write(f"Host: {host}  Serial: {serial}  Model: {model_id}")
        log.write(f"Description: {model_name}")
        log.write("Transport: embedded Solarman V5 TCP, no pysolarmanv5")
        log.write("=" * 72)
        log.write("")

        for req in definition["requests"]:
            start, end, fc = req["start"], req["end"], req["mb_functioncode"]
            count = end - start + 1
            log.write(f"Reading fc={fc} registers [{start}-{end}]...")
            try:
                values = await read_block(host, serial, fc, start, end, log)
                for i, value in enumerate(values):
                    all_registers[start + i] = value
                log.write(f"  OK: {count} registers")
            except Exception as exc:
                log.write(f"  FAILED: {exc}")
            await asyncio.sleep(0.3)

        log.write("")
        log.write("Raw registers (non-zero):")
        for reg in sorted(all_registers):
            value = all_registers[reg]
            if value:
                log.write(f"  reg {reg:5d} (0x{reg:04X}) = {value:7d}  (0x{value:04X})")

        parsed_results = {}
        for group in definition["parameters"]:
            group_name = group.get("group", "")
            for sensor in group["items"]:
                raw, value = parse_sensor(sensor, all_registers)
                if value is not None:
                    parsed_results[sensor["name"]] = {
                        "raw": raw,
                        "value": value,
                        "uom": sensor.get("uom", ""),
                        "registers": sensor["registers"],
                        "note": "",
                        "group": group_name,
                    }

        if model_id in ("deye_string", "deye_micro"):
            for idx in (1, 2, 3, 4):
                pv_v = parsed_results.get(f"PV{idx} Voltage", {}).get("value")
                pv_a = parsed_results.get(f"PV{idx} Current", {}).get("value")
                if pv_v is not None and pv_a is not None:
                    power = round(float(pv_v) * float(pv_a), 1)
                    add_derived(
                        parsed_results,
                        f"PV{idx} Power",
                        power,
                        "W",
                        f"derived: PV{idx} Voltage x PV{idx} Current",
                    )
            pv_total = sum(
                parsed_results[f"PV{i} Power"]["value"]
                for i in (1, 2, 3, 4)
                if f"PV{i} Power" in parsed_results
            )
            if pv_total:
                add_derived(
                    parsed_results,
                    "PV Power Total",
                    pv_total,
                    "W",
                    "derived: sum of PV1..PV4 Power",
                )

        log.write("")
        log.write("Parsed values by group:")
        log.write("")
        ordered_names: list[tuple[str, list[str]]] = []
        for group in definition["parameters"]:
            group_name = group.get("group", "")
            expanded = []
            for sensor in group["items"]:
                name = sensor["name"]
                expanded.append(name)
                for idx in (1, 2, 3, 4):
                    if name == f"PV{idx} Current":
                        pv_power_name = f"PV{idx} Power"
                        if pv_power_name in parsed_results:
                            expanded.append(pv_power_name)
            ordered_names.append((group_name, expanded))

        for idx, (group_name, names) in enumerate(ordered_names):
            if group_name.lower() in ("solar", "pv", "") and "PV Power Total" in parsed_results:
                if "PV Power Total" not in names:
                    names.append("PV Power Total")
                ordered_names[idx] = (group_name, names)
                break

        for group_name, names in ordered_names:
            log.write(f"[{group_name or 'General'}]")
            seen = set()
            for name in names:
                if name in seen or name not in parsed_results:
                    continue
                seen.add(name)
                item = parsed_results[name]
                regs = ",".join(str(r) for r in item["registers"]) if item["registers"] else "derived"
                note = f"  # {item['note']}" if item["note"] else ""
                log.write(
                    f"  {name + ':':34s} {fmt(item['value'], item['uom']):16s} "
                    f"raw={str(item['raw'] if item['raw'] is not None else '--'):10s} regs={regs}{note}"
                )
            log.write("")

        log.write(f"Done. File saved to: {outfile}")
        return 0
    finally:
        log.close()


def main() -> int:
    try:
        return asyncio.run(run_scan())
    except KeyboardInterrupt:
        print("Interrupted.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
