Deye Inverter (Local – Solarman V5)

Monitor your Deye solar inverter directly on your local network — no cloud account, no internet dependency.

This app communicates with the Solarman Wi-Fi data logger stick using the SolarmanV5 protocol over TCP port 8899, polling your inverter every 60 seconds.

SUPPORTED MODELS
- Deye G0* String Inverters, 2 MPPT inputs (SUN-5K-G03, SUN-6K-G03, SUN-8K-G03, SUN-10K-G03, SUN-12K-G03)
- Deye G0* String Inverters, 4 MPPT inputs (SUN-15K-G03, SUN-20K-G03)

REQUIREMENTS
- Homey Pro
- Solarman Wi-Fi data logger stick connected to your local network
- TCP port 8899 accessible from Homey (no firewall blocking)

AVAILABLE DATA
- Real-time AC output power (W)
- PV string voltage and current per input
- Grid voltage, current and frequency
- Inverter temperature
- Daily production (kWh)
- Total production (kWh)
- Fault / Alarm state

HOMEY ENERGY
This app is fully integrated with Homey Energy. Your inverter will appear as a solar panel device and contribute to your energy dashboard automatically.

PAIRING
1. Open Homey and add a new device
2. Select the number of MPPT inputs your inverter has (2 or 4)
3. Enter the IP address of your logger stick
4. The logger serial number is detected automatically
5. If auto-detection fails, enter the serial manually — it is printed on the label of the logger stick

NOTES
- This app communicates locally only. It does not use the Deye cloud or SolarmanCloud.
- Grid power, load power and battery data are not available on string inverters without an external energy meter or battery.
- Tested with SUN-9K-G03 and Solarman logger firmware supporting the SolarmanV5 protocol.
