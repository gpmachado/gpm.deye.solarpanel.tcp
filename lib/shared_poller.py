"""
Shared polling coordinator — one TCP connection per Solarman logger serial.
Both the inverter device and battery device subscribe to the same poll loop.
"""

import asyncio
import logging
import os

_LOGGER = logging.getLogger(__name__)

_registry: dict[int, "SharedPoller"] = {}


def get_or_create(serial: int, *, host: str, port: int,
                  slave_id: int, model: str, interval: int) -> "SharedPoller":
    if serial not in _registry:
        _registry[serial] = SharedPoller(serial)
    p = _registry[serial]
    p.reconfigure(host=host, port=port, slave_id=slave_id,
                  model=model, interval=interval)
    return p


def release(serial: int, callback) -> None:
    p = _registry.get(serial)
    if p:
        p.unsubscribe(callback)
        if not p.has_subscribers():
            p.stop()
            _registry.pop(serial, None)


class SharedPoller:

    def __init__(self, serial: int):
        self.serial = serial
        self._host: str = ""
        self._port: int = 8899
        self._slave_id: int = 1
        self._model: str = "deye_string"
        self._interval: int = 60
        self._client = None
        self._subscribers: list = []
        self._task: asyncio.Task | None = None

    def reconfigure(self, *, host: str, port: int, slave_id: int,
                    model: str, interval: int) -> None:
        changed = (host != self._host or port != self._port or
                   slave_id != self._slave_id or model != self._model)
        self._host = host
        self._port = port
        self._slave_id = slave_id
        self._model = model
        self._interval = interval
        if changed:
            self._client = None

    def subscribe(self, cb) -> None:
        if cb not in self._subscribers:
            self._subscribers.append(cb)
        self._ensure_running()

    def unsubscribe(self, cb) -> None:
        self._subscribers = [s for s in self._subscribers if s is not cb]

    def has_subscribers(self) -> bool:
        return bool(self._subscribers)

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self._client = None

    def _ensure_running(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    def _build_client(self):
        from app.lib.solarman_client import SolarmanClient
        defs_dir = os.path.join(os.path.dirname(__file__), "..", "inverter_definitions")
        json_path = os.path.join(defs_dir, f"{self._model}.json")
        client = SolarmanClient(self._host, self.serial,
                                port=self._port, slave_id=self._slave_id)
        client.load_definition(json_path)
        return client

    async def _loop(self) -> None:
        _LOGGER.info(f"SharedPoller start serial={self.serial} host={self._host}")
        try:
            while self._subscribers:
                await self._poll()
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            pass
        _LOGGER.info(f"SharedPoller stop serial={self.serial}")

    async def _poll(self) -> None:
        if not self._client:
            self._client = self._build_client()
        try:
            values = await self._client.read_all()
        except Exception as e:
            _LOGGER.warning(f"SharedPoller poll error serial={self.serial}: {e}")
            self._client = None
            values = None

        for cb in list(self._subscribers):
            try:
                await cb(values)
            except Exception as e:
                _LOGGER.debug(f"SharedPoller subscriber error: {e}")
