"""
Homey-local calendar date for the daily midnight reset.

The Python SDK's ManagerClock (homey 0.0.11) starts at "UTC" and only learns the
real time zone from an onTimezoneChange broadcast — unlike ManagerGeolocation it
fetches nothing at init — so get_timezone() returns "UTC" after every normal start,
whatever is set on the Homey. Sources, most exact first:

1. Homey's time zone, when it isn't a UTC alias (fixed SDK, or changed while running).
2. One seen earlier from (1), kept by the caller (e.g. in the device store) —
   ignored when its offset is more than 4 h from the longitude's (the Homey moved).
3. A whole-hour UTC offset from the longitude (round(lon / 15)) when far from
   Greenwich. Exact without DST (e.g. Brazil); 1–2 h off with DST or in political
   time zones (Spain, Iceland, western China), and 30–45 min off in half-hour zones
   (India, Iran, Nepal) — still the middle of the night, which is all the daily
   reset needs.

Kept identical in the Deye and Hoymiles apps.
"""

from datetime import datetime, timedelta, timezone, tzinfo, UTC
from zoneinfo import ZoneInfo

UTC_ALIASES = frozenset({
    "UTC", "Etc/UTC", "UCT", "Etc/UCT", "GMT", "Etc/GMT", "Etc/GMT+0", "Etc/GMT-0",
    "Etc/GMT0", "GMT0", "Greenwich", "Etc/Greenwich", "Universal", "Etc/Universal",
    "Zulu", "Etc/Zulu",
})

# Beyond half a time zone from Greenwich a "UTC" Homey is almost certainly the SDK
# default, not the user's setting.
_MIN_OFFSET_LONGITUDE = 7.5
# Political time zones sit up to ~3 h from their longitude (western China); more than
# this and a stored zone is from before the Homey moved.
_MAX_STORED_DRIFT_H = 4


def real_tz_name(name: str | None) -> str | None:
    """`name` if it is a loadable, non-UTC IANA time zone, else None."""
    if not name or name in UTC_ALIASES:
        return None
    try:
        ZoneInfo(name)
    except Exception:
        return None
    return name


def _near_longitude(name: str, longitude: float | None) -> bool:
    if longitude is None:
        return True
    offset = datetime.now(UTC).astimezone(ZoneInfo(name)).utcoffset()
    return abs(offset.total_seconds() / 3600 - longitude / 15) <= _MAX_STORED_DRIFT_H


def resolve_tz(homey_tz: str | None, learned_tz: str | None,
               longitude: float | None) -> tuple[tzinfo, str]:
    """(time zone, how it was chosen) — the description goes in the device log."""
    if name := real_tz_name(homey_tz):
        return ZoneInfo(name), f"Homey time zone {name}"
    if (name := real_tz_name(learned_tz)) and _near_longitude(name, longitude):
        return ZoneInfo(name), f"stored time zone {name} (Homey reports {homey_tz})"
    if longitude is not None and abs(longitude) > _MIN_OFFSET_LONGITUDE:
        hours = round(longitude / 15)
        return (timezone(timedelta(hours=hours)),
                f"UTC{hours:+d} from longitude {longitude:.1f} (Homey reports {homey_tz})")
    return UTC, f"UTC (Homey reports {homey_tz})"


def local_date(tz: tzinfo, now: datetime | None = None) -> str:
    """ISO calendar date in `tz` — `now` (aware) for tests, else the current time."""
    return (now or datetime.now(UTC)).astimezone(tz).date().isoformat()
