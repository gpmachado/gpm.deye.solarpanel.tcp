"""
Async Solarman inverter client for Homey Python runtime.
Uses V5Transport (pure asyncio) — required by the Homey sandbox.
Logic adapted from home_assistant_solarman (MIT License).
"""

import asyncio
import json
import logging

from app.lib.v5_transport import V5Transport
from app.lib.parser import ParameterParser

log = logging.getLogger(__name__)

QUERY_RETRY_ATTEMPTS = 3
_RETRY_SLEEP_S = 3        # seconds between retry attempts (give logger time to recover)
MAX_REGISTERS_PER_REQUEST = 125  # Request the full JSON-defined range per call.
                                  # Solarman loggers may return fewer registers than requested
                                  # (partial response); _send_request advances by the actual
                                  # received count and loops until the full range is covered.
                                  # Using the full range avoids the pathological case where
                                  # smaller chunks (e.g. 50) cause the logger to return even
                                  # fewer registers (e.g. 7) than a large request (~58).


class SolarmanClient:

    def __init__(self, host: str, serial: int, port: int = 8899, slave_id: int = 1):
        self._host = host
        self._serial = int(serial)
        self._port = port
        self._slave_id = slave_id
        self._modbus: V5Transport | None = None
        self._parameter_definition: dict | None = None

    def load_definition(self, json_path: str) -> None:
        with open(json_path, encoding="utf-8") as f:
            self._parameter_definition = json.load(f)

    # ── Connection ────────────────────────────────────────────────────────────

    async def _connect(self) -> None:
        if self._modbus:
            return
        log.debug(f"Connecting to {self._host}:{self._port} serial={self._serial}")
        self._modbus = V5Transport(
            self._host,
            self._serial,
            port=self._port,
            slave=self._slave_id,
            timeout=8.0,
        )
        await self._modbus.connect()

    async def _disconnect(self) -> None:
        if self._modbus:
            try:
                await self._modbus.disconnect()
            except Exception:
                pass
            finally:
                self._modbus = None

    # ── Register I/O ──────────────────────────────────────────────────────────

    async def _send_request(self, params: ParameterParser, start: int, end: int, mb_fc: int) -> None:
        """Read registers [start..end], splitting into chunks ≤ MAX_REGISTERS_PER_REQUEST.

        Advances by the actual number of registers returned so partial responses
        (where the logger returns fewer than requested) are handled gracefully.
        If the logger returns 0 registers for a chunk, a ValueError is raised to
        trigger the normal retry / connection-error path.
        """
        addr = start
        while addr <= end:
            chunk = min(MAX_REGISTERS_PER_REQUEST, end - addr + 1)
            if mb_fc == 3:
                response = await self._modbus.read_holding_registers(register_addr=addr, quantity=chunk)
            elif mb_fc == 4:
                response = await self._modbus.read_input_registers(register_addr=addr, quantity=chunk)
            else:
                raise ValueError(f"Unsupported Modbus function code: {mb_fc}")
            received = len(response)
            if received == 0:
                raise ValueError(f"Register [{addr:#x}]: logger returned 0 registers")
            params.parse(response, addr, received)
            addr += received

    # ── Public async API ──────────────────────────────────────────────────────

    async def read_all(self) -> dict:
        """Read all registers defined in the loaded JSON. Returns {name: value}."""
        if not self._parameter_definition:
            raise ValueError("No definition loaded. Call load_definition() first.")

        params = ParameterParser(self._parameter_definition)
        requests = self._parameter_definition["requests"]

        for request in requests:
            start = request["start"]
            end = request["end"]
            mb_fc = request["mb_functioncode"]

            success = False
            for attempt in range(QUERY_RETRY_ATTEMPTS):
                try:
                    await self._connect()
                    await self._send_request(params, start, end, mb_fc)
                    success = True
                    break
                except Exception as e:
                    log.warning(
                        f"Query [{start:#x}-{end:#x}] attempt {attempt + 1}/{QUERY_RETRY_ATTEMPTS} "
                        f"failed: {type(e).__name__}: {e}"
                    )
                    await self._disconnect()
                    if attempt < QUERY_RETRY_ATTEMPTS - 1:
                        await asyncio.sleep(_RETRY_SLEEP_S)

            if not success:
                await self._disconnect()
                raise ConnectionError(f"Failed to query registers [{start:#x}-{end:#x}] after {QUERY_RETRY_ATTEMPTS} attempts")

        await self._disconnect()
        return params.get_result()

    async def test_connection(self) -> bool:
        """Test basic TCP connectivity by reading one register."""
        try:
            await self._connect()
            await self._modbus.read_holding_registers(register_addr=0x0003, quantity=1)
            return True
        except Exception as e:
            log.warning(f"Connection test failed: {e}")
            return False
        finally:
            await self._disconnect()

    async def read_register(self, addr: int) -> int:
        """Read a single holding register."""
        try:
            await self._connect()
            result = await self._modbus.read_holding_registers(register_addr=addr, quantity=1)
            return result[0] if result else 0
        except Exception:
            return 0
        finally:
            await self._disconnect()

    def get_sensors(self) -> list:
        """Return all sensor definitions from the loaded JSON."""
        if not self._parameter_definition:
            return []
        return ParameterParser(self._parameter_definition).get_sensors()
