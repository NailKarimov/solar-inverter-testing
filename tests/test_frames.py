"""Building and reading messages byte by byte, on a serial line (RTU) and on a network (TCP)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from inverter_lab import mbap, pdu, rtu
from inverter_lab.pdu import Function, MalformedPdu, ModbusException

pytestmark = pytest.mark.once

registers = st.lists(st.integers(0, 0xFFFF), min_size=1, max_size=pdu.MAX_WRITE)


def hexs(data: bytes) -> str:
    return data.hex(" ").upper()


def test_read_request_matches_the_specification_example() -> None:
    """Reading 3 registers from address 107 is the five bytes 03 00 6B 00 03, as in the specification."""
    assert hexs(pdu.read_request(Function.READ_HOLDING, 107, 3)) == "03 00 6B 00 03"


def test_write_single_request_matches_the_specification_example() -> None:
    """Writing the value 3 to register 1 is 06 00 01 00 03, as in the specification."""
    assert hexs(pdu.write_single_request(1, 3)) == "06 00 01 00 03"


def test_write_multiple_request_matches_the_specification_example() -> None:
    """Writing 0x000A and 0x0102 from register 1 is 10 00 01 00 02 04 00 0A 01 02, as in the specification."""
    assert hexs(pdu.write_multiple_request(1, [0x000A, 0x0102])) == "10 00 01 00 02 04 00 0A 01 02"


def test_rtu_frame_is_address_then_message_then_checksum() -> None:
    """A serial frame is the device address, the message and the checksum, in that order."""
    frame = rtu.encode(1, pdu.read_request(Function.READ_HOLDING, 0, 2))
    assert hexs(frame) == "01 03 00 00 00 02 C4 0B"
    assert rtu.decode(frame) == (1, bytes.fromhex("0300000002"))


@given(st.integers(0, 247), st.binary(min_size=1, max_size=252))
def test_rtu_round_trip(unit: int, message: bytes) -> None:
    """Whatever is packed into a serial frame comes out unchanged."""
    assert rtu.decode(rtu.encode(unit, message)) == (unit, message)


@pytest.mark.parametrize("frame", ["", "01", "01 03", "01 03 00"], ids=["empty", "1-byte", "2-bytes", "3-bytes"])
def test_rtu_rejects_fragments(frame: str) -> None:
    """A serial frame shorter than four bytes is refused."""
    with pytest.raises(rtu.FrameError, match="too short"):
        rtu.decode(bytes.fromhex(frame))


def test_rtu_rejects_a_wrong_checksum() -> None:
    """A serial frame whose checksum does not fit is refused."""
    with pytest.raises(rtu.FrameError, match="wrong CRC"):
        rtu.decode(bytes.fromhex("010300000002C40C"))


@pytest.mark.parametrize(
    ("start", "length"),
    [
        ("01 03", 8),
        ("01 04", 8),
        ("01 06", 8),
        ("01 10 00 01 00 02 04", 13),
        ("01 10 00 01 00", None),  # the byte count has not arrived yet
        ("01", None),
        ("01 2B", None),  # a function this device does not know: only silence ends the frame
    ],
    ids=["read-holding", "read-input", "write-single", "write-multiple", "write-multiple-partial", "1-byte", "unknown"],
)
def test_request_length_is_known_from_the_first_bytes(start: str, length: int | None) -> None:
    """The device can tell how long a request will be from its first bytes."""
    assert rtu.request_length(bytes.fromhex(start)) == length


@pytest.mark.parametrize(
    ("start", "length"),
    [("01 03 04", 9), ("01 04 FA", 255), ("01 06", 8), ("01 10", 8), ("01 83", 5), ("01 03", None), ("01 2B", None)],
    ids=["read-2", "read-125", "write-single", "write-multiple", "exception", "read-partial", "unknown"],
)
def test_response_length_is_known_from_the_first_bytes(start: str, length: int | None) -> None:
    """The client can tell how long an answer will be from its first bytes."""
    assert rtu.response_length(bytes.fromhex(start)) == length


def test_tcp_header_layout() -> None:
    """A network frame starts with 7 bytes: transaction number, protocol 0, length, unit; no checksum."""
    frame = mbap.encode(0x1234, 1, pdu.read_request(Function.READ_HOLDING, 0, 2))
    assert hexs(frame) == "12 34 00 00 00 06 01 03 00 00 00 02"
    assert mbap.decode_header(frame[:7]) == (0x1234, 0, 6, 1)


@given(st.integers(0, 0xFFFF), st.integers(0, 255), st.binary(min_size=1, max_size=253))
def test_tcp_header_round_trip(transaction: int, unit: int, message: bytes) -> None:
    """The length in the header always counts the unit byte plus the message."""
    frame = mbap.encode(transaction, unit, message)
    assert mbap.decode_header(frame[:7]) == (transaction, 0, len(message) + 1, unit)
    assert frame[7:] == message


@given(st.integers(0, 0xFFFF), registers)
def test_read_answer_round_trip(address: int, values: list[int]) -> None:
    """The registers of a read answer come back in the order they were sent."""
    request = pdu.read_request(Function.READ_HOLDING, address, len(values))
    response = bytes([Function.READ_HOLDING, 2 * len(values)]) + b"".join(v.to_bytes(2, "big") for v in values)
    assert pdu.parse_response(request, response) == values


def test_exception_answer_raises_with_its_code() -> None:
    """An answer 83 02 to a read is reported as exception 02 (illegal data address)."""
    request = pdu.read_request(Function.READ_HOLDING, 9999, 1)
    with pytest.raises(ModbusException) as error:
        pdu.parse_response(request, bytes.fromhex("8302"))
    assert (error.value.function, error.value.code) == (3, 2)


@pytest.mark.parametrize(
    "response",
    ["04 02 00 01", "03 04 00 01", "03 02 00 01 00 02", "03", ""],
    ids=["other-function", "wrong-byte-count", "too-many-registers", "one-byte", "empty"],
)
def test_answers_that_do_not_fit_the_request_are_refused(response: str) -> None:
    """An answer with another function, a wrong byte count or a wrong size is refused."""
    request = pdu.read_request(Function.READ_HOLDING, 0, 1)
    with pytest.raises(MalformedPdu):
        pdu.parse_response(request, bytes.fromhex(response))


def test_write_answer_must_echo_the_request() -> None:
    """A write is confirmed only if the answer repeats the address and the value."""
    request = pdu.write_single_request(40155, 50)
    assert pdu.parse_response(request, request) == []
    with pytest.raises(MalformedPdu, match="not echoed"):
        pdu.parse_response(request, pdu.write_single_request(40155, 51))
