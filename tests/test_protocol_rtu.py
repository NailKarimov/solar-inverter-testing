"""The rules of the serial line: who answers, who stays silent, and what a damaged message causes."""

from __future__ import annotations

import time

import pytest

from conftest import KIND, SILENCE, Rig
from inverter_lab import pdu, rtu
from inverter_lab.crc import crc_ok, with_crc
from inverter_lab.device import SIM_BASE, SIM_CLOUD
from inverter_lab.pdu import Function
from support.evidence import step

pytestmark = pytest.mark.rtu

AC_POWER = 40084  # register of the AC power (model 101, point W)


def frame(rig: Rig, body: str) -> bytes:
    """A frame for this rig's unit: ``body`` is the hex of everything between the address and the CRC."""
    return with_crc(bytes([rig.station.unit]) + bytes.fromhex(body))


def exception_frame(rig: Rig, function: int, code: int) -> bytes:
    return with_crc(bytes([rig.station.unit, function | 0x80, code]))


def is_silent(rig: Rig, data: bytes) -> bool:
    return rig.rtu.raw(data, timeout=SILENCE) == b""


@pytest.mark.smoke
def test_hand_built_request_gets_a_valid_answer(rig: Rig) -> None:
    """Eight hand-built bytes asking for the AC power get a seven-byte answer that reads 5000 W at noon."""
    rig.sim.at("12:00")
    with step("Send: address, 03 (read), register 40084, count 1, checksum"):
        answer = rig.rtu.raw(frame(rig, "03 9C 94 00 01"))
    assert len(answer) == 7
    assert crc_ok(answer)
    assert answer[0] == rig.station.unit
    assert answer[1] == Function.READ_HOLDING
    assert answer[2] == 2  # two data bytes follow
    assert int.from_bytes(answer[3:5], "big") == 5000


@pytest.mark.parametrize("count", [1, 2, 60, 125])
def test_answer_is_exactly_as_long_as_requested(rig: Rig, count: int) -> None:
    """A read of N registers is answered with exactly 5 + 2N bytes, up to the limit of 125 registers."""
    answer = rig.rtu.raw(rtu.encode(rig.station.unit, pdu.read_request(Function.READ_HOLDING, 40000, count)))
    assert len(answer) == 5 + 2 * count
    assert crc_ok(answer)
    assert answer[2] == 2 * count


def test_inverter_answers_quickly(rig: Rig) -> None:
    """The answer to a read arrives within a tenth of a second (plus the time the bytes need on a real line)."""
    wire_time = (8 + 7) * 11 / rig.station.baud if KIND == "serial" else 0.0
    started = time.monotonic()
    rig.rtu.read_holding(AC_POWER, 1)
    assert time.monotonic() - started < 0.1 + wire_time


@pytest.mark.parametrize("function", [0x01, 0x02, 0x05, 0x07, 0x0F, 0x11, 0x17, 0x2B, 0x41, 0x7F])
def test_unknown_function_is_refused_with_exception_1(rig: Rig, function: int) -> None:
    """A function the inverter does not support is refused with exception 01, not ignored."""
    answer = rig.rtu.raw(frame(rig, f"{function:02X} 00 00 00 01"))
    assert answer == exception_frame(rig, function, 1)


@pytest.mark.parametrize("address", [0, 99, 116, 39999, 40178, 65535])
def test_missing_register_is_refused_with_exception_2(rig: Rig, address: int) -> None:
    """Reading a register that does not exist is refused with exception 02."""
    answer = rig.rtu.raw(rtu.encode(rig.station.unit, pdu.read_request(Function.READ_HOLDING, address, 1)))
    assert answer == exception_frame(rig, Function.READ_HOLDING, 2)


@pytest.mark.parametrize(("address", "count"), [(40170, 9), (40177, 2), (115, 2), (39999, 2), (98, 3)])
def test_read_running_past_the_end_is_refused(rig: Rig, address: int, count: int) -> None:
    """A read that starts on a real register and runs past the end of the block is refused as a whole."""
    answer = rig.rtu.raw(rtu.encode(rig.station.unit, pdu.read_request(Function.READ_HOLDING, address, count)))
    assert answer == exception_frame(rig, Function.READ_HOLDING, 2)


@pytest.mark.parametrize("count", [0, 126, 127, 2000, 65535])
def test_impossible_count_is_refused_with_exception_3(rig: Rig, count: int) -> None:
    """Asking for zero registers or for more than 125 is refused with exception 03."""
    answer = rig.rtu.raw(rtu.encode(rig.station.unit, pdu.read_request(Function.READ_HOLDING, 40000, count)))
    assert answer == exception_frame(rig, Function.READ_HOLDING, 3)


@pytest.mark.parametrize("other", [2, 3, 17, 100, 247])
def test_request_for_another_address_is_met_with_silence(rig: Rig, other: int) -> None:
    """A request addressed to another device on the same line gets no answer at all."""
    if other == rig.station.unit:
        pytest.skip("this is the inverter's own address")
    before = rig.sim.counters()
    assert is_silent(rig, rtu.encode(other, pdu.read_request(Function.READ_HOLDING, 40000, 2)))
    assert rig.sim.counters().other_unit == before.other_unit + 1


def test_broadcast_read_is_met_with_silence(rig: Rig) -> None:
    """A read sent to everyone (address 0) is never answered: all devices would talk at once."""
    assert is_silent(rig, rtu.encode(rtu.BROADCAST, pdu.read_request(Function.READ_HOLDING, 40000, 2)))


def test_broadcast_write_is_carried_out_without_an_answer(rig: Rig) -> None:
    """A write sent to everyone (address 0) is carried out, and still nobody answers."""
    with step("Broadcast: set the cloud cover to 40 %"):
        assert is_silent(rig, rtu.encode(rtu.BROADCAST, pdu.write_single_request(SIM_BASE + SIM_CLOUD, 40)))
    with step("Ask the inverter directly whether it took the value"):
        assert rig.rtu.read_holding(SIM_BASE + SIM_CLOUD, 1) == [40]


@pytest.mark.parametrize("position", range(8))
def test_damaged_frame_is_met_with_silence(rig: Rig, position: int) -> None:
    """A request with one damaged byte, whichever byte it is, gets no answer and is counted as damaged."""
    damaged = bytearray(frame(rig, "03 9C 94 00 01"))
    damaged[position] ^= 0x04
    before = rig.sim.counters()
    assert is_silent(rig, bytes(damaged))
    after = rig.sim.counters()
    # A damaged function byte makes the length unknown, so that frame is dropped as a framing error.
    assert after.crc_errors + after.framing_errors == before.crc_errors + before.framing_errors + 1
    assert after.other_unit == before.other_unit  # a damaged address is not taken for another device
    assert after.exceptions == before.exceptions


def test_damaged_frame_does_not_disturb_the_next_one(rig: Rig) -> None:
    """After a damaged request the very next good request is answered as usual."""
    damaged = bytearray(frame(rig, "03 9C 94 00 01"))
    damaged[-1] ^= 0xFF
    with step("Send a request with a wrong checksum"):
        assert is_silent(rig, bytes(damaged))
    with step("Send the same request undamaged"):
        assert rig.rtu.read_holding(40000, 2) == [0x5375, 0x6E53]


@pytest.mark.parametrize("length", range(1, 8))
def test_unfinished_frame_is_forgotten_after_silence(rig: Rig, length: int) -> None:
    """A request that stops halfway is dropped when the line goes quiet, and the next one is answered."""
    whole = frame(rig, "03 9C 94 00 01")
    before = rig.sim.counters()
    with step(f"Send only the first {length} of 8 bytes, then stay quiet"):
        assert is_silent(rig, whole[:length])
    with step("Send a complete request"):
        assert rig.rtu.read_holding(40000, 2) == [0x5375, 0x6E53]
    assert rig.sim.counters().framing_errors == before.framing_errors + 1


def test_noise_before_a_request_is_ignored(rig: Rig) -> None:
    """Random bytes on the line, followed by silence, do not stop the inverter from answering."""
    with step("Put 40 bytes of noise on the line"):
        assert is_silent(rig, bytes(range(0xA0, 0xC8)))
    with step("Send a good request"):
        assert rig.rtu.read_holding(40000, 2) == [0x5375, 0x6E53]


def test_request_arriving_in_two_pieces_is_understood(rig: Rig) -> None:
    """A request delivered in two bursts a few milliseconds apart, as USB adapters do, is still answered."""
    whole = frame(rig, "03 9C 40 00 02")
    rig.rtu.link.reset_input()
    rig.rtu.link.write(whole[:3])
    time.sleep(0.005)
    rig.rtu.link.write(whole[3:])
    answer = rig.rtu.listen(1.0)
    assert crc_ok(answer)
    assert answer[3:7] == b"SunS"


def test_overlong_burst_is_dropped(rig: Rig) -> None:
    """Three hundred bytes with no pause cannot be a Modbus frame: they are dropped and counted."""
    before = rig.sim.counters()
    burst = bytes([rig.station.unit, 0x2B]) + bytes(298)
    assert is_silent(rig, burst)
    assert rig.rtu.read_holding(40000, 2) == [0x5375, 0x6E53]
    assert rig.sim.counters().framing_errors == before.framing_errors + 1


def test_write_single_is_confirmed_by_an_echo(rig: Rig) -> None:
    """A single-register write is confirmed by an answer identical to the request."""
    request = rtu.encode(rig.station.unit, pdu.write_single_request(SIM_BASE + SIM_CLOUD, 55))
    assert rig.rtu.raw(request) == request


def test_write_multiple_is_confirmed_with_address_and_count(rig: Rig) -> None:
    """A multi-register write is confirmed by an answer that repeats the address and the count."""
    limit = rig.sunspec.address_of(123, "WMaxLimPct")
    request = pdu.write_multiple_request(limit, [50, 0, 0, 0, 1])
    answer = rig.rtu.raw(rtu.encode(rig.station.unit, request))
    assert answer == rtu.encode(rig.station.unit, request[:5])


def test_write_with_wrong_byte_count_is_refused(rig: Rig) -> None:
    """A write that announces two registers but carries the bytes of one is refused with exception 03."""
    limit = rig.sunspec.address_of(123, "WMaxLimPct")
    body = bytes([Function.WRITE_MULTIPLE]) + limit.to_bytes(2, "big") + bytes.fromhex("00 02 02 00 32")
    answer = rig.rtu.raw(rtu.encode(rig.station.unit, body))
    assert answer == exception_frame(rig, Function.WRITE_MULTIPLE, 3)
    assert rig.sunspec.get(123, "WMaxLimPct") == 100


def test_write_of_too_many_registers_is_refused(rig: Rig) -> None:
    """A write of 124 registers, one more than the protocol allows, is refused with exception 03."""
    answer = rig.rtu.raw(rtu.encode(rig.station.unit, pdu.write_multiple_request(40000, [0] * 124)))
    assert answer == exception_frame(rig, Function.WRITE_MULTIPLE, 3)


def test_counters_record_what_happened_on_the_line(rig: Rig) -> None:
    """The diagnostic counters grow by exactly the number of good, refused, damaged and foreign frames sent."""
    before = rig.sim.counters()
    with step("3 good reads"):
        for _ in range(3):
            rig.rtu.read_holding(40000, 2)
    with step("1 request that must be refused"):
        rig.rtu.raw(rtu.encode(rig.station.unit, pdu.read_request(Function.READ_HOLDING, 0, 1)))
    with step("2 requests with a wrong checksum"):
        damaged = bytearray(frame(rig, "03 9C 40 00 02"))
        damaged[-1] ^= 0x55
        for _ in range(2):
            assert is_silent(rig, bytes(damaged))
    with step("1 request for another address"):
        other = 2 if rig.station.unit != 2 else 3
        assert is_silent(rig, rtu.encode(other, pdu.read_request(Function.READ_HOLDING, 40000, 2)))
    after = rig.sim.counters()
    # "before" was itself a good read, and it is counted before "after" is taken.
    assert after.frames_ok - before.frames_ok == 3 + 1 + 1
    assert after.exceptions - before.exceptions == 1
    assert after.crc_errors - before.crc_errors == 2
    assert after.other_unit - before.other_unit == 1
