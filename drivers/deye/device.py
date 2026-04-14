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
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.sun import sun

from homey.device import Device
from app.lib.capability_map import get_sensor_capability_map, BATTERY_CAPS
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
    _was_producing: bool = False
    _grid_was_available: bool = True
    _is_unavailable: bool = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def on_init(self) -> None:
        self._is_battery = (self.get_setting("device_type") == "battery")
        host = self.get_setting("host") or ""
        self.log(f"DeyeDevice init — type={'battery' if self._is_battery else 'inverter'} host={host}")
        self._build_sensor_map()
        self._attach_poller()
        if not self._is_battery:
            asyncio.create_task(self._refresh_wifi_info(host))

    async def on_settings(self, event) -> None:
        changed_keys = event.get("changedKeys", [])
        if any(k in changed_keys for k in
               ("host", "loggerSerial", "port", "slaveId", "model", "pollingInterval")):
            old_serial = int((event.get("oldSettings") or {}).get("loggerSerial") or
                             self.get_setting("loggerSerial") or 0)
            self._detach_poller(serial_override=old_serial)
            self._build_sensor_map()
            self._attach_poller()

    async def on_deleted(self) -> None:
        self._detach_poller()

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
            self._sensor_cap_map = get_sensor_capability_map(sensors)
            self.log(f"Sensor map: {len(self._sensor_cap_map)} sensors, model={model}")
        except Exception as e:
            _LOGGER.error(f"Failed to build sensor map: {e}")
            self._sensor_cap_map = {}

    # ── SharedPoller ──────────────────────────────────────────────────────────

    def _poller_cfg(self) -> dict:
        return {
            "host":     self.get_setting("host") or "",
            "port":     int(self.get_setting("port") or 8899),
            "slave_id": int(self.get_setting("slaveId") or 1),
            "model":    self.get_setting("model") or "deye_string",
            "interval": max(35, int(self.get_setting("pollingInterval") or 60)),
        }

    def _attach_poller(self) -> None:
        serial = int(self.get_setting("loggerSerial") or 0)
        poller = _poller_mod.get_or_create(serial, **self._poller_cfg())
        poller.subscribe(self._on_values)
        self.log(f"Subscribed to SharedPoller serial={serial}")

    def _detach_poller(self, serial_override: int | None = None) -> None:
        serial = serial_override if serial_override is not None else int(self.get_setting("loggerSerial") or 0)
        _poller_mod.release(serial, self._on_values)

    # ── Value handler ─────────────────────────────────────────────────────────

    def _is_string_night(self) -> bool:
        """True when this is a string/micro inverter device during night hours.
        Hybrid models stay online 24/7 — detected via model name, not a flag."""
        if self._is_battery:
            return False
        model = str(self.get_setting("model") or "")
        is_hybrid = "hybrid" in model.lower() or model == "deye_sg04lp3"
        return not is_hybrid and self._is_night_time()

    async def _on_values(self, values: dict | None) -> None:
        if values is None:
            # For string/micro inverters: logger loses power at night — expected, not an error
            if self._is_string_night():
                self._consecutive_errors = 0
                await self._apply_zeros()
                self.log("night offline (expected) — logger without power")
                return
            await self._handle_error()
            return

        # Night backoff — inverter only, and only for non-hybrid (hybrid stays on 24/7 via battery)
        if self._is_string_night():
            self._consecutive_errors = 0
            await self._apply_zeros()
            sr, ss = self._get_sunrise_sunset()
            self.log(f"night offline (expected) — backing off 30 min "
                     f"| sunrise≈{sr:.2f}h sunset≈{ss:.2f}h")
            return

        self._consecutive_errors = 0
        await self._clear_warning()
        if self._is_unavailable:
            self._is_unavailable = False
            await self.set_available()

        for sensor_name, cap_id in self._sensor_cap_map.items():
            # Battery device only gets BATTERY_CAPS; inverter gets everything else
            if self._is_battery != (cap_id in BATTERY_CAPS):
                continue
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

            await self._set(cap_id, coerced)

            if cap_id == "measure_power" and isinstance(value, (int, float)):
                self._last_power_w = float(value)

        if self._is_battery:
            # Mirror battery power to measure_power for the Energy Dashboard.
            # Deye: positive = discharging → negate for Homey convention (positive = charging).
            if "Battery Power" in values and self.has_capability("measure_power"):
                raw = values.get("Battery Power") or 0
                await self._set("measure_power", -float(raw))
        else:
            # Inverter: override measure_power with total PV (solar production only).
            # AC output includes battery discharge and overstates solar.
            if self.has_capability("measure_power.solar"):
                pv_names = [n for n, c in self._sensor_cap_map.items()
                            if c.startswith("measure_power.pv")]
                pv_total = sum(float(values.get(n) or 0) for n in pv_names)
                await self._set("measure_power.solar", pv_total)
                if self.has_capability("measure_power"):
                    await self._set("measure_power", pv_total)
                    self._last_power_w = pv_total

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

    def _get_sunrise_sunset(self) -> tuple[float, float]:
        """Returns (sunrise, sunset) as decimal local hours."""
        try:
            lat     = self.homey.geolocation.get_latitude()
            lng     = self.homey.geolocation.get_longitude()
            tz_name = self.homey.clock.get_timezone()
            if not lat or not lng:
                raise ValueError("no geolocation")
            loc = LocationInfo(latitude=lat, longitude=lng, timezone=tz_name)
            s   = sun(loc.observer, tzinfo=ZoneInfo(tz_name))
            return (
                s["sunrise"].hour + s["sunrise"].minute / 60,
                s["sunset"].hour  + s["sunset"].minute  / 60,
            )
        except Exception:
            return (6.0, 19.0)

    def _is_night_time(self) -> bool:
        """True when outside solar window + 30-minute buffer on each side."""
        try:
            sunrise, sunset = self._get_sunrise_sunset()
            tz_name = self.homey.clock.get_timezone()
            now     = datetime.now(timezone.utc)
            local   = now.astimezone(ZoneInfo(tz_name)) if tz_name else now
            local_h = local.hour + local.minute / 60
            return local_h < (sunrise - 0.5) or local_h >= (sunset + 0.5)
        except Exception:
            h = datetime.now().hour
            return h < 6 or h >= 19

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

    # ── Helper ────────────────────────────────────────────────────────────────

    async def _set(self, cap: str, value) -> None:
        try:
            await self.set_capability_value(cap, value)
        except Exception:
            pass


homey_export = DeyeDevice
