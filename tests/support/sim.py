"""The test bench's hands: set the time of day, the weather and the grid through the simulator block.

Everything goes through Modbus registers 100..115, so the same calls work whether the simulator runs
inside the test process, behind a virtual serial port or on another machine at the end of a cable.
"""

from __future__ import annotations

from dataclasses import dataclass

from inverter_lab.client import Master
from inverter_lab.device import (
    HEAT_OFF,
    MAX_ADVANCE_S,
    SIM_ADVANCE,
    SIM_AMBIENT,
    SIM_BASE,
    SIM_CLOCK_MIN,
    SIM_CLOUD,
    SIM_FRAMES_OK,
    SIM_GRID,
    SIM_HEAT,
    SIM_MAGIC,
    SIM_RESET,
    SIM_RESET_KEY,
)
from support.evidence import step


class NotASimulator(Exception):
    """The device at the other end is not the simulator. The tests refuse to steer a real inverter."""


@dataclass(frozen=True)
class Counters:
    frames_ok: int
    crc_errors: int
    framing_errors: int
    exceptions: int
    other_unit: int
    broadcasts: int


def minutes(hhmm: str) -> int:
    hours, _, mins = hhmm.partition(":")
    return int(hours) * 60 + int(mins)


class SimControl:
    def __init__(self, master: Master) -> None:
        self.master = master

    def require_simulator(self) -> None:
        if self.master.read_holding(SIM_BASE, 1) != [SIM_MAGIC]:
            raise NotASimulator("register 100 does not hold the simulator marker")

    def reset(self) -> None:
        self.master.write_register(SIM_BASE + SIM_RESET, SIM_RESET_KEY)

    def set_time(self, hhmm: str) -> None:
        self.master.write_register(SIM_BASE + SIM_CLOCK_MIN, minutes(hhmm))

    def advance(self, seconds: int) -> None:
        """Let simulated time pass."""
        while seconds > 0:
            chunk = min(seconds, MAX_ADVANCE_S)
            self.master.write_register(SIM_BASE + SIM_ADVANCE, chunk)
            seconds -= chunk

    def at(self, hhmm: str, settle: int = 60) -> None:
        """Jump to a time of day and give the inverter ``settle`` seconds to react."""
        with step(f"Set the clock to {hhmm} and wait {settle} s"):
            self.set_time(hhmm)
            self.advance(settle)

    def clouds(self, percent: int) -> None:
        self.master.write_register(SIM_BASE + SIM_CLOUD, percent)

    def ambient(self, celsius: float) -> None:
        self.master.write_register(SIM_BASE + SIM_AMBIENT, round(celsius * 10) & 0xFFFF)

    def grid(self, present: bool) -> None:
        self.master.write_register(SIM_BASE + SIM_GRID, 1 if present else 0)

    def heat_sink(self, celsius: float | None) -> None:
        """Force the heat sink temperature; None lets the thermal model run again."""
        value = HEAT_OFF if celsius is None else round(celsius * 10)
        self.master.write_register(SIM_BASE + SIM_HEAT, value)

    def clock(self) -> int:
        """Seconds since midnight."""
        mins, secs = self.master.read_holding(SIM_BASE + SIM_CLOCK_MIN, 2)
        return mins * 60 + secs

    def counters(self) -> Counters:
        return Counters(*self.master.read_holding(SIM_BASE + SIM_FRAMES_OK, 6))
