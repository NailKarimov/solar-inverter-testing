"""Second opinion: the SunSpec Alliance's own Python client discovers and controls the inverter."""

from __future__ import annotations

import struct
from collections.abc import Iterator
from typing import Any

import pytest
import sunspec2.modbus.client as sunspec_client
from sunspec2.modbus.modbus import ModbusClientException

from conftest import TIMEOUT, Station
from inverter_lab.client import RtuMaster, TcpMaster
from inverter_lab.device import SIM_ADVANCE, SIM_BASE, SIM_CLOCK_MIN
from inverter_lab.links import open_serial, open_tcp
from inverter_lab.reader import SunSpecReader
from inverter_lab.sunspec import Value
from support import datasheet as ds
from support.evidence import TapLink, step, trace_sunspec
from support.official import official_points

pytestmark = pytest.mark.port

MODEL_IDS = [1, 101, 120, 123]


def own_measurements(station: Station, model_id: int) -> dict[str, Value]:
    """The same model read by this project's own client, on a connection of its own."""
    if station.tcp is not None:
        link = TapLink(open_tcp(*station.tcp))
        master: RtuMaster | TcpMaster = TcpMaster(link, station.unit, TIMEOUT)
    else:
        link = TapLink(open_serial(f"{station.serial_port}?baud={station.baud}"))
        master = RtuMaster(link, station.unit, TIMEOUT)
    try:
        return SunSpecReader(master).measurements(model_id)
    finally:
        link.close()


def connect(station: Station) -> Any:
    if station.tcp is not None:
        host, port = station.tcp
        return sunspec_client.SunSpecModbusClientDeviceTCP(
            slave_id=station.unit, ipaddr=host, ipport=port, timeout=TIMEOUT, trace_func=trace_sunspec
        )
    return sunspec_client.SunSpecModbusClientDeviceRTU(
        slave_id=station.unit,
        name=station.serial_port,
        baudrate=station.baud,
        timeout=TIMEOUT,
        trace_func=trace_sunspec,
    )


def set_noon(device: Any) -> None:
    device.write(SIM_BASE + SIM_CLOCK_MIN, struct.pack(">H", 720))
    device.write(SIM_BASE + SIM_ADVANCE, struct.pack(">H", 60))


@pytest.fixture
def official(station: Station) -> Iterator[Any]:
    """The official SunSpec client, connected and with the device scanned."""
    device = connect(station)
    with step("The official client scans the device: marker, then model after model"):
        device.scan()
    yield device
    device.close()


@pytest.mark.smoke
def test_official_client_finds_all_models_by_itself(official: Any) -> None:
    """The official SunSpec client, given only an address, finds all four models of the inverter."""
    assert official.base_addr == 40000
    assert [key for key in official.models if isinstance(key, int)] == MODEL_IDS
    assert {key for key in official.models if isinstance(key, str)} == {
        "common",
        "inverter_single_phase",
        "nameplate",
        "controls",
    }


def test_official_client_reads_the_identity(official: Any, station: Station) -> None:
    """The official client shows the manufacturer, model and serial number of the device."""
    common = official.models[1][0]
    assert common.Mn.value == "QA Portfolio Lab"
    assert common.Md.value == "SIM-5000-1P"
    assert common.SN.value == "SIM5K-2026-0001"
    assert common.DA.value == station.unit


def test_official_client_reads_full_power_at_noon(official: Any) -> None:
    """The official client applies the scale factors itself and reads 5000 W, 234.0 V and 21.37 A at noon."""
    set_noon(official)
    inverter = official.models[101][0]
    inverter.read()
    assert inverter.W.cvalue == 5000
    assert inverter.PhVphA.cvalue == 234.0
    assert inverter.A.cvalue == 21.37
    assert inverter.St.value == ds.ST_MPPT


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_official_client_and_own_client_read_the_same_values(official: Any, station: Station, model_id: int) -> None:
    """Value by value, the official client and this project's client decode the same numbers."""
    set_noon(official)
    model = official.models[model_id][0]
    model.read()
    official.close()  # one client at a time on a serial line
    ours = own_measurements(station, model_id)
    for name, mine in ours.items():
        if name == "Pad":
            continue  # padding carries no information; the two clients merely label it differently
        point = model.points[name]
        theirs = point.cvalue if point.cvalue is not None else point.value
        if isinstance(mine, float):
            assert theirs == pytest.approx(mine, abs=1e-6), name
        else:
            assert theirs == mine, name


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_official_client_finds_every_mandatory_value(official: Any, model_id: int) -> None:
    """In the official client no mandatory value of any model comes back empty."""
    set_noon(official)
    model = official.models[model_id][0]
    model.read()
    empty = [p.name for p in official_points(model_id) if p.mandatory and model.points[p.name].value is None]
    assert empty == []


def test_official_client_shows_absent_values_as_empty(official: Any) -> None:
    """Values a single-phase inverter does not have, such as phase B current, come back empty, not as zero."""
    inverter = official.models[101][0]
    assert [inverter.points[name].value for name in ("AphB", "AphC", "PhVphB", "TmpTrns")] == [None] * 4


def test_official_client_sets_a_power_limit(official: Any) -> None:
    """A 50 % limit set through the official client's model objects takes effect: 2500 W, THROTTLED."""
    set_noon(official)
    controls = official.models[123][0]
    with step("Set WMaxLimPct = 50 and WMaxLim_Ena = 1, then write the model"):
        controls.WMaxLimPct.cvalue = 50
        controls.WMaxLim_Ena.value = 1
        controls.write()
    official.write(SIM_BASE + SIM_ADVANCE, struct.pack(">H", 1))
    inverter = official.models[101][0]
    inverter.read()
    assert inverter.W.cvalue == 2500
    assert inverter.St.value == ds.ST_THROTTLED


def test_official_client_reports_a_refusal(official: Any) -> None:
    """A read of a register that does not exist reaches the official client as Modbus exception 2."""
    with pytest.raises(ModbusClientException, match="exception 2"):
        official.read(0, 1)
