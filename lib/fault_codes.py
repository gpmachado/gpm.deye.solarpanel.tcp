"""
Deye "Alert" bitmask decoding — Warning (32-bit) + Fault (64-bit) words.

The "Alert" sensor is 6 raw registers (rule 6 in parser.py — no built-in
lookup). registers[0:2] = "Device Alarm"/"Warning" (32 bits), registers[2:6] =
"Device Fault" (64 bits). Bit numbering and register grouping cross-checked
against two independent public sources — they agree on every overlapping
bit, and the mapping is identical across deye_hybrid, deye_sg04lp3 and
deye_string (only the register *addresses* differ, which the JSON
definitions already handle correctly):
  - github.com/davidrapan/ha-solarman (deye_hybrid.yaml / deye_p3.yaml,
    "Device Alarm" / "Device Fault" rule-3 lookups)
  - Deye's official Modbus protocol V118 doc (Single Phase, String &
    Microinverters — linked from the ha-solarman wiki's Documentation
    page), which spells out registers 101/102 as "Warning message word
    1/2" and 103-106 as "Fault information word 1-4" — the exact same
    6-register layout as the hybrid "Alert" block — plus an F-code/W-code
    appendix, cross-referenced as bit = code - 1 (confirmed via F07/F10/
    F13/F18/F20/F22/F23/F24/F26/F29/F35/F41/F42/F47/F48/F58/F63/F64 and
    W02/W03/W04 all matching bit names exactly; F60 and F61 corrected the
    other way — see bits 59/60 below)
NOT exhaustive — many bits have no publicly documented meaning yet. Unknown
set bits are surfaced as "Unknown alarm/fault (bit N)" rather than silently
dropped, so a user can report the number back instead of losing the signal.
"""

_ALARM_BIT_NAMES: dict[int, str] = {
    1: "Fan failure",
    2: "Grid phase failure",
    3: "Meter communication failure",
    4: "CT reversed",
    5: "CT not connected",
    6: "Fan 1 failure",
    7: "Fan 2 failure",
    8: "Fan 3 failure",
    30: "Battery loss",
    31: "Parallel communication quality",
}
_FAULT_BIT_NAMES: dict[int, str] = {
    0: "Reverse DC polarity (PV wiring)",
    1: "DC insulation resistance permanently low",
    2: "DC leakage current",
    3: "Grounding fault (GFDI)",
    4: "EEPROM read error",
    5: "EEPROM write error",
    6: "DC/DC Soft Start failure",
    7: "GFDI relay failure (ground-fault protection)",
    8: "IGBT hardware fault",
    9: "Auxiliary power supply failure",
    10: "AC main contactor fault",
    11: "AC auxiliary contactor fault",
    12: "Working mode changed",
    13: "DC over-current (software protection)",
    16: "Active battery hold",
    17: "AC over-current failure",
    18: "Tz_Integ_Fault failure",
    19: "DC over-current failure",
    21: "Emergency-stop fault",
    22: "AC current leakage failure",
    23: "DC insulation impedance failure",
    24: "AC active battery fault",
    25: "DC busbar unbalanced",
    28: "Parallel CAN-bus fault",
    30: "Soft start failed",
    33: "AC over-current fault",
    34: "No AC grid detected",
    36: "DCLLC soft over-current",
    38: "DCLLC over-current",
    39: "Battery over-current",
    40: "Parallel system stop",
    41: "AC line low voltage",
    45: "Battery defect",
    46: "AC over frequency",
    47: "AC under frequency",
    54: "DC bus voltage too high",
    55: "DC busbar voltage too low",
    57: "Battery BMS communication fault",
    59: "Generator voltage/frequency fault",
    60: "Manual OFF (button pressed)",
    61: "Battery BMS stopped charge/discharge",
    62: "Arc fault (AFCI) — fire risk",
    63: "Temperature is too high",
}

# Per-model overrides/additions, merged over the shared tables above.
# Empty for now — every model with a confirmed Alert register (hybrid,
# sg04lp3, string) uses the same bit meanings per Deye's official Modbus
# V118 doc. Add a model key here if a model is later found to diverge.
_MODEL_ALARM_OVERRIDES: dict[str, dict[int, str]] = {}
_MODEL_FAULT_OVERRIDES: dict[str, dict[int, str]] = {}


def known_fault_names(model: str = "") -> list[str]:
    """All alarm/fault names decode_alert() can produce for a given model
    (alphabetically, deduplicated). Used to populate the flow condition
    autocomplete — battery-specific names are filtered out there for
    non-hybrid models, since string/micro inverters have no battery port."""
    alarm_names = {**_ALARM_BIT_NAMES, **_MODEL_ALARM_OVERRIDES.get(model, {})}
    fault_names = {**_FAULT_BIT_NAMES, **_MODEL_FAULT_OVERRIDES.get(model, {})}
    return sorted(set(alarm_names.values()) | set(fault_names.values()))


def decode_alert(raw: list, model: str = "") -> str:
    """Decode the 6-register "Alert" reading into a human-readable summary.
    raw is a list of hex strings (parser.py rule 6 output), one per register,
    in the same order as the JSON's "registers" list — [alarm_lo, alarm_hi,
    fault_word0..3]. model selects per-model bit-name overrides, if any."""
    if not raw or len(raw) < 6:
        return "OK"
    try:
        regs = [int(h, 16) for h in raw]
    except (TypeError, ValueError):
        return "OK"

    alarm_names = {**_ALARM_BIT_NAMES, **_MODEL_ALARM_OVERRIDES.get(model, {})}
    fault_names = {**_FAULT_BIT_NAMES, **_MODEL_FAULT_OVERRIDES.get(model, {})}

    alarm_word = regs[0] | (regs[1] << 16)
    fault_word = regs[2] | (regs[3] << 16) | (regs[4] << 32) | (regs[5] << 48)

    active: list[str] = []
    for bit, name in alarm_names.items():
        if alarm_word & (1 << bit):
            active.append(name)
    for bit in range(32):
        if bit not in alarm_names and (alarm_word & (1 << bit)):
            active.append(f"Unknown alarm (bit {bit})")

    for bit, name in fault_names.items():
        if fault_word & (1 << bit):
            active.append(name)
    for bit in range(64):
        if bit not in fault_names and (fault_word & (1 << bit)):
            active.append(f"Unknown fault (bit {bit})")

    return ", ".join(active) if active else "OK"
