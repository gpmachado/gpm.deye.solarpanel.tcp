"""
Deye device — inverter or battery.
Device type is stored in the 'device_type' setting ('inverter' or 'battery').
Both types subscribe to a SharedPoller so only one TCP connection is used per logger.

Night backoff (astral sunrise/sunset) is applied only to the inverter device —
the battery device keeps polling through the night to track SOC and discharge.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

from astral import LocationInfo
from astral.sun import sun

from homey.device import Device
from app.lib.capability_map import get_sensor_capability_map, BATTERY_CAPS, GRID_METER_CAPS, GRID_CAP_REMAP
from app.lib import shared_poller as _poller_mod

_LOGGER = logging.getLogger(__name__)

_BACKOFF_NIGHT   = 30 * 60   # 30 min — inverter expected offline at night
_ERROR_THRESHOLD = 5          # consecutive failures before set_unavailable

# Capabilities zeroed on the inverter device at night
_INVERTER_NIGHT_ZERO = frozenset({
    "measure_power",
    "measure_power.pv1", "measure_power.pv2",
    "measure_power.pv3", "measure_power.pv4",
    "measure_power.load", "measure_power.grid", "measure_power.micro",
    "measure_power.solar",
    "measure_voltage.pv1", "measure_voltage.pv2",
    "measure_voltage.pv3", "measure_voltage.pv4",
    "measure_voltage.grid",
    "measure_voltage.l1", "measure_voltage.l2", "measure_voltage.l3",
    "measure_current.pv1", "measure_current.pv2",
    "measure_current.pv3", "measure_current.pv4",
    "measure_current.grid",
    "measure_current.l1", "measure_current.l2", "measure_current.l3",
    "measure_frequency",
    "measure_temperature",
})

# Capabilities zeroed on the battery device at night (optional — battery may
# still be discharging, but if inverter is off these will all be 0 anyway)
_BATTERY_NIGHT_ZERO = frozenset({
    "measure_power.battery",
    "measure_voltage.battery",
    "measure_current.battery",
})


class DeyeDevice(Device):

    _sensor_cap_map: dict = {}
    _consecutive_errors: int = 0
    _last_power_w: float = 0.0
    _is_battery: bool = False
    _is_grid_meter: bool = False
    _was_producing: bool = False
    _grid_was_available: bool = True
    _is_unavailable: bool = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def on_init(self) -> None:
        device_type = self.get_setting("device_type") or "inverter"
        self._is_battery    = (device_type == "battery")
        self._is_grid_meter = (device_type == "grid_meter")
        host = self.get_setting("host") or ""
        self.log(f"DeyeDevice init — type={device_type} host={host}")

        self._build_sensor_map()

        # Grid meters paired before v1.3.2 don't have measure_power — add it now.
        # Required for measurePowerConsumedCapability (live grid W in Homey Energy Dashboard).
        if (self._is_grid_meter
                and self.has_capability("measure_power.grid")
                and not self.has_capability("measure_power")):
            try:
                await self.addCapability("measure_power")
                self.log("Added measure_power cap to grid meter (upgraded from pre-1.3.2)")
            except Exception as e:
                _LOGGER.warning(f"Could not add measure_power to grid meter: {e}")

        await self._ensure_pv_structural_caps()

        # Initialise synthetic inverter caps to 0 so Energy Dashboard never shows null
        # before the first successful poll.
        if not self._is_battery and not self._is_grid_meter:
            for cap in ("measure_power.solar", "measure_power.load", "measure_power"):
                if self.has_capability(cap):
                    try:
                        await self._set(cap, 0)
                    except Exception:
                        pass

        self._attach_poller()
        if not self._is_battery:
            asyncio.create_task(self._refresh_wifi_info(host))

    async def on_settings(self, old_settings=None, new_settings=None, changed_keys=None) -> None:
        # Homey Python SDK passes changed_keys as a keyword argument list.
        # Guard against None in case the SDK calls with no changedKeys.
        keys = changed_keys or []
        if any(k in keys for k in (
            "host", "loggerSerial", "port", "slaveId", "model", "pollingInterval",
            "solar_latitude", "solar_longitude",
        )):
            self._detach_poller()
            self._build_sensor_map()
            self._attach_poller()

            # Restart Wi-Fi info task if IP was changed (only for main/inverter device)
            if "host" in keys and not self._is_battery:
                host = self.get_setting("host") or ""
                asyncio.create_task(self._refresh_wifi_info(host))

    async def on_deleted(self) -> None:
        self._detach_poller()

    def _safe_int(self, key: str, default: int) -> int:
        val = self.get_setting(key)
        if not val:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    # ── Sensor map ────────────────────────────────────────────────────────────

    def _build_sensor_map(self) -> None:
        import json
        model = self.get_setting("model") or "deye_string"
        defs_dir = os.path.join(os.path.dirname(__file__), "..", "..", "inverter_definitions")
        json_path = os.path.join(defs_dir, f"{model}.json")
        try:
            with open(json_path, encoding="utf-8") as f:
                definition = json.load(f)
            sensors = [item
                       for group in definition.get("parameters", [])
                       for item in group.get("items", [])]
            raw_map = get_sensor_capability_map(sensors)

            # Filter and remap by device type so each device only processes its own caps
            if self._is_grid_meter:
                self._sensor_cap_map = {
                    sensor: GRID_CAP_REMAP.get(cap, cap)
                    for sensor, cap in raw_map.items()
                    if cap in GRID_METER_CAPS
                }
            elif self._is_battery:
                self._sensor_cap_map = {
                    sensor: cap for sensor, cap in raw_map.items()
                    if cap in BATTERY_CAPS
                }
            else:
                # Hybrid models: exclude GRID_METER_CAPS (they live on the grid meter device).
                # String/micro inverters: keep grid caps on the main inverter tile (no grid device).
                is_hybrid = "hybrid" in model.lower() or model == "deye_sg04lp3"
                self._sensor_cap_map = {
                    sensor: cap for sensor, cap in raw_map.items()
                    if cap not in BATTERY_CAPS and (not is_hybrid or cap not in GRID_METER_CAPS)
                }

            self.log(f"Sensor map: {len(self._sensor_cap_map)} sensors, model={model}")
        except Exception as e:
            _LOGGER.error(f"Failed to build sensor map: {e}")
            self._sensor_cap_map = {}

    async def _ensure_pv_structural_caps(self) -> None:
        """Add missing PV1/PV2 capabilities to inverter devices paired during weak sunlight.

        The pairing sensor filter used to exclude PV1/PV2 sensors when they read 0 at
        detection time (e.g. sunset or cloudy startup). The bug affected all models except
        deye_string. This method runs once at startup and silently adds any missing
        PV1/PV2 caps so existing devices recover without requiring re-pairing.

        Cap set for all 4 models: voltage + current + power for PV1/PV2.
        For string/micro, pv1/pv2 power is derived (V×I) at poll time — the
        capability still needs to exist so the value can be written.
        """
        if self._is_battery or self._is_grid_meter:
            return
        model = (self.get_setting("model") or "").strip()
        if not model:
            return

        # Caps that should always exist for the PV1/PV2 strings of each model
        base_pv_caps = (
            "measure_voltage.pv1", "measure_voltage.pv2",
            "measure_current.pv1", "measure_current.pv2",
        )
        power_pv_caps = (
            "measure_power.pv1", "measure_power.pv2",
        )

        if model in ("deye_hybrid", "deye_sg04lp3", "deye_string", "deye_micro"):
            required = base_pv_caps + power_pv_caps
        else:
            return

        for cap_id in required:
            if self.has_capability(cap_id):
                continue
            try:
                await self.addCapability(cap_id)
                self.log(f"Added missing PV structural cap {cap_id} ({model})")
            except Exception as e:
                _LOGGER.warning(f"Could not add missing PV cap {cap_id}: {e}")

    # ── SharedPoller ──────────────────────────────────────────────────────────

    def _poller_cfg(self) -> dict:
        return {
            "host":     self.get_setting("host") or "",
            "port":     self._safe_int("port", 8899),
            "slave_id": self._safe_int("slaveId", 1),
            "model":    self.get_setting("model") or "deye_string",
            "interval": max(35, self._safe_int("pollingInterval", 60)),
        }

    def _attach_poller(self) -> None:
        serial = self._safe_int("loggerSerial", 0)
        poller = _poller_mod.get_or_create(serial, **self._poller_cfg())
        poller.subscribe(self._on_values)
        self.log(f"Subscribed to SharedPoller serial={serial}")

    def _detach_poller(self, serial_override: int | None = None) -> None:
        _poller_mod.release_callback(self._on_values)

    # ── Value handler ─────────────────────────────────────────────────────────

    def _is_string_night(self) -> bool:
        """True when this is a string/micro inverter device during night hours.
        Convenience wrapper — computes sun_times internally."""
        return self._is_string_night_from(self._get_sunrise_sunset())

    def _is_string_night_from(self, sun_times: tuple[float, float, str] | None) -> bool:
        """True when this is a string/micro inverter device during night hours.
        Accepts pre-computed sun_times to avoid a second SDK call."""
        if self._is_battery or self._is_grid_meter:
            return False
        model = str(self.get_setting("model") or "")
        is_hybrid = "hybrid" in model.lower() or model == "deye_sg04lp3"
        return not is_hybrid and self._is_night_time_from(sun_times)

    async def _on_values(self, values: dict | None) -> None:
        # Compute sun_times once — shared by both night checks below.
        sun_times = self._get_sunrise_sunset()

        if values is None:
            # For string/micro inverters: logger loses power at night — expected, not an error
            if self._is_string_night_from(sun_times):
                self._consecutive_errors = 0
                await self._apply_zeros()
                self.log("night offline (expected) — logger without power")
                return
            await self._handle_error()
            return

        # Night backoff — inverter only, and only for non-hybrid (hybrid stays on 24/7 via battery)
        if self._is_string_night_from(sun_times):
            self._consecutive_errors = 0
            await self._apply_zeros()
            if sun_times:
                sr, ss = sun_times
                self.log(f"night offline (expected) — backing off 30 min "
                         f"| sunrise≈{sr:.2f}h sunset≈{ss:.2f}h (UTC)")
            else:
                self.log("night offline (expected) — backing off 30 min")
            return

        self._consecutive_errors = 0
        await self._clear_warning()
        if self._is_unavailable:
            self._is_unavailable = False
            await self.set_available()

        for sensor_name, cap_id in self._sensor_cap_map.items():
            # sensor_cap_map is pre-filtered per device type in _build_sensor_map
            # has_capability guard below covers any edge cases
            value = values.get(sensor_name)
            if value is None:
                continue
            if not self.has_capability(cap_id):
                continue

            if cap_id == "alarm_generic":
                coerced = str(value).lower() in ("fault", "alarm", "warning")
            elif cap_id == "battery_charging_state":
                v_lower = str(value).lower()
                if "discharge" in v_lower:
                    coerced = "discharge"
                elif "charge" in v_lower:
                    coerced = "charge"
                else:
                    coerced = "standby"
            else:
                coerced = value
                # Skip temperature readings below −50 °C: the Deye firmware returns
                # register value 0 for hardware sensors that are not physically present,
                # which yields (0 − 1000) × 0.1 = −100 °C.  Nothing legitimate runs
                # this cold, so we suppress the update rather than confuse Homey.
                if (cap_id.startswith("measure_temperature")
                        and isinstance(coerced, (int, float))
                        and coerced < -50):
                    continue

            await self._set(cap_id, coerced)

            if cap_id == "measure_power" and isinstance(value, (int, float)):
                self._last_power_w = float(value)

        if self._is_battery:
            # Derive battery_charging_state from Battery Power sign — more reliable than the
            # Battery Status sensor (deye_hybrid reg 189 is shared with PV4 Power, making
            # the lookup-based status unreliable).
            # Deye convention: positive Battery Power = discharging, negative = charging.
            if "Battery Power" in values and self.has_capability("battery_charging_state"):
                raw_pwr = float(values.get("Battery Power") or 0)
                if raw_pwr > 5:
                    await self._set("battery_charging_state", "discharge")
                elif raw_pwr < -5:
                    await self._set("battery_charging_state", "charge")
                else:
                    await self._set("battery_charging_state", "standby")

            # Mirror battery power to measure_power for the Energy Dashboard.
            # Deye: positive = discharging → negate for Homey convention (positive = charging).
            if "Battery Power" in values and self.has_capability("measure_power"):
                raw = values.get("Battery Power") or 0
                await self._set("measure_power", -float(raw))
        elif self._is_grid_meter:
            # Mirror live grid power to base measure_power for measurePowerConsumedCapability.
            # Homey Energy reads measure_power to display instantaneous grid consumption (W).
            if self.has_capability("measure_power"):
                grid_pwr = values.get("Total Grid Power")
                if grid_pwr is not None:
                    await self._set("measure_power", float(grid_pwr))
        else:
            # Inverter: ensure measure_power reflects solar production (not AC output,
            # which includes battery discharge and overstates production).
            if self.has_capability("measure_power.solar"):
                pv_names = [n for n, c in self._sensor_cap_map.items()
                            if c.startswith("measure_power.pv")]
                if pv_names:
                    # Multi-channel models (hybrid, micro): sum all individual PV channel powers.
                    # measure_power.solar is synthetic — no single sensor maps to it directly.
                    pv_total = sum(float(values.get(n) or 0) for n in pv_names)
                    await self._set("measure_power.solar", pv_total)
                    if self.has_capability("measure_power"):
                        await self._set("measure_power", pv_total)
                        self._last_power_w = pv_total
                else:
                    # String models: measure_power.solar was already set by the "Input Power"
                    # sensor in the loop above (Input Power → measure_power.solar via cap map).
                    # Do NOT override it with 0. Just mirror its value to measure_power so the
                    # Energy Dashboard receives the correct live solar production reading.
                    solar_sensor = next(
                        (sname for sname, cap in self._sensor_cap_map.items()
                         if cap == "measure_power.solar"),
                        None,
                    )
                    if solar_sensor is not None and self.has_capability("measure_power"):
                        val = float(values.get(solar_sensor) or 0)
                        await self._set("measure_power", val)
                        self._last_power_w = val

            # ── Derived PV power for string / micro ────────────────────────
            # These models have no direct PV-power registers in the JSON definition.
            # Power is approximated as V × I per channel and written to the
            # measure_power.pv{N} capability (added at pairing / by _ensure_pv_structural_caps).
            # For deye_micro the derived total also drives measure_power.solar because
            # there is no "Input Power" register to use as a solar proxy.
            model = self.get_setting("model") or ""
            if model in ("deye_string", "deye_micro"):
                derived_total = 0.0
                for idx in (1, 2, 3, 4):
                    pwr_cap = f"measure_power.pv{idx}"
                    if not self.has_capability(pwr_cap):
                        continue
                    v_cap = f"measure_voltage.pv{idx}"
                    i_cap = f"measure_current.pv{idx}"
                    v_name = next(
                        (n for n, c in self._sensor_cap_map.items() if c == v_cap), None
                    )
                    i_name = next(
                        (n for n, c in self._sensor_cap_map.items() if c == i_cap), None
                    )
                    if v_name and i_name:
                        v_val = values.get(v_name)
                        i_val = values.get(i_name)
                        if v_val is not None and i_val is not None:
                            pv_power = round(float(v_val) * float(i_val), 1)
                            await self._set(pwr_cap, pv_power)
                            derived_total += pv_power

                # deye_micro: no "Input Power" register — use derived PV total as
                # the solar proxy so the Energy Dashboard shows correct production.
                if model == "deye_micro" and self.has_capability("measure_power.solar"):
                    solar_w = round(derived_total, 1)
                    await self._set("measure_power.solar", solar_w)
                    if self.has_capability("measure_power"):
                        await self._set("measure_power", solar_w)
                    self._last_power_w = solar_w

            # ── Flow triggers ──────────────────────────────────────────────
            await self._fire_flow_triggers(values)

    async def _fire_flow_triggers(self, values: dict) -> None:
        """Fire flow triggers based on state transitions detected in poll values."""
        power = float(self._last_power_w or 0)
        is_producing = power > 5.0

        # Solar production started / stopped
        if is_producing and not self._was_producing:
            self._was_producing = True
            await self._trigger("solar_production_started", {"power": power})
        elif not is_producing and self._was_producing:
            self._was_producing = False
            await self._trigger("solar_production_stopped", {})

        # Grid lost / restored (hybrid only — needs Grid-connected Status sensor)
        grid_status = values.get("Grid-connected Status") or values.get("Grid Connected Status")
        if grid_status is not None:
            grid_available = str(grid_status).lower() == "on-grid"
            if not grid_available and self._grid_was_available:
                self._grid_was_available = False
                await self._trigger("grid_lost", {})
            elif grid_available and not self._grid_was_available:
                self._grid_was_available = True
                await self._trigger("grid_restored", {})

        # Data updated — fires every successful poll with current values as tokens
        tokens = {"power": power, "daily_production": 0.0, "battery_soc": 0.0, "grid_power": 0.0}
        for sname, cap in self._sensor_cap_map.items():
            v = values.get(sname)
            if v is None:
                continue
            if cap == "meter_power.today":
                tokens["daily_production"] = float(v)
            elif cap == "measure_battery":
                tokens["battery_soc"] = float(v)
            elif cap == "measure_power.grid":
                tokens["grid_power"] = float(v)
        await self._trigger("data_updated", tokens)

    async def _trigger(self, card_id: str, tokens: dict) -> None:
        """Fire a flow trigger card."""
        try:
            card = self.homey.flow.get_trigger_card(card_id)
            await card.trigger(self, tokens, {})
        except Exception as e:
            _LOGGER.debug(f"Flow trigger '{card_id}' failed: {e}")

    _has_warning: bool = False

    async def _clear_warning(self) -> None:
        if self._has_warning:
            self._has_warning = False
            await self.unset_warning()

    async def _handle_error(self) -> None:
        self._consecutive_errors += 1

        if self._consecutive_errors == _ERROR_THRESHOLD:
            self.log(f"poll failed {self._consecutive_errors}x during daytime — marking unavailable")
            self._is_unavailable = True
            await self.set_unavailable("Connection failed")
        elif self._consecutive_errors > _ERROR_THRESHOLD:
            pass  # already unavailable — do not spam set_unavailable on every poll
        else:
            self.log(f"poll error {self._consecutive_errors}/{_ERROR_THRESHOLD}")

    # ── Night detection (astral) ──────────────────────────────────────────────

    def _get_sunrise_sunset(self) -> tuple[float, float] | None:
        """Returns (sunrise_utc, sunset_utc) as decimal UTC hours using astral.

        Everything is in UTC — no timezone conversion needed.
        Priority: manual solar_latitude/longitude → Homey geolocation."""
        try:
            lat = self._get_float_setting("solar_latitude")
            lng = self._get_float_setting("solar_longitude")

            if lat is None:
                lat = self.homey.geolocation.get_latitude()
            if lng is None:
                lng = self.homey.geolocation.get_longitude()

            if lat is None or lng is None:
                self.log("Night backoff disabled — location not available")
                return None

            today = datetime.now(timezone.utc).date()
            loc   = LocationInfo(latitude=lat, longitude=lng)
            s     = sun(loc.observer, date=today, tzinfo=timezone.utc)
            sr    = s["sunrise"].hour + s["sunrise"].minute / 60
            ss    = s["sunset"].hour  + s["sunset"].minute  / 60
            self.log(f"Sun times (UTC): sunrise={sr:.2f}h sunset={ss:.2f}h lat={lat:.4f} lng={lng:.4f}")
            return (sr, ss)
        except Exception as e:
            self.log(f"Night backoff disabled — sun calculation failed: {e}")
            return None

    def _is_night_time(self) -> bool:
        """True when outside solar window. Convenience wrapper."""
        return self._is_night_time_from(self._get_sunrise_sunset())

    def _is_night_time_from(self, sun_times: tuple[float, float] | None) -> bool:
        """True when outside solar window with a 30-minute buffer on each side.
        Compares UTC current time against UTC sunrise/sunset."""
        if sun_times is None:
            return False
        sunrise, sunset = sun_times
        try:
            now      = datetime.now(timezone.utc)
            utc_hour = now.hour + now.minute / 60
            is_night = utc_hour < (sunrise - 0.5) or utc_hour >= (sunset + 0.5)
            self.log(
                f"Sun check: utc={now.strftime('%H:%M')} ({utc_hour:.2f}h) "
                f"window={sunrise - 0.5:.2f}h–{sunset + 0.5:.2f}h "
                f"→ {'NIGHT' if is_night else 'DAY'}"
            )
            return is_night
        except Exception as e:
            self.log(f"Night time check failed ({e}) — assuming daytime")
            return False

    # ── Apply zeros ───────────────────────────────────────────────────────────

    async def _apply_zeros(self) -> None:
        caps = _BATTERY_NIGHT_ZERO if self._is_battery else _INVERTER_NIGHT_ZERO
        for cap in caps:
            if self.has_capability(cap):
                await self._set(cap, 0)
        if not self._is_battery and self.has_capability("alarm_generic"):
            await self._set("alarm_generic", False)
        self._last_power_w = 0.0

    # ── Wi-Fi info refresh ────────────────────────────────────────────────────

    async def _refresh_wifi_info(self, host: str) -> None:
        """Fetch SSID and RSSI from logger status page and update settings."""
        if not host:
            return
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, 80), timeout=5
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
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=5)
                    if not chunk:
                        break
                    data += chunk
            except asyncio.TimeoutError:
                pass
            writer.close()
            await writer.wait_closed()

            import re
            text = data.decode("latin-1", errors="replace")
            ssid_m = re.search(r'webdata_wifi_ssid\s*=\s*["\']([^"\']*)["\']', text)
            rssi_m = re.search(r'webdata_wifi_rssi\s*=\s*["\']?(-?\d+)', text)

            updates = {}
            if ssid_m:
                updates["wifiSsid"] = ssid_m.group(1)
            if rssi_m:
                updates["wifiRssi"] = rssi_m.group(1) + " dBm"
            if updates:
                await self.set_settings(updates)
                self.log(f"Wi-Fi info updated: {updates}")
        except Exception as e:
            _LOGGER.debug(f"Wi-Fi info refresh failed: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_float_setting(self, key: str) -> float | None:
        """Return a device setting as float, or None if absent/invalid."""
        raw = self.get_setting(key)
        if raw in (None, ""):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            self.log(f"Ignoring invalid numeric setting {key}={raw!r}")
            return None

    async def _set(self, cap: str, value) -> None:
        try:
            await self.set_capability_value(cap, value)
        except Exception:
            pass


homey_export = DeyeDevice
