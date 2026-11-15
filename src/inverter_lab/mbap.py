"""Modbus TCP framing: the 7-byte MBAP header replaces the address byte and the CRC.

    transaction id (2) | protocol id (2, always 0) | length (2) | unit id (1) | PDU

``length`` counts the unit id and the PDU. TCP already protects the bytes, so there is no checksum.
"""

from __future__ import annotations

import struct

HEADER = struct.Struct(">HHHB")
HEADER_SIZE = HEADER.size  # 7
PROTOCOL_ID = 0
MAX_PDU = 253


def encode(transaction: int, unit: int, pdu: bytes) -> bytes:
    return HEADER.pack(transaction, PROTOCOL_ID, len(pdu) + 1, unit) + pdu


def decode_header(header: bytes) -> tuple[int, int, int, int]:
    """Transaction id, protocol id, length and unit id."""
    transaction, protocol, length, unit = HEADER.unpack(header)
    return transaction, protocol, length, unit
