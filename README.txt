Monitor your Deye solar inverter directly on your local network — no cloud account, no internet dependency.

This app communicates with the Solarman Wi-Fi data logger stick using the SolarmanV5 protocol over TCP port 8899, polling your inverter every 60 seconds.

SUPPORTED MODELS
- Deye Microinverter 2 MPPT (SUN600G3 / SUN800G3 / SUN1000G3)
- Deye Microinverter 4 MPPT (SUN2000G3)
- Deye String Inverter 3-phase, 2 MPPT
- Deye Hybrid Inverter with battery, 2 MPPT
- Deye Hybrid Inverter 3-phase SG04LP3 (SUN-8K / SUN-10K / SUN-12K-SG04LP3-EU)

REQUIREMENTS
- Homey Pro (firmware 13.0 or later)
- Solarman Wi-Fi data logger stick connected to your local network
- TCP port 8899 accessible from Homey (no firewall blocking)

AVAILABLE DATA
Depending on inverter model:
- Real-time AC output power (W)
- PV string voltage and current per channel (PV1–PV4)
- Grid voltage, current and frequency
- Inverter temperature
- Daily and total production (kWh)
- Battery power, voltage, current and state of charge (hybrid models)
- Grid import / export energy (hybrid models)
- Load power consumption (hybrid models)
- Fault / Alarm state

HOMEY ENERGY
Fully integrated with Homey Energy. Your inverter appears as a solar panel device and contributes to your energy dashboard automatically.

PAIRING
1. Open Homey and add a new device
2. Leave the IP field empty to auto-discover loggers on your network, or enter the IP manually
3. The logger serial number is detected automatically (or enter it manually from the sticker)
4. Select your inverter model from the list
5. Capabilities are configured automatically based on your model

NOTES
- Local communication only — no Deye cloud or SolarmanCloud required.
- Auto-discovery uses UDP broadcast on port 48899 (Solarman discovery protocol).
- Night-time detection pauses polling between sunset and sunrise to avoid false unavailability alerts.
- Inverter definitions based on the home_assistant_solarman open-source project.
