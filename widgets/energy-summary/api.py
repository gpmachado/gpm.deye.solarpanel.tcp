from typing import Any, Never

from homey.homey import Homey


async def getSummary(  # noqa: N802 — name must match widget.compose.json key exactly
    *,
    homey: Homey,
    query: dict[str, str],
    params: dict[str, str],
    body: dict[Never, Never],
) -> Any:
    return homey.app.get_solar_summary()  # type: ignore[attr-defined]


__all__ = ["getSummary"]
