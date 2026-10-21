"""
Per-device debug output for diagnostic reports.

Library and transport debug lines don't say which device they belong to, so each
poll runs with `scope` set to its key (the logger serial); a filter on the one
stdout handler passes DEBUG/INFO only for scopes whose "Debug logging" setting is
on (or everything while DEBUG_LOG is set). Warnings and errors always pass.
A ContextVar follows the poll task through every await, including library code.
"""

import contextvars
import logging
import sys

scope: contextvars.ContextVar[str | None] = contextvars.ContextVar("debug_scope", default=None)

_enabled: set[str] = set()
_force = False


class _ScopeFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING or _force or scope.get() in _enabled


def install(force: bool = False) -> None:
    """Route app.* logging through one stdout handler (stdout reaches the Homey
    diagnostic report). Without a handler Python drops anything below WARNING."""
    global _force
    _force = force
    logger = logging.getLogger("app")
    if any(isinstance(f, _ScopeFilter) for h in logger.handlers for f in h.filters):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    handler.addFilter(_ScopeFilter())
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False


def set_enabled(key: str, on: bool) -> None:
    (_enabled.add if on else _enabled.discard)(key)


def active(key: str | None) -> bool:
    return _force or key in _enabled
