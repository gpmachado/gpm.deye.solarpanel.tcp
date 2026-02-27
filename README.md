# Deye Inverter (Local – Solarman V5) for Homey

Local integration for Deye solar inverters using the SolarmanV5 protocol over TCP. No cloud account required.

## Why this app

The existing Deye app for Homey ([com.heszi.deye](https://github.com/heszegi/com.heszi.deye)) uses the Deye/Solarman cloud API. This app communicates directly with the Wi-Fi data logger stick on your local network via TCP port 8899, giving you:

- 60s polling with no cloud latency
- No dependency on external servers or internet connectivity
- No account or credentials beyond your local network

## Supported devices

| Driver | Models | MPPT inputs | Status |
|--------|--------|-------------|--------|
| `deye_string_2mppt` | SUN-5/6/8/10/12K-G03 | 2 | ✅ Tested (SUN-9K-G03) |
| `deye_string_4mppt` | SUN-15/20K-G03 | 4 | ⚠️ Untested (same register map) |

### Planned / not yet implemented

These models use the same SolarmanV5 transport but different register maps. Contributions welcome.

| Model family | Notes |
|---|---|
| Deye Hybrid (SG0xLP1 / SG0xHP) | Single-phase hybrid with battery. Register map partially mapped in `deyeRegisters.js` as `DEYE_HYBRID` but no driver created yet. |
| Deye 3-phase (SG0xLP3 / SG0xHP3) | 3-phase string/hybrid. Needs 3-phase grid capabilities. |
| Deye Microinverter | Different register layout. |
| Sofar, Solis, Afore | Same SolarmanV5 transport, different register definitions. Could be added as separate apps or drivers. |

Register definitions for all the above exist in [ha-solarman](https://github.com/StephanJoubert/home_assistant_solarman) and could be ported following the same pattern used for `DEYE_STRING`.

## Architecture

```
lib/
  solarmanV5.js          TCP client — SolarmanV5 framing, auto-detect Modbus RTU/TCP
  registerParser.js      Decodes raw register values (rules 1–7, matches ha-solarman)
  deyeRegisters.js       Register definitions: DEYE_STRING_2MPPT, DEYE_STRING_4MPPT, DEYE_HYBRID
  DeyeDevice.js          Base Homey Device class (polling loop, capability updates)
  DeyeDriver.js          Base Homey Driver class (pairing, logger serial auto-detection)
  getLoggerWifiStatus.js Reads status.html from logger to extract serial and Wi-Fi info

drivers/
  deye_string_2mppt/     2 MPPT string inverter driver
  deye_string_4mppt/     4 MPPT string inverter driver
```

Each driver is minimal — `device.js` sets `this._definitions` and calls `super.onInit()`, `driver.js` extends `DeyeDriver` with no overrides. All logic lives in `lib/`.

## Register parsing

Register definitions follow the [ha-solarman](https://github.com/StephanJoubert/home_assistant_solarman) rule numbering exactly:

| Rule | Type | Notes |
|------|------|-------|
| 1, 3 | Unsigned, N registers lo-first | Rule 3 = uint32 |
| 2, 4 | Signed, N registers lo-first | Sign-extended via `Math.pow` to avoid JS int32 truncation |
| 5 | ASCII string | `chr(hi) + chr(lo)` per register |
| 6 | Hex bit array | Not used for capabilities |
| 7 | Version string (nibble) | Not used for capabilities |

Formula: `decoded = (raw - offset) * scale`

Temperature registers use `offset: 1000, scale: 0.1` — raw value 1617 → 61.7°C.

## Pairing flow

1. User enters logger IP address
2. App fetches `http://IP/status.html` with `admin:admin` credentials
3. Logger serial extracted from AP SSID field (`AP_1782317166` → `1782317166`)
4. App connects TCP 8899, reads inverter serial (ASCII, registers 0x0003–0x0007)
5. Device created as `Deye {inverterSerial}`
6. If step 2 fails (non-default credentials or unsupported firmware), user enters serial manually

## Adding a new device type

1. Find or create a register definition in [ha-solarman inverter_definitions](https://github.com/StephanJoubert/home_assistant_solarman/tree/main/inverter_definitions)
2. Add a new export to `lib/deyeRegisters.js` following the existing pattern
3. Create a new driver folder under `drivers/` with:
   - `device.js` — sets `this._definitions` and calls `super.onInit()`
   - `driver.js` — extends `DeyeDriver`
   - `driver.compose.json` — capabilities matching the register definitions
   - `pair/pair.html` — copy from existing driver

The `lib/` files need no changes for new register maps.

## Requirements

- Homey Pro (local platform)
- Solarman Wi-Fi logger stick with SolarmanV5 firmware
- TCP port 8899 reachable from Homey
- Logger and Homey on the same network segment (or routed with port access)

## Tested hardware

- Inverter: Deye SUN-9K-G03 (serial 2104284092)
- Logger: Solarman Wi-Fi stick (serial 1782317166, firmware APSTA mode)
- Homey Pro

## Credits

- Register definitions adapted from [ha-solarman](https://github.com/StephanJoubert/home_assistant_solarman) by Stephan Joubert (MIT)
- SolarmanV5 protocol reference from the home assistant solarman community
- Inspired by [com.heszi.deye](https://github.com/heszegi/com.heszi.deye) by Andras Heszegi

## License

MIT
