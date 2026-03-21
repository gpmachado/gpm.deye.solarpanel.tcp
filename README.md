# Deye Inverter (Local – Solarman V5) for Homey

Local integration for Deye solar inverters using the SolarmanV5 protocol over TCP. No cloud account required.

## Why this app

The existing Deye app for Homey ([com.heszi.deye](https://github.com/heszegi/com.heszi.deye)) uses the Deye/Solarman cloud API. This app communicates directly with the Wi-Fi data logger stick on your local network via TCP port 8899, giving you:

- 60s polling with no cloud latency
- No dependency on external servers or internet connectivity
- No account or credentials beyond your local network

## Supported models

| Model ID | Inverter family | MPPT | Type | Status |
|---|---|---|---|---|
| `deye_2mppt` | SUN-xK-G03 (single-phase string) | 2 | String | ✅ Tested |
| `deye_4mppt` | SUN-15/20K-G03 (single-phase string) | 4 | String | ⚠️ Untested |
| `deye_hybrid` | SUN-xK-SG0xLP1 / SG0xHP (single-phase hybrid) | 2 | Hybrid + Battery | ⚠️ Untested |
| `deye_string` | SUN-xK 3-phase string | 2 | 3-phase String | ⚠️ Untested |
| `deye_sg04lp3` | SUN-8/10/12K-SG04LP3-EU (3-phase hybrid) | 2 | 3-phase Hybrid | ⚠️ Untested |

Register definitions are adapted from [ha-solarman](https://github.com/StephanJoubert/home_assistant_solarman) (MIT).

> **Note on MW4C loggers:** Some newer Deye logger sticks ship with MW4C firmware instead of the standard LSW3. The SolarmanV5 protocol does not work reliably with MW4C firmware. If your logger does not respond after pairing, check the firmware version on the logger's status page (`http://<logger-ip>/status.html`).

## Pairing

1. Open the Homey app → Add device → Deye Inverter
2. Leave the IP field blank for automatic UDP discovery, or enter the logger IP manually
3. The app broadcasts a UDP discovery packet on port 48899 and detects all loggers on the LAN
4. Once connected, the app probes the inverter registers to auto-detect the model
5. The detected model is shown for confirmation before the device is added

If auto-discovery fails (different network segment), enter the IP address of the logger. The serial number is read automatically from the logger's status page or via UDP. As a last resort, enter it manually — it is printed on the sticker on the logger stick.

## Architecture

```
app.py                          Homey app entry point
lib/
  solarman_client.py            Async SolarmanV5 TCP client (wraps pysolarmanv5)
  parser.py                     Register value decoder (rules 1–10, adapted from ha-solarman)
  capability_map.py             Maps sensor names to Homey capability IDs
drivers/
  deye/
    driver.py                   Pairing flow: UDP discovery, model auto-detection
    device.py                   Polling loop, night backoff (astral), capability updates
inverter_definitions/
  deye_2mppt.json               Register map for single-phase string 2 MPPT
  deye_4mppt.json               Register map for single-phase string 4 MPPT
  deye_hybrid.json              Register map for single-phase hybrid
  deye_string.json              Register map for 3-phase string
  deye_sg04lp3.json             Register map for 3-phase hybrid SG04LP3
```

## Model auto-detection

The driver reads register sets from all 5 models and scores each one based on non-zero values returned. The model with the highest score is selected. The user can override the detected model in the confirmation step before adding the device.

## Night behaviour

The device uses the [astral](https://astral.readthedocs.io/) library with the Homey geolocation to calculate local sunrise and sunset. Outside the solar window (plus a 30-minute buffer), polling stops and instantaneous capabilities are zeroed. Energy counters (lifetime production) are preserved.

## Register parsing

Register definitions follow the [ha-solarman](https://github.com/StephanJoubert/home_assistant_solarman) rule numbering:

| Rule | Type |
|---|---|
| 1, 3 | Unsigned integer (1 or 2 registers, lo-first) |
| 2, 4 | Signed integer |
| 5 | ASCII string |
| 6 | Hex bit array |
| 7 | Version string (nibble-encoded) |
| 8 | DateTime |
| 9 | Time |
| 10 | Raw |

Formula: `value = (raw - offset) * scale`

Temperature registers use `offset: 1000, scale: 0.1` — raw 1261 → 26.1°C. A `validation: {min: -20}` guard filters the -100°C reading that occurs when the inverter is off and the temperature sensor returns 0.

## Requirements

- Homey Pro with Python runtime (firmware 13+)
- Solarman Wi-Fi logger stick with **LSW3** firmware (LSW3_15_FFFF or similar)
- TCP port 8899 reachable from Homey
- UDP port 48899 reachable for auto-discovery (same network segment)

## Tested hardware

- Inverter: Deye SUN-9K-G03 (single-phase string, 2 MPPT)
- Logger: Solarman Wi-Fi stick LSW3 (firmware LSW3_15_FFFF_1.0.9E)
- Homey Pro (2023)

## Credits

- Register definitions from [ha-solarman](https://github.com/StephanJoubert/home_assistant_solarman) by Stephan Joubert (MIT)
- SolarmanV5 Python library: [pysolarmanv5](https://github.com/jmccrohan/pysolarmanv5) by Jonathan McCrohan (MIT)
- Inspired by [com.heszi.deye](https://github.com/heszegi/com.heszi.deye) by Andras Heszegi

## License

MIT
