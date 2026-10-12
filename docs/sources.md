# Sources

Not packaged into the Homey app build (see `.homeyignore`) — reference material for maintainers.

## Fault/Alarm Detail bit tables (`lib/fault_codes.py`)

The `_ALARM_BIT_NAMES` and `_FAULT_BIT_NAMES` tables (registers 101-106, "Device Alarm"/"Device Fault") are cross-checked against two independent sources:

- [ha-solarman](https://github.com/davidrapan/ha-solarman/wiki/Documentation) (`deye_hybrid.yaml` / `deye_p3.yaml`, "Device Alarm" / "Device Fault" rule-3 lookups) — davidrapan's `ha-solarman`, not to be confused with StephanJoubert's `home_assistant_solarman` used for the register maps themselves.
- Deye's official Modbus protocol V118 document ("Single Phase, String & Microinverters"), linked from the ha-solarman wiki's Documentation page: [Deye Modbus protocol V118.pdf](https://github.com/user-attachments/files/16597960/Deye.Modbus.protocol.V118.pdf). This document confirms registers 101-106 as "Warning message word 1-2" + "Fault information word 1-4" — the same 6-register layout already used for the hybrid "Alert" block — and includes an F-code/W-code appendix, cross-referenced as `bit = code - 1`.

Third-party AI-generated fault code lists (from Gemini, Grok, Qwen) were evaluated during development but only used where they corroborated the two sources above; contradicting entries (e.g. Qwen's F13/F18/F20 meanings) were discarded. See git log around the `fault_codes.py` history for the reasoning trail.

Not exhaustive — bits without a confirmed source are surfaced as "Unknown alarm/fault (bit N)" rather than guessed.

## Register maps (`inverter_definitions/*.json`)

Deye maps were first converted from [StephanJoubert/home_assistant_solarman](https://github.com/StephanJoubert/home_assistant_solarman) YAML profiles (Apache-2.0 — see `THIRD_PARTY_NOTICES.txt` and `LICENSES/Apache-2.0.txt`) and later checked and updated against [davidrapan/ha-solarman](https://github.com/davidrapan/ha-solarman) (MIT), which is the more current source. **Use davidrapan as the primary reference for new or updated profiles.**

`sofar_g3_hybrid.json` starts from that project's `sofar_g3hyd.yaml`, cross-checked with davidrapan's `sofar_g3hyd.yaml`, SOFARSOLAR's *Modbus-G3 Protocol V1.42* (§4.5, 0x0667/0x0668) and two register dumps from a SOFAR ESI-12K-T1 (GitHub issues #7/#8; anonymised fixture in `tests/fixtures/`).

## Reference projects

Consulted for register meanings, scales and sign conventions. Copying code or
maps is only allowed under each project's license, with attribution in
`THIRD_PARTY_NOTICES.txt`.

| Project | License | Covers | Notes |
|---|---|---|---|
| [davidrapan/ha-solarman](https://github.com/davidrapan/ha-solarman) | MIT | ~30 Solarman-logger profiles: Deye, SOFAR, Solis, Afore, Kstar, Chint, INVT, SRNE… | Most active Solarman integration. Its YAML adds composite sensors, `uint`, `range` that `lib/parser.py` does not support — drop or adapt those sensors when converting. |
| [StephanJoubert/home_assistant_solarman](https://github.com/StephanJoubert/home_assistant_solarman) | Apache-2.0 | 17 profiles, same rule numbering as `lib/parser.py` | Origin of the parser and Deye maps. Inactive since 2024. |
| [kellerza/sunsynk](https://github.com/kellerza/sunsynk) | Apache-2.0 | Deye / Sunsynk single- and three-phase register definitions (Python) | Good second opinion for Deye hybrid registers and signs. |
| [jlopez77/DeyeInverterHA](https://github.com/jlopez77/DeyeInverterHA) | MIT | Deye hybrids and clones (TurboEnergy…) | |
| [Developer089/deye-modbus-ha](https://github.com/Developer089/deye-modbus-ha) | MIT | Deye 3-phase hybrids SG04LP3 / SG05LP3 (incl. 12K SG05) over Modbus TCP | Useful for `deye_sg04lp3.json`. |
| [solarmanpv/homeassistant-solarman](https://github.com/solarmanpv/homeassistant-solarman) | **none** | Solarman | No license = all rights reserved: read for reference only, do not copy code or maps. |

Adding a profile: get a register dump and the inverter display values from a user
with the hardware (`scan-auto-detect/test_registers.py` or
`sofar_register_dump.py`), then add a fixture case to `tests/test_core.py`.
