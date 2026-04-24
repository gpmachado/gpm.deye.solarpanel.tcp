# Project context — gpm.python.deye (Python)

## Locations

- Local: `/Users/gabriel/HomeyApp/gpm.python.deye`
- GitHub: https://github.com/gpmachado/gpm.python.deye (branch: `main`)

## Architecture

Single universal driver (`drivers/deye/`) supporting four inverter models selected
at pairing (auto-detected or manually chosen).

### Key files

| File | Role |
|------|------|
| `drivers/deye/driver.py` | Pairing wizard, UDP discovery, model auto-detection, repair flow |
| `drivers/deye/device.py` | Device lifecycle, polling loop, night backoff, capability updates |
| `drivers/deye/pair/login.html` | Pairing UI: auto-scan → tile preview → error/manual fallback |
| `drivers/deye/repair/repair_device.html` | Repair UI: re-detect, change model, change IP |
| `drivers/deye/driver.compose.json` | Driver manifest, settings, pair/repair arrays |
| `capability_map.py` | Maps inverter entity names → Homey capability IDs |
| `inverter_definitions/` | JSON register maps for each model |
| `v5_transport.py` | SolarmanV5 TCP protocol implementation |
| `app.py` | App entry point |

### Supported models

| ID | Description |
|----|-------------|
| `deye_micro` | Micro-inverter (single-phase, 1–4 PV inputs) |
| `deye_string` | String inverter (single/split-phase, up to 4 MPPT) |
| `deye_hybrid` | Hybrid inverter with battery and grid meter (LP1 series) |
| `deye_sg04lp3` | 3-phase hybrid with battery (SG04LP3 series) |

Model is auto-detected at pairing based on register fingerprinting. Score > 0 means
confident detection; score = 0 (e.g. night-time pairing with no PV data) falls back
to showing the dropdown.

### Inverter definitions

Each `inverter_definitions/deye_*.json` is a list of sensor objects. Fields:

| Field | Meaning |
|-------|---------|
| `name` | Entity name (matched by `capability_map.py`) |
| `rule` | Decode rule: 1=signed×scale, 2=unsigned×scale, 3=32-bit LE, 4=status string |
| `registers` | Register address(es) |
| `offset` | Subtracted before scale (e.g. `1000` for T×10+1000 encoding) |
| `scale` | Multiplier after offset |
| `validation` | `{min, max}` range check — values outside are suppressed |

**Important**: `deye_sg04lp3` temperature sensors use `offset: 1000` (encoding is
`T×10+1000`, same as hybrid). This is intentional — confirmed in Node.js source
with explicit comment `// (raw - 1000) * 0.1`. Do NOT remove these offsets.

### Connection protocol

- SolarmanV5 TCP, port 8899 (configurable)
- UDP discovery on port 48899, two payloads with 100 ms gap:
  - `b"WIFIKIT-214028-READ"` — standard logger
  - `b"HF-A11ASSISTHREAD"` — HF-A11 module loggers (davidrapan scanner.py pattern)
- Modbus slave ID default: 1 (configurable)

### Polling

- Default: every 60 seconds (configurable 35–3600 s)
- Night backoff: reduced polling rate during solar night
- Night detection: `astral` library using Homey geolocation + timezone

### Settings (driver.compose.json)

| Key | Type | Description |
|-----|------|-------------|
| `host` | text | Logger IP address |
| `loggerSerial` | number | Logger serial (auto-detected if 0) |
| `model` | label | Detected inverter model (read-only display) |
| `loggerMac` | label | Logger MAC address |
| `wifiSsid` | label | Wi-Fi network SSID |
| `wifiRssi` | label | Wi-Fi signal strength |
| `port` | number | TCP port (default 8899) |
| `slaveId` | number | Modbus slave ID (default 1) |
| `pollingInterval` | number | Polling interval in seconds (default 60) |

## Read-only policy

**This app is read-only.** It reads telemetry, updates capabilities, and fires flow
cards based on measured data. It must NOT write to inverter registers.

Forbidden actions:
- Set Work Mode, Solar Sell, TOU schedules
- Set battery limits (low SOC, max charge/discharge current)
- Set Grid Charge / Gen Charge
- Set export limit or Peak Shaving
- Turn inverter on/off
- Write any Modbus configuration register

Flow card actions are allowed only if they have no effect on the inverter
(e.g. refresh logger info, force data re-read, reset local state).

## Pairing flow

```
login (auto-scan + tile preview)  →  add_devices
```

`login.html` auto-scans on load. Shows 3 phases:
1. **scan** — spinner while UDP discovery + login runs
2. **found** — device tile (IP, serial), model badge (green=confident / orange=uncertain),
   model dropdown if uncertain, "Add Inverter" button calls `confirm_model` emit then
   `Homey.nextView()`
3. **error** — manual IP/serial fields + "Retry auto-scan" button

`confirm_model` is no longer a separate screen — model confirmation happens inline in
`login.html`.

## Repair flow

`repair_device.html` accessible via device → three-dot menu → Repair.

Features:
- Shows current model and IP
- "Re-detect" button runs `_detect_model()` against live device
- Model dropdown pre-selected with current model
- IP input pre-filled with current host
- Save calls `device.set_settings()` which triggers `on_settings` → poller rebuild

Changing model via repair changes which registers are polled but does NOT add/remove
devices (battery/grid meter devices require re-pairing for that).

## Recent fixes (latest first)

### `0f39dd5` — fix: repair screen crash `'DeyeDevice' object has no attribute 'id'`
`device.id` → `device.get_id()`. Homey Python SDK uses method, not attribute.

### `fcd1cc3` — fix: night backoff disabled when geolocation/timezone unavailable
When `clock.get_timezone()` returned `None`, `_get_sunrise_sunset()` fell back to
hardcoded `(6.0, 19.0)` in UTC. For Brazil (UTC-3) this triggered night mode at
~18h local. Fix: return `None`, `_is_night_time()` returns `False` (assume daytime).

### `d4c53c5` — revert: restore offset:1000 for sg04lp3 temperature sensors
Incorrectly removed in previous commit after misreading Mathajas diff. The offset is
intentional (T×10+1000 encoding). Confirmed in Node.js deyeSG04LP3Registers.js.

### `83e3a15` — fix: on_repair device.get_id() crash (same as 0f39dd5 above)

### UDP discovery — dual payload
Added `HF-A11ASSISTHREAD` as second discovery payload so HF-A11 module loggers
respond during pairing (matches davidrapan/ha-solarman scanner.py).

## Known users / testers

| User | Model | Notes |
|------|-------|-------|
| Gabriel | deye_string | Main dev/tester, Brazil |
| Luis | deye_hybrid (SUN-5K-SG05LP1-EU-AM2-P) | Battery not in Energy dashboard; AC Output Power shown instead of PV1 Power for instantaneous production |

## Pending tasks

### High priority

- [ ] **Test new login.html auto-scan** — no real device test yet on current version.
  Verify tile shows correctly for both confident (score > 0) and uncertain (score = 0)
  detection.
- [ ] **Luis's hybrid issues** (after publishing):
  - Battery device not appearing in Homey Energy dashboard
  - AC Output Power shown instead of PV1 Power as primary production value

### Flow cards (Phase 1 — highest value)

- [ ] `Solar power crossed threshold` trigger (T↑, T↓) with `power` / `daily_production` tokens
- [ ] `Grid import/export crossed threshold` trigger — useful for surplus automation
- [ ] `Battery SOC crossed threshold` trigger (for hybrid/sg04lp3 users)
- [ ] `Battery started charging/discharging/idle` trigger
- [ ] `Night mode started` / `Night mode ended` triggers with `reason`, `timezone`,
  `sunrise`, `sunset` tokens — reduces confusion between real failure and expected offline

### Flow cards (Phase 2)

- [ ] `Logger connection lost` / `Logger connection restored` triggers
- [ ] `Polling failed N times` trigger
- [ ] `Wi-Fi signal dropped below threshold` trigger/condition
- [ ] `Daily production reached target` trigger
- [ ] `Inverter fault appeared/cleared` trigger (more detail than current `alarm_generic`)

### Flow cards (Phase 3 — hybrid-specific)

- [ ] `Work mode changed` trigger (reads Work Mode register, fires on state change)
- [ ] `Generator started/stopped` trigger
- [ ] `Load power crossed threshold` trigger

### Flow cards — avoid for now

- Per-PV-input triggers (PV1/PV2/PV3/PV4 individual) — too noisy
- Raw register triggers
- Write actions (set work mode, set export limit, etc.) — read-only policy

### Capability gaps (from HA entity comparison)

Mapping change status:
- `deye_string.json` was not rewritten after `v1.3.2`; current tests show the
  core register map matches Gabriel's HA/Deye Cloud values for production,
  voltage/current/frequency, totals, and status.
- `deye_hybrid.json` did receive targeted changes after `v1.3.2`: PV3/PV4
  voltage/current/power were added, the first request was extended from register
  112 to 116, and Grid Current L1/L2 decode changed from unsigned (`rule: 1`) to
  signed (`rule: 2`).
- Do not broadly rewrite either map without a new register baseline. Future work
  should compare each changed/added hybrid sensor against Luis's HA screenshots
  and diagnostic files before publishing.

Capability profile idea:
- Add a pairing/settings checkbox for "advanced sensors" (wording TBD).
- Default profile should expose only reliable, production-focused capabilities for
  string inverters without battery.
- Advanced profile can expose additional/experimental sensors for users who want
  full HA-style comparison.

For pairing, split capabilities into:

Required/essential capabilities:
- These should be added automatically when the model supports them.
- They represent the core purpose of the device and should be reliable enough for
  normal Homey use.
- For a string inverter without battery, these are production/solar telemetry,
  status, and basic AC context.

Optional/advanced capabilities:
- These should be behind a pairing checkbox or equivalent advanced choice.
- They are useful for diagnostics, HA parity, or advanced users, but may be
  model/firmware/install dependent.
- A zero value is not automatically invalid for power/energy sensors, but some
  sensors may still be non-informative on a given installation.

For `deye_string` without battery (Gabriel's case), treat the inverter primarily
as a solar production device, not as a whole-home/grid meter. Gabriel has 3-phase
utility service and exports through only 2 phases, so string-inverter telemetry
does not represent complete house load or complete grid import/export.

Basic/immediate-interest `deye_string` capabilities:
- PV1 Voltage.
- PV1 Current.
- PV1 Power, derived when the inverter has no direct PV1 power register:
  `PV1 Voltage * PV1 Current`.
- PV2 Voltage.
- PV2 Current.
- PV2 Power, derived when the inverter has no direct PV2 power register:
  `PV2 Voltage * PV2 Current`.
- Solar Power / DC Input Power, mapped from `Input Power` when available
  (`regs 82,83` on Gabriel's inverter).
- AC Output Power, mapped from `Output AC Power` when available (`regs 80,81`
  on Gabriel's inverter).
- Power Losses, derived as `Input Power - Output AC Power` when both values are
  present. This is useful for immediate diagnostics but should be labelled
  clearly as a derived conversion-loss estimate.
- Daily Production.
- Total Production.
- Grid L1 Voltage.
- Grid L1 Current.
- Grid Frequency.
- DC/module Temperature when decoded value is valid.
- Running Status.
- Fault / Alarm.
- PV1/PV2 voltage/current are structural on 2-MPPT `deye_string` devices and
  should not be filtered out just because pairing happens near sunset/night.

Keep available but advanced/optional for `deye_string`:
- Today/Total Energy Import/Export (0 is valid and should not be suppressed)
- Today/Total Load Consumption (may mirror production on Gabriel's inverter)
- `AC Output Power` as an alternate AC power register if it exists separately
  from `Output AC Power` (`regs 86,87` on Gabriel's inverter).
- Output Apparent Power / Output Reactive Power.
- PV3/PV4 voltage/current/power for 4-MPPT string devices or when values are
  actually present.

Avoid publishing by default for Gabriel-like `deye_string` devices:
- Grid Power (stays 0 on Gabriel's inverter)
- Load Power (stays 0 in HA on Gabriel's inverter)
- Today/Total Losses (Total Losses is unknown in HA; Total Production equals
  Total Load Consumption on Gabriel's inverter)
- Radiator/Ambient Temperature when decoded value is `-100 °C` (raw 0 with
  offset means sensor unavailable)
- Battery capabilities
- PV3/PV4 when voltage and current are consistently 0 on 2-MPPT devices

High priority additions to inverter_definitions:
- `PV1..PV4 Power` for deye_micro and deye_string (capability_map.py already handles
  `measure_power.pv1..pv4`, just missing from JSON sensor definitions)
- `PV3/PV4` full set (voltage, current, power) for deye_hybrid
- `Today Battery Discharge` and daily battery energy metrics for deye_hybrid
- `Work Mode` and `Grid-connected Status` as enum/text capabilities for deye_hybrid

Medium priority:
- `Grid L2/L3 Voltage` and current for deye_string (3-phase installations)
- `Output Apparent Power` / `Reactive Power` / `Input Power` / `Power losses`

Diagnostic-only (lower priority):
- `Device Alarm` and `Device Fault` with more detail than current `alarm_generic`
- CT internal/external measurements
- Generator metrics
- Separate grid/load/output frequencies

### Settings improvements

- [ ] Consider adding a `Diagnostics` group (separate from `Advanced`) containing
  read-only labels: `Last successful poll`, `Last error`, `Night mode`, `Timezone`
- [ ] `Last successful poll` label would help users distinguish real failure from
  expected night offline

### sg04lp3 temperature validation

- [ ] Needs real device test from an sg04lp3 owner. Offset:1000 is confirmed correct
  from Node.js source, but validation ranges (`min:1, max:99` for battery temp,
  no range for DC/AC temps) may need adjustment based on real hardware.

## Patterns / conventions

- All comments and docstrings in **English**
- `_LOGGER = logging.getLogger(__name__)` for module-level logging
- `self.log(...)` for device-level operational messages
- Night backoff: **never use hardcoded time fallbacks** — return `None` and assume daytime
- `on_settings(self, old_settings, new_settings, changed_keys)` — keyword args (SDK ≥ 1.x)
- `device.get_id()` not `device.id` — Homey Python SDK uses methods for device identity
- Temperature encoding with `offset:1000`: raw = T×10+1000 → decoded = (raw−1000)×0.1

## Relationship with gpm.python.hoymiles

Both apps share patterns (night backoff, `on_settings` signature, polling loop). Fixes
that affect shared logic should be applied to both. Hoymiles app is at
`/Users/gabriel/HomeyApp/gpm.python.hoymiles`.

Hoymiles pending: repair flow not yet implemented (see Hoymiles CONTEXT.md).
