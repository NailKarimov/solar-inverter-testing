"""The inverter itself: a small physical model with a clock, protections and remote controls.

A 5 kW single-phase inverter with a 6 kWp array on a clear mid-June day in Riga. Simulated time moves
in one-second ticks and only when ``advance`` is called, so every test is repeatable.

The model uses nothing but additions, multiplications and divisions. The JavaScript twin behind the
visual pages repeats the same operations in the same order, and the two answer byte for byte alike.

What it models:

- sunlight by time of day and cloud cover, so DC power rises in the morning and falls in the evening
- conversion losses and clipping at the 5 kW rating
- start-up: enough light, then 20 s of grid checks, then a soft ramp of 1 kW per second
- anti-islanding: the grid disappears, the output is zero on the next tick, and it stays zero for
  60 s after the grid returns
- over-temperature trip at 95 C with a reset at 75 C
- remote controls: disconnect, and a power limit with a ramp time and a revert timeout
"""

from __future__ import annotations

from inverter_lab.sunspec import (
    EVT_GRID_DISCONNECT,
    EVT_OVER_TEMP,
    ST_FAULT,
    ST_MPPT,
    ST_SLEEPING,
    ST_STANDBY,
    ST_STARTING,
    ST_THROTTLED,
    Value,
    round_half_up,
)

DAY_S = 86400
NOON_S = 12 * 3600
SUNRISE_S = 4 * 3600 + 30 * 60  # 04:30
SUNSET_S = 22 * 3600 + 15 * 60  # 22:15

RATED_W = 5000.0  # nameplate AC power
ARRAY_WP = 6000.0  # DC power of the array in full sun
CLOUD_LOSS = 0.75  # a fully overcast sky still lets a quarter of the light through
EFFICIENCY = 0.975
SELF_USE_W = 20.0  # the electronics' own consumption

START_W = 60.0  # DC power needed to start
STOP_W = 30.0  # below this the inverter goes back to sleep
STARTUP_S = 20  # grid checks before feeding in
RECONNECT_S = 60  # wait after the grid returns
RAMP_W_PER_S = 1000.0  # soft start

MPP_V = 360.0  # array voltage at the maximum power point
OPEN_V = 440.0  # array voltage with no load
NOMINAL_V = 230.0
V_RISE = 4.0  # the grid voltage rises a little while the inverter feeds in
NOMINAL_HZ = 50.0

AMBIENT_C = 25.0
RISE_C = 45.0  # heat sink rise above ambient at rated power
TAU_S = 300.0  # thermal time constant
TRIP_C = 95.0
RESET_C = 75.0

START_ENERGY_WH = 1_234_567.0
RATED_A_X10 = 217  # 5000 W / 230 V = 21.7 A


class Inverter:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Factory state: noon, clear sky, 25 C, grid present, asleep and about to start."""
        # environment
        self.clock = NOON_S
        self.cloud_pct = 0
        self.ambient_c = AMBIENT_C
        self.grid_ok = True
        self.heat_override_c: float | None = None
        # state
        self.state = ST_SLEEPING
        self.events = 0
        self.over_temp = False
        self.startup_left = STARTUP_S
        self.uptime_s = 0
        # measurements
        self.ac_w = 0.0
        self.dc_w = 0.0
        self.dc_v = 0.0
        self.dc_a = 0.0
        self.ac_v = NOMINAL_V
        self.ac_a = 0.0
        self.hz = NOMINAL_HZ
        self.sink_c = AMBIENT_C
        self.cab_c = AMBIENT_C
        self.energy_wh = START_ENERGY_WH
        # controls
        self.conn = True
        self.conn_rvrt_s = 0
        self.conn_age = 0
        self.limit_ena = False
        self.limit_pct = 100
        self.limit_rvrt_s = 0
        self.limit_rmp_s = 0
        self.limit_age = 0
        # the limit in force right now, in percent of the rating, and its ramp
        self.eff_pct = 100.0
        self.ramp_from = 100.0
        self.ramp_to = 100.0
        self.ramp_total = 0
        self.ramp_left = 0
        self._measure(self.available_dc())

    # ---- environment ----------------------------------------------------------------------

    def available_dc(self) -> float:
        """DC power the array could deliver right now, in watts."""
        if not SUNRISE_S < self.clock < SUNSET_S:
            return 0.0
        x = (self.clock - SUNRISE_S) / (SUNSET_S - SUNRISE_S)
        sun = 4.0 * x * (1.0 - x)  # 0 at sunrise and sunset, 1 at solar noon
        return ARRAY_WP * sun * sun * sun * (1.0 - CLOUD_LOSS * self.cloud_pct / 100.0)

    # ---- controls -------------------------------------------------------------------------

    def write_controls(self, changes: dict[str, int]) -> None:
        """Apply validated writes to the points of model 123."""
        if "Conn_RvrtTms" in changes:
            self.conn_rvrt_s = changes["Conn_RvrtTms"]
        if "Conn" in changes:
            self.conn = changes["Conn"] == 1
            self.conn_age = 0
        if "WMaxLimPct_RvrtTms" in changes:
            self.limit_rvrt_s = changes["WMaxLimPct_RvrtTms"]
        if "WMaxLimPct_RmpTms" in changes:
            self.limit_rmp_s = changes["WMaxLimPct_RmpTms"]
        if "WMaxLimPct" in changes or "WMaxLim_Ena" in changes:
            if "WMaxLimPct" in changes:
                self.limit_pct = changes["WMaxLimPct"]
            if "WMaxLim_Ena" in changes:
                self.limit_ena = changes["WMaxLim_Ena"] == 1
            self.limit_age = 0  # every write of the limit restarts the revert timer
            self._retarget()

    def _retarget(self) -> None:
        target = float(self.limit_pct) if self.limit_ena else 100.0
        if target == self.ramp_to:
            return
        self.ramp_from = self.eff_pct
        self.ramp_to = target
        self.ramp_total = self.limit_rmp_s
        self.ramp_left = self.limit_rmp_s
        if self.ramp_total == 0:
            self.eff_pct = target

    # ---- time -----------------------------------------------------------------------------

    def advance(self, seconds: int) -> None:
        for _ in range(seconds):
            self._tick()

    def _tick(self) -> None:
        self.clock = (self.clock + 1) % DAY_S
        self.uptime_s += 1

        # Timers of the remote controls: a command that is not refreshed in time is dropped.
        if self.limit_ena and self.limit_rvrt_s > 0:
            self.limit_age += 1
            if self.limit_age >= self.limit_rvrt_s:
                self.limit_ena = False
                self._retarget()
        if not self.conn and self.conn_rvrt_s > 0:
            self.conn_age += 1
            if self.conn_age >= self.conn_rvrt_s:
                self.conn = True

        if self.ramp_left > 0:
            self.ramp_left -= 1
            self.eff_pct = self.ramp_to - (self.ramp_to - self.ramp_from) * self.ramp_left / self.ramp_total

        # Protections.
        if self.sink_c >= TRIP_C:
            self.over_temp = True
        elif self.sink_c <= RESET_C:
            self.over_temp = False
        events = 0
        if not self.grid_ok:
            events |= EVT_GRID_DISCONNECT
        if self.over_temp:
            events |= EVT_OVER_TEMP
        self.events = events

        available = self.available_dc()
        running = self.state in (ST_MPPT, ST_THROTTLED)
        if events:
            self.state = ST_FAULT
            self.ac_w = 0.0
            self._hold_start(STARTUP_S if self.grid_ok else RECONNECT_S)
        elif not self.conn:
            self.state = ST_STANDBY
            self.ac_w = 0.0
            self._hold_start(STARTUP_S)
        elif running and available >= STOP_W:
            self._produce(available)
        elif not running and available >= START_W:
            if self.startup_left > 0:
                self.startup_left -= 1
                self.state = ST_STARTING
                self.ac_w = 0.0
            else:
                self._produce(available)
        else:
            self.state = ST_SLEEPING
            self.ac_w = 0.0
            self._hold_start(STARTUP_S)

        self._measure(available)
        self.energy_wh += self.ac_w / 3600.0

    def _hold_start(self, seconds: int) -> None:
        if self.startup_left < seconds:
            self.startup_left = seconds

    def _produce(self, available: float) -> None:
        unconstrained = available * EFFICIENCY - SELF_USE_W
        if unconstrained < 0.0:
            unconstrained = 0.0
        if unconstrained > RATED_W:
            unconstrained = RATED_W  # clipping at the nameplate
        limit_w = RATED_W * self.eff_pct / 100.0
        target = limit_w if limit_w < unconstrained else unconstrained
        if target > self.ac_w + RAMP_W_PER_S:
            self.ac_w += RAMP_W_PER_S  # power rises gently and falls at once
        else:
            self.ac_w = target
        self.state = ST_THROTTLED if limit_w < unconstrained else ST_MPPT

    def _measure(self, available: float) -> None:
        self.dc_w = (self.ac_w + SELF_USE_W) / EFFICIENCY if self.ac_w > 0.0 else 0.0
        if available > 0.0:
            used = self.dc_w / available
            if used > 1.0:
                used = 1.0
            self.dc_v = OPEN_V - (OPEN_V - MPP_V) * used
        else:
            self.dc_v = 0.0
        self.dc_a = self.dc_w / self.dc_v if self.dc_v > 0.0 else 0.0
        if self.grid_ok:
            self.ac_v = NOMINAL_V + V_RISE * self.ac_w / RATED_W
            self.hz = NOMINAL_HZ
        else:
            self.ac_v = 0.0
            self.hz = 0.0
        self.ac_a = self.ac_w / self.ac_v if self.ac_v > 0.0 else 0.0
        if self.heat_override_c is not None:
            self.sink_c = self.heat_override_c
        else:
            self.sink_c += (self.ambient_c + RISE_C * self.ac_w / RATED_W - self.sink_c) / TAU_S
        self.cab_c = self.ambient_c + 0.4 * (self.sink_c - self.ambient_c)

    # ---- registers ------------------------------------------------------------------------

    def values(self, unit: int) -> dict[tuple[int, str], Value]:
        """Every implemented SunSpec point as the raw integer or string that goes into the registers."""
        r = round_half_up
        amps = r(self.ac_a * 100.0)
        watts = r(self.ac_w)
        return {
            (1, "Mn"): "QA Portfolio Lab",
            (1, "Md"): "SIM-5000-1P",
            (1, "Opt"): "RIGA-JUNE",
            (1, "Vr"): "1.0.0",
            (1, "SN"): "SIM5K-2026-0001",
            (1, "DA"): unit,
            (101, "A"): amps,
            (101, "AphA"): amps,
            (101, "A_SF"): -2,
            (101, "PhVphA"): r(self.ac_v * 10.0),
            (101, "V_SF"): -1,
            (101, "W"): watts,
            (101, "W_SF"): 0,
            (101, "Hz"): r(self.hz * 100.0),
            (101, "Hz_SF"): -2,
            (101, "VA"): watts,
            (101, "VA_SF"): 0,
            (101, "VAr"): 0,
            (101, "VAr_SF"): 0,
            (101, "PF"): 10000,
            (101, "PF_SF"): -2,
            (101, "WH"): r(self.energy_wh),
            (101, "WH_SF"): 0,
            (101, "DCA"): r(self.dc_a * 100.0),
            (101, "DCA_SF"): -2,
            (101, "DCV"): r(self.dc_v * 10.0),
            (101, "DCV_SF"): -1,
            (101, "DCW"): r(self.dc_w),
            (101, "DCW_SF"): 0,
            (101, "TmpCab"): r(self.cab_c * 10.0),
            (101, "TmpSnk"): r(self.sink_c * 10.0),
            (101, "Tmp_SF"): -1,
            (101, "St"): self.state,
            (101, "Evt1"): self.events,
            (101, "Evt2"): 0,
            (120, "DERTyp"): 4,  # PV
            (120, "WRtg"): r(RATED_W),
            (120, "WRtg_SF"): 0,
            (120, "VARtg"): r(RATED_W),
            (120, "VARtg_SF"): 0,
            (120, "VArRtgQ1"): 0,
            (120, "VArRtgQ2"): 0,
            (120, "VArRtgQ3"): 0,
            (120, "VArRtgQ4"): 0,
            (120, "VArRtg_SF"): 0,
            (120, "ARtg"): RATED_A_X10,
            (120, "ARtg_SF"): -1,
            (120, "PFRtgQ1"): 100,
            (120, "PFRtgQ2"): 100,
            (120, "PFRtgQ3"): 100,
            (120, "PFRtgQ4"): 100,
            (120, "PFRtg_SF"): -2,
            (123, "Conn_WinTms"): 0,
            (123, "Conn_RvrtTms"): self.conn_rvrt_s,
            (123, "Conn"): 1 if self.conn else 0,
            (123, "WMaxLimPct"): self.limit_pct,
            (123, "WMaxLimPct_WinTms"): 0,
            (123, "WMaxLimPct_RvrtTms"): self.limit_rvrt_s,
            (123, "WMaxLimPct_RmpTms"): self.limit_rmp_s,
            (123, "WMaxLim_Ena"): 1 if self.limit_ena else 0,
            (123, "OutPFSet"): 100,
            (123, "OutPFSet_Ena"): 0,
            (123, "VArPct_Ena"): 0,
            (123, "WMaxLimPct_SF"): 0,
            (123, "OutPFSet_SF"): -2,
        }
