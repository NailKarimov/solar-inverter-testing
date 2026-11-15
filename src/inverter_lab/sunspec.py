"""The SunSpec register map of the simulated inverter, written by hand from the SunSpec specification.

A SunSpec device starts with the marker ``SunS`` at register 40000, followed by a chain of models.
Each model begins with its id and its length; the chain ends with id 0xFFFF. A client that has never
seen this device can walk the chain and read every value.

Models of this device:

- 1    Common: manufacturer, model, version, serial number
- 101  Single phase inverter: current, voltage, power, energy, temperatures, state, events
- 120  Nameplate: ratings
- 123  Immediate controls: connect or disconnect, limit the output power

The tests compare this file with the official model definitions shipped with pysunspec2.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

BASE_ADDRESS = 40000
MARKER = (0x5375, 0x6E53)  # "Su", "nS"
END_MODEL_ID = 0xFFFF

# Values that mean "this point is not implemented", by type.
NOT_IMPLEMENTED: dict[str, int] = {
    "uint16": 0xFFFF,
    "int16": 0x8000,
    "enum16": 0xFFFF,
    "sunssf": 0x8000,
    "pad": 0x8000,
    "acc32": 0x00000000,
    "uint32": 0xFFFFFFFF,
    "bitfield32": 0xFFFFFFFF,
}
TYPE_SIZE = {"uint16": 1, "int16": 1, "enum16": 1, "sunssf": 1, "pad": 1, "acc32": 2, "uint32": 2, "bitfield32": 2}
SIGNED = ("int16", "sunssf")

Value = int | float | str | None


@dataclass(frozen=True)
class Point:
    """One value of a model: its name, type, size in registers and scale factor point."""

    name: str
    type: str
    size: int = 1
    sf: str | None = None
    writable: bool = False
    units: str = ""
    label: str = ""


@dataclass(frozen=True)
class Model:
    id: int
    name: str
    label: str
    points: tuple[Point, ...]

    @property
    def length(self) -> int:
        """Registers after the id and the length, as stored in the ``L`` register."""
        return sum(p.size for p in self.points)


def _p(
    name: str,
    type_: str,
    label: str,
    *,
    size: int | None = None,
    sf: str | None = None,
    w: bool = False,
    units: str = "",
) -> Point:
    return Point(name, type_, size if size is not None else TYPE_SIZE[type_], sf, w, units, label)


COMMON = Model(
    1,
    "common",
    "Common",
    (
        _p("Mn", "string", "Manufacturer", size=16),
        _p("Md", "string", "Model", size=16),
        _p("Opt", "string", "Options", size=8),
        _p("Vr", "string", "Version", size=8),
        _p("SN", "string", "Serial number", size=16),
        _p("DA", "uint16", "Device address"),
        _p("Pad", "pad", "Padding"),
    ),
)

INVERTER = Model(
    101,
    "inverter_single_phase",
    "Inverter (single phase)",
    (
        _p("A", "uint16", "AC current", sf="A_SF", units="A"),
        _p("AphA", "uint16", "Phase A current", sf="A_SF", units="A"),
        _p("AphB", "uint16", "Phase B current", sf="A_SF", units="A"),
        _p("AphC", "uint16", "Phase C current", sf="A_SF", units="A"),
        _p("A_SF", "sunssf", "Current scale factor"),
        _p("PPVphAB", "uint16", "Phase voltage AB", sf="V_SF", units="V"),
        _p("PPVphBC", "uint16", "Phase voltage BC", sf="V_SF", units="V"),
        _p("PPVphCA", "uint16", "Phase voltage CA", sf="V_SF", units="V"),
        _p("PhVphA", "uint16", "AC voltage", sf="V_SF", units="V"),
        _p("PhVphB", "uint16", "Phase voltage BN", sf="V_SF", units="V"),
        _p("PhVphC", "uint16", "Phase voltage CN", sf="V_SF", units="V"),
        _p("V_SF", "sunssf", "Voltage scale factor"),
        _p("W", "int16", "AC power", sf="W_SF", units="W"),
        _p("W_SF", "sunssf", "Power scale factor"),
        _p("Hz", "uint16", "Grid frequency", sf="Hz_SF", units="Hz"),
        _p("Hz_SF", "sunssf", "Frequency scale factor"),
        _p("VA", "int16", "Apparent power", sf="VA_SF", units="VA"),
        _p("VA_SF", "sunssf", "Apparent power scale factor"),
        _p("VAr", "int16", "Reactive power", sf="VAr_SF", units="var"),
        _p("VAr_SF", "sunssf", "Reactive power scale factor"),
        _p("PF", "int16", "Power factor", sf="PF_SF", units="%"),
        _p("PF_SF", "sunssf", "Power factor scale factor"),
        _p("WH", "acc32", "Lifetime energy", sf="WH_SF", units="Wh"),
        _p("WH_SF", "sunssf", "Energy scale factor"),
        _p("DCA", "uint16", "DC current", sf="DCA_SF", units="A"),
        _p("DCA_SF", "sunssf", "DC current scale factor"),
        _p("DCV", "uint16", "DC voltage", sf="DCV_SF", units="V"),
        _p("DCV_SF", "sunssf", "DC voltage scale factor"),
        _p("DCW", "int16", "DC power", sf="DCW_SF", units="W"),
        _p("DCW_SF", "sunssf", "DC power scale factor"),
        _p("TmpCab", "int16", "Cabinet temperature", sf="Tmp_SF", units="C"),
        _p("TmpSnk", "int16", "Heat sink temperature", sf="Tmp_SF", units="C"),
        _p("TmpTrns", "int16", "Transformer temperature", sf="Tmp_SF", units="C"),
        _p("TmpOt", "int16", "Other temperature", sf="Tmp_SF", units="C"),
        _p("Tmp_SF", "sunssf", "Temperature scale factor"),
        _p("St", "enum16", "Operating state"),
        _p("StVnd", "enum16", "Vendor operating state"),
        _p("Evt1", "bitfield32", "Events"),
        _p("Evt2", "bitfield32", "Events 2"),
        _p("EvtVnd1", "bitfield32", "Vendor events 1"),
        _p("EvtVnd2", "bitfield32", "Vendor events 2"),
        _p("EvtVnd3", "bitfield32", "Vendor events 3"),
        _p("EvtVnd4", "bitfield32", "Vendor events 4"),
    ),
)

NAMEPLATE = Model(
    120,
    "nameplate",
    "Nameplate ratings",
    (
        _p("DERTyp", "enum16", "Type of device"),
        _p("WRtg", "uint16", "Rated power", sf="WRtg_SF", units="W"),
        _p("WRtg_SF", "sunssf", "Rated power scale factor"),
        _p("VARtg", "uint16", "Rated apparent power", sf="VARtg_SF", units="VA"),
        _p("VARtg_SF", "sunssf", "Rated apparent power scale factor"),
        _p("VArRtgQ1", "int16", "Rated reactive power Q1", sf="VArRtg_SF", units="var"),
        _p("VArRtgQ2", "int16", "Rated reactive power Q2", sf="VArRtg_SF", units="var"),
        _p("VArRtgQ3", "int16", "Rated reactive power Q3", sf="VArRtg_SF", units="var"),
        _p("VArRtgQ4", "int16", "Rated reactive power Q4", sf="VArRtg_SF", units="var"),
        _p("VArRtg_SF", "sunssf", "Rated reactive power scale factor"),
        _p("ARtg", "uint16", "Rated current", sf="ARtg_SF", units="A"),
        _p("ARtg_SF", "sunssf", "Rated current scale factor"),
        _p("PFRtgQ1", "int16", "Minimum power factor Q1", sf="PFRtg_SF", units="cos()"),
        _p("PFRtgQ2", "int16", "Minimum power factor Q2", sf="PFRtg_SF", units="cos()"),
        _p("PFRtgQ3", "int16", "Minimum power factor Q3", sf="PFRtg_SF", units="cos()"),
        _p("PFRtgQ4", "int16", "Minimum power factor Q4", sf="PFRtg_SF", units="cos()"),
        _p("PFRtg_SF", "sunssf", "Power factor scale factor"),
        _p("WHRtg", "uint16", "Storage capacity", sf="WHRtg_SF", units="Wh"),
        _p("WHRtg_SF", "sunssf", "Storage capacity scale factor"),
        _p("AhrRtg", "uint16", "Storage capacity", sf="AhrRtg_SF", units="AH"),
        _p("AhrRtg_SF", "sunssf", "Storage capacity scale factor"),
        _p("MaxChaRte", "uint16", "Maximum charge rate", sf="MaxChaRte_SF", units="W"),
        _p("MaxChaRte_SF", "sunssf", "Charge rate scale factor"),
        _p("MaxDisChaRte", "uint16", "Maximum discharge rate", sf="MaxDisChaRte_SF", units="W"),
        _p("MaxDisChaRte_SF", "sunssf", "Discharge rate scale factor"),
        _p("Pad", "pad", "Padding"),
    ),
)

CONTROLS = Model(
    123,
    "controls",
    "Immediate controls",
    (
        _p("Conn_WinTms", "uint16", "Connect: random delay window", w=True, units="s"),
        _p("Conn_RvrtTms", "uint16", "Connect: revert timeout", w=True, units="s"),
        _p("Conn", "enum16", "Connect or disconnect", w=True),
        _p("WMaxLimPct", "uint16", "Power limit", sf="WMaxLimPct_SF", w=True, units="%"),
        _p("WMaxLimPct_WinTms", "uint16", "Power limit: random delay window", w=True, units="s"),
        _p("WMaxLimPct_RvrtTms", "uint16", "Power limit: revert timeout", w=True, units="s"),
        _p("WMaxLimPct_RmpTms", "uint16", "Power limit: ramp time", w=True, units="s"),
        _p("WMaxLim_Ena", "enum16", "Power limit enabled", w=True),
        _p("OutPFSet", "int16", "Power factor set point", sf="OutPFSet_SF", units="cos()"),
        _p("OutPFSet_WinTms", "uint16", "Power factor: random delay window", units="s"),
        _p("OutPFSet_RvrtTms", "uint16", "Power factor: revert timeout", units="s"),
        _p("OutPFSet_RmpTms", "uint16", "Power factor: ramp time", units="s"),
        _p("OutPFSet_Ena", "enum16", "Power factor control enabled", w=True),
        _p("VArWMaxPct", "int16", "Reactive power, % of rated power", sf="VArPct_SF", units="%"),
        _p("VArMaxPct", "int16", "Reactive power, % of maximum", sf="VArPct_SF", units="%"),
        _p("VArAvalPct", "int16", "Reactive power, % of available", sf="VArPct_SF", units="%"),
        _p("VArPct_WinTms", "uint16", "Reactive power: random delay window", units="s"),
        _p("VArPct_RvrtTms", "uint16", "Reactive power: revert timeout", units="s"),
        _p("VArPct_RmpTms", "uint16", "Reactive power: ramp time", units="s"),
        _p("VArPct_Mod", "enum16", "Reactive power mode"),
        _p("VArPct_Ena", "enum16", "Reactive power control enabled", w=True),
        _p("WMaxLimPct_SF", "sunssf", "Power limit scale factor"),
        _p("OutPFSet_SF", "sunssf", "Power factor scale factor"),
        _p("VArPct_SF", "sunssf", "Reactive power scale factor"),
    ),
)

MODELS: tuple[Model, ...] = (COMMON, INVERTER, NAMEPLATE, CONTROLS)

# Operating states (model 101, point St) and event bits (point Evt1).
ST_OFF, ST_SLEEPING, ST_STARTING, ST_MPPT, ST_THROTTLED, ST_SHUTTING_DOWN, ST_FAULT, ST_STANDBY = range(1, 9)
STATE_NAMES = {
    ST_OFF: "OFF",
    ST_SLEEPING: "SLEEPING",
    ST_STARTING: "STARTING",
    ST_MPPT: "MPPT",
    ST_THROTTLED: "THROTTLED",
    ST_SHUTTING_DOWN: "SHUTTING_DOWN",
    ST_FAULT: "FAULT",
    ST_STANDBY: "STANDBY",
}
EVT_GRID_DISCONNECT = 1 << 4
EVT_OVER_TEMP = 1 << 7
EVENT_NAMES = {EVT_GRID_DISCONNECT: "GRID_DISCONNECT", EVT_OVER_TEMP: "OVER_TEMP"}


@dataclass(frozen=True)
class Entry:
    """A point placed in the address space."""

    address: int
    model: Model
    point: Point


class Layout:
    """Where every register of the SunSpec block lives: marker, model headers, points, end marker."""

    def __init__(self, models: Sequence[Model] = MODELS, base: int = BASE_ADDRESS) -> None:
        self.base = base
        self.models = tuple(models)
        self.entries: list[Entry] = []
        self.model_address: dict[int, int] = {}
        address = base + len(MARKER)
        for model in self.models:
            self.model_address[model.id] = address
            address += 2  # id and length
            for point in model.points:
                self.entries.append(Entry(address, model, point))
                address += point.size
        self.end_address = address
        self.size = address + 2 - base  # the end marker takes two registers
        self._by_name = {(e.model.id, e.point.name): e for e in self.entries}
        self._by_address: dict[int, Entry] = {}
        for entry in self.entries:
            for offset in range(entry.point.size):
                self._by_address[entry.address + offset] = entry

    def entry(self, model_id: int, name: str) -> Entry:
        return self._by_name[(model_id, name)]

    def at(self, address: int) -> Entry | None:
        """The point that owns ``address``; None for the marker, the headers and the end marker."""
        return self._by_address.get(address)

    def contains(self, address: int, count: int) -> bool:
        return self.base <= address and address + count <= self.base + self.size

    def image(self, values: Mapping[tuple[int, str], Value]) -> list[int]:
        """All registers of the block, built from ``values`` keyed by (model id, point name)."""
        registers = list(MARKER)
        for model in self.models:
            registers += [model.id, model.length]
            for point in model.points:
                registers += encode(point, values.get((model.id, point.name)))
        registers += [END_MODEL_ID, 0]
        return registers


def round_half_up(value: float) -> int:
    """Round to the nearest integer, halves up. The JavaScript twin uses the same rule."""
    return math.floor(value + 0.5)


def encode(point: Point, value: Value) -> list[int]:
    """Registers that hold ``value``. None becomes the "not implemented" pattern of the type."""
    if point.type == "string":
        raw = b"" if value is None else str(value).encode("ascii")
        raw = raw[: 2 * point.size].ljust(2 * point.size, b"\x00")
        return [int.from_bytes(raw[i : i + 2], "big") for i in range(0, len(raw), 2)]
    if value is None:
        number = NOT_IMPLEMENTED[point.type]
    else:
        number = int(value)
        if point.type in SIGNED:
            number &= 0xFFFF
    if point.size == 2:
        return [(number >> 16) & 0xFFFF, number & 0xFFFF]
    return [number & 0xFFFF]


def decode(point: Point, registers: Sequence[int]) -> Value:
    """The value held by ``registers``; None if the point is not implemented."""
    if point.type == "string":
        raw = b"".join(r.to_bytes(2, "big") for r in registers)
        return raw.split(b"\x00", 1)[0].decode("ascii")
    number = (registers[0] << 16 | registers[1]) if point.size == 2 else registers[0]
    if number == NOT_IMPLEMENTED[point.type] and point.type != "acc32":
        return None
    if point.type in SIGNED and number >= 0x8000:
        number -= 0x10000
    return number


def scaled(raw: int, scale_factor: int) -> float:
    """A raw register value in real units: raw x 10^scale_factor."""
    return float(raw * 10**scale_factor) if scale_factor >= 0 else raw / 10**-scale_factor
