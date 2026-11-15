"""Modbus protocol data unit: the function code and its data, the same on a serial line and on TCP.

Only the functions a SunSpec inverter needs are implemented:

- 0x03 read holding registers, 0x04 read input registers
- 0x06 write single register, 0x10 write multiple registers

Reference: MODBUS Application Protocol Specification V1.1b3, chapters 6 and 7.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from enum import IntEnum


class Function(IntEnum):
    READ_HOLDING = 0x03
    READ_INPUT = 0x04
    WRITE_SINGLE = 0x06
    WRITE_MULTIPLE = 0x10


class ExceptionCode(IntEnum):
    ILLEGAL_FUNCTION = 1
    ILLEGAL_DATA_ADDRESS = 2
    ILLEGAL_DATA_VALUE = 3
    SERVER_DEVICE_FAILURE = 4


READ_FUNCTIONS = (Function.READ_HOLDING, Function.READ_INPUT)
MAX_READ = 125  # registers in one read: the response must fit in 253 bytes
MAX_WRITE = 123  # registers in one write
ERROR_FLAG = 0x80


class ModbusException(Exception):
    """The device answered with an exception response: function code + 0x80, then a reason code."""

    def __init__(self, function: int, code: int) -> None:
        self.function = function
        self.code = code
        try:
            name = ExceptionCode(code).name
        except ValueError:
            name = "UNKNOWN"
        super().__init__(f"exception {code:02X} ({name}) for function {function:02X}")


class MalformedPdu(ValueError):
    """A response that does not match the request it answers."""


def read_request(function: int, address: int, count: int) -> bytes:
    return struct.pack(">BHH", function, address, count)


def write_single_request(address: int, value: int) -> bytes:
    return struct.pack(">BHH", Function.WRITE_SINGLE, address, value)


def write_multiple_request(address: int, values: Sequence[int]) -> bytes:
    head = struct.pack(">BHHB", Function.WRITE_MULTIPLE, address, len(values), 2 * len(values))
    return head + struct.pack(f">{len(values)}H", *values)


def exception_response(function: int, code: int) -> bytes:
    return bytes([function | ERROR_FLAG, code])


def parse_response(request: bytes, response: bytes) -> list[int]:
    """Registers carried by ``response`` (empty for a write). Raises on an exception or a mismatch."""
    if len(response) < 2:
        raise MalformedPdu(f"response too short: {response.hex(' ')}")
    function = request[0]
    if response[0] == function | ERROR_FLAG:
        raise ModbusException(function, response[1])
    if response[0] != function:
        raise MalformedPdu(f"function {response[0]:02X} in the answer to {function:02X}")
    if function in READ_FUNCTIONS:
        (count,) = struct.unpack(">H", request[3:5])
        if len(response) != 2 + 2 * count or response[1] != 2 * count:
            raise MalformedPdu(f"expected {count} registers, got {response.hex(' ')}")
        return list(struct.unpack(f">{count}H", response[2:]))
    # Both write functions echo the first five bytes of the request.
    if response != request[:5]:
        raise MalformedPdu(f"write not echoed: sent {request[:5].hex(' ')}, got {response.hex(' ')}")
    return []
