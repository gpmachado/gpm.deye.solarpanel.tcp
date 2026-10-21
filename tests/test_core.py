"""
Core checks that run without a Homey: register parsing, capability mapping and
the pairing capability plan. Run: python3 tests/test_core.py
"""

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

from app.lib.parser import ParameterParser  # noqa: E402
from app.lib.capability_map import get_sensor_capability_map  # noqa: E402
from app.drivers.deye.driver import DEYE_MODELS, SOFAR_MODELS, plan_device_capabilities  # noqa: E402


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


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
