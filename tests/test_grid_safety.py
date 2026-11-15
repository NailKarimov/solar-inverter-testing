"""Protections: the inverter must stop by itself when the grid disappears or when it overheats."""

from __future__ import annotations

import pytest

from conftest import Rig
from support import datasheet as ds
from support.evidence import step


def status(rig: Rig) -> tuple[int, int, float]:
    """State, event bits and AC power."""
    model = rig.sunspec.measurements(101)
    return int(model["St"]), int(model["Evt1"]), float(model["W"])  # type: ignore[arg-type]


def at_full_power(rig: Rig) -> None:
    rig.sim.at("12:00")
    assert status(rig) == (ds.ST_MPPT, 0, ds.RATED_W)


@pytest.mark.smoke
def test_grid_loss_stops_the_feed_in_within_a_second(rig: Rig) -> None:
    """When the grid disappears the inverter stops feeding in within one second, so nobody repairs a live line."""
    at_full_power(rig)
    with step("The grid disappears"):
        rig.sim.grid(False)
        rig.sim.advance(1)
    now = rig.sunspec.measurements(101)
    assert (now["W"], now["A"], now["DCW"]) == (0, 0, 0)


def test_grid_loss_is_reported_as_a_fault(rig: Rig) -> None:
    """During a grid outage the inverter reports FAULT with the event GRID_DISCONNECT, zero volts and zero hertz."""
    at_full_power(rig)
    rig.sim.grid(False)
    rig.sim.advance(1)
    state, events, _ = status(rig)
    assert state == ds.ST_FAULT
    assert events == ds.EVT_GRID_DISCONNECT
    assert rig.sunspec.number(101, "PhVphA") == 0
    assert rig.sunspec.number(101, "Hz") == 0


def test_inverter_waits_a_minute_after_the_grid_returns(rig: Rig) -> None:
    """After the grid returns the inverter waits a full 60 seconds before it feeds in again."""
    at_full_power(rig)
    rig.sim.grid(False)
    rig.sim.advance(10)
    with step("The grid returns"):
        rig.sim.grid(True)
        rig.sim.advance(ds.RECONNECT_S)
        assert status(rig) == (ds.ST_STARTING, 0, 0)
    with step("One second later the soft start begins"):
        rig.sim.advance(1)
        assert status(rig) == (ds.ST_MPPT, 0, 1000)
    rig.sim.advance(4)
    assert status(rig) == (ds.ST_MPPT, 0, ds.RATED_W)


def test_even_a_one_second_dip_costs_the_full_minute(rig: Rig) -> None:
    """A grid dip of a single second is treated like any outage: the full 60-second wait follows."""
    at_full_power(rig)
    rig.sim.grid(False)
    rig.sim.advance(1)
    rig.sim.grid(True)
    rig.sim.advance(ds.RECONNECT_S - 1)
    assert status(rig)[2] == 0
    rig.sim.advance(10)
    assert status(rig)[2] == ds.RATED_W


def test_fault_flag_clears_when_the_grid_is_back(rig: Rig) -> None:
    """The GRID_DISCONNECT event disappears as soon as the grid is back, while the inverter still waits."""
    at_full_power(rig)
    rig.sim.grid(False)
    rig.sim.advance(5)
    rig.sim.grid(True)
    rig.sim.advance(1)
    assert status(rig) == (ds.ST_STARTING, 0, 0)


def test_grid_loss_at_night_is_still_reported(rig: Rig) -> None:
    """A grid outage at night is reported as a fault too, and afterwards the inverter goes back to sleep."""
    rig.sim.at("03:00")
    rig.sim.grid(False)
    rig.sim.advance(1)
    assert status(rig) == (ds.ST_FAULT, ds.EVT_GRID_DISCONNECT, 0)
    rig.sim.grid(True)
    rig.sim.advance(1)
    assert status(rig) == (ds.ST_SLEEPING, 0, 0)


def test_overheating_stops_the_inverter(rig: Rig) -> None:
    """When the heat sink reaches 95 degrees the inverter stops and reports OVER_TEMP."""
    at_full_power(rig)
    with step("Heat the heat sink to 96 C"):
        rig.sim.heat_sink(96.0)
        rig.sim.advance(2)
    assert status(rig) == (ds.ST_FAULT, ds.EVT_OVER_TEMP, 0)


@pytest.mark.parametrize(("celsius", "trips"), [(94.9, False), (95.0, True)])
def test_trip_threshold_is_exactly_95_degrees(rig: Rig, celsius: float, trips: bool) -> None:
    """At 94.9 degrees the inverter keeps running; at 95.0 it stops."""
    at_full_power(rig)
    rig.sim.heat_sink(celsius)
    rig.sim.advance(2)
    assert (status(rig)[0] == ds.ST_FAULT) is trips


@pytest.mark.parametrize(("celsius", "restarts"), [(75.1, False), (75.0, True)])
def test_restart_threshold_is_exactly_75_degrees(rig: Rig, celsius: float, restarts: bool) -> None:
    """After a trip the inverter stays off at 75.1 degrees and starts again at 75.0."""
    at_full_power(rig)
    rig.sim.heat_sink(96.0)
    rig.sim.advance(2)
    with step(f"Cool the heat sink to {celsius} C and wait"):
        rig.sim.heat_sink(celsius)
        rig.sim.advance(ds.STARTUP_S + 10)
    state, events, watts = status(rig)
    if restarts:
        assert (state, events) == (ds.ST_MPPT, 0)
        assert watts == ds.RATED_W
    else:
        assert (state, events, watts) == (ds.ST_FAULT, ds.EVT_OVER_TEMP, 0)


def test_hot_cabinet_makes_the_inverter_cycle_but_never_cook(rig: Rig) -> None:
    """In a 60-degree cabinet the inverter trips, cools, restarts and trips again; it never runs past 95 degrees."""
    rig.sim.ambient(60.0)
    rig.sim.at("12:00", settle=1)
    hottest, tripped, restarted_after_trip = 0.0, False, False
    with step("Two hours at noon light in a 60 C cabinet, read every 30 s"):
        for _ in range(240):
            rig.sim.set_time("12:00")  # keep the light constant
            rig.sim.advance(30)
            now = rig.sunspec.measurements(101)
            hottest = max(hottest, float(now["TmpSnk"]))  # type: ignore[arg-type]
            if now["St"] == ds.ST_FAULT:
                tripped = True
            elif tripped and now["St"] == ds.ST_MPPT:
                restarted_after_trip = True
    assert tripped
    assert restarted_after_trip
    assert hottest < ds.TRIP_C + 0.5


def test_two_faults_at_once_show_both_events(rig: Rig) -> None:
    """With the grid down and the heat sink too hot, both events are reported at the same time."""
    at_full_power(rig)
    rig.sim.heat_sink(100.0)
    rig.sim.grid(False)
    rig.sim.advance(2)
    assert status(rig) == (ds.ST_FAULT, ds.EVT_GRID_DISCONNECT | ds.EVT_OVER_TEMP, 0)


def test_energy_counter_stands_still_during_a_fault(rig: Rig) -> None:
    """While a fault keeps the inverter off, the energy counter does not move."""
    at_full_power(rig)
    rig.sim.grid(False)
    rig.sim.advance(1)
    before = rig.sunspec.number(101, "WH")
    rig.sim.advance(600)
    assert rig.sunspec.number(101, "WH") == before
