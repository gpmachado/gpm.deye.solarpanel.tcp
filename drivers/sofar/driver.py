"""
SOFAR driver — same pairing, polling and device logic as the Deye driver,
restricted to SOFAR register maps. No auto-detection: choosing this driver
already identifies the vendor (Deye probes on a SOFAR return plausible-looking
garbage, so the two vendors are kept in separate drivers).
"""

from app.drivers.deye.driver import DeyeDriver, SOFAR_MODELS


class SofarDriver(DeyeDriver):
    MODELS = SOFAR_MODELS
    AUTO_DETECT = False
    DEVICE_ID_PREFIX = "sofar"


homey_export = SofarDriver
