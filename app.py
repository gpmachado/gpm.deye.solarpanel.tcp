import json
import os
from collections.abc import Mapping
from typing import Any

from homey.app import App

from app.drivers.deye.driver import HYBRID_MODELS
from app.lib.fault_codes import known_fault_names

# ── Debug verbosity ───────────────────────────────────────────────────────────
# True  → one log line per poll (solar/battery/grid values) — homey app run --remote
# False → silent (production)
# Flip this ONE constant instead of hunting across device.py.
DEBUG_LOG = False
# ─────────────────────────────────────────────────────────────────────────────


def _app_version() -> str:
    try:
        manifest = os.path.join(os.path.dirname(__file__), "app.json")
        with open(manifest, encoding="utf-8") as f:
            return json.load(f).get("version", "unknown")
    except Exception:
        return "unknown"


class MyApp(App):

    async def on_init(self):
        await super().on_init()
        self.log(f"Deye app v{_app_version()} initialized")
        self._register_flow_conditions()

    def get_solar_summary(self) -> dict[str, Any]:
        """Return current energy snapshot for the dashboard widget.

        Called synchronously from the widget's HTTP API handler — must never
        raise, or the widget shows a broken tile instead of empty values.
        """
        solar: Any = None
        load: Any = None
        grid: Any = None
        battery: Any = None
        battery_soc: Any = None
        has_battery = False

        try:
            driver = self.homey.drivers.get_driver("deye")
            devices = driver.get_devices() if driver else []
        except Exception as e:
            self.log(f"get_solar_summary: driver lookup failed: {e}")
            devices = []

        for device in devices:
            try:
                dtype = device.get_setting("device_type") or "inverter"
                if dtype == "inverter":
                    if device.has_capability("measure_power"):
                        solar = device.get_capability_value("measure_power")
                    if device.has_capability("measure_power.load"):
                        load = device.get_capability_value("measure_power.load")
                    if device.has_capability("measure_power.grid"):
                        grid = device.get_capability_value("measure_power.grid")
                elif dtype == "grid_meter":
                    if device.has_capability("measure_power.grid"):
                        grid = device.get_capability_value("measure_power.grid")
                elif dtype == "battery":
                    has_battery = True
                    if device.has_capability("measure_power.battery"):
                        battery = device.get_capability_value("measure_power.battery")
                    if device.has_capability("measure_battery"):
                        battery_soc = device.get_capability_value("measure_battery")
            except Exception as e:
                self.log(f"get_solar_summary: skipping device due to error: {e}")
                continue

        return {
            "solar": solar,
            "load": load,
            "grid": grid,
            "battery": battery if has_battery else None,
            "battery_soc": battery_soc if has_battery else None,
        }

    def _register_flow_conditions(self):
        """Register run listeners for all condition flow cards."""

        async def _is_solar_producing(card_arguments: Mapping[str, Any], **kwargs: Any) -> bool:
            device = card_arguments.get("device")
            if not device:
                return False
            power = device.get_capability_value("measure_power") or 0
            return float(power) > 5.0

        async def _is_battery_charging(card_arguments: Mapping[str, Any], **kwargs: Any) -> bool:
            device = card_arguments.get("device")
            if not device:
                return False
            # battery_charging_state is the authoritative source (normalized enum)
            status = device.get_capability_value("battery_charging_state")
            if status is not None:
                return status == "charge"
            # Fallback: measure_power on the battery device is already normalized
            # (positive = charging, per Homey convention) — NOT the raw Deye value
            power = device.get_capability_value("measure_power") or 0
            return float(power) > 0

        async def _is_grid_feeding(card_arguments: Mapping[str, Any], **kwargs: Any) -> bool:
            device = card_arguments.get("device")
            if not device:
                return False
            grid = device.get_capability_value("measure_power.grid") or 0
            return float(grid) < 0  # negative = exporting to grid

        async def _battery_soc_above(card_arguments: Mapping[str, Any], **kwargs: Any) -> bool:
            device = card_arguments.get("device")
            if not device:
                return False
            soc = device.get_capability_value("measure_battery")
            threshold = card_arguments.get("value")
            if soc is None or threshold is None:
                return False
            return float(soc) >= float(threshold)

        def _active_faults(device: Any) -> list[str]:
            current = device.get_capability_value("fault_description") or ""
            return [s.strip() for s in current.split(",") if s.strip() and s.strip() != "OK"]

        async def _has_active_fault(card_arguments: Mapping[str, Any], **kwargs: Any) -> bool:
            device = card_arguments.get("device")
            if not device:
                return False
            return bool(_active_faults(device))

        async def _fault_is(card_arguments: Mapping[str, Any], **kwargs: Any) -> bool:
            device = card_arguments.get("device")
            fault = card_arguments.get("fault")
            if not device or not fault:
                return False
            name = fault.get("name") if isinstance(fault, dict) else fault
            return name in _active_faults(device)

        async def _fault_autocomplete(query: str, **kwargs: Any) -> list[dict]:
            device = kwargs.get("device")
            model = device.get_setting("model") if device else ""
            names = known_fault_names(model or "")
            if model not in HYBRID_MODELS:
                # No battery port on string/micro inverters — never suggest
                # battery-specific faults for them.
                names = [n for n in names if "battery" not in n.lower()]
            query_lower = (query or "").lower()
            return [{"name": n} for n in names if query_lower in n.lower()]

        try:
            self.homey.flow.get_condition_card("is_solar_producing") \
                .register_run_listener(_is_solar_producing)
            self.homey.flow.get_condition_card("is_battery_charging") \
                .register_run_listener(_is_battery_charging)
            self.homey.flow.get_condition_card("is_grid_feeding") \
                .register_run_listener(_is_grid_feeding)
            self.homey.flow.get_condition_card("battery_soc_above") \
                .register_run_listener(_battery_soc_above)
            self.homey.flow.get_condition_card("has_active_fault") \
                .register_run_listener(_has_active_fault)
            fault_is_card = self.homey.flow.get_condition_card("fault_is")
            fault_is_card.register_run_listener(_fault_is)
            fault_is_card.register_argument_autocomplete_listener("fault", _fault_autocomplete)
        except Exception as e:
            self.log(f"Flow condition registration failed: {e}")


homey_export = MyApp
