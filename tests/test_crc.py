"""The checksum: every message on the wire ends with two bytes that prove it arrived undamaged."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from inverter_lab.crc import crc16, crc_ok, with_crc

pytestmark = pytest.mark.once

frames = st.binary(min_size=2, max_size=253)


@pytest.mark.smoke
def test_textbook_request_has_the_textbook_checksum() -> None:
    """The request 01 03 00 00 00 02 from the Modbus textbooks gets the checksum C4 0B."""
    assert with_crc(bytes.fromhex("010300000002")).hex(" ").upper() == "01 03 00 00 00 02 C4 0B"


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"123456789", 0x4B37),  # the check value of CRC-16/MODBUS in the catalogue of CRC algorithms
        (bytes.fromhex("0103006B0003"), 0x1774),  # request example of the Modbus specification, as sent: 74 17
        (bytes.fromhex("110300000001"), 0x9A86),
        (b"", 0xFFFF),
        (b"\x00", 0x40BF),
    ],
    ids=["catalogue-check-value", "spec-read-example", "unit-17-read", "empty", "single-zero"],
)
def test_known_checksums(data: bytes, expected: int) -> None:
    """Published examples give the published checksums."""
    assert crc16(data) == expected


def test_checksum_goes_low_byte_first() -> None:
    """On the wire the low byte of the checksum is sent before the high byte."""
    body = bytes.fromhex("010300000002")
    assert crc16(body) == 0x0BC4
    assert with_crc(body)[-2:] == bytes([0xC4, 0x0B])


@given(frames)
def test_a_frame_with_its_checksum_is_accepted(body: bytes) -> None:
    """Any message followed by its own checksum is accepted as undamaged."""
    assert crc_ok(with_crc(body))
    assert crc16(with_crc(body)) == 0


@given(frames, st.data())
def test_any_single_flipped_bit_is_detected(body: bytes, data: st.DataObject) -> None:
    """Flip any one bit of any message and the checksum no longer fits."""
    frame = bytearray(with_crc(body))
    bit = data.draw(st.integers(0, len(frame) * 8 - 1))
    frame[bit // 8] ^= 1 << (bit % 8)
    assert not crc_ok(bytes(frame))


@given(frames, st.data())
def test_any_burst_of_up_to_16_damaged_bits_is_detected(body: bytes, data: st.DataObject) -> None:
    """A burst of noise up to 16 bits long, anywhere in the message, is always detected."""
    frame = with_crc(body)
    bits = len(frame) * 8
    length = data.draw(st.integers(1, 16))
    start = data.draw(st.integers(0, bits - length))
    # A burst begins and ends with a damaged bit; the bits in between may or may not be damaged.
    inner = data.draw(st.integers(0, (1 << max(length - 2, 0)) - 1)) << 1
    pattern = 1 | inner | (1 << (length - 1))
    damaged = int.from_bytes(frame, "big") ^ (pattern << (bits - start - length))
    assert not crc_ok(damaged.to_bytes(len(frame), "big"))


@given(st.binary(max_size=3))
def test_fragments_shorter_than_a_frame_are_rejected(fragment: bytes) -> None:
    """Fewer than four bytes can never be a valid message."""
    assert not crc_ok(fragment)
