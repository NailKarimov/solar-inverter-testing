"""A day in the life of the inverter: asleep at night, awake at sunrise, never above its rating."""

from __future__ import annotations

import time

import pytest

from conftest import Rig
from inverter_lab.sunspec import BASE_ADDRESS
from support import datasheet as ds
from support.evidence import step


def reading(rig: Rig) -> dict[str, float]:
    """The numeric measurements of the inverter model in real units."""
    return {k: float(v) for k, v in rig.sunspec.measurements(101).items() if isinstance(v, int | float)}


def power(rig: Rig) -> float:
    return rig.sunspec.number(101, "W")


def state(rig: Rig) -> int:
    return int(rig.sunspec.number(101, "St"))


def sample_day(rig: Rig, step_s: int = 1800) -> list[dict[str, float]]:
    """Measurements every ``step_s`` seconds from midnight to midnight."""
    rig.sim.set_time("00:00")
    samples = []
    for _ in range(86400 // step_s):
        rig.sim.advance(step_s)
        samples.append(reading(rig))
    return samples


@pytest.mark.smoke
def test_at_night_the_inverter_sleeps(rig: Rig) -> None:
    """At three in the morning the inverter sleeps: no power, no current, no array voltage."""
    rig.sim.at("03:00")
    now = reading(rig)
    assert now["St"] == ds.ST_SLEEPING
    assert (now["W"], now["A"], now["DCW"], now["DCV"]) == (0, 0, 0, 0)


@pytest.mark.smoke
def test_at_noon_it_delivers_its_rated_power(rig: Rig) -> None:
    """At noon under a clear sky the inverter delivers exactly its rated 5000 W."""
    rig.sim.at("12:00")
    assert power(rig) == ds.RATED_W
    assert state(rig) == ds.ST_MPPT


def test_power_never_exceeds_the_nameplate(rig: Rig) -> None:
    """Sampled every half hour for a whole day, the power never goes above the rating on the nameplate."""
    rated = rig.sunspec.number(120, "WRtg")
    with step("Run a whole clear day and read the power every 30 minutes"):
        samples = sample_day(rig)
    assert max(s["W"] for s in samples) == rated  # the array is larger than the inverter, so it does clip
    assert all(0 <= s["W"] <= rated for s in samples)


@pytest.mark.parametrize("hhmm", ["06:00", "08:00", "10:00", "17:00", "19:00", "21:00"])
def test_power_follows_the_datasheet_curve(rig: Rig, hhmm: str) -> None:
    """At any hour of a clear day the power is what the datasheet formula gives, to the watt."""
    rig.sim.at(hhmm)
    expected = ds.ac_power(rig.sim.clock())
    assert power(rig) == pytest.approx(expected, abs=1.0)


def test_power_rises_all_morning_and_falls_all_evening(rig: Rig) -> None:
    """Hour by hour the power only rises until the plateau and only falls after it."""
    morning, evening = [], []
    for hour in range(6, 12):
        rig.sim.at(f"{hour:02d}:00")
        morning.append(power(rig))
    for hour in range(16, 22):
        rig.sim.at(f"{hour:02d}:00")
        evening.append(power(rig))
    assert morning == sorted(set(morning))
    assert evening == sorted(set(evening), reverse=True)


@pytest.mark.parametrize("hours", [3, 5, 7])
def test_day_is_symmetric_around_solar_noon(rig: Rig, hours: int) -> None:
    """The same time before and after solar noon (13:22:30) gives the same power."""
    values = []
    for sign in (-1, 1):
        moment = ds.SOLAR_NOON_S + sign * hours * 3600 - 90
        rig.sim.set_time(f"{moment // 3600:02d}:{moment % 3600 // 60:02d}")
        rig.sim.advance(90 + moment % 60)
        assert rig.sim.clock() == ds.SOLAR_NOON_S + sign * hours * 3600
        values.append(power(rig))
    assert values[0] == pytest.approx(values[1], abs=1.0)
    assert values[0] > 0


def test_clouds_reduce_the_power(rig: Rig) -> None:
    """More cloud means less power, and a fully overcast noon still gives what a quarter of the light can."""
    rig.sim.at("12:00")
    levels = []
    for cloud in (0, 25, 50, 75, 100):
        rig.sim.clouds(cloud)
        rig.sim.advance(10)
        levels.append(power(rig))
    assert levels == sorted(set(levels), reverse=True)
    assert levels[-1] == pytest.approx(ds.ac_power(rig.sim.clock(), cloud_pct=100), abs=1.0)


def test_power_falls_at_once_and_rises_gently(rig: Rig) -> None:
    """When a cloud arrives the power drops within a second; when it leaves, power returns at 1 kW per second."""
    rig.sim.at("12:00")
    with step("A thick cloud arrives"):
        rig.sim.clouds(100)
        rig.sim.advance(1)
        shaded = power(rig)
    assert shaded == pytest.approx(ds.ac_power(rig.sim.clock(), cloud_pct=100), abs=1.0)
    with step("The cloud leaves"):
        rig.sim.clouds(0)
        climb = []
        for _ in range(5):
            rig.sim.advance(1)
            climb.append(power(rig))
    steps = [b - a for a, b in zip([shaded, *climb], climb, strict=False)]
    assert all(0 < s <= ds.RAMP_W_PER_S + 1 for s in steps[:3])
    assert climb[-1] == ds.RATED_W


def test_start_up_takes_twenty_seconds_of_grid_checks(rig: Rig) -> None:
    """At dawn the inverter first checks the grid for 20 seconds with zero output, then starts feeding in."""
    rig.sim.set_time("05:30")
    seen = []
    for wait in (45, 10, 10, 10):
        rig.sim.advance(wait)
        seen.append((rig.sim.clock() - 5 * 3600 - 30 * 60, state(rig), power(rig) > 0))
    assert seen == [
        (45, ds.ST_SLEEPING, False),  # not enough light yet
        (55, ds.ST_STARTING, False),  # enough light since second 51: checking the grid
        (65, ds.ST_STARTING, False),
        (75, ds.ST_MPPT, True),  # 20 s later: feeding in
    ]


def test_soft_start_adds_one_kilowatt_per_second(rig: Rig) -> None:
    """After start-up the power climbs by 1 kW each second until it reaches what the sun delivers."""
    rig.sim.advance(ds.STARTUP_S)  # a fresh inverter at noon: 20 s of grid checks
    assert power(rig) == 0
    climb = []
    for _ in range(6):
        rig.sim.advance(1)
        climb.append(power(rig))
    assert climb == [1000, 2000, 3000, 4000, 5000, 5000]


def test_ac_power_is_always_below_dc_power(rig: Rig) -> None:
    """All day the inverter gives out less than it takes in: at least 20 W and 2.5 % are lost as heat."""
    for sample in sample_day(rig, step_s=3600):
        if sample["W"] > 0:
            loss = sample["DCW"] - sample["W"]
            assert loss == pytest.approx(ds.SELF_USE_W + (1 - ds.EFFICIENCY) * sample["DCW"], abs=1.5)
        else:
            assert sample["DCW"] == 0


def test_ac_power_equals_voltage_times_current(rig: Rig) -> None:
    """On the AC side the reported power equals voltage times current, within the rounding of the registers."""
    for sample in sample_day(rig, step_s=3600):
        assert sample["W"] == pytest.approx(sample["PhVphA"] * sample["A"], abs=3.0)
        assert sample["A"] == sample["AphA"]


def test_dc_power_equals_voltage_times_current(rig: Rig) -> None:
    """On the DC side the reported power equals voltage times current, within the rounding of the registers."""
    for sample in sample_day(rig, step_s=3600):
        assert sample["DCW"] == pytest.approx(sample["DCV"] * sample["DCA"], abs=3.5)


def test_apparent_power_equals_active_power(rig: Rig) -> None:
    """With a power factor of 100 % the apparent power equals the active power and reactive power is zero."""
    rig.sim.at("09:00")
    now = reading(rig)
    assert now["PF"] == 100.0
    assert now["VA"] == now["W"] > 0
    assert now["VAr"] == 0


def test_energy_counter_adds_up_the_power(rig: Rig) -> None:
    """One hour at a steady 5000 W adds exactly 5000 Wh to the energy counter."""
    rig.sim.at("12:00")
    before = rig.sunspec.number(101, "WH")
    rig.sim.advance(3600)
    assert rig.sunspec.number(101, "WH") - before == pytest.approx(5000, abs=1)


def test_energy_counter_never_goes_down(rig: Rig) -> None:
    """Over a whole day the energy counter only grows, and a clear June day yields about 45 kWh."""
    start = rig.sunspec.number(101, "WH")
    assert start == ds.START_ENERGY_WH
    readings = [s["WH"] for s in sample_day(rig, step_s=3600)]
    assert readings == sorted(readings)
    assert 44_000 < readings[-1] - start < 46_000


def test_energy_counter_stands_still_at_night(rig: Rig) -> None:
    """Between sunset and sunrise the energy counter does not move."""
    rig.sim.at("23:00")
    before = rig.sunspec.number(101, "WH")
    rig.sim.advance(4 * 3600)
    assert rig.sunspec.number(101, "WH") == before


def test_evening_shutdown_happens_once(rig: Rig) -> None:
    """At dusk the inverter goes to sleep once and stays asleep: it does not flicker on and off."""
    rig.sim.at("21:00")
    rig.sim.advance(19 * 60)
    states = []
    for _ in range(40):
        rig.sim.advance(15)
        states.append(state(rig))
    changes = sum(a != b for a, b in zip(states, states[1:], strict=False))
    assert states[0] == ds.ST_MPPT
    assert states[-1] == ds.ST_SLEEPING
    assert changes == 1


def test_weak_light_keeps_a_running_inverter_on_and_a_sleeping_one_asleep(rig: Rig) -> None:
    """In the weak light of 21:21 an inverter that was running keeps running and one that slept stays asleep."""
    with step("An inverter that has been running since 21:00"):
        rig.sim.at("21:00")
        rig.sim.advance(20 * 60)
        running = state(rig), power(rig)
    with step("A fresh inverter that meets the same light"):
        rig.sim.reset()
        rig.sim.at("21:20")
        fresh = state(rig), power(rig)
    assert ds.STOP_W < ds.available_dc(rig.sim.clock()) < ds.START_W
    assert running[0] == ds.ST_MPPT
    assert running[1] > 0
    assert fresh == (ds.ST_SLEEPING, 0)


def test_next_morning_it_starts_again(rig: Rig) -> None:
    """After a night asleep the inverter wakes up by itself the next morning."""
    rig.sim.at("21:00")
    with step("Let ten hours pass, across midnight"):
        rig.sim.advance(10 * 3600)
    assert rig.sim.clock() == 7 * 3600 + 60
    assert state(rig) == ds.ST_MPPT
    assert power(rig) == pytest.approx(ds.ac_power(rig.sim.clock()), abs=1.0)


def test_clock_wraps_at_midnight(rig: Rig) -> None:
    """Two minutes after 23:59 the clock reads 00:01."""
    rig.sim.set_time("23:59")
    rig.sim.advance(120)
    assert rig.sim.clock() == 60


def test_simulated_time_moves_only_on_command(rig: Rig) -> None:
    """The simulated clock stands still unless a test moves it, so every run sees the same day."""
    first = rig.sim.clock()
    time.sleep(0.3)
    assert rig.sim.clock() == first


def test_heat_sink_warms_with_load_and_cools_at_night(rig: Rig) -> None:
    """After an hour at full power the heat sink is 45 degrees above ambient; at night it cools back down."""
    rig.sim.at("12:00", settle=3600)
    hot = reading(rig)
    assert hot["TmpSnk"] == pytest.approx(25 + ds.HEAT_RISE_C, abs=0.2)
    assert 25 < hot["TmpCab"] < hot["TmpSnk"]
    rig.sim.at("23:00", settle=3600)
    assert reading(rig)["TmpSnk"] == pytest.approx(25.0, abs=0.2)


def test_ambient_temperature_shifts_the_heat_sink(rig: Rig) -> None:
    """On a frosty night the idle inverter settles at the ambient temperature, below zero included."""
    rig.sim.ambient(-15.0)
    rig.sim.at("02:00", settle=3600)
    now = reading(rig)
    assert now["TmpSnk"] == pytest.approx(-15.0, abs=0.2)
    assert now["TmpCab"] == pytest.approx(-15.0, abs=0.2)


def test_grid_voltage_rises_slightly_while_feeding_in(rig: Rig) -> None:
    """The inverter reads 230.0 V at night and 234.0 V while it feeds in at full power."""
    rig.sim.at("03:00")
    assert rig.sunspec.number(101, "PhVphA") == 230.0
    rig.sim.at("12:00")
    assert rig.sunspec.number(101, "PhVphA") == 234.0


def test_grid_frequency_reads_fifty_hertz(rig: Rig) -> None:
    """The grid frequency reads 50.00 Hz, with two decimals."""
    assert rig.sunspec.number(101, "Hz") == 50.0
    assert rig.sunspec.model(101)["Hz"] == 5000


def test_array_voltage_tells_what_the_inverter_is_doing(rig: Rig) -> None:
    """The array reads 0 V in the dark, 440 V unloaded at dawn, 360 V at full use and more when power is clipped."""
    seen = {}
    for label, hhmm in [("dark", "03:00"), ("dawn", "05:00"), ("working", "09:00"), ("clipping", "13:00")]:
        rig.sim.at(hhmm)
        seen[label] = rig.sunspec.number(101, "DCV")
    assert seen["dark"] == 0
    assert seen["dawn"] == 440.0
    assert seen["working"] == 360.0
    assert 360.0 < seen["clipping"] < 440.0


def test_same_commands_give_the_same_registers(rig: Rig) -> None:
    """Two runs of the same scenario leave every register of the map identical: nothing is random."""

    def scenario() -> list[int]:
        rig.sim.reset()
        rig.sim.at("08:15")
        rig.sim.clouds(35)
        rig.sim.advance(1234)
        rig.sunspec.set_many(123, "WMaxLimPct", [40, 0, 0, 7, 1])
        rig.sim.advance(3)
        return rig.master.read_holding(BASE_ADDRESS, 125) + rig.master.read_holding(BASE_ADDRESS + 125, 53)

    assert scenario() == scenario()
