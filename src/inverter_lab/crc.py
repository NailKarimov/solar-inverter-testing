"""CRC-16/MODBUS, the checksum at the end of every Modbus RTU frame.

Polynomial 0x8005 processed low bit first (0xA001), initial value 0xFFFF, no final XOR.
On the wire the low byte goes first: ``01 03 00 00 00 02`` is followed by ``C4 0B``.
"""

from __future__ import annotations

INIT = 0xFFFF
POLY = 0xA001


def crc16(data: bytes) -> int:
    crc = INIT
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ POLY if crc & 1 else crc >> 1
    return crc


def with_crc(body: bytes) -> bytes:
    """``body`` followed by its checksum, low byte first."""
    return body + crc16(body).to_bytes(2, "little")


def crc_ok(frame: bytes) -> bool:
    """True if the last two bytes of ``frame`` are the checksum of the rest."""
    return len(frame) >= 4 and crc16(frame[:-2]) == int.from_bytes(frame[-2:], "little")
