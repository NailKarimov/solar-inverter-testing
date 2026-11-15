"""The client's side of the bargain: on a bad line it may fail to get an answer, but it must never get a wrong one."""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from inverter_lab import mbap, pdu, rtu
from inverter_lab.client import BadResponse, NoResponse, RtuMaster, TcpMaster
from inverter_lab.device import InverterDevice
from inverter_lab.links import memory_pair
from inverter_lab.pdu import Function, ModbusException
from inverter_lab.server import RtuServer
from inverter_lab.sunspec import BASE_ADDRESS
from support.evidence import TapLink, step
from support.noise import NoisyLink, ScriptedLink

pytestmark = pytest.mark.once

UNIT = 1
READ_TWO = pdu.read_request(Function.READ_HOLDING, BASE_ADDRESS, 2)
GOOD_ANSWER = rtu.encode(UNIT, bytes.fromhex("03 04 53 75 6E 53"))


@dataclass
class NoisyBench:
    device: InverterDevice
    line: NoisyLink
    master: RtuMaster


@pytest.fixture
def noisy_bench(request: pytest.FixtureRequest) -> Iterator[NoisyBench]:
    """An inverter at noon behind a line that flips bits on the way back to the client."""
    bit_error_rate, retries = request.param
    client_end, device_end = memory_pair()
    device = InverterDevice(UNIT)
    device.inverter.advance(60)
    server = RtuServer(device_end, device).start()
    line = NoisyLink(client_end, bit_error_rate)
    yield NoisyBench(device, line, RtuMaster(TapLink(line), UNIT, timeout=0.3, retries=retries))
    server.stop()
    client_end.close()
    device_end.close()


def scripted(*replies: bytes, retries: int = 0, timeout: float = 0.1) -> tuple[RtuMaster, ScriptedLink]:
    link = ScriptedLink(list(replies))
    return RtuMaster(TapLink(link), UNIT, timeout=timeout, retries=retries, gap=0.01), link


@pytest.mark.parametrize("noisy_bench", [(1 / 400, 0)], indirect=True, ids=["1-bit-in-400"])
def test_client_never_hands_out_a_damaged_value(noisy_bench: NoisyBench) -> None:
    """With one bit in 400 flipped on the line, 300 readings give the true values or an error, never a wrong value."""
    address = noisy_bench.device.layout.entry(101, "A").address
    truth = noisy_bench.device.read(address, 10)
    correct = rejected = 0
    for _ in range(300):
        try:
            assert noisy_bench.master.read_holding(address, 10) == truth
            correct += 1
        except (BadResponse, NoResponse):
            rejected += 1
    assert noisy_bench.line.flipped > 100  # the line really was bad
    assert rejected > 50
    assert correct > 100
    assert correct + rejected == 300


@pytest.mark.parametrize("noisy_bench", [(1 / 2000, 5)], indirect=True, ids=["1-bit-in-2000-with-retries"])
def test_retries_get_the_true_value_through_a_bad_line(noisy_bench: NoisyBench) -> None:
    """With retries allowed, 200 readings over a noisy line all end with the true values."""
    address = noisy_bench.device.layout.entry(101, "A").address
    truth = noisy_bench.device.read(address, 10)
    for _ in range(200):
        assert noisy_bench.master.read_holding(address, 10) == truth
    assert noisy_bench.master.rejected > 0  # some answers were damaged and asked for again


def test_good_answer_is_accepted() -> None:
    """An undamaged answer from the right device is accepted."""
    master, _ = scripted(GOOD_ANSWER)
    assert master.read_holding(BASE_ADDRESS, 2) == [0x5375, 0x6E53]


def test_answer_with_a_wrong_checksum_is_rejected() -> None:
    """An answer whose checksum does not fit is rejected."""
    damaged = bytearray(GOOD_ANSWER)
    damaged[4] ^= 0x01
    master, _ = scripted(bytes(damaged))
    with pytest.raises(BadResponse, match="wrong CRC"):
        master.read_holding(BASE_ADDRESS, 2)


def test_answer_from_another_device_is_rejected() -> None:
    """A perfectly valid answer that comes from another address is rejected."""
    master, _ = scripted(rtu.encode(2, bytes.fromhex("03 04 53 75 6E 53")))
    with pytest.raises(BadResponse, match="unit 2"):
        master.read_holding(BASE_ADDRESS, 2)


def test_cut_off_answer_is_rejected() -> None:
    """An answer that stops halfway is rejected once the wait is over."""
    master, _ = scripted(GOOD_ANSWER[:5])
    with pytest.raises(BadResponse, match="incomplete"):
        master.read_holding(BASE_ADDRESS, 2)


def test_answer_to_another_question_is_rejected() -> None:
    """A valid frame that answers a different function than the one asked is rejected."""
    master, _ = scripted(rtu.encode(UNIT, bytes.fromhex("04 04 53 75 6E 53")))
    with pytest.raises(BadResponse, match="function 04"):
        master.read_holding(BASE_ADDRESS, 2)


def test_answer_with_the_wrong_number_of_registers_is_rejected() -> None:
    """An answer that carries one register when two were asked for is rejected."""
    master, _ = scripted(rtu.encode(UNIT, bytes.fromhex("03 02 53 75")))
    with pytest.raises(BadResponse, match="expected 2 registers"):
        master.read_holding(BASE_ADDRESS, 2)


def test_write_confirmed_with_another_value_is_rejected() -> None:
    """A write whose confirmation repeats a different value than the one sent is rejected."""
    master, _ = scripted(rtu.encode(UNIT, pdu.write_single_request(40155, 51)))
    with pytest.raises(BadResponse, match="not echoed"):
        master.write_register(40155, 50)


def test_refusal_is_not_asked_again() -> None:
    """A refusal from the device is final: the client reports it and does not repeat the request."""
    master, link = scripted(rtu.encode(UNIT, bytes.fromhex("83 02")), GOOD_ANSWER, retries=3)
    with pytest.raises(ModbusException) as refusal:
        master.read_holding(BASE_ADDRESS, 2)
    assert refusal.value.code == 2
    assert len(link.sent) == 1


def test_damaged_answer_is_asked_again() -> None:
    """After a damaged answer the client repeats the request and takes the good answer."""
    damaged = bytearray(GOOD_ANSWER)
    damaged[-1] ^= 0x80
    master, link = scripted(bytes(damaged), GOOD_ANSWER, retries=1)
    assert master.read_holding(BASE_ADDRESS, 2) == [0x5375, 0x6E53]
    assert len(link.sent) == 2
    assert master.rejected == 1


def test_silent_device_makes_the_client_give_up_on_time() -> None:
    """If the device stays silent the client tries three times, 0.2 s each, and then reports no answer."""
    master, link = scripted(retries=2, timeout=0.2)
    started = time.monotonic()
    with step("Ask a device that never answers"), pytest.raises(NoResponse):
        master.read_holding(BASE_ADDRESS, 2)
    elapsed = time.monotonic() - started
    assert len(link.sent) == 3
    assert 0.6 <= elapsed < 0.9


def test_tcp_answer_to_an_older_request_is_rejected() -> None:
    """On TCP an answer that carries the number of another request is rejected."""
    link = ScriptedLink([mbap.encode(7, UNIT, bytes.fromhex("03 04 53 75 6E 53"))])
    master = TcpMaster(TapLink(link), UNIT, timeout=0.1)
    with pytest.raises(BadResponse, match="transaction 7"):
        master.read_holding(BASE_ADDRESS, 2)


def test_tcp_answer_that_is_not_modbus_is_rejected() -> None:
    """On TCP an answer whose header does not say "Modbus" is rejected."""
    link = ScriptedLink([mbap.HEADER.pack(1, 5, 7, UNIT) + bytes.fromhex("03 04 53 75 6E 53")])
    master = TcpMaster(TapLink(link), UNIT, timeout=0.1)
    with pytest.raises(BadResponse, match="not a Modbus TCP header"):
        master.read_holding(BASE_ADDRESS, 2)
