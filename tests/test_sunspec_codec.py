"""How numbers and text are packed into 16-bit registers, and where each value lives in the map."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from inverter_lab import sunspec
from inverter_lab.sunspec import MODELS, Layout, Point, decode, encode, scaled

pytestmark = pytest.mark.once


@pytest.mark.parametrize(
    ("type_", "value", "registers"),
    [
        ("uint16", 5000, [0x1388]),
        ("int16", -2, [0xFFFE]),
        ("sunssf", -1, [0xFFFF]),
        ("enum16", 4, [0x0004]),
        ("acc32", 1_234_567, [0x0012, 0xD687]),
        ("bitfield32", 1 << 7 | 1 << 4, [0x0000, 0x0090]),
    ],
    ids=["uint16", "int16-negative", "scale-factor", "enum", "acc32-two-registers", "bitfield32"],
)
def test_numbers_are_stored_big_endian(type_: str, value: int, registers: list[int]) -> None:
    """Numbers go into registers high part first; negative numbers use two's complement."""
    point = Point("X", type_, sunspec.TYPE_SIZE[type_])
    assert encode(point, value) == registers
    assert decode(point, registers) == value


def test_text_is_stored_two_characters_per_register_and_padded() -> None:
    """Text takes two characters per register and the unused rest is filled with zero bytes."""
    point = Point("Md", "string", 4)
    assert encode(point, "SIM") == [0x5349, 0x4D00, 0x0000, 0x0000]
    assert decode(point, [0x5349, 0x4D00, 0x0000, 0x0000]) == "SIM"


@given(st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), max_size=32))
def test_text_round_trip(text: str) -> None:
    """Any printable text of up to 32 characters survives the trip through 16 registers."""
    point = Point("Mn", "string", 16)
    registers = encode(point, text)
    assert len(registers) == 16
    assert decode(point, registers) == text


@pytest.mark.parametrize(
    ("type_", "pattern"),
    [
        ("uint16", [0xFFFF]),
        ("int16", [0x8000]),
        ("enum16", [0xFFFF]),
        ("sunssf", [0x8000]),
        ("pad", [0x8000]),
        ("bitfield32", [0xFFFF, 0xFFFF]),
    ],
)
def test_missing_values_use_the_not_implemented_pattern(type_: str, pattern: list[int]) -> None:
    """A value the device does not have is stored as the agreed pattern and is read back as "no value"."""
    point = Point("X", type_, sunspec.TYPE_SIZE[type_])
    assert encode(point, None) == pattern
    assert decode(point, pattern) is None


@pytest.mark.parametrize(
    ("raw", "factor", "real"),
    [(2137, -2, 21.37), (2340, -1, 234.0), (5000, 0, 5000.0), (5, 3, 5000.0), (-125, -1, -12.5)],
)
def test_scale_factor_moves_the_decimal_point(raw: int, factor: int, real: float) -> None:
    """A scale factor of -2 means two decimal places: the register value 2137 reads 21.37."""
    assert scaled(raw, factor) == real


@given(st.integers(-0x8000, 0x7FFF))
def test_signed_round_trip(value: int) -> None:
    """Every signed 16-bit number except the reserved pattern survives the trip through a register."""
    point = Point("W", "int16")
    expected = None if value == -0x8000 else value
    assert decode(point, encode(point, value)) == expected


def test_map_has_no_gaps_and_no_overlaps() -> None:
    """Every register between the marker and the end marker belongs to exactly one value."""
    layout = Layout()
    address = layout.base + 2
    for model in MODELS:
        assert layout.model_address[model.id] == address
        address += 2
        for point in model.points:
            entry = layout.entry(model.id, point.name)
            assert entry.address == address, f"{model.id}.{point.name}"
            assert all(layout.at(address + i) is entry for i in range(point.size))
            address += point.size
    assert address == layout.end_address
    assert layout.size == 178


def test_scale_factors_point_at_real_scale_factor_points() -> None:
    """Every value that needs a scale factor names one that exists in the same model."""
    for model in MODELS:
        by_name = {p.name: p for p in model.points}
        for point in model.points:
            if point.sf is not None:
                assert by_name[point.sf].type == "sunssf", f"{model.id}.{point.name} -> {point.sf}"
