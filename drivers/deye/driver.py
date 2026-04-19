"""
Deye universal driver — supports all 4 Deye inverter models via Solarman V5.
Model selection: present all 4 options; user picks the correct one.
Capabilities are built dynamically from the selected YAML definition.
"""

import asyncio
import json
import logging
import os
import socket

from homey.driver import Driver
from app.lib.solarman_client import SolarmanClient
from app.lib.capability_map import build_capabilities, BATTERY_CAPS, GRID_METER_CAPS, GRID_CAP_REMAP

_LOGGER = logging.getLogger(__name__)

# ── Available Deye models (yaml filename → display name) ─────────────────────
DEYE_MODELS: dict[str, str] = {
    "deye_string":  "Deye String Inverter (2/4 MPPT)",
    "deye_micro":   "Deye Microinverter (4 MPPT) — SUN-M/SUN2000G3",
    "deye_hybrid":  "Deye Hybrid (Battery + 2 MPPT)",
    "deye_sg04lp3": "Deye SG04LP3 Hybrid 3-phase — SUN-8/10/12K",
}

# Only hybrid models get a separate Grid Meter device.
# String/micro inverters show grid caps directly on the main inverter tile.
HYBRID_MODELS: frozenset[str] = frozenset({"deye_hybrid", "deye_sg04lp3"})

_INVERTER_DEFS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "inverter_definitions")


def _yaml_path(model_id: str) -> str:
    return os.path.join(_INVERTER_DEFS_DIR, f"{model_id}.json")


def _load_sensors(model_id: str) -> list:
    path = _yaml_path(model_id)
    with open(path, encoding="utf-8") as f:
        definition = json.load(f)
    sensors = []
    for group in definition.get("parameters", []):
        for item in group.get("items", []):
            sensors.append(item)
    return sensors


async def _detect_model(host: str, serial: int, port: int = 8899) -> tuple[str, dict, int]:
    """
    Auto-detect the inverter model by reading all register sets and scoring each model.
    Scoring: +2 for each non-zero value from measure_power/meter_power caps, +1 for other non-zero values.
    Returns (model_id, parsed_values, best_score) for the best-scoring model (falls back to 'deye_string').
    A score of 0 means no live data was found (night-time / logger offline).

    Each model probe is capped at 10 s total (asyncio.wait_for) so that models with many
    register groups (e.g. deye_sg04lp3 has 7 requests × 5 s timeout each) cannot block
    the pairing wizard for minutes.
    """
    from app.lib.parser import ParameterParser
    from app.lib.capability_map import get_sensor_capability_map
    from app.lib.v5_transport import V5Transport

    best_model  = "deye_string"
    # Start at 0: a model must have at least one non-zero sensor value to override
    # the default. Prevents night-time probes (all zeros) from picking the wrong model.
    best_score  = 0
    best_values: dict = {}

    async def _probe(model_id: str, definition: dict) -> tuple[dict, int]:
        """Connect and read all register groups for one model. Returns (values, score)."""
        m = V5Transport(host, serial, port=port, slave=1, timeout=5.0)
        await m.connect()
        try:
            params = ParameterParser(definition)
            for req in definition["requests"]:
                start, end, fc = req["start"], req["end"], req["mb_functioncode"]
                length = end - start + 1
                for _attempt in range(2):
                    try:
                        if fc == 3:
                            raw = await m.read_holding_registers(register_addr=start, quantity=length)
                        else:
                            raw = await m.read_input_registers(register_addr=start, quantity=length)
                        params.parse(raw, start, length)
                        break
                    except Exception as req_e:
                        if _attempt == 0:
                            await asyncio.sleep(0.5)  # brief recovery before retry
                        else:
                            _LOGGER.debug(
                                f"Model probe {model_id} request [{start}-{end}] skipped: {req_e}"
                            )
        finally:
            await m.disconnect()

        values = params.get_result()
        cap_map = get_sensor_capability_map(list(
            item
            for group in definition.get("parameters", [])
            for item in group.get("items", [])
        ))
        score = 0
        for sensor_name, cap_id in cap_map.items():
            val = values.get(sensor_name)
            if val is None or val == 0:
                continue
            if cap_id in ("measure_power", "meter_power"):
                score += 2
            else:
                score += 1
        return values, score

    for model_id in DEYE_MODELS:
        path = _yaml_path(model_id)
        with open(path, encoding="utf-8") as f:
            definition = json.load(f)

        try:
            values, score = await asyncio.wait_for(
                _probe(model_id, definition), timeout=10.0
            )
            _LOGGER.info(f"Model probe {model_id}: score={score}")
            if score > best_score:
                best_score = score
                best_model = model_id
                best_values = values
        except asyncio.TimeoutError:
            _LOGGER.warning(f"Model probe {model_id} timed out after 10 s — skipped")
        except Exception as e:
            _LOGGER.debug(f"Model probe {model_id} failed: {e}")

        await asyncio.sleep(1.5)  # let logger fully close the TCP slot before next probe

    _LOGGER.info(f"Detected model: {best_model} (score={best_score})")
    return best_model, best_values, best_score


async def _discover_loggers(timeout: float = 3.0) -> list[dict]:
    """
    UDP broadcast discovery — sends both known probe payloads to port 48899.

    Two payloads are used (matching davidrapan/ha-solarman scanner.py):
      1. "WIFIKIT-214028-READ"   — standard Solarman Wi-Fi stick (LSW-3/LSE-3)
      2. "HF-A11ASSISTHREAD"     — HF-A11 module used in some older/OEM loggers

    Both are broadcast; replies are "IP,MAC,Serial" CSV strings.
    Returns deduplicated list of {ip, mac, serial}.
    """
    DISCOVERY_PORT     = 48899
    DISCOVERY_PAYLOADS = [b"WIFIKIT-214028-READ", b"HF-A11ASSISTHREAD"]
    found: list[dict] = []
    seen: set[str] = set()

    loop = asyncio.get_event_loop()

    class _Protocol(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr):
            try:
                parts = data.decode("latin-1").strip().split(",")
                if len(parts) < 3:
                    return
                ip  = parts[0].strip()
                mac = parts[1].strip()
                serial_str = parts[2].strip()
                if not ip or ip in seen or not serial_str.isdigit():
                    return
                seen.add(ip)
                found.append({"ip": ip, "mac": mac, "serial": int(serial_str)})
            except Exception:
                pass

        def error_received(self, exc):
            pass

        def connection_lost(self, exc):
            pass

    try:
        transport, _ = await loop.create_datagram_endpoint(
            _Protocol,
            local_addr=("0.0.0.0", 0),
            allow_broadcast=True,
        )
        for payload in DISCOVERY_PAYLOADS:
            transport.sendto(payload, ("<broadcast>", DISCOVERY_PORT))
            await asyncio.sleep(0.1)   # small gap so HF-A11 has time to arm
        await asyncio.sleep(timeout)
        transport.close()
    except Exception as e:
        _LOGGER.warning(f"UDP discovery error: {e}")

    return found


async def _fetch_logger_info(host: str) -> dict:
    """
    Fetch logger metadata from http://{host}/status.html (admin:admin).
    Returns a dict with keys: serial, mac, ssid, rssi (all may be None).
    """
    import re
    result: dict = {"serial": None, "mac": "", "ssid": "", "rssi": ""}
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, 80), timeout=5
        )
        request = (
            f"GET /status.html HTTP/1.0\r\n"
            f"Host: {host}\r\n"
            f"Authorization: Basic YWRtaW46YWRtaW4=\r\n"  # admin:admin
            f"\r\n"
        )
        writer.write(request.encode())
        await writer.drain()
        data = b""
        try:
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5)
                if not chunk:
                    break
                data += chunk
        except asyncio.TimeoutError:
            pass
        writer.close()
        await writer.wait_closed()

        text = data.decode("latin-1", errors="replace")

        def _var(name: str) -> str:
            m = re.search(rf'{name}\s*=\s*["\']?([^"\';\s]+)', text)
            return m.group(1) if m else ""

        sn = _var("webdata_sn")
        result["serial"] = int(sn) if sn.isdigit() else None
        result["mac"]    = _var("cover_sta_mac")
        result["ssid"]   = _var("cover_sta_ssid")
        rssi_raw         = _var("cover_sta_rssi")
        # RSSI is typically a hex string like "0x48" or decimal dBm
        if rssi_raw.startswith("0x"):
            try:
                rssi_int = int(rssi_raw, 16)
                # Convert unsigned byte to signed dBm (e.g. 0xC8 → -56 dBm)
                result["rssi"] = f"{rssi_int - 256} dBm" if rssi_int > 127 else f"{rssi_int} dBm"
            except ValueError:
                result["rssi"] = rssi_raw
        elif rssi_raw:
            result["rssi"] = f"{rssi_raw} dBm"

    except Exception as e:
        _LOGGER.debug(f"Logger info fetch failed: {e}")
    return result


async def _fetch_logger_serial(host: str) -> int | None:
    """Convenience wrapper — returns only the serial number."""
    return (await _fetch_logger_info(host))["serial"]


async def _fetch_logger_serial_udp(host: str, timeout: float = 2.0) -> int | None:
    """
    Send a UDP unicast discovery packet directly to the logger's IP and return its serial.

    The standard Solarman discovery payload works on both broadcast and unicast.
    This is more reliable than parsing the HTTP status page, which returns the
    INVERTER serial (webdata_sn) on some firmware versions instead of the
    LOGGER serial that the V5 protocol header requires.
    Returns None if the logger does not respond within timeout.
    """
    found_serial: list = [None]
    loop = asyncio.get_event_loop()

    class _Protocol(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr):
            try:
                parts = data.decode("latin-1").strip().split(",")
                if len(parts) >= 3 and parts[2].strip().isdigit():
                    found_serial[0] = int(parts[2].strip())
            except Exception:
                pass

        def error_received(self, exc):
            pass

        def connection_lost(self, exc):
            pass

    try:
        transport, _ = await loop.create_datagram_endpoint(
            _Protocol,
            local_addr=("0.0.0.0", 0),
        )
        for payload in [b"WIFIKIT-214028-READ", b"HF-A11ASSISTHREAD"]:
            transport.sendto(payload, (host, 48899))
            await asyncio.sleep(0.1)
        await asyncio.sleep(timeout)
        transport.close()
    except Exception as e:
        _LOGGER.debug(f"UDP unicast to {host}:48899 failed: {e}")

    return found_serial[0]


class DeyeDriver(Driver):

    async def on_init(self) -> None:
        self.log("DeyeDriver init")

    async def on_pair(self, session) -> None:
        self.log("onPair started")

        found: dict = {}           # stores {host, serial} after login
        confirmed: dict = {}       # stores {model_id} after confirm step

        async def on_login(data: dict) -> dict:
            """
            Fast path: discover logger + verify connectivity. No model detection here.
            Returns {host, serial} so login.html can show the tile immediately.
            Model detection runs in on_get_detected_model (called next by login.html).
            """
            nonlocal found
            host       = str(data.get("username", "")).strip()
            serial_str = str(data.get("password", "")).strip()

            # ── Auto-discovery when IP is left blank ──────────────────────────
            if not host:
                self.log("No IP entered — scanning network for Solarman loggers (UDP)...")
                loggers = await _discover_loggers(timeout=3.0)
                self.log(f"UDP scan found: {loggers}")
                if not loggers:
                    raise Exception(
                        "No Solarman logger found on network. "
                        "Enter the IP address manually."
                    )
                # Use first discovered logger — fetch additional info via HTTP
                logger_info = await _fetch_logger_info(loggers[0]["ip"])
                found = {
                    "host":   loggers[0]["ip"],
                    "serial": loggers[0]["serial"],
                    "mac":    logger_info["mac"] or loggers[0].get("mac", ""),
                    "ssid":   logger_info["ssid"],
                    "rssi":   logger_info["rssi"],
                }
                self.log(f"Auto-discovered: {found}")
                return {"host": found["host"], "serial": found["serial"]}

            # ── Manual IP entry ───────────────────────────────────────────────
            parts = host.split(".")
            if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                raise Exception(f"Invalid IP address: {host}")

            # Resolve serial
            serial: int | None = None
            if serial_str and serial_str.isdigit():
                serial = int(serial_str)
            else:
                # UDP unicast to the specific IP first — gives the LOGGER serial
                # (the V5 protocol header serial printed on the Wi-Fi stick sticker).
                # HTTP webdata_sn on some firmware returns the INVERTER serial instead,
                # which is different and causes all data reads to fail.
                self.log(f"No serial — trying UDP unicast to {host}")
                serial = await _fetch_logger_serial_udp(host, timeout=2.0)
                if serial:
                    self.log(f"Serial from UDP unicast: {serial}")
                else:
                    self.log(f"UDP unicast returned nothing — falling back to HTTP")
                    serial = await _fetch_logger_serial(host)
                    if serial:
                        self.log(f"Serial from HTTP: {serial}")

            if serial is None:
                raise Exception(
                    "Cannot auto-detect logger serial. "
                    "Enter the serial number printed on the logger sticker."
                )

            # Quick connectivity test before returning to the UI
            client = SolarmanClient(host, serial)
            ok = await client.test_connection()
            if not ok:
                raise Exception(
                    f"Cannot connect to Solarman logger at {host}. "
                    "Check IP, serial number, and that port 8899 is reachable."
                )

            found = {"host": host, "serial": serial}
            self.log(f"login OK — host:{host} serial:{serial}")
            return {"host": found["host"], "serial": found["serial"]}

        async def on_get_detected_model(data: dict = None) -> dict:
            """
            Called by login.html right after the tile appears.
            Runs model detection (may take up to ~45 s) and returns the result.
            login.html shows an inline 'Detecting model…' spinner while waiting.
            """
            if not found:
                raise Exception("No logger found — go back and try again.")
            if not confirmed:
                self.log(f"Running model detection for {found['host']}...")
                detected_id, active_values, det_score = await _detect_model(
                    found["host"], found["serial"]
                )
                self.log(f"Detection result: {detected_id} (score={det_score})")
                confirmed["model_id"] = detected_id
                confirmed["active_values"] = active_values
                confirmed["score"] = det_score
            return {
                "detected":      confirmed["model_id"],
                "models":        DEYE_MODELS,
                "auto_confirmed": confirmed.get("score", 0) > 0,
            }

        async def on_confirm_model(data: dict) -> bool:
            """Called when user clicks Confirm in confirm_model.html."""
            model_id = data.get("model", "")
            if model_id not in DEYE_MODELS:
                raise Exception(f"Unknown model: {model_id}")
            confirmed["model_id"] = model_id
            self.log(f"Model confirmed by user: {model_id}")
            return True

        async def on_list_devices(data: dict = None) -> list:
            if not found:
                raise Exception("No logger found — go back and try again.")
            if not confirmed:
                raise Exception("No model confirmed — go back and try again.")

            host         = found["host"]
            serial       = found["serial"]
            mac          = found.get("mac", "")
            ssid         = found.get("ssid", "")
            rssi         = found.get("rssi", "")
            model_id     = confirmed["model_id"]
            active_values = confirmed.get("active_values", {})

            sensors = _load_sensors(model_id)

            # Filter to sensors that returned non-zero data during detection.
            # Always keep: production totals, status sensors, lookup-based sensors,
            # and cumulative energy meters (may be 0 on new devices or at pairing time).
            _ALWAYS_KEEP = {"Today Production", "Total Production", "Running Status"}
            _METER_KEYWORDS = ("energy", "production", "charged", "discharged",
                               "import", "export", "buy", "sell")
            if active_values:
                def _keep(s: dict) -> bool:
                    if s["name"] in _ALWAYS_KEEP:
                        return True
                    if "lookup" in s:
                        return True
                    # Cumulative energy counters are always meaningful even when 0
                    name_lower = s["name"].lower()
                    if any(kw in name_lower for kw in _METER_KEYWORDS):
                        return True
                    return bool(active_values.get(s["name"]))
                sensors = [s for s in sensors if _keep(s)]

            caps, caps_opts = build_capabilities(sensors)

            # Hybrid models get a separate Grid Meter device — grid caps are split off.
            # String/micro inverters keep grid caps on the main inverter tile (no grid device).
            is_hybrid = model_id in HYBRID_MODELS

            battery_caps  = [c for c in caps if c in BATTERY_CAPS]
            grid_caps_raw = [c for c in caps if c in GRID_METER_CAPS] if is_hybrid else []
            inverter_caps = [c for c in caps
                             if c not in BATTERY_CAPS and (not is_hybrid or c not in GRID_METER_CAPS)]
            battery_opts  = {k: v for k, v in caps_opts.items() if k in BATTERY_CAPS}
            grid_opts_raw = ({k: v for k, v in caps_opts.items() if k in GRID_METER_CAPS}
                             if is_hybrid else {})
            inverter_opts = {k: v for k, v in caps_opts.items()
                             if k not in BATTERY_CAPS and (not is_hybrid or k not in GRID_METER_CAPS)}

            # Add measure_power.solar for inverters with PV sub-capabilities or Input Power.
            # Points Energy Dashboard to solar-only production (not AC output).
            # Note: Input Power (DC from PV array) also maps to measure_power.solar via
            # capability_map — avoid inserting a duplicate if it's already present.
            pv_caps = [c for c in inverter_caps if c.startswith("measure_power.pv")]
            has_solar = "measure_power.solar" in inverter_caps
            if pv_caps and not has_solar:
                inverter_caps = ["measure_power.solar"] + inverter_caps
                inverter_opts["measure_power.solar"] = {"title": {"en": "Solar Power (DC Input)"}}
            elif has_solar and "measure_power.solar" not in inverter_opts:
                inverter_opts["measure_power.solar"] = {"title": {"en": "Solar Power (DC Input)"}}
            produced_cap = "measure_power.solar" if (pv_caps or has_solar) else "measure_power"

            base_settings = {
                "host":            host,
                "loggerSerial":    serial,
                "port":            8899,
                "slaveId":         1,
                "model":           model_id,
                "pollingInterval": 60,
                "loggerMac":       mac,
                "wifiSsid":        ssid,
                "wifiRssi":        rssi,
            }

            self.log(f"list_devices — model:{model_id} host:{host} "
                     f"inverter_caps:{len(inverter_caps)} battery_caps:{len(battery_caps)} "
                     f"grid_caps:{len(grid_caps_raw)}")

            devices = [{
                "name": DEYE_MODELS[model_id],
                "icon": "/drivers/deye/assets/icon_inverter.svg",
                "data": {"id": f"deye_{serial}_inverter"},
                "capabilities": inverter_caps,
                "capabilitiesOptions": inverter_opts,
                "energy": {
                    "measurePowerProducedCapability": produced_cap,
                    "meterPowerExportedCapability":   "meter_power",
                },
                "settings": {**base_settings, "device_type": "inverter", "is_hybrid": bool(battery_caps)},
            }]

            if battery_caps:
                batt_caps_final = list(battery_caps)
                batt_opts_final = dict(battery_opts)
                # Energy Dashboard needs measure_power to track charge/discharge flow
                if "measure_power.battery" in batt_caps_final and "measure_power" not in batt_caps_final:
                    batt_caps_final.insert(0, "measure_power")
                    batt_opts_final["measure_power"] = {"title": {"en": "Battery Power"}}

                devices.append({
                    "name": f"{DEYE_MODELS[model_id]} — Battery",
                    "data": {"id": f"deye_{serial}_battery"},
                    "class": "battery",
                    "capabilities": batt_caps_final,
                    "capabilitiesOptions": batt_opts_final,
                    "energy": {
                        "homeBattery": True,
                        "meterPowerImportedCapability": "meter_power.battery_charged",
                        "meterPowerExportedCapability": "meter_power.battery_discharged",
                    },
                    "settings": {**base_settings, "device_type": "battery"},
                })
                self.log(f"Battery device — caps:{batt_caps_final}")
            else:
                self.log("No battery caps detected — battery device skipped")

            if grid_caps_raw:
                # Remap internal cap IDs to standard Homey Energy names for a cumulative sensor
                grid_caps_final = [GRID_CAP_REMAP.get(c, c) for c in grid_caps_raw]
                grid_opts_final = {GRID_CAP_REMAP.get(k, k): v for k, v in grid_opts_raw.items()}
                # Fix titles for remapped caps
                if "meter_power" in grid_opts_final:
                    grid_opts_final["meter_power"]["title"]["en"] = "Grid Import Energy"
                if "meter_power.exported" in grid_opts_final:
                    grid_opts_final["meter_power.exported"] = {"title": {"en": "Grid Export Energy"}}
                if "measure_power.grid" in grid_opts_final:
                    grid_opts_final["measure_power.grid"]["title"]["en"] = "Grid Power"

                # Add base measure_power cap so Homey Energy can track live grid consumption.
                # measurePowerConsumedCapability requires a base measure_power (not a sub-cap).
                if "measure_power.grid" in grid_caps_final and "measure_power" not in grid_caps_final:
                    grid_caps_final = ["measure_power"] + grid_caps_final
                    grid_opts_final["measure_power"] = {"title": {"en": "Grid Power (Live)"}}

                devices.append({
                    "name": f"{DEYE_MODELS[model_id]} — Grid",
                    "icon": "/drivers/deye/assets/icon_inverter.svg",
                    "data": {"id": f"deye_{serial}_grid"},
                    "class": "sensor",
                    "capabilities": grid_caps_final,
                    "capabilitiesOptions": grid_opts_final,
                    "energy": {
                        "cumulative": True,
                        "cumulativeImportedCapability": "meter_power",
                        "cumulativeExportedCapability": "meter_power.exported",
                        "measurePowerConsumedCapability": "measure_power",
                    },
                    "settings": {**base_settings, "device_type": "grid_meter"},
                })
                self.log(f"Grid meter device — caps:{grid_caps_final}")
            else:
                self.log("No grid caps detected — grid meter device skipped")

            return devices

        session.set_handler("login", on_login)
        session.set_handler("get_detected_model", on_get_detected_model)
        session.set_handler("confirm_model", on_confirm_model)
        session.set_handler("list_devices", on_list_devices)

    async def on_repair(self, session, device) -> None:
        """
        Repair flow — lets the user re-detect the model or fix the logger IP
        without removing and re-adding the device.
        Only updates device settings (model, host). Does NOT add or remove
        capabilities — changing between string and hybrid still requires re-pairing.
        """
        self.log(f"onRepair started for device {device.get_id()}")

        async def on_get_current(data=None) -> dict:
            return {
                "host":   device.get_setting("host") or "",
                "model":  device.get_setting("model") or "deye_string",
                "models": DEYE_MODELS,
            }

        async def on_run_detection(data=None) -> dict:
            host   = device.get_setting("host") or ""
            serial = int(str(device.get_setting("loggerSerial") or "0").strip() or 0)
            if not host:
                raise Exception("No IP configured — enter an IP address and save first.")
            self.log(f"Repair: running detection on {host} serial={serial}")
            detected, _, score = await _detect_model(host, serial)
            self.log(f"Repair detection: {detected} (score={score})")
            return {
                "detected":      detected,
                "models":        DEYE_MODELS,
                "auto_confirmed": score > 0,
            }

        async def on_save_repair(data: dict) -> bool:
            model = str(data.get("model", "")).strip()
            host  = str(data.get("host",  "")).strip()
            if model and model not in DEYE_MODELS:
                raise Exception(f"Unknown model: {model}")
            new_settings: dict = {}
            if model:
                new_settings["model"] = model
            if host:
                parts = host.split(".")
                if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                    raise Exception(f"Invalid IP address: {host}")
                new_settings["host"] = host
            if not new_settings:
                raise Exception("Nothing to save.")
            self.log(f"Repair: applying settings {new_settings}")
            await device.set_settings(new_settings)
            return True

        session.set_handler("get_current",   on_get_current)
        session.set_handler("run_detection", on_run_detection)
        session.set_handler("save_repair",   on_save_repair)


homey_export = DeyeDriver
