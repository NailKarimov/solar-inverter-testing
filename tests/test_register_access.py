"""What may be written and what may not: a wrong command must be refused and must change nothing."""

from __future__ import annotations

import pytest

from conftest import Rig
from inverter_lab.device import (
    SIM_ADVANCE,
    SIM_AMBIENT,
    SIM_BASE,
    SIM_CLOCK_MIN,
    SIM_CLOCK_SEC,
    SIM_CLOUD,
    SIM_GRID,
    SIM_HEAT,
    SIM_ID,
    SIM_MAGIC,
    SIM_RESET,
    SIM_TIME_SCALE,
)
from inverter_lab.pdu import ModbusException
from inverter_lab.sunspec import BASE_ADDRESS
from support import datasheet as ds
from support.evidence import step

ILLEGAL_ADDRESS, ILLEGAL_VALUE = 2, 3


def refused(rig: Rig, address: int, values: list[int]) -> int:
    """Write ``values`` and return the exception code the inverter answers with."""
    try:
        if len(values) == 1:
            rig.master.write_register(address, values[0])
        else:
            rig.master.write_registers(address, values)
    except ModbusException as refusal:
        return refusal.code
    pytest.fail(f"the write of {values} to {address} was accepted")


@pytest.mark.parametrize(
    ("model", "point"),
    [(101, "W"), (101, "WH"), (101, "St"), (101, "Evt1"), (1, "Mn"), (1, "DA"), (120, "WRtg"), (123, "WMaxLimPct_SF")],
)
def test_measurements_cannot_be_overwritten(rig: Rig, model: int, point: str) -> None:
    """Measurements, ratings and identity are read-only: a write is refused with exception 02."""
    address = rig.sunspec.address_of(model, point)
    before = rig.master.read_holding(address, 1)
    assert refused(rig, address, [1]) == ILLEGAL_ADDRESS
    assert rig.master.read_holding(address, 1) == before


@pytest.mark.parametrize("address", [40000, 40001, 40002, 40003, 40070, 40176, 40177])
def test_skeleton_of_the_map_cannot_be_overwritten(rig: Rig, address: int) -> None:
    """The marker, the model ids and lengths and the end marker cannot be written."""
    before = rig.master.read_holding(address, 1)
    assert refused(rig, address, [0]) == ILLEGAL_ADDRESS
    assert rig.master.read_holding(address, 1) == before


@pytest.mark.parametrize("percent", [101, 150, 1000, 65535])
def test_limit_above_100_percent_is_refused(rig: Rig, percent: int) -> None:
    """A power limit above 100 % is refused with exception 03 and the previous limit stays."""
    assert refused(rig, rig.sunspec.address_of(123, "WMaxLimPct"), [percent]) == ILLEGAL_VALUE
    assert rig.sunspec.get(123, "WMaxLimPct") == 100


@pytest.mark.parametrize(
    ("point", "value"),
    [
        ("Conn", 2),
        ("Conn", 65535),
        ("WMaxLim_Ena", 2),
        ("Conn_WinTms", 5),
        ("WMaxLimPct_WinTms", 1),
        ("OutPFSet_Ena", 1),
        ("VArPct_Ena", 1),
        ("Conn_RvrtTms", 3601),
        ("WMaxLimPct_RvrtTms", 3601),
        ("WMaxLimPct_RmpTms", 601),
    ],
)
def test_values_the_inverter_cannot_honour_are_refused(rig: Rig, point: str, value: int) -> None:
    """A switch set to anything but 0 or 1, an unsupported feature or a too-long timer is refused with exception 03."""
    before = rig.sunspec.model(123)
    assert refused(rig, rig.sunspec.address_of(123, point), [value]) == ILLEGAL_VALUE
    assert rig.sunspec.model(123) == before


@pytest.mark.parametrize(
    ("point", "value"),
    [("Conn_RvrtTms", 3600), ("WMaxLimPct_RvrtTms", 3600), ("WMaxLimPct_RmpTms", 600), ("WMaxLimPct", 0)],
)
def test_largest_allowed_values_are_accepted(rig: Rig, point: str, value: int) -> None:
    """The largest value each control allows is accepted and reads back."""
    rig.sunspec.set(123, point, value)
    assert rig.sunspec.get(123, point) == value


def test_write_with_one_bad_value_changes_nothing(rig: Rig) -> None:
    """A five-register write whose last value is invalid is refused as a whole: no register changes."""
    before = rig.sunspec.model(123)
    address = rig.sunspec.address_of(123, "WMaxLimPct")
    with step("Write limit 50 %, timers 10 s and 5 s, and an invalid enable flag of 2"):
        assert refused(rig, address, [50, 0, 10, 5, 2]) == ILLEGAL_VALUE
    assert rig.sunspec.model(123) == before


def test_write_reaching_into_a_read_only_register_changes_nothing(rig: Rig) -> None:
    """A write that covers five writable registers and one read-only register is refused as a whole."""
    before = rig.sunspec.model(123)
    address = rig.sunspec.address_of(123, "WMaxLimPct")
    assert refused(rig, address, [50, 0, 10, 5, 1, 100]) == ILLEGAL_ADDRESS
    assert rig.sunspec.model(123) == before


def test_five_limit_registers_can_be_set_in_one_request(rig: Rig) -> None:
    """Limit, timers and enable flag can be set together, so the inverter never sees half a command."""
    rig.sunspec.set_many(123, "WMaxLimPct", [35, 0, 120, 8, 1])
    controls = rig.sunspec.model(123)
    assert [controls[n] for n in ("WMaxLimPct", "WMaxLimPct_RvrtTms", "WMaxLimPct_RmpTms", "WMaxLim_Ena")] == [
        35,
        120,
        8,
        1,
    ]


@pytest.mark.parametrize(
    ("offset", "value"),
    [
        (SIM_CLOCK_MIN, 1440),
        (SIM_ADVANCE, 0),
        (SIM_ADVANCE, 43201),
        (SIM_CLOUD, 101),
        (SIM_AMBIENT, 701),
        (SIM_AMBIENT, 0x10000 - 401),
        (SIM_GRID, 2),
        (SIM_HEAT, 1501),
        (SIM_TIME_SCALE, 3601),
        (SIM_RESET, 1),
    ],
    ids=[
        "clock-24:00",
        "advance-0",
        "advance-over-12h",
        "cloud-101%",
        "ambient+70.1C",
        "ambient-40.1C",
        "grid-2",
        "heat-150.1C",
        "time-scale-3601",
        "reset-without-key",
    ],
)
def test_test_bench_block_refuses_impossible_settings(rig: Rig, offset: int, value: int) -> None:
    """The simulator's own control block refuses settings outside its ranges with exception 03."""
    before = rig.master.read_holding(SIM_BASE, 10)
    assert refused(rig, SIM_BASE + offset, [value]) == ILLEGAL_VALUE
    assert rig.master.read_holding(SIM_BASE, 10) == before


@pytest.mark.parametrize("offset", [SIM_ID, SIM_CLOCK_SEC, 10, 11, 12, 13, 14, 15])
def test_marker_and_counters_of_the_bench_block_are_read_only(rig: Rig, offset: int) -> None:
    """The simulator marker, the seconds and the diagnostic counters cannot be written."""
    assert refused(rig, SIM_BASE + offset, [0]) == ILLEGAL_ADDRESS


def test_refusals_are_counted(rig: Rig) -> None:
    """Every refused request adds one to the inverter's exception counter."""
    before = rig.sim.counters().exceptions
    refused(rig, BASE_ADDRESS, [0])
    refused(rig, rig.sunspec.address_of(123, "WMaxLimPct"), [101])
    assert rig.sim.counters().exceptions == before + 2


def test_reset_returns_the_inverter_to_its_factory_state(rig: Rig) -> None:
    """After a reset the clock, the weather, the controls and the energy counter are back at their defaults."""
    with step("Change the time, the weather, the grid and the controls"):
        rig.sim.at("17:45")
        rig.sim.clouds(60)
        rig.sim.ambient(31.5)
        rig.sim.heat_sink(50.0)
        rig.sunspec.set_many(123, "WMaxLimPct", [20, 0, 300, 10, 1])
        rig.sunspec.set(123, "Conn", 0)
        rig.sim.grid(False)
        rig.sim.advance(100)
    with step("Reset"):
        rig.sim.reset()
    assert rig.master.read_holding(SIM_BASE, 10) == [SIM_MAGIC, 720, 0, 0, 0, 250, 1, 0x8000, 0, 0]
    controls = rig.sunspec.model(123)
    assert (controls["Conn"], controls["WMaxLimPct"], controls["WMaxLim_Ena"]) == (1, 100, 0)
    assert (controls["WMaxLimPct_RvrtTms"], controls["WMaxLimPct_RmpTms"], controls["Conn_RvrtTms"]) == (0, 0, 0)
    inverter = rig.sunspec.measurements(101)
    assert (inverter["W"], inverter["St"], inverter["Evt1"]) == (0, ds.ST_SLEEPING, 0)
    assert inverter["WH"] == ds.START_ENERGY_WH
    assert inverter["TmpSnk"] == 25.0


def test_reset_needs_its_key(rig: Rig) -> None:
    """A reset happens only with the key 0xC0DE; any other value is refused and nothing is reset."""
    rig.sim.clouds(60)
    for wrong in (0, 1, 0xC0DD, 0xFFFF):
        assert refused(rig, SIM_BASE + SIM_RESET, [wrong]) == ILLEGAL_VALUE
    assert rig.master.read_holding(SIM_BASE + SIM_CLOUD, 1) == [60]


def test_negative_temperature_is_stored_as_twos_complement(rig: Rig) -> None:
    """An ambient temperature of -15.0 degrees is written and read back as the 16-bit value 0xFF6A."""
    rig.sim.ambient(-15.0)
    assert rig.master.read_holding(SIM_BASE + SIM_AMBIENT, 1) == [0xFF6A]
