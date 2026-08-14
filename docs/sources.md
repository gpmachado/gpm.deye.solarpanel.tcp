# Sources

Not packaged into the Homey app build (see `.homeyignore`) — reference material for maintainers.

## Fault/Alarm Detail bit tables (`lib/fault_codes.py`)

The `_ALARM_BIT_NAMES` and `_FAULT_BIT_NAMES` tables (registers 101-106, "Device Alarm"/"Device Fault") are cross-checked against two independent sources:

- [ha-solarman](https://github.com/davidrapan/ha-solarman/wiki/Documentation) (`deye_hybrid.yaml` / `deye_p3.yaml`, "Device Alarm" / "Device Fault" rule-3 lookups) — davidrapan's `ha-solarman`, not to be confused with StephanJoubert's `home_assistant_solarman` used for the register maps themselves.
- Deye's official Modbus protocol V118 document ("Single Phase, String & Microinverters"), linked from the ha-solarman wiki's Documentation page: [Deye Modbus protocol V118.pdf](https://github.com/user-attachments/files/16597960/Deye.Modbus.protocol.V118.pdf). This document confirms registers 101-106 as "Warning message word 1-2" + "Fault information word 1-4" — the same 6-register layout already used for the hybrid "Alert" block — and includes an F-code/W-code appendix, cross-referenced as `bit = code - 1`.

Third-party AI-generated fault code lists (from Gemini, Grok, Qwen) were evaluated during development but only used where they corroborated the two sources above; contradicting entries (e.g. Qwen's F13/F18/F20 meanings) were discarded. See git log around the `fault_codes.py` history for the reasoning trail.

Not exhaustive — bits without a confirmed source are surfaced as "Unknown alarm/fault (bit N)" rather than guessed.

## Register maps (`inverter_definitions/*.json`)

Converted from [ha-solarman (StephanJoubert/home_assistant_solarman)](https://github.com/StephanJoubert/home_assistant_solarman) YAML profiles (MIT license).
