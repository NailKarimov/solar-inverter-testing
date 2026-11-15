"""Modbus RTU framing: unit address, PDU, CRC-16.

On a real line frames are separated by silence of 3.5 character times. A PC cannot measure that
reliably through a USB adapter, so both sides also work out the frame length from the function code.
"""

from __future__ import annotations

from inverter_lab.crc import crc_ok, with_crc
from inverter_lab.pdu import ERROR_FLAG, Function

BROADCAST = 0
MIN_FRAME = 4  # address, function, CRC low, CRC high
MAX_FRAME = 256

FIXED_REQUEST = (Function.READ_HOLDING, Function.READ_INPUT, Function.WRITE_SINGLE)
KNOWN_FUNCTIONS = (*FIXED_REQUEST, Function.WRITE_MULTIPLE)


class FrameError(ValueError):
    """Bytes that are not a valid RTU frame: too short or a wrong checksum."""


def encode(unit: int, pdu: bytes) -> bytes:
    return with_crc(bytes([unit]) + pdu)


def decode(frame: bytes) -> tuple[int, bytes]:
    """Unit address and PDU of ``frame``. Raises ``FrameError`` if the frame is damaged."""
    if len(frame) < MIN_FRAME:
        raise FrameError(f"frame too short: {frame.hex(' ')}")
    if not crc_ok(frame):
        raise FrameError(f"wrong CRC: {frame.hex(' ')}")
    return frame[0], frame[1:-2]


def request_length(buf: bytes) -> int | None:
    """Length of the request frame that starts ``buf``; None while it cannot be known."""
    if len(buf) < 2:
        return None
    function = buf[1]
    if function in FIXED_REQUEST:
        return 8
    if function == Function.WRITE_MULTIPLE:
        return 9 + buf[6] if len(buf) >= 7 else None
    return None  # unknown function: only silence on the line ends the frame


def response_length(buf: bytes) -> int | None:
    """Length of the response frame that starts ``buf``; None while it cannot be known."""
    if len(buf) < 2:
        return None
    function = buf[1]
    if function & ERROR_FLAG:
        return 5
    if function in (Function.READ_HOLDING, Function.READ_INPUT):
        return 5 + buf[2] if len(buf) >= 3 else None
    if function in (Function.WRITE_SINGLE, Function.WRITE_MULTIPLE):
        return 8
    return None
