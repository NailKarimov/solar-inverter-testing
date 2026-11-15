"""The device as the bus sees it: registers that can be read and written, and the answers to requests.

Two blocks of holding registers exist:

- 40000..40175  the SunSpec map (see ``sunspec.py``)
- 100..115      the simulator block: the test bench sets the time of day, the clouds, the grid and
                the temperature here, and reads the diagnostic counters

Everything else answers with exception 02 (illegal data address).
"""

from __future__ import annotations

import struct
import threading
from collections.abc import Callable
from dataclasses import dataclass, fields

from inverter_lab.inverter import DAY_S, Inverter
from inverter_lab.pdu import (
    ERROR_FLAG,
    MAX_READ,
    MAX_WRITE,
    READ_FUNCTIONS,
    ExceptionCode,
    Function,
    exception_response,
)
from inverter_lab.sunspec import Layout, round_half_up

SIM_BASE = 100
SIM_MAGIC = 0x51A1
SIM_RESET_KEY = 0xC0DE
HEAT_OFF = 0x8000
MAX_ADVANCE_S = 43200  # twelve hours in one command

# Offsets inside the simulator block.
(
    SIM_ID,
    SIM_CLOCK_MIN,
    SIM_CLOCK_SEC,
    SIM_ADVANCE,
    SIM_CLOUD,
    SIM_AMBIENT,
    SIM_GRID,
    SIM_HEAT,
    SIM_TIME_SCALE,
    SIM_RESET,
    SIM_FRAMES_OK,
    SIM_CRC_ERRORS,
    SIM_FRAMING_ERRORS,
    SIM_EXCEPTIONS,
    SIM_OTHER_UNIT,
    SIM_BROADCASTS,
) = range(16)
SIM_SIZE = 16

# Inclusive ranges of the values a write may carry, for every writable SunSpec point.
CONTROL_RANGES: dict[str, tuple[int, int]] = {
    "Conn_WinTms": (0, 0),  # random delay windows are not simulated: only 0 is accepted
    "Conn_RvrtTms": (0, 3600),
    "Conn": (0, 1),
    "WMaxLimPct": (0, 100),
    "WMaxLimPct_WinTms": (0, 0),
    "WMaxLimPct_RvrtTms": (0, 3600),
    "WMaxLimPct_RmpTms": (0, 600),
    "WMaxLim_Ena": (0, 1),
    "OutPFSet_Ena": (0, 0),  # power factor and reactive power controls are not available
    "VArPct_Ena": (0, 0),
}


class IllegalAddress(Exception):
    """The request touches a register that does not exist or cannot be written."""


class IllegalValue(Exception):
    """The request is well formed but carries a value the device does not accept."""


@dataclass
class Diagnostics:
    """Counters of what the device saw on the bus, readable at 110..115."""

    frames_ok: int = 0
    crc_errors: int = 0
    framing_errors: int = 0
    exceptions: int = 0
    other_unit: int = 0
    broadcasts: int = 0

    def clear(self) -> None:
        for field in fields(self):
            setattr(self, field.name, 0)


def _signed(value: int) -> int:
    return value - 0x10000 if value >= 0x8000 else value


def _in_sim_block(address: int, count: int) -> bool:
    return address >= SIM_BASE and address + count <= SIM_BASE + SIM_SIZE


class InverterDevice:
    def __init__(self, unit: int = 1) -> None:
        self.unit = unit
        self.inverter = Inverter()
        self.layout = Layout()
        self.diag = Diagnostics()
        self.time_scale = 0  # simulated seconds per real second; 0 means the clock moves only on command
        self.lock = threading.RLock()

    # ---- registers ------------------------------------------------------------------------

    def read(self, address: int, count: int) -> list[int]:
        if self.layout.contains(address, count):
            image = self.layout.image(self.inverter.values(self.unit))
            start = address - self.layout.base
            return image[start : start + count]
        if _in_sim_block(address, count):
            start = address - SIM_BASE
            return self._sim_image()[start : start + count]
        raise IllegalAddress(address)

    def write(self, address: int, values: list[int]) -> None:
        """All or nothing: every register is checked before the first one changes."""
        if self.layout.contains(address, len(values)):
            self._write_controls(address, values)
        elif _in_sim_block(address, len(values)):
            self._write_sim(address - SIM_BASE, values)
        else:
            raise IllegalAddress(address)

    def _write_controls(self, address: int, values: list[int]) -> None:
        changes: dict[str, int] = {}
        for offset, value in enumerate(values):
            entry = self.layout.at(address + offset)
            if entry is None or not entry.point.writable:
                raise IllegalAddress(address + offset)
            changes[entry.point.name] = value
        for name, value in changes.items():
            low, high = CONTROL_RANGES[name]
            if not low <= value <= high:
                raise IllegalValue(name)
        self.inverter.write_controls(changes)

    def _sim_image(self) -> list[int]:
        inv = self.inverter
        heat = HEAT_OFF if inv.heat_override_c is None else round_half_up(inv.heat_override_c * 10.0) & 0xFFFF
        d = self.diag
        return [
            SIM_MAGIC,
            inv.clock // 60,
            inv.clock % 60,
            0,
            inv.cloud_pct,
            round_half_up(inv.ambient_c * 10.0) & 0xFFFF,
            1 if inv.grid_ok else 0,
            heat,
            self.time_scale,
            0,
            d.frames_ok & 0xFFFF,
            d.crc_errors & 0xFFFF,
            d.framing_errors & 0xFFFF,
            d.exceptions & 0xFFFF,
            d.other_unit & 0xFFFF,
            d.broadcasts & 0xFFFF,
        ]

    def _write_sim(self, start: int, values: list[int]) -> None:
        checks: dict[int, Callable[[int], bool]] = {
            SIM_CLOCK_MIN: lambda v: 0 <= v < DAY_S // 60,
            SIM_ADVANCE: lambda v: 1 <= v <= MAX_ADVANCE_S,
            SIM_CLOUD: lambda v: 0 <= v <= 100,
            SIM_AMBIENT: lambda v: -400 <= _signed(v) <= 700,
            SIM_GRID: lambda v: v in (0, 1),
            SIM_HEAT: lambda v: v == HEAT_OFF or 0 <= v <= 1500,
            SIM_TIME_SCALE: lambda v: 0 <= v <= 3600,
            SIM_RESET: lambda v: v == SIM_RESET_KEY,
        }
        for offset, value in enumerate(values, start):
            if offset not in checks:
                raise IllegalAddress(SIM_BASE + offset)  # read-only register
            if not checks[offset](value):
                raise IllegalValue(SIM_BASE + offset)
        inv = self.inverter
        for offset, value in enumerate(values, start):
            if offset == SIM_CLOCK_MIN:
                inv.clock = value * 60
            elif offset == SIM_ADVANCE:
                inv.advance(value)
            elif offset == SIM_CLOUD:
                inv.cloud_pct = value
            elif offset == SIM_AMBIENT:
                inv.ambient_c = _signed(value) / 10.0
            elif offset == SIM_GRID:
                inv.grid_ok = value == 1
            elif offset == SIM_HEAT:
                inv.heat_override_c = None if value == HEAT_OFF else value / 10.0
            elif offset == SIM_TIME_SCALE:
                self.time_scale = value
            elif offset == SIM_RESET:
                inv.reset()
                self.diag.clear()
                self.time_scale = 0

    # ---- requests -------------------------------------------------------------------------

    def respond(self, pdu: bytes) -> bytes:
        """The response PDU for a request PDU. Never raises: a failure becomes an exception response."""
        with self.lock:
            response = self._handle(pdu)
            self.diag.frames_ok += 1
            if response[0] & ERROR_FLAG:
                self.diag.exceptions += 1
            return response

    def _handle(self, pdu: bytes) -> bytes:
        function = pdu[0]
        try:
            if function in READ_FUNCTIONS:
                if len(pdu) != 5:
                    raise IllegalValue(pdu)
                address, count = struct.unpack(">HH", pdu[1:])
                if not 1 <= count <= MAX_READ:
                    raise IllegalValue(count)
                registers = self.read(address, count)
                return bytes([function, 2 * count]) + struct.pack(f">{count}H", *registers)
            if function == Function.WRITE_SINGLE:
                if len(pdu) != 5:
                    raise IllegalValue(pdu)
                address, value = struct.unpack(">HH", pdu[1:])
                self.write(address, [value])
                return pdu
            if function == Function.WRITE_MULTIPLE:
                if len(pdu) < 6:
                    raise IllegalValue(pdu)
                address, count, size = struct.unpack(">HHB", pdu[1:6])
                if not 1 <= count <= MAX_WRITE or size != 2 * count or len(pdu) != 6 + size:
                    raise IllegalValue(count)
                self.write(address, list(struct.unpack(f">{count}H", pdu[6:])))
                return pdu[:5]
            return exception_response(function, ExceptionCode.ILLEGAL_FUNCTION)
        except IllegalAddress:
            return exception_response(function, ExceptionCode.ILLEGAL_DATA_ADDRESS)
        except IllegalValue:
            return exception_response(function, ExceptionCode.ILLEGAL_DATA_VALUE)
        except Exception:  # a bug in the device must not take the bus down
            return exception_response(function, ExceptionCode.SERVER_DEVICE_FAILURE)

    def tick_real_time(self, real_seconds: float, carry: float) -> float:
        """Advance the clock by ``time_scale`` simulated seconds per real second. Returns the remainder."""
        with self.lock:
            total = carry + real_seconds * self.time_scale
            whole = int(total)
            if whole:
                self.inverter.advance(whole)
            return total - whole
