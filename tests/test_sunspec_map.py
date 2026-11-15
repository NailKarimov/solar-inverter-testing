"""The register map follows the SunSpec standard, so any SunSpec software can read this inverter."""

from __future__ import annotations

import pytest

from conftest import Rig
from inverter_lab import sunspec
from inverter_lab.sunspec import BASE_ADDRESS, END_MODEL_ID, MODELS, NOT_IMPLEMENTED
from support.evidence import step
from support.official import official_length, official_points

MODEL_IDS = [m.id for m in MODELS]
OUR = {m.id: m for m in MODELS}

# Optional points this inverter does not have: it must say so with the "not implemented" pattern.
ABSENT = {
    101: ["AphB", "AphC", "PPVphAB", "PPVphBC", "PPVphCA", "PhVphB", "PhVphC", "TmpTrns", "TmpOt", "StVnd"],
    120: ["WHRtg", "AhrRtg", "MaxChaRte", "MaxDisChaRte"],
    123: ["OutPFSet_WinTms", "VArWMaxPct", "VArMaxPct", "VArAvalPct", "VArPct_Mod", "VArPct_SF"],
}


@pytest.mark.once
@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_model_layout_equals_the_official_definition(model_id: int) -> None:
    """Every value has the name, position, size, type and scale factor of the official SunSpec model."""
    official = official_points(model_id)
    ours = OUR[model_id].points
    assert [p.name for p in ours] == [p.name for p in official]
    offset = 2
    for mine, theirs in zip(ours, official, strict=True):
        assert (mine.type, mine.size, mine.sf, offset) == (theirs.type, theirs.size, theirs.sf, theirs.offset), (
            f"{model_id}.{mine.name}"
        )
        offset += mine.size
    assert OUR[model_id].length == official_length(model_id)


@pytest.mark.once
@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_only_points_the_standard_allows_are_writable(model_id: int) -> None:
    """The inverter accepts writes only to values the standard marks as writable."""
    allowed = {p.name for p in official_points(model_id) if p.writable}
    writable = {p.name for p in OUR[model_id].points if p.writable}
    assert writable <= allowed


@pytest.mark.once
def test_state_and_event_numbers_equal_the_official_ones() -> None:
    """The state and event codes are the numbers the standard assigns to those names."""
    states = next(p for p in official_points(101) if p.name == "St").symbols
    assert {name: value for value, name in sunspec.STATE_NAMES.items()} == states
    events = next(p for p in official_points(101) if p.name == "Evt1").symbols
    assert 1 << events["GRID_DISCONNECT"] == sunspec.EVT_GRID_DISCONNECT
    assert 1 << events["OVER_TEMP"] == sunspec.EVT_OVER_TEMP


@pytest.mark.smoke
def test_map_starts_with_the_suns_marker(rig: Rig) -> None:
    """Registers 40000 and 40001 spell "SunS": the sign that this device speaks SunSpec."""
    high, low = rig.master.read_holding(BASE_ADDRESS, 2)
    assert (high.to_bytes(2, "big") + low.to_bytes(2, "big")).decode("ascii") == "SunS"


def test_models_form_a_chain_to_the_end_marker(rig: Rig) -> None:
    """Following the lengths from model to model leads through 1, 101, 120 and 123 to the end marker."""
    with step("Walk the chain: read id and length, jump ahead by the length, repeat"):
        found = rig.sunspec.discover()
    assert list(found) == MODEL_IDS
    assert found == {1: 40002, 101: 40070, 120: 40122, 123: 40150}
    end = 40150 + 2 + rig.sunspec.lengths[123]
    assert rig.master.read_holding(end, 2) == [END_MODEL_ID, 0]


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_length_register_equals_the_official_length(rig: Rig, model_id: int) -> None:
    """The length each model announces is the length the standard gives it."""
    rig.sunspec.discover()
    assert rig.sunspec.lengths[model_id] == official_length(model_id)


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_every_mandatory_value_is_present(rig: Rig, model_id: int) -> None:
    """Every value the standard calls mandatory holds real data, not the "not implemented" pattern."""
    rig.sim.at("12:00")
    values = rig.sunspec.model(model_id)
    missing = [p.name for p in official_points(model_id) if p.mandatory and values[p.name] is None]
    assert missing == []


@pytest.mark.parametrize("model_id", sorted(ABSENT))
def test_absent_optional_values_say_not_implemented(rig: Rig, model_id: int) -> None:
    """Optional values this inverter does not have read as "not implemented", never as zero."""
    address = rig.sunspec.discover()[model_id]
    for name in ABSENT[model_id]:
        point = next(p for p in OUR[model_id].points if p.name == name)
        raw = rig.master.read_holding(rig.sunspec.address_of(model_id, name), point.size)
        assert raw == [NOT_IMPLEMENTED[point.type]], f"{model_id}.{name} at {address}"


def test_common_model_names_the_device(rig: Rig) -> None:
    """The first model says who made the device, which model it is and its serial number."""
    common = rig.sunspec.model(1)
    assert common["Mn"] == "QA Portfolio Lab"
    assert common["Md"] == "SIM-5000-1P"
    assert common["Vr"] == "1.0.0"
    assert common["SN"] == "SIM5K-2026-0001"
    assert common["DA"] == rig.station.unit


def test_nameplate_states_the_ratings(rig: Rig) -> None:
    """The nameplate model says it is a 5 kW solar inverter rated for 21.7 A."""
    plate = rig.sunspec.measurements(120)
    assert plate["DERTyp"] == 4  # PV
    assert plate["WRtg"] == 5000.0
    assert plate["VARtg"] == 5000.0
    assert plate["ARtg"] == 21.7
    assert [plate[f"PFRtgQ{q}"] for q in (1, 2, 3, 4)] == [1.0] * 4


def test_scale_factors_are_small_constants(rig: Rig) -> None:
    """Scale factors stay between -10 and 10 and do not change while the inverter runs."""
    rig.sim.at("03:00")
    night = {k: v for k, v in rig.sunspec.model(101).items() if k.endswith("_SF")}
    rig.sim.at("12:00")
    noon = {k: v for k, v in rig.sunspec.model(101).items() if k.endswith("_SF")}
    assert night == noon
    assert all(isinstance(v, int) and -10 <= v <= 10 for v in noon.values())


def test_whole_map_read_in_blocks_equals_single_register_reads(rig: Rig) -> None:
    """Reading the map in two big blocks gives the same registers as reading them one by one."""
    rig.sim.at("12:00")
    size = rig.station.device.layout.size if rig.station.device else 178
    with step("Read the map in two blocks of at most 125 registers"):
        blocks = rig.master.read_holding(BASE_ADDRESS, 125) + rig.master.read_holding(BASE_ADDRESS + 125, size - 125)
    with step("Read every register on its own"):
        singles = [rig.master.read_holding(BASE_ADDRESS + i, 1)[0] for i in range(size)]
    assert blocks == singles


def test_input_registers_mirror_holding_registers(rig: Rig) -> None:
    """Function 04 (input registers) returns the same data as function 03 (holding registers)."""
    rig.sim.at("12:00")
    address = rig.sunspec.discover()[101]
    assert rig.master.read_input(address, 52) == rig.master.read_holding(address, 52)
