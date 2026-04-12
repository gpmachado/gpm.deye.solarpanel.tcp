"""
Deye inverter device — polls Solarman logger and updates Homey capabilities.
Based on the Hoymiles Python device pattern (astral for sunrise/sunset,
asyncio polling loop, night backoff, consecutive error tolerance).
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.sun import sun

from homey.device import Device
from app.lib.solarman_client import SolarmanClient
from app.lib.capability_map import get_sensor_capability_map

_LOGGER = logging.getLogger(__name__)

_BACKOFF_NIGHT = 30 * 60   # 30 minutes — expected offline
_BACKOFF_DAY   =  5 * 60   #  5 minutes — unexpected error
_ERROR_THRESHOLD = 5        # consecutive failures before set_unavailable
_POWER_THRESHOLD_W = 5      # below this = inverter idle (dawn/dusk)


class DeyeDevice(Device):

    _client: SolarmanClient | None = None
    _poll_task: asyncio.Task | None = None
    _consecutive_errors: int = 0
    _backoff_until: float = 0.0
    _last_power_w: float = 0.0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def on_init(self) -> None:
        host = self.get_setting("host") or ""
        self.log(f"DeyeDevice init — {host}")
        self._build_client()
        self._start_polling()
        # Refresh Wi-Fi info in settings (non-blocking — failure is silent)
        asyncio.create_task(self._refresh_wifi_info(host))

    async def on_settings(self, old_settings, new_settings, changed_keys) -> None:
        if any(k in changed_keys for k in ("host", "loggerSerial", "port", "slaveId", "model")):
            self._build_client()
        if "pollingInterval" in changed_keys:
            self._start_polling()

    async def on_deleted(self) -> None:
        self._stop_polling()

    # ── Client setup ──────────────────────────────────────────────────────────

    def _build_client(self) -> None:
        host    = self.get_setting("host") or ""
        serial  = int(self.get_setting("loggerSerial") or 0)
        port    = int(self.get_setting("port") or 8899)
        slave   = int(self.get_setting("slaveId") or 1)
        model   = self.get_setting("model") or "deye_string"

        json_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "inverter_definitions", f"{model}.json"
        )

        self._client = SolarmanClient(host, serial, port=port, slave_id=slave)
        self._client.load_definition(json_path)

        # Build sensor → capability mapping
        self._sensor_cap_map = get_sensor_capability_map(self._client.get_sensors())
        self.log(f"Client built — {host} serial:{serial} model:{model} "
                 f"sensors:{len(self._sensor_cap_map)}")

    # ── Polling ───────────────────────────────────────────────────────────────

    def _start_polling(self) -> None:
        self._stop_polling()
        interval = max(35, int(self.get_setting("pollingInterval") or 60))
        self._poll_task = asyncio.create_task(self._poll_loop(interval))
        self._poll_task.add_done_callback(self._on_poll_task_done)

    def _stop_polling(self) -> None:
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        self._poll_task = None

    def _on_poll_task_done(self, task: asyncio.Task) -> None:
        if not task.cancelled() and (exc := task.exception()):
            _LOGGER.error(f"Poll task crashed: {exc!r}")

    async def _poll_loop(self, interval: int) -> None:
        self.log(f"Polling started — every {interval}s")
        try:
            while True:
                remaining = self._backoff_until - time.monotonic()
                if remaining > 0:
                    await asyncio.sleep(min(remaining, interval))
                    continue
                await self._poll()
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    async def _poll(self) -> None:
        if not self._client:
            return

        try:
            values = await self._client.read_all()
        except Exception as e:
            await self._handle_poll_error(e)
            return

        # Successful poll
        self._consecutive_errors = 0
        await self.set_available()

        for sensor_name, cap_id in self._sensor_cap_map.items():
            value = values.get(sensor_name)
            if value is None:
                continue
            if not self.has_capability(cap_id):
                continue

            # alarm_generic expects boolean
            if cap_id == "alarm_generic":
                coerced = str(value).lower() in ("fault", "alarm", "warning")
            else:
                coerced = value

            await self._set(cap_id, coerced)

            # Track last known AC output power for error classification
            if cap_id == "measure_power" and isinstance(value, (int, float)):
                self._last_power_w = float(value)

        # For hybrid models: override measure_power with total PV production (PV1+PV2).
        # AC output includes battery discharge and is misleading for Energy Dashboard.
        if self.has_capability("measure_power.battery") and self.has_capability("measure_power"):
            pv_total = 0.0
            for sname, cid in self._sensor_cap_map.items():
                if cid in ("measure_power.pv1", "measure_power.pv2"):
                    pv_total += float(values.get(sname) or 0)
            await self._set("measure_power", pv_total)
            self._last_power_w = pv_total

    async def _handle_poll_error(self, err: Exception) -> None:
        self._consecutive_errors += 1

        if self._is_night_time():
            # Night — expected offline, zero live values and back off
            self._consecutive_errors = 0
            await self._apply_zeros()
            await self.set_available()
            self._backoff_until = time.monotonic() + _BACKOFF_NIGHT
            sr, ss = self._get_sunrise_sunset()
            self.log(f"poll: night offline (expected) — backing off 30 min "
                     f"| sunrise≈{sr:.2f}h sunset≈{ss:.2f}h | {err}")

        elif self._consecutive_errors >= _ERROR_THRESHOLD:
            # Daytime + repeated failures — mark unavailable regardless of last power.
            # Covers: connection loss mid-day, logger crash, cloudy day with 0 W output.
            self.log(f"poll failed {self._consecutive_errors}x during daytime "
                     f"(lastPower={self._last_power_w}W): {err}")
            await self.set_unavailable(str(err))

        else:
            # First few errors — tolerate silently (dawn ramp-up, transient glitch)
            self.log(f"poll error (attempt {self._consecutive_errors}/{_ERROR_THRESHOLD}, "
                     f"lastPower={self._last_power_w}W): {err}")

    # ── Night detection (astral — same as Hoymiles) ───────────────────────────

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
            tz_name  = self.homey.clock.get_timezone()
            now      = datetime.now(timezone.utc)
            local    = now.astimezone(ZoneInfo(tz_name)) if tz_name else now
            local_h  = local.hour + local.minute / 60
            return local_h < (sunrise - 0.5) or local_h >= (sunset + 0.5)
        except Exception:
            h = datetime.now().hour
            return h < 6 or h >= 19

    # ── Apply zeros at night ──────────────────────────────────────────────────

    async def _apply_zeros(self) -> None:
        """Zero instantaneous capabilities. Preserves meter_power (lifetime energy)."""
        instant_caps = [
            "measure_power",
            "measure_power.pv1", "measure_power.pv2",
            "measure_power.pv3", "measure_power.pv4",
            "measure_power.battery", "measure_power.load", "measure_power.grid",
            "measure_power.micro",
            "measure_voltage.pv1", "measure_voltage.pv2",
            "measure_voltage.pv3", "measure_voltage.pv4",
            "measure_voltage.grid", "measure_voltage.battery",
            "measure_voltage.l1",  "measure_voltage.l2",  "measure_voltage.l3",
            "measure_current.pv1", "measure_current.pv2",
            "measure_current.pv3", "measure_current.pv4",
            "measure_current.grid", "measure_current.battery",
            "measure_current.l1",  "measure_current.l2",  "measure_current.l3",
            "measure_frequency",
            "measure_temperature",
        ]
        for cap in instant_caps:
            if self.has_capability(cap):
                await self._set(cap, 0)
        if self.has_capability("alarm_generic"):
            await self._set("alarm_generic", False)
        self._last_power_w = 0.0

    # ── Wi-Fi info refresh ────────────────────────────────────────────────────

    async def _refresh_wifi_info(self, host: str) -> None:
        """Fetch SSID and RSSI from logger status page and update settings."""
        if not host:
            return
        try:
            from app.drivers.deye.driver import _fetch_logger_info
            info = await _fetch_logger_info(host)
            updates: dict = {}
            if info.get("ssid"):
                updates["wifiSsid"] = info["ssid"]
            if info.get("rssi"):
                updates["wifiRssi"] = info["rssi"]
            if updates:
                await self.set_settings(updates)
                self.log(f"Wi-Fi: SSID={info.get('ssid')} RSSI={info.get('rssi')}")
        except Exception as e:
            _LOGGER.debug(f"Wi-Fi info refresh failed: {e}")

    # ── Helper ────────────────────────────────────────────────────────────────

    async def _set(self, cap: str, value) -> None:
        try:
            await self.set_capability_value(cap, value)
        except Exception:
            pass


homey_export = DeyeDevice
