"""SOFAR device — identical behaviour to the Deye device (see drivers/deye/device.py)."""

from app.drivers.deye.device import DeyeDevice


class SofarDevice(DeyeDevice):
    pass


homey_export = SofarDevice
