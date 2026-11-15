"""Robustness: whatever arrives on the line, the inverter keeps working and never invents an answer."""

from __future__ import annotations

import os
from collections.abc import Callable

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from conftest import TIMEOUT, Rig
from inverter_lab import pdu, rtu
from inverter_lab.client import TcpMaster
from inverter_lab.device import SIM_BASE, SIM_CLOUD, SIM_SIZE
from inverter_lab.links import LinkClosed, open_tcp
from inverter_lab.pdu import Function, ModbusException
from inverter_lab.sunspec import BASE_ADDRESS
from support.evidence import step

MAP_SIZE = 178
MARKER = [0x5375, 0x6E53]
QUIET = 0.08  # long enough for the inverter to notice the silence that ends a frame

EXAMPLES = int(os.getenv("FUZZ_EXAMPLES", "60"))
fuzz = settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])

# Addresses around both blocks are tried more often than the rest of the 16-bit range.
addresses = st.one_of(st.integers(39990, 40190), st.integers(90, 125), st.integers(0, 0xFFFF))
few_bits = st.sets(st.integers(0, 63), min_size=1, max_size=3)


def attempt[T](request: Callable[[], T]) -> T | str:
    """The answer to a request, or ``"refused: <code>"`` if the inverter refused it."""
    try:
        return request()
    except ModbusException as refusal:
        return f"refused: {refusal.code}"


def inside(address: int, count: int) -> bool:
    in_map = address >= BASE_ADDRESS and address + count <= BASE_ADDRESS + MAP_SIZE
    in_bench_block = address >= SIM_BASE and address + count <= SIM_BASE + SIM_SIZE
    return in_map or in_bench_block


@pytest.mark.rtu
@fuzz
@given(noise=st.binary(min_size=1, max_size=300))
def test_random_bytes_never_stop_the_inverter(rig: Rig, noise: bytes) -> None:
    """After any burst of random bytes on the line the inverter still answers the next good request."""
    rig.rtu.raw(noise, timeout=QUIET)
    assert rig.rtu.read_holding(BASE_ADDRESS, 2) == MARKER


@pytest.mark.rtu
@fuzz
@given(bits=few_bits)
def test_request_with_up_to_three_flipped_bits_is_never_answered(rig: Rig, bits: set[int]) -> None:
    """A request with one, two or three flipped bits is never answered: the checksum catches every such error."""
    damaged = bytearray(rtu.encode(rig.station.unit, pdu.read_request(Function.READ_HOLDING, BASE_ADDRESS, 2)))
    for bit in bits:
        damaged[bit // 8] ^= 1 << (bit % 8)
    assert rig.rtu.raw(bytes(damaged), timeout=QUIET) == b""


@pytest.mark.rtu
def test_cut_off_write_is_never_carried_out(rig: Rig) -> None:
    """A write command cut off at any point is not carried out, not even in part."""
    command = rtu.encode(rig.station.unit, pdu.write_multiple_request(SIM_BASE + SIM_CLOUD, [77]))
    for length in range(1, len(command)):
        assert rig.rtu.raw(command[:length], timeout=QUIET) == b""
    assert rig.rtu.read_holding(SIM_BASE + SIM_CLOUD, 1) == [0]
    with step("The complete command is carried out"):
        assert rig.rtu.raw(command) != b""
        assert rig.rtu.read_holding(SIM_BASE + SIM_CLOUD, 1) == [77]


@fuzz
@given(address=addresses, count=st.integers(0, 200))
def test_every_read_gets_all_its_registers_or_a_refusal(rig: Rig, address: int, count: int) -> None:
    """Any read, from any address and of any size, returns exactly the registers asked for or a clear refusal."""
    answer = attempt(lambda: rig.master.read_holding(address, count))
    if not 1 <= count <= pdu.MAX_READ:
        assert answer == "refused: 3"
    elif not inside(address, count):
        assert answer == "refused: 2"
    else:
        assert isinstance(answer, list)
        assert len(answer) == count


@fuzz
@given(address=addresses, values=st.lists(st.integers(0, 0xFFFF), min_size=1, max_size=10))
def test_every_write_is_confirmed_or_refused_and_the_map_stays_whole(rig: Rig, address: int, values: list[int]) -> None:
    """Any write is either confirmed or refused with a reason, and afterwards the map still has its skeleton."""
    answer = attempt(lambda: rig.master.write_registers(address, values))
    assert answer in (None, "refused: 2", "refused: 3")
    assert rig.master.read_holding(BASE_ADDRESS, 4) == [*MARKER, 1, 66]
    assert rig.master.read_holding(BASE_ADDRESS + MAP_SIZE - 2, 2) == [0xFFFF, 0]


@pytest.mark.tcp
@fuzz
@given(noise=st.binary(min_size=1, max_size=300))
def test_random_bytes_on_a_connection_never_stop_the_server(rig: Rig, noise: bytes) -> None:
    """A client that sends random bytes is at worst disconnected; everyone else is served as before."""
    assert rig.station.tcp is not None
    vandal = open_tcp(*rig.station.tcp)
    try:
        vandal.write(noise)
        vandal.read(0.02)
    except LinkClosed:
        pass
    finally:
        vandal.close()
    assert rig.master.read_holding(BASE_ADDRESS, 2) == MARKER
    fresh = TcpMaster(open_tcp(*rig.station.tcp), rig.station.unit, TIMEOUT)
    assert fresh.read_holding(BASE_ADDRESS, 2) == MARKER
    fresh.link.close()


def test_five_hundred_polls_in_a_row(rig: Rig) -> None:
    """Five hundred readings in a row all succeed, and the inverter counts no damaged frame."""
    rig.sim.at("12:00")
    before = rig.sim.counters()
    address = rig.sunspec.discover()[101]
    for _ in range(500):
        assert len(rig.master.read_holding(address, 52)) == 52
    after = rig.sim.counters()
    # discover() reads the marker, four model headers and the end marker; the request that fetched
    # "before" is counted too, because a request is counted after it has been answered
    assert after.frames_ok - before.frames_ok == 500 + 6 + 1
    assert (after.crc_errors, after.framing_errors, after.exceptions) == (
        before.crc_errors,
        before.framing_errors,
        before.exceptions,
    )
