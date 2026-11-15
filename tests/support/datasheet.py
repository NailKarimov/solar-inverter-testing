"""What the inverter's datasheet promises, restated independently of the simulator's code.

The tests compare the device with these formulas. The numbers are typed in again on purpose:
if a constant in the simulator changes by mistake, the two no longer agree and a test fails.
"""

from __future__ import annotations

RATED_W = 5000.0
ARRAY_WP = 6000.0
SUNRISE_S = 4 * 3600 + 30 * 60
SUNSET_S = 22 * 3600 + 15 * 60
SOLAR_NOON_S = (SUNRISE_S + SUNSET_S) // 2  # 13:22:30
EFFICIENCY = 0.975
SELF_USE_W = 20.0
START_W = 60.0
STOP_W = 30.0
STARTUP_S = 20
RECONNECT_S = 60
RAMP_W_PER_S = 1000
TRIP_C = 95.0
RESET_C = 75.0
HEAT_RISE_C = 45.0
START_ENERGY_WH = 1_234_567

ST_SLEEPING, ST_STARTING, ST_MPPT, ST_THROTTLED, ST_FAULT, ST_STANDBY = 2, 3, 4, 5, 7, 8
EVT_GRID_DISCONNECT = 1 << 4
EVT_OVER_TEMP = 1 << 7


def available_dc(clock_s: int, cloud_pct: int = 0) -> float:
    """DC power of the array: a bell between sunrise and sunset, reduced by clouds to a quarter at most."""
    if not SUNRISE_S < clock_s < SUNSET_S:
        return 0.0
    x = (clock_s - SUNRISE_S) / (SUNSET_S - SUNRISE_S)
    return ARRAY_WP * (4 * x * (1 - x)) ** 3 * (1 - 0.75 * cloud_pct / 100)


def ac_power(clock_s: int, cloud_pct: int = 0, limit_pct: float = 100.0) -> float:
    """AC power once the inverter has settled: losses taken off, clipped at the rating and at the limit."""
    available = available_dc(clock_s, cloud_pct)
    if available < STOP_W:
        return 0.0
    return min(RATED_W, RATED_W * limit_pct / 100, max(0.0, available * EFFICIENCY - SELF_USE_W))
