"""Read a SunSpec device the way a monitoring system does: find the models, then read values by name.

``SunSpecReader(master).discover()`` returns where each model starts, for this inverter
``{1: 40002, 101: 40070, 120: 40122, 123: 40150}``. ``get(101, "W")`` then returns the AC power in watts,
already multiplied by its scale factor, and ``set(123, "WMaxLimPct", 50)`` writes a 50 % power limit.
"""

from __future__ import annotations

from collections.abc import Sequence

from inverter_lab.client import Master
from inverter_lab.sunspec import BASE_ADDRESS, END_MODEL_ID, MARKER, MODELS, Model, Value, decode, scaled

KNOWN_MODELS = {model.id: model for model in MODELS}


class NotSunSpec(Exception):
    """The device does not start with the SunS marker."""


class SunSpecReader:
    def __init__(self, master: Master, base: int = BASE_ADDRESS) -> None:
        self.master = master
        self.base = base
        self.addresses: dict[int, int] = {}  # model id -> address of its ID register
        self.lengths: dict[int, int] = {}

    def discover(self) -> dict[int, int]:
        """Walk the chain of models from the marker to the end model."""
        if tuple(self.master.read_holding(self.base, 2)) != MARKER:
            raise NotSunSpec(f"no SunS marker at {self.base}")
        self.addresses, self.lengths = {}, {}
        address = self.base + 2
        while True:
            model_id, length = self.master.read_holding(address, 2)
            if model_id == END_MODEL_ID:
                return self.addresses
            self.addresses[model_id] = address
            self.lengths[model_id] = length
            address += 2 + length

    def _model(self, model_id: int) -> tuple[Model, int]:
        if not self.addresses:
            self.discover()
        return KNOWN_MODELS[model_id], self.addresses[model_id]

    def model(self, model_id: int) -> dict[str, Value]:
        """Every point of a model as stored: integers not yet scaled, strings, None if not implemented."""
        model, address = self._model(model_id)
        registers = self.master.read_holding(address + 2, model.length)
        values: dict[str, Value] = {}
        offset = 0
        for point in model.points:
            values[point.name] = decode(point, registers[offset : offset + point.size])
            offset += point.size
        return values

    def measurements(self, model_id: int) -> dict[str, Value]:
        """Every point of a model in real units: scale factors applied."""
        raw = self.model(model_id)
        result: dict[str, Value] = {}
        for point in KNOWN_MODELS[model_id].points:
            value = raw[point.name]
            factor = raw.get(point.sf) if point.sf else None
            if isinstance(value, int) and isinstance(factor, int):
                result[point.name] = scaled(value, factor)
            else:
                result[point.name] = value
        return result

    def get(self, model_id: int, name: str) -> Value:
        return self.measurements(model_id)[name]

    def number(self, model_id: int, name: str) -> float:
        """A numeric point in real units. Fails if the point is not implemented or is a string."""
        value = self.get(model_id, name)
        if not isinstance(value, int | float):
            raise ValueError(f"{model_id}.{name} is {value!r}, not a number")
        return float(value)

    def address_of(self, model_id: int, name: str) -> int:
        model, address = self._model(model_id)
        offset = 2
        for point in model.points:
            if point.name == name:
                return address + offset
            offset += point.size
        raise KeyError(name)

    def set(self, model_id: int, name: str, value: int) -> None:
        """Write one point with function 06."""
        self.master.write_register(self.address_of(model_id, name), value & 0xFFFF)

    def set_many(self, model_id: int, first: str, values: Sequence[int]) -> None:
        """Write consecutive points in one request (function 16), starting at ``first``."""
        self.master.write_registers(self.address_of(model_id, first), [v & 0xFFFF for v in values])
