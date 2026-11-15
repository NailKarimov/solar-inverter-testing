"""Remote control: the grid operator tells the inverter to reduce its output or to disconnect."""

from __future__ import annotations

import pytest

from conftest import Rig
from support import datasheet as ds
from support.evidence import step


def limit(rig: Rig, percent: int, enabled: bool = True, revert_s: int = 0, ramp_s: int = 0) -> None:
    """Write the five limit registers in one request: percent, window, revert timeout, ramp time, enable."""
    rig.sunspec.set_many(123, "WMaxLimPct", [percent, 0, revert_s, ramp_s, 1 if enabled else 0])


def power(rig: Rig) -> float:
    return rig.sunspec.number(101, "W")


def state(rig: Rig) -> int:
    return int(rig.sunspec.number(101, "St"))


def every_second(rig: Rig, seconds: int) -> list[float]:
    values = []
    for _ in range(seconds):
        rig.sim.advance(1)
        values.append(power(rig))
    return values


@pytest.fixture
def noon(rig: Rig) -> Rig:
    """An inverter at full power at noon."""
    rig.sim.at("12:00")
    assert power(rig) == ds.RATED_W
    return rig


@pytest.mark.smoke
def test_limit_of_50_percent_halves_the_output(noon: Rig) -> None:
    """Told to limit itself to 50 %, the inverter delivers 2500 W and reports that it is throttled."""
    with step("Write the limit: 50 %, enabled"):
        limit(noon, 50)
    noon.sim.advance(1)
    assert power(noon) == 2500
    assert state(noon) == ds.ST_THROTTLED


@pytest.mark.parametrize("percent", [0, 1, 10, 25, 50, 75, 99, 100])
def test_limit_sets_the_output_to_that_share_of_the_rating(noon: Rig, percent: int) -> None:
    """Any limit from 0 to 100 % gives exactly that share of the rated 5000 W."""
    limit(noon, percent)
    noon.sim.advance(1)
    assert power(noon) == ds.RATED_W * percent / 100
    assert state(noon) == (ds.ST_MPPT if percent == 100 else ds.ST_THROTTLED)


def test_limit_above_what_the_sun_delivers_changes_nothing(noon: Rig) -> None:
    """Under thick cloud a 50 % limit is higher than what the sun delivers, so the inverter is not throttled."""
    noon.sim.clouds(100)
    noon.sim.advance(5)
    limit(noon, 50)
    noon.sim.advance(5)
    unlimited = ds.ac_power(noon.sim.clock(), cloud_pct=100)
    assert unlimited < 2500
    assert power(noon) == pytest.approx(unlimited, abs=1.0)
    assert state(noon) == ds.ST_MPPT


def test_limit_that_is_not_enabled_has_no_effect(noon: Rig) -> None:
    """A limit value written without the enable flag changes nothing."""
    limit(noon, 30, enabled=False)
    noon.sim.advance(5)
    assert power(noon) == ds.RATED_W
    assert noon.sunspec.get(123, "WMaxLimPct") == 30


def test_limit_can_be_read_back(noon: Rig) -> None:
    """The limit, its timers and the enable flag read back exactly as written."""
    limit(noon, 42, revert_s=900, ramp_s=15)
    controls = noon.sunspec.model(123)
    assert controls["WMaxLimPct"] == 42
    assert controls["WMaxLimPct_RvrtTms"] == 900
    assert controls["WMaxLimPct_RmpTms"] == 15
    assert controls["WMaxLim_Ena"] == 1


def test_removing_the_limit_brings_the_power_back_gently(noon: Rig) -> None:
    """When the limit is removed the power returns at 1 kW per second, not in one jump."""
    limit(noon, 20)
    noon.sim.advance(1)
    assert power(noon) == 1000
    with step("Disable the limit"):
        limit(noon, 20, enabled=False)
    assert every_second(noon, 5) == [2000, 3000, 4000, 5000, 5000]
    assert state(noon) == ds.ST_MPPT


def test_ramp_time_spreads_the_change_evenly(noon: Rig) -> None:
    """With a ramp time of 10 s the output falls from 100 % to 50 % in ten equal steps of 250 W."""
    limit(noon, 50, ramp_s=10)
    assert every_second(noon, 12) == [5000 - 250 * t for t in range(1, 11)] + [2500, 2500]


def test_ramp_also_applies_on_the_way_up(noon: Rig) -> None:
    """Raising the limit from 20 % to 60 % with a ramp time of 4 s takes four equal steps of 500 W."""
    limit(noon, 20)
    noon.sim.advance(1)
    limit(noon, 60, ramp_s=4)
    assert every_second(noon, 6) == [1500, 2000, 2500, 3000, 3000, 3000]


def test_limit_is_dropped_when_the_controller_goes_quiet(noon: Rig) -> None:
    """A limit with a 30-second revert timeout is dropped by the inverter itself if nobody renews it."""
    limit(noon, 50, revert_s=30)
    noon.sim.advance(29)
    assert power(noon) == 2500
    assert noon.sunspec.get(123, "WMaxLim_Ena") == 1
    with step("Second 30 passes without a new command"):
        noon.sim.advance(1)
    assert noon.sunspec.get(123, "WMaxLim_Ena") == 0
    assert every_second(noon, 3) == [4500, 5000, 5000]


def test_renewing_the_limit_restarts_its_timer(noon: Rig) -> None:
    """Writing the limit again before the timeout keeps it alive for another full period."""
    limit(noon, 50, revert_s=30)
    noon.sim.advance(20)
    with step("Renew the same limit at second 20"):
        limit(noon, 50, revert_s=30)
    noon.sim.advance(29)
    assert power(noon) == 2500
    noon.sim.advance(5)
    assert power(noon) == ds.RATED_W


def test_limit_of_zero_keeps_the_inverter_connected(noon: Rig) -> None:
    """A limit of 0 % brings the output to zero while the inverter stays connected and ready."""
    limit(noon, 0)
    noon.sim.advance(1)
    assert power(noon) == 0
    assert state(noon) == ds.ST_THROTTLED
    limit(noon, 100)
    assert every_second(noon, 5)[-1] == ds.RATED_W


def test_limit_holds_while_a_cloud_passes(noon: Rig) -> None:
    """After a cloud passes, the power climbs back to the limit and stops there."""
    limit(noon, 50)
    noon.sim.advance(1)
    noon.sim.clouds(100)
    noon.sim.advance(5)
    assert power(noon) < 2500
    noon.sim.clouds(0)
    climb = every_second(noon, 8)
    assert max(climb) == 2500
    assert climb[-1] == 2500


def test_output_never_overshoots_the_limit_during_start_up(rig: Rig) -> None:
    """An inverter that starts up with a 30 % limit already set never delivers more than 1500 W."""
    limit(rig, 30)
    samples = every_second(rig, 40)
    assert max(samples) == 1500
    assert samples[-1] == 1500


def test_throttled_inverter_lets_the_array_voltage_rise(noon: Rig) -> None:
    """When throttled the inverter takes less from the array, so the array voltage rises above 360 V."""
    limit(noon, 50)
    noon.sim.advance(1)
    now = noon.sunspec.measurements(101)
    assert 395 < float(now["DCV"]) < 410  # type: ignore[arg-type]
    assert float(now["DCW"]) == pytest.approx((2500 + ds.SELF_USE_W) / ds.EFFICIENCY, abs=1)  # type: ignore[arg-type]


def test_limit_survives_the_night(rig: Rig) -> None:
    """A limit without a timeout is still in force the next day."""
    rig.sim.at("20:00")
    limit(rig, 50)
    with step("Sixteen hours later: noon of the next day"):
        rig.sim.advance(16 * 3600)
    assert power(rig) == 2500
    assert state(rig) == ds.ST_THROTTLED


def test_disconnect_command_stops_the_feed_in(noon: Rig) -> None:
    """Told to disconnect, the inverter stops within a second and reports STANDBY, without any fault."""
    noon.sunspec.set(123, "Conn", 0)
    noon.sim.advance(1)
    assert power(noon) == 0
    assert state(noon) == ds.ST_STANDBY
    assert noon.sunspec.get(101, "Evt1") == 0


def test_reconnect_command_goes_through_the_grid_checks(noon: Rig) -> None:
    """Told to connect again, the inverter first checks the grid for 20 s and then starts softly."""
    noon.sunspec.set(123, "Conn", 0)
    noon.sim.advance(5)
    noon.sunspec.set(123, "Conn", 1)
    noon.sim.advance(ds.STARTUP_S)
    assert (state(noon), power(noon)) == (ds.ST_STARTING, 0)
    assert every_second(noon, 5) == [1000, 2000, 3000, 4000, 5000]


def test_disconnect_with_a_timeout_reconnects_by_itself(noon: Rig) -> None:
    """A disconnect command with a 30-second timeout is undone by the inverter after 30 seconds."""
    noon.sunspec.set(123, "Conn_RvrtTms", 30)
    noon.sunspec.set(123, "Conn", 0)
    noon.sim.advance(29)
    assert noon.sunspec.get(123, "Conn") == 0
    noon.sim.advance(1)
    assert noon.sunspec.get(123, "Conn") == 1
    noon.sim.advance(ds.STARTUP_S + 5)
    assert power(noon) == ds.RATED_W
