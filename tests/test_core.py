"""
Core checks that run without a Homey: register parsing, capability mapping and
the pairing capability plan. Run: python3 tests/test_core.py
"""

import asyncio
import datetime
import json
import os
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The app imports itself as the `app` package and needs the Homey SDK; stub both.
_app = types.ModuleType("app")
_app.__path__ = [REPO]
sys.modules["app"] = _app
for name, attrs in (("homey", {}), ("homey.driver", {"Driver": object}), ("homey.device", {"Device": object})):
    sys.modules[name] = types.SimpleNamespace(**attrs)
# astral ships in python_packages/ only after a Homey build; the tests don't need it.
for name, attrs in (("astral", {"LocationInfo": object}), ("astral.sun", {"sun": None})):
    sys.modules.setdefault(name, types.SimpleNamespace(**attrs))

from app.lib.parser import ParameterParser  # noqa: E402
from app.lib.capability_map import get_sensor_capability_map  # noqa: E402
from app.drivers.deye.driver import (  # noqa: E402
    DEYE_MODELS, SOFAR_MODELS, _model_from_device_type, plan_device_capabilities,
)


def load_definition(model: str) -> dict:
    with open(os.path.join(REPO, "inverter_definitions", f"{model}.json"), encoding="utf-8") as f:
        return json.load(f)


def parse(definition: dict, regs: dict[int, int]) -> dict:
    p = ParameterParser(definition)
    for r in definition["requests"]:
        start, end = r["start"], r["end"]
        p.parse([regs.get(a, 0) for a in range(start, end + 1)], start, end - start + 1)
    return p.get_result()


def test_signed_two_complement():
    for raw, expected in ((65535, -1), (32768, -32768), (32767, 32767), (0, 0)):
        d = {"parameters": [{"items": [{"name": "x", "rule": 2, "registers": [0]}]}]}
        assert parse({**d, "requests": [{"start": 0, "end": 0}]}, {0: raw})["x"] == expected, raw


def test_sofar_dumps_match_inverter_display():
    # Values read on the SOFAR display / app at the same moment (issues #7, #8).
    with open(os.path.join(REPO, "tests", "fixtures", "sofar_g3_dumps.json"), encoding="utf-8") as f:
        dumps = json.load(f)
    definition = load_definition("sofar_g3_hybrid")
    expected = {
        # Deye convention used by device.py: Battery Power + = discharging; grid + = import.
        "charging":    {"Battery SOC": 90, "Battery Power": -2470, "Total Grid Power": -1420,
                        "PV1 Power": 3480, "Total Load Power": 1750, "Daily Production": 7},
        "discharging": {"Battery SOC": 65, "Battery Power": 2410, "Total Grid Power": 0,
                        "PV1 Power": 1150, "Total Load Power": 4300, "Daily Production": 33.22},
    }
    for name, want in expected.items():
        values = parse(definition, {int(k, 16): v for k, v in dumps[name].items()})
        for key, val in want.items():
            assert abs(values[key] - val) < 1e-6, (name, key, values[key], val)


def test_deye_registers_match_official_doc():
    # Deye Modbus protocol V118: 198/199 load power and 203/204 meter power are 1 W,
    # meter power is signed with "buying negative, selling positive". The app shows
    # grid power + = import, so buying 1500 W must read +1500.
    regs = {198: 2500, 199: 0, 203: 0x10000 - 1500, 204: 0xFFFF}
    values = parse(load_definition("deye_string"), regs)
    assert values["Load Power"] == 2500, values["Load Power"]
    assert values["Grid Power"] == 1500, values["Grid Power"]
    # Hybrid load power is signed (sunsynk and davidrapan agree): 0xFF9C is -100 W.
    assert parse(load_definition("deye_hybrid"), {178: 0xFF9C})["Total Load Power"] == -100


def test_hv_profile_differs_from_lv_only_in_hv_scales():
    # davidrapan deye_p3.yaml scale lists [LV, HV]: PV power [1, 10], battery power
    # [1, 10], battery voltage [0.01, 0.1]. Same raw registers, 10x apart.
    regs = {672: 520, 590: 0x10000 - 300, 587: 4012, 588: 55, 586: 1250}  # 586: 25 °C
    lv = parse(load_definition("deye_sg04lp3"), regs)
    hv = parse(load_definition("deye_sg01hp3"), regs)
    assert (lv["PV1 Power"], hv["PV1 Power"]) == (520, 5200)
    assert (lv["Battery Power"], hv["Battery Power"]) == (-300, -3000)
    assert (round(lv["Battery Voltage"], 2), round(hv["Battery Voltage"], 1)) == (40.12, 401.2)
    assert lv["Battery SOC"] == hv["Battery SOC"] == 55
    hv_scaled = {"PV1 Power", "PV2 Power", "Battery Power", "Battery Voltage"}
    def items(model):
        return {s["name"]: {k: v for k, v in s.items() if k != "scale" or s["name"] not in hv_scaled}
                for g in load_definition(model)["parameters"] for s in g["items"]}
    assert items("deye_sg04lp3") == items("deye_sg01hp3")
    assert load_definition("deye_sg04lp3")["requests"] == load_definition("deye_sg01hp3")["requests"]


def test_device_type_register_picks_hv():
    # 0x0000 = 6 on a SUN-20K-SG01HP3 (forum #36); 2 on a string inverter.
    for hv in (0x0006, 0x0007, 0x0008, 0x0600, 0x0601):
        assert _model_from_device_type(hv) == "deye_sg01hp3", hv
    # Every other family (and an unreadable register) keeps the score method.
    for other in (None, 0, 0x0002, 0x0003, 0x0004, 0x0005, 0x0500):
        assert _model_from_device_type(other) is None, other


def test_debug_logging_is_scoped_per_logger():
    # Per-device "Debug logging": only polls tagged with an enabled scope show
    # DEBUG lines; warnings always pass. Two pollers run interleaved.
    import asyncio
    import io
    import logging
    from app.lib import debug
    debug.install()
    handler = next(h for h in logging.getLogger("app").handlers
                   if any(isinstance(f, debug._ScopeFilter) for f in h.filters))
    buf = io.StringIO()
    handler.setStream(buf)
    log = logging.getLogger("app.lib.v5_transport")

    async def poll(serial):
        debug.scope.set(serial)
        await asyncio.sleep(0)
        log.debug("read from %s", serial)
        log.warning("timeout on %s", serial)

    async def main():
        await asyncio.gather(poll("111"), poll("222"))

    debug.set_enabled("111", True)
    asyncio.run(main())
    debug.set_enabled("111", False)
    out = buf.getvalue()
    assert "read from 111" in out and "read from 222" not in out, out
    assert "timeout on 111" in out and "timeout on 222" in out, out


def test_sofar_sensor_names_map_to_capabilities():
    caps = get_sensor_capability_map([i for g in load_definition("sofar_g3_hybrid")["parameters"]
                                      for i in g["items"]])
    assert caps["Battery Power"] == "measure_power.battery"
    assert caps["Battery SOC"] == "measure_battery"
    assert caps["Total Grid Power"] == "measure_power.grid"
    assert caps["Total Load Power"] == "measure_power.load"
    assert caps["Daily Production"] == "meter_power.today"


def test_pairing_plan():
    for model in [*DEYE_MODELS, *SOFAR_MODELS]:
        for advanced in (False, True):
            plan = plan_device_capabilities(model, {}, advanced)
            hybrid = "battery" in plan
            assert hybrid == ("grid_meter" in plan), model
            if not hybrid:
                continue
            batt = plan["battery"]
            assert {"measure_power", "measure_power.battery_charging",
                    "measure_power.battery_discharging", "battery_charging_state"} <= set(batt["caps"]), model
            assert "measure_power.battery" not in batt["caps"], model
            assert batt["opts"]["measure_power"]["uiComponent"] is None, model
            assert "meter_power.exported" in plan["grid_meter"]["caps"], model
    assert "battery" in plan_device_capabilities("deye_sg04lp3", {}, True)
    assert "battery" not in plan_device_capabilities("deye_string", {}, True)
    # Restore uses advanced=False for strings: no CT-dependent load/grid values.
    string_default = plan_device_capabilities("deye_string", {}, False)["inverter"]["caps"]
    assert "measure_power.load" not in string_default and "measure_power.grid" not in string_default
    # Unwired PV3 (reads 0) is left out; without values nothing is filtered.
    assert "measure_power.pv3" not in plan_device_capabilities(
        "sofar_g3_hybrid", {"PV3 Power": 0, "PV1 Power": 100}, True)["inverter"]["caps"]


def _fake_deye_device(model="deye_string", setting=None, store=None, homey_tz="UTC"):
    from app.drivers.deye import device as device_mod

    class FakeDevice(device_mod.DeyeDevice):
        def __init__(self):
            self.settings = {"model": model, "resetDailyMidnight": setting}
            self.caps = {"meter_power.today": 45.5, "meter_power.today_load": 3.0,
                         "meter_power": 72835.3}
            self.store = dict(store or {})
            # homey 0.0.11 reports "UTC" whatever the Homey is set to (lib/local_time.py)
            self.homey = types.SimpleNamespace(
                clock=types.SimpleNamespace(get_timezone=lambda: homey_tz),
                geolocation=types.SimpleNamespace(get_longitude=lambda: -42.6984))
            self._sensor_cap_map = {"Today Production": "meter_power.today",
                                    "Today Load Consumption": "meter_power.today_load"}
        def get_store(self):
            return self.store
        async def set_store_value(self, key, value):
            self.store[key] = value
        def get_setting(self, key):
            return self.settings.get(key)
        def has_capability(self, cap):
            return cap in self.caps
        async def _set(self, cap, value):
            self.caps[cap] = value
        def log(self, *args):
            self.logs.append(" ".join(map(str, args)))
    dev = FakeDevice()
    dev.logs = []
    return dev


def _at(utc: str):
    """Freeze lib/local_time.py's clock at a UTC instant (São Paulo is UTC-3)."""
    from app.lib import local_time
    instant = datetime.datetime.fromisoformat(utc).replace(tzinfo=datetime.UTC)

    class Frozen(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant
    local_time.datetime = Frozen


def test_local_time_sources():
    from app.lib.local_time import local_date, resolve_tz
    now = datetime.datetime(2026, 11, 24, 0, 1, tzinfo=datetime.UTC)  # field log: 21:01 local
    tz, how = resolve_tz("America/Sao_Paulo", None, -42.7)
    assert local_date(tz, now) == "2026-11-23" and how == "Homey time zone America/Sao_Paulo"
    # The SDK default: a stored zone wins, else the longitude (-42.7 / 15 -> UTC-3).
    tz, how = resolve_tz("UTC", "America/Sao_Paulo", -42.7)
    assert local_date(tz, now) == "2026-11-23" and how.startswith("stored")
    tz, how = resolve_tz("UTC", None, -42.7)
    assert local_date(tz, now) == "2026-11-23" and how.startswith("UTC-3 from longitude")
    # Near Greenwich (or no location / a bad name) "UTC" is taken as is.
    for args in (("UTC", None, 4.9), ("UTC", None, None), ("Not/AZone", "Etc/GMT", None)):
        assert resolve_tz(*args)[1].startswith("UTC (Homey reports")
    assert resolve_tz(None, None, 139.7)[1].startswith("UTC+9")


def test_homey_time_zone_is_remembered():
    dev = _fake_deye_device(homey_tz="America/Sao_Paulo")
    asyncio.run(dev._local_date())
    assert dev.store["homeyTimezone"] == "America/Sao_Paulo"
    assert dev.logs == ["daily reset uses Homey time zone America/Sao_Paulo"]
    # After a restart the SDK says "UTC" again: the stored zone is used.
    dev = _fake_deye_device(store=dev.store)
    asyncio.run(dev._local_date())
    assert dev.logs == ["daily reset uses stored time zone America/Sao_Paulo (Homey reports UTC)"]


def test_daily_counters_reset_at_local_midnight():
    from app.lib import local_time
    real_datetime = local_time.datetime
    try:
        dev = _fake_deye_device()
        _at("2026-11-23T02:30")                  # 23:30 local on the 22nd
        asyncio.run(dev._maybe_reset_daily())   # first run: only remembers the date
        assert dev.caps["meter_power.today"] == 45.5 and dev.store["dailyLocalDate"] == "2026-11-22"
        _at("2026-11-23T02:59")                  # 00:00 UTC passed, still the 22nd locally
        asyncio.run(dev._maybe_reset_daily())
        assert dev.caps["meter_power.today"] == 45.5 and not dev._daily_stale
        _at("2026-11-23T03:01")                  # 00:01 local: reset
        asyncio.run(dev._maybe_reset_daily())
        assert dev.caps == {"meter_power.today": 0, "meter_power.today_load": 0,
                            "meter_power": 72835.3}
        assert dev.store == {"dailyLocalDate": "2026-11-23", "dailyStale": True}

        # App restart at 03:00, after the reset: the hold survives.
        dev = _fake_deye_device(store=dev.store)
        dev.caps["meter_power.today"] = 0
        _at("2026-11-23T06:00")
        asyncio.run(dev._maybe_reset_daily())
        assert dev._daily_stale
        # 07:57 wake-up with yesterday's 45.5 kWh at 0 W: still held.
        values = {"Today Production": 45.5, "Today Load Consumption": 3.0}
        dev._last_power_w = 0.0
        asyncio.run(dev._release_daily_hold(values))
        assert dev._daily_stale and dev.caps["meter_power.today"] == 0
        # 08:03 producing 84 W, inverter zeroed its counter: released and written.
        dev._last_power_w = 84.0
        asyncio.run(dev._release_daily_hold({"Today Production": 0.0, "Today Load Consumption": 0.0}))
        assert not dev._daily_stale and dev.store["dailyStale"] is False
        assert dev.caps["meter_power.today"] == 0.0

        # App restart before dawn with yesterday's date stored: the reset still happens.
        dev = _fake_deye_device(store={"dailyLocalDate": "2026-11-22", "dailyStale": False})
        asyncio.run(dev._maybe_reset_daily())
        assert dev.caps["meter_power.today"] == 0 and dev._daily_stale

        # Setting off, or a hybrid (resets on its own clock): untouched.
        for dev in (_fake_deye_device(setting=False, store={"dailyLocalDate": "2026-11-22"}),
                    _fake_deye_device("deye_sg01hp3", store={"dailyLocalDate": "2026-11-22"})):
            asyncio.run(dev._maybe_reset_daily())
            assert dev.caps["meter_power.today"] == 45.5 and not dev._daily_stale
    finally:
        local_time.datetime = real_datetime


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
