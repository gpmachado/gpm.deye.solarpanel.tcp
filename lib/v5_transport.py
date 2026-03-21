"""
Minimal async SolarmanV5 TCP transport — zero external dependencies.

Replaces pysolarmanv5, which uses multiprocessing.Event (POSIX semaphores)
that are blocked by the Homey Pro seccomp sandbox (OSError ENOSYS).

Protocol reference: jmccrohan/pysolarmanv5 (MIT License).
"""

import asyncio
import logging
import socket
import struct

_LOGGER = logging.getLogger(__name__)

# ── V5 protocol constants ─────────────────────────────────────────────────────

_V5_START       = 0xA5
_V5_END         = 0x15
_V5_CTRL_REQ    = struct.pack("<H", 0x4510)   # request control code
_V5_CTRL_RESP   = struct.pack("<H", 0x1510)   # expected response control code

# ── CRC-16/Modbus ─────────────────────────────────────────────────────────────

def _crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else crc >> 1
    return crc


# ── V5 frame construction ─────────────────────────────────────────────────────

def _v5_checksum(frame: bytes) -> int:
    """Sum of bytes [1 .. len-2] (excludes start byte and the last 2 bytes)."""
    return sum(frame[i] & 0xFF for i in range(1, len(frame) - 2)) & 0xFF


def _build_v5_frame(serial: int, seq: int, modbus_payload: bytes) -> bytearray:
    """Encode a Modbus RTU payload inside a SolarmanV5 TCP frame."""
    payload = bytearray(
        bytes([0x02])        # frametype
        + bytes(2)           # sensortype (0x0000)
        + bytes(4)           # deliverytime (0x00000000)
        + bytes(4)           # powerontime  (0x00000000)
        + bytes(4)           # offsettime   (0x00000000)
        + modbus_payload
    )
    length = len(payload)    # = 15 + len(modbus_payload)

    header = bytearray(
        bytes([_V5_START])
        + struct.pack("<H", length)   # length field
        + _V5_CTRL_REQ               # control code 0x4510 LE → bytes [10, 45]
        + struct.pack("<H", seq)      # sequence number
        + struct.pack("<I", serial)   # logger serial (4B LE)
    )

    frame = header + payload + bytearray(2)   # 2-byte trailer placeholder
    frame[-2] = _v5_checksum(frame)
    frame[-1] = _V5_END
    return frame


# ── V5 response parsing ───────────────────────────────────────────────────────

def _parse_v5_response(frame: bytes, expected_seq: int) -> bytes:
    """
    Validate and decode a V5 response frame.
    Returns the embedded Modbus RTU response bytes (frame[25:-2]).
    """
    frame_len = len(frame)
    if frame_len < 29:   # minimum: 11 header + 16 inner-header + 2 modbus-min bytes + 2 trailer
        raise ValueError(f"V5 response too short: {frame_len} bytes")

    if frame[0] != _V5_START:
        raise ValueError(f"V5 start mismatch: {frame[0]:#04x}")
    if frame[-1] != _V5_END:
        raise ValueError(f"V5 end mismatch: {frame[-1]:#04x}")

    payload_len = struct.unpack("<H", frame[1:3])[0]
    if frame_len != 13 + payload_len:
        _LOGGER.debug("V5 frame_len / payload_len mismatch — proceeding anyway")

    if frame[3:5] != _V5_CTRL_RESP:
        _LOGGER.debug("V5 unexpected ctrl code: %s", frame[3:5].hex())

    if frame[5] != (expected_seq & 0xFF):
        _LOGGER.debug("V5 sequence mismatch: got %d expected %d", frame[5], expected_seq)

    expected_cs = _v5_checksum(frame)
    if frame[-2] != expected_cs:
        _LOGGER.debug("V5 checksum mismatch: got %02x expected %02x", frame[-2], expected_cs)

    if frame[11] != 0x02:
        _LOGGER.debug("V5 unexpected frametype: %02x", frame[11])

    # Modbus RTU response lives at bytes 25 .. -2
    modbus = frame[25:-2]
    if len(modbus) < 5:
        raise ValueError(f"Modbus payload too short: {len(modbus)} bytes")
    return bytes(modbus)


# ── Modbus RTU helpers ────────────────────────────────────────────────────────

def _build_modbus_request(slave: int, fc: int, start: int, count: int) -> bytes:
    """Build a Modbus RTU read-register request with CRC."""
    msg = struct.pack(">BBHH", slave, fc, start, count)
    return msg + struct.pack("<H", _crc16_modbus(msg))


def _parse_modbus_registers(data: bytes, count: int) -> list[int]:
    """Parse a Modbus RTU read-register response. Returns register values."""
    if len(data) < 5:
        raise ValueError(f"Modbus response too short ({len(data)} bytes)")
    if data[1] & 0x80:
        raise ValueError(f"Modbus exception, code {data[2]:#04x}")
    byte_count = data[2]
    n = min(count, byte_count // 2)
    return [struct.unpack(">H", data[3 + i*2: 5 + i*2])[0] for i in range(n)]


# ── Transport class ───────────────────────────────────────────────────────────

class V5Transport:
    """
    Minimal async SolarmanV5 TCP client.

    Intentionally simple: connect → send frame → read response → disconnect.
    Uses asyncio.Event (not multiprocessing.Event) and explicit AF_INET to
    avoid the Homey Pro sandbox restrictions (ENOSYS on semaphores / IPv6).
    """

    def __init__(
        self,
        host: str,
        serial: int,
        port: int = 8899,
        slave: int = 1,
        timeout: float = 8.0,
    ) -> None:
        self.host    = host
        self.serial  = serial
        self.port    = port
        self.slave   = slave
        self.timeout = timeout

        self._seq    = 0
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    # ── connection management ─────────────────────────────────────────────────

    async def connect(self) -> None:
        """Open TCP connection.  Explicit AF_INET prevents IPv6 ENOSYS on
        Homey Pro ARM64 Linux (which may not support AF_INET6 sockets)."""
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port, family=socket.AF_INET),
            timeout=self.timeout,
        )
        _LOGGER.debug("V5Transport connected %s:%d", self.host, self.port)

    async def disconnect(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                await asyncio.wait_for(self._writer.wait_closed(), timeout=2.0)
            except Exception:
                pass
            finally:
                self._writer = None
                self._reader = None

    # ── register I/O ─────────────────────────────────────────────────────────

    async def read_holding_registers(self, register_addr: int, quantity: int) -> list[int]:
        """Modbus FC3 — read holding registers."""
        return await self._read_registers(3, register_addr, quantity)

    async def read_input_registers(self, register_addr: int, quantity: int) -> list[int]:
        """Modbus FC4 — read input registers."""
        return await self._read_registers(4, register_addr, quantity)

    async def _read_registers(self, fc: int, start: int, count: int) -> list[int]:
        if not self._writer:
            raise ConnectionError("Not connected — call connect() first")

        seq = self._next_seq()
        modbus_req  = _build_modbus_request(self.slave, fc, start, count)
        v5_frame    = _build_v5_frame(self.serial, seq, modbus_req)

        self._writer.write(v5_frame)
        await self._writer.drain()

        # Read full V5 response frame
        response = await self._read_v5_frame()
        modbus_resp = _parse_v5_response(response, seq)
        return _parse_modbus_registers(modbus_resp, count)

    async def _read_v5_frame(self) -> bytes:
        """Read one complete V5 frame from the stream.
        Skips any non-data frames the logger might push (e.g. heartbeat)."""
        for _ in range(5):
            # Read fixed-size header (11 bytes)
            header = await asyncio.wait_for(
                self._reader.readexactly(11), timeout=self.timeout
            )
            if header[0] != _V5_START:
                raise ValueError(f"Unexpected V5 start byte: {header[0]:#04x}")

            payload_len = struct.unpack("<H", header[1:3])[0]
            # Read remainder: payload_len + 2 bytes (checksum + END)
            rest = await asyncio.wait_for(
                self._reader.readexactly(payload_len + 2), timeout=self.timeout
            )
            frame = header + rest

            ctrl = frame[3:5]
            if ctrl == _V5_CTRL_RESP:
                return frame

            # Heartbeat / handshake / other — skip silently
            _LOGGER.debug("V5Transport: skipped ctrl=%s frame", ctrl.hex())

        raise TimeoutError("No V5 data response received after 5 frames")

    # ── helpers ───────────────────────────────────────────────────────────────

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFF
        return self._seq
