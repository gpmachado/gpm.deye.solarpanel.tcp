"""
Maps Solarman YAML sensor definitions to Homey capabilities.
Handles dynamic capability building for all Deye inverter models.
"""

import re

# ── Name-based pattern rules ──────────────────────────────────────────────────
# Ordered by specificity. First match wins.
# (regex_pattern, homey_capability_id, english_title)
_NAME_RULES: list[tuple[str, str, str]] = [
    # PV channel power
    (r'\bpv1\b.+power|power.+\bpv1\b',        'measure_power.pv1',     'PV1 Power'),
    (r'\bpv2\b.+power|power.+\bpv2\b',        'measure_power.pv2',     'PV2 Power'),
    (r'\bpv3\b.+power|power.+\bpv3\b',        'measure_power.pv3',     'PV3 Power'),
    (r'\bpv4\b.+power|power.+\bpv4\b',        'measure_power.pv4',     'PV4 Power'),
    # Other power variants
    (r'battery.+power|power.+battery',         'measure_power.battery', 'Battery Power'),
    (r'\bload\b.+power|power.+\bload\b',       'measure_power.load',    'Load Power'),
    (r'grid.+power|power.+grid',               'measure_power.grid',    'Grid Power'),
    (r'micro.+power|power.+micro',             'measure_power.micro',   'Micro-inverter Power'),
    # Frequency — must come before AC output power to catch "AC Output Frequency"
    (r'ac.+freq|output.+freq|freq.+ac',        'measure_frequency',     'Grid Frequency'),
    # Main AC output (must come after the specific ones above)
    # Use \bac\b to avoid matching "active" (which starts with "ac")
    (r'ac.+output|total.+ac|output.+power|\bac\b.+power|inverter.+power',
                                               'measure_power',         'AC Output Power'),

    # PV voltage
    (r'\bpv1\b.+volt|volt.+\bpv1\b',          'measure_voltage.pv1',   'PV1 Voltage'),
    (r'\bpv2\b.+volt|volt.+\bpv2\b',          'measure_voltage.pv2',   'PV2 Voltage'),
    (r'\bpv3\b.+volt|volt.+\bpv3\b',          'measure_voltage.pv3',   'PV3 Voltage'),
    (r'\bpv4\b.+volt|volt.+\bpv4\b',          'measure_voltage.pv4',   'PV4 Voltage'),
    # Other voltage
    (r'battery.+volt|volt.+battery',           'measure_voltage.battery','Battery Voltage'),
    (r'\bl1\b.+volt|volt.+\bl1\b|phase.+a.+volt|volt.+phase.+a',
                                               'measure_voltage.l1',    'L1 Voltage'),
    (r'\bl2\b.+volt|volt.+\bl2\b|phase.+b.+volt|volt.+phase.+b',
                                               'measure_voltage.l2',    'L2 Voltage'),
    (r'\bl3\b.+volt|volt.+\bl3\b|phase.+c.+volt|volt.+phase.+c',
                                               'measure_voltage.l3',    'L3 Voltage'),
    (r'grid.+volt|volt.+grid|ac.+volt|grid.+\bl\b',
                                               'measure_voltage.grid',  'Grid Voltage'),

    # PV current
    (r'\bpv1\b.+curr|curr.+\bpv1\b',          'measure_current.pv1',   'PV1 Current'),
    (r'\bpv2\b.+curr|curr.+\bpv2\b',          'measure_current.pv2',   'PV2 Current'),
    (r'\bpv3\b.+curr|curr.+\bpv3\b',          'measure_current.pv3',   'PV3 Current'),
    (r'\bpv4\b.+curr|curr.+\bpv4\b',          'measure_current.pv4',   'PV4 Current'),
    # Other current
    (r'battery.+curr|curr.+battery',           'measure_current.battery','Battery Current'),
    (r'\bl1\b.+curr|curr.+\bl1\b',            'measure_current.l1',    'L1 Current'),
    (r'\bl2\b.+curr|curr.+\bl2\b',            'measure_current.l2',    'L2 Current'),
    (r'\bl3\b.+curr|curr.+\bl3\b',            'measure_current.l3',    'L3 Current'),
    (r'grid.+curr|curr.+grid|ac.+curr',        'measure_current.grid',  'Grid Current'),

    # Energy meters (order matters: daily before total)
    (r'daily|today',                           'meter_power.today',           'Daily Production'),
    (r'total.+prod|lifetime|total.+energy(?!.+buy|.+sell|.+import|.+export)',
                                               'meter_power',                 'Total Production'),
    (r'grid.+import|import.+energy|energy.+import|energy.+buy|total.+buy',
                                               'meter_power.grid_import',     'Grid Import Energy'),
    (r'grid.+export|export.+energy|energy.+export|energy.+sell|total.+sell',
                                               'meter_power.grid_export',     'Grid Export Energy'),
    (r'battery.+charg.+energy|energy.+battery.+charg|total.+charg',
                                               'meter_power.battery_charged', 'Battery Charged Energy'),
    (r'battery.+discharg.+energy|energy.+battery.+discharg|total.+discharg',
                                               'meter_power.battery_discharged', 'Battery Discharged Energy'),

    # Temperature — battery-specific before generic
    (r'battery.+temp|temp.+battery',           'measure_temperature.battery', 'Battery Temperature'),
    (r'temp',                                  'measure_temperature',   'Temperature'),

    # Frequency
    (r'freq',                                  'measure_frequency',     'Grid Frequency'),

    # Battery charging state (lookup: Charge / Stand-by / Discharge)
    (r'battery.+status|status.+battery',       'battery_charging_state', 'Battery Status'),

    # Battery SOC
    (r'soc|state.of.charge|battery.+level',   'measure_battery',       'Battery SOC'),
]

# Homey built-in capability types that need `usingInsights: false` for sub-caps
_METER_SUBCAPS = {
    'meter_power.today',
    'meter_power.grid_import',
    'meter_power.grid_export',
    'meter_power.battery_charged',
    'meter_power.battery_discharged',
}


def _is_alarm_sensor(sensor: dict) -> bool:
    """Returns True if sensor represents a fault/alarm status via lookup."""
    if 'lookup' not in sensor:
        return False
    values = [str(o.get('value', '')).lower() for o in sensor.get('lookup', [])]
    return any(v in ('fault', 'alarm', 'warning') for v in values)


def _match_capability(sensor: dict) -> tuple[str, str] | None:
    """
    Returns (capability_id, title) for the sensor, or None if not mappable.
    Alarm sensors are detected first, then name-pattern rules are applied.
    """
    # Alarm via lookup table
    if _is_alarm_sensor(sensor):
        return ('alarm_generic', 'Fault / Alarm')

    name_lower = sensor.get('name', '').lower()

    for pattern, cap_id, title in _NAME_RULES:
        if re.search(pattern, name_lower):
            return (cap_id, title)

    # Fallback: class only
    cls = sensor.get('class', '')
    name = sensor.get('name', '')
    if cls == 'temperature':
        return ('measure_temperature', name)
    if cls == 'frequency':
        return ('measure_frequency', name)

    return None


def build_capabilities(sensors: list) -> tuple[list, dict]:
    """
    Given sensor definitions from a YAML 'parameters' list, returns:
    - capabilities:        list[str]  — Homey capability IDs
    - capabilitiesOptions: dict       — {cap_id: {title, usingInsights?}}

    Only the first sensor mapped to each capability ID is used (deduplication).
    """
    seen: set[str] = set()
    capabilities: list[str] = []
    options: dict = {}

    for sensor in sensors:
        match = _match_capability(sensor)
        if not match:
            continue
        cap_id, title = match
        if cap_id in seen:
            continue
        seen.add(cap_id)
        capabilities.append(cap_id)
        opt: dict = {'title': {'en': title}}
        if cap_id in _METER_SUBCAPS:
            opt['usingInsights'] = False
        options[cap_id] = opt

    return capabilities, options


# Capabilities that belong to the battery device (not the inverter).
# Used at pairing to split sensors into two devices.
BATTERY_CAPS: frozenset[str] = frozenset({
    "measure_battery",
    "measure_power.battery",
    "measure_voltage.battery",
    "measure_current.battery",
    "measure_temperature.battery",
    "battery_charging_state",
    "meter_power.battery_charged",
    "meter_power.battery_discharged",
})


def get_sensor_capability_map(sensors: list) -> dict[str, str]:
    """
    Returns {sensor_name: homey_capability_id} for use during polling.
    Used to map parsed register values to Homey capability updates.
    First match per capability wins (deduplication).
    """
    result: dict[str, str] = {}
    seen: set[str] = set()

    for sensor in sensors:
        match = _match_capability(sensor)
        if not match:
            continue
        cap_id, _ = match
        if cap_id not in seen:
            seen.add(cap_id)
            result[sensor['name']] = cap_id

    return result
