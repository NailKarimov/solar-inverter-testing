"""Second opinion: pymodbus, the most used open-source Modbus library, talks to the inverter."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pymodbus import ModbusException
from pymodbus.client import ModbusSerialClient, ModbusTcpClient

from conftest import TIMEOUT, Station
from inverter_lab.device import SIM_ADVANCE, SIM_BASE, SIM_CLOCK_MIN
from inverter_lab.sunspec import BASE_ADDRESS, Layout
from support.evidence import step, trace_pymodbus

pytestmark = pytest.mark.port

LAYOUT = Layout()
Client = ModbusTcpClient | ModbusSerialClient


def address_of(model: int, point: str) -> int:
    return LAYOUT.entry(model, point).address


@pytest.fixture
def modbus(station: Station) -> Iterator[Client]:
    """A pymodbus client connected to the inverter over the link under test."""
    client: Client
    if station.tcp is not None:
        host, port = station.tcp
        client = ModbusTcpClient(host, port=port, timeout=TIMEOUT, retries=0, trace_packet=trace_pymodbus)
    else:
        assert station.serial_port is not None
        client = ModbusSerialClient(
            station.serial_port, baudrate=station.baud, timeout=TIMEOUT, retries=0, trace_packet=trace_pymodbus
        )
    assert client.connect()
    yield client
    client.close()


def noon(modbus: Client, unit: int) -> None:
    modbus.write_register(SIM_BASE + SIM_CLOCK_MIN, 720, device_id=unit)
    modbus.write_register(SIM_BASE + SIM_ADVANCE, 60, device_id=unit)


@pytest.mark.smoke
def test_pymodbus_reads_the_marker(modbus: Client, station: Station) -> None:
    """A standard Modbus library reads the SunS marker without any knowledge of this project's code."""
    answer = modbus.read_holding_registers(BASE_ADDRESS, count=2, device_id=station.unit)
    assert not answer.isError()
    assert answer.registers == [0x5375, 0x6E53]


def test_pymodbus_decodes_text_numbers_and_counters(modbus: Client, station: Station) -> None:
    """The library's own decoders read the manufacturer name, the power and the 32-bit energy counter."""
    noon(modbus, station.unit)
    unit = station.unit
    name = modbus.read_holding_registers(address_of(1, "Mn"), count=16, device_id=unit).registers
    watts = modbus.read_holding_registers(address_of(101, "W"), count=1, device_id=unit).registers
    energy = modbus.read_holding_registers(address_of(101, "WH"), count=2, device_id=unit).registers
    assert modbus.convert_from_registers(name, data_type=modbus.DATATYPE.STRING) == "QA Portfolio Lab"
    assert modbus.convert_from_registers(watts, data_type=modbus.DATATYPE.INT16) == 5000
    assert modbus.convert_from_registers(energy, data_type=modbus.DATATYPE.UINT32) == 1_234_620


def test_pymodbus_reads_the_largest_block(modbus: Client, station: Station) -> None:
    """The library reads 125 registers, the largest block the protocol allows, in one request."""
    answer = modbus.read_holding_registers(BASE_ADDRESS, count=125, device_id=station.unit)
    assert len(answer.registers) == 125


def test_pymodbus_input_registers_match_holding_registers(modbus: Client, station: Station) -> None:
    """Through the library, function 04 returns the same data as function 03."""
    holding = modbus.read_holding_registers(address_of(101, "A"), count=50, device_id=station.unit)
    inputs = modbus.read_input_registers(address_of(101, "A"), count=50, device_id=station.unit)
    assert holding.registers == inputs.registers


def test_pymodbus_sets_a_power_limit(modbus: Client, station: Station) -> None:
    """A power limit written by the library with function 16 takes effect: 2500 W at noon."""
    noon(modbus, station.unit)
    with step("Write 50 %, window 0, timeout 0, ramp 0, enabled, in one request"):
        answer = modbus.write_registers(address_of(123, "WMaxLimPct"), [50, 0, 0, 0, 1], device_id=station.unit)
        assert not answer.isError()
    modbus.write_register(SIM_BASE + SIM_ADVANCE, 1, device_id=station.unit)
    watts = modbus.read_holding_registers(address_of(101, "W"), count=1, device_id=station.unit).registers
    assert watts == [2500]


@pytest.mark.parametrize(("address", "code"), [(0, 2), (39999, 2), (40178, 2)])
def test_pymodbus_sees_the_refusal_code(modbus: Client, station: Station, address: int, code: int) -> None:
    """The library reports a refused read as an exception response with the code the inverter sent."""
    answer = modbus.read_holding_registers(address, count=1, device_id=station.unit)
    assert answer.isError()
    assert answer.exception_code == code


def test_pymodbus_sees_a_refused_value(modbus: Client, station: Station) -> None:
    """The library reports a limit of 101 % as exception 03, and the limit stays at 100 %."""
    answer = modbus.write_register(address_of(123, "WMaxLimPct"), 101, device_id=station.unit)
    assert answer.isError()
    assert answer.exception_code == 3
    current = modbus.read_holding_registers(address_of(123, "WMaxLimPct"), count=1, device_id=station.unit)
    assert current.registers == [100]


def test_pymodbus_gets_no_answer_from_another_unit(modbus: Client, station: Station) -> None:
    """Asked for a unit number that is not the inverter's, the library waits and then reports no answer."""
    modbus.comm_params.timeout_connect = 0.3
    with pytest.raises(ModbusException, match="No response"):
        modbus.read_holding_registers(BASE_ADDRESS, count=2, device_id=station.unit + 1)
    answer = modbus.read_holding_registers(BASE_ADDRESS, count=2, device_id=station.unit)
    assert answer.registers == [0x5375, 0x6E53]
