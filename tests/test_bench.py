"""On the bench: the same inverter at the end of a real RS-485 cable, through two USB adapters."""

from __future__ import annotations

import statistics
import time

import pytest

from conftest import Rig
from inverter_lab.sunspec import BASE_ADDRESS

pytestmark = [pytest.mark.bench, pytest.mark.rtu]

USB_LATENCY_S = 0.040  # two adapters, each may hold bytes for up to 16 ms, plus margin


def wire_time(rig: Rig, request_bytes: int, answer_bytes: int) -> float:
    """Seconds the bytes of one exchange spend on the wire: 11 bit times per byte at 8N1 plus gaps."""
    return (request_bytes + answer_bytes) * 11 / rig.station.baud


def test_one_thousand_polls_without_a_lost_frame(rig: Rig) -> None:
    """One thousand readings over the real cable all arrive, and the inverter counts no damaged frame."""
    before = rig.sim.counters()
    for _ in range(1000):
        assert len(rig.rtu.read_holding(BASE_ADDRESS, 10)) == 10
    after = rig.sim.counters()
    assert rig.rtu.rejected == 0
    assert (after.crc_errors, after.framing_errors) == (before.crc_errors, before.framing_errors)


def test_round_trip_time_fits_the_baud_rate(rig: Rig) -> None:
    """The typical round trip takes no longer than the bytes need on the wire plus the delay of the USB adapters."""
    budget = wire_time(rig, 8, 5 + 2 * 10) + USB_LATENCY_S + 0.035
    times = []
    for _ in range(200):
        started = time.monotonic()
        rig.rtu.read_holding(BASE_ADDRESS, 10)
        times.append(time.monotonic() - started)
    assert statistics.median(times) < budget
    assert sorted(times)[int(len(times) * 0.95)] < 2 * budget


def test_largest_block_crosses_the_cable(rig: Rig) -> None:
    """The largest answer the protocol allows, 255 bytes, crosses the real cable undamaged."""
    registers = rig.rtu.read_holding(BASE_ADDRESS, 125)
    assert len(registers) == 125
    assert registers[:2] == [0x5375, 0x6E53]
