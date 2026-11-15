"""The same inverter on a network: Modbus TCP wraps each message in a 7-byte header instead of a checksum."""

from __future__ import annotations

import threading
import time

import pytest

from conftest import SILENCE, TIMEOUT, Rig
from inverter_lab import mbap, pdu
from inverter_lab.client import TcpMaster
from inverter_lab.device import SIM_BASE, SIM_MAGIC
from inverter_lab.links import LinkClosed, open_tcp
from inverter_lab.pdu import Function
from support.evidence import TapLink, step

pytestmark = pytest.mark.tcp

READ_MARKER = pdu.read_request(Function.READ_HOLDING, 40000, 2)
MARKER_ANSWER = bytes.fromhex("03 04 53 75 6E 53")


def connect(rig: Rig) -> TapLink:
    assert rig.station.tcp is not None
    return TapLink(open_tcp(*rig.station.tcp))


@pytest.mark.smoke
@pytest.mark.parametrize("transaction", [1, 0x1234, 0xFFFF, 0])
def test_answer_repeats_the_transaction_number(rig: Rig, transaction: int) -> None:
    """The answer carries the transaction number of its request, so the client can match the two."""
    answer = rig.tcp.raw(mbap.encode(transaction, rig.station.unit, READ_MARKER))
    assert mbap.decode_header(answer[:7]) == (transaction, 0, 1 + len(MARKER_ANSWER), rig.station.unit)
    assert answer[7:] == MARKER_ANSWER


def test_network_frame_has_no_checksum(rig: Rig) -> None:
    """A network answer is the 7-byte header plus the message and nothing more: TCP guards the bytes itself."""
    answer = rig.tcp.raw(mbap.encode(7, rig.station.unit, pdu.read_request(Function.READ_HOLDING, 40000, 10)))
    assert len(answer) == 7 + 2 + 2 * 10


def test_refusal_keeps_the_header(rig: Rig) -> None:
    """A refused request is answered with the same header and a two-byte exception message."""
    answer = rig.tcp.raw(mbap.encode(0x0A0B, rig.station.unit, pdu.read_request(Function.READ_HOLDING, 0, 1)))
    assert mbap.decode_header(answer[:7]) == (0x0A0B, 0, 3, rig.station.unit)
    assert answer[7:] == bytes.fromhex("83 02")


@pytest.mark.parametrize("function", [0x01, 0x2B, 0x7F])
def test_unknown_function_is_refused_on_tcp_too(rig: Rig, function: int) -> None:
    """A function the inverter does not support is refused with exception 01 on the network as well."""
    answer = rig.tcp.raw(mbap.encode(1, rig.station.unit, bytes([function, 0, 0, 0, 1])))
    assert answer[7:] == bytes([function | 0x80, 1])


def test_wrong_protocol_number_closes_the_connection(rig: Rig) -> None:
    """A header whose protocol field is not 0 is not Modbus: the inverter hangs up instead of guessing."""
    header = mbap.HEADER.pack(1, 1, len(READ_MARKER) + 1, rig.station.unit)
    with pytest.raises(LinkClosed):
        rig.tcp.raw(header + READ_MARKER)
    with step("A new connection is served as usual"):
        fresh = TcpMaster(connect(rig), rig.station.unit, TIMEOUT)
        assert fresh.read_holding(40000, 2) == [0x5375, 0x6E53]
        fresh.link.close()


@pytest.mark.parametrize("length", [0, 1, 255, 65535])
def test_impossible_length_closes_the_connection(rig: Rig, length: int) -> None:
    """A header that announces an impossible length makes the inverter hang up; others are not affected."""
    header = mbap.HEADER.pack(1, 0, length, rig.station.unit)
    with pytest.raises(LinkClosed):
        rig.tcp.raw(header + READ_MARKER)
    fresh = TcpMaster(connect(rig), rig.station.unit, TIMEOUT)
    assert fresh.read_holding(40000, 2) == [0x5375, 0x6E53]
    fresh.link.close()


@pytest.mark.parametrize("other", [0, 2, 255])
def test_request_for_another_unit_is_not_answered(rig: Rig, other: int) -> None:
    """A request for another unit number gets no answer, and the connection stays usable."""
    if other == rig.station.unit:
        pytest.skip("this is the inverter's own unit number")
    with step(f"Ask unit {other}"):
        assert rig.tcp.raw(mbap.encode(5, other, READ_MARKER), timeout=SILENCE) == b""
    with step("Ask the right unit on the same connection"):
        assert rig.tcp.read_holding(40000, 2) == [0x5375, 0x6E53]


def test_three_requests_in_one_packet_are_answered_in_order(rig: Rig) -> None:
    """Three requests sent in one go are answered one after another, in the order they were sent."""
    unit = rig.station.unit
    packet = b"".join(
        mbap.encode(tid, unit, pdu.read_request(Function.READ_HOLDING, address, 1))
        for tid, address in [(11, 40000), (12, 40001), (13, SIM_BASE)]
    )
    stream = rig.tcp.raw(packet)
    answers = [stream[i : i + 11] for i in range(0, len(stream), 11)]
    assert [mbap.decode_header(a[:7])[0] for a in answers] == [11, 12, 13]
    assert [int.from_bytes(a[9:11], "big") for a in answers] == [0x5375, 0x6E53, SIM_MAGIC]


def test_request_sent_one_byte_at_a_time_is_understood(rig: Rig) -> None:
    """A request that trickles in byte by byte, as a slow network delivers it, is still answered."""
    request = mbap.encode(21, rig.station.unit, READ_MARKER)
    for byte in request:
        rig.tcp.link.write(bytes([byte]))
        time.sleep(0.002)
    assert rig.tcp.receive(21) == MARKER_ANSWER


def test_two_clients_get_their_own_answers(rig: Rig) -> None:
    """Two programs asking at the same time each get the answers to their own questions."""
    assert rig.station.tcp is not None
    results: dict[str, list[list[int]]] = {"a": [], "b": []}

    def poll(name: str, address: int) -> None:
        assert rig.station.tcp is not None
        master = TcpMaster(open_tcp(*rig.station.tcp), rig.station.unit, TIMEOUT)
        for _ in range(50):
            results[name].append(master.read_holding(address, 1))
        master.link.close()

    threads = [
        threading.Thread(target=poll, args=("a", 40000)),
        threading.Thread(target=poll, args=("b", SIM_BASE)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert results["a"] == [[0x5375]] * 50
    assert results["b"] == [[SIM_MAGIC]] * 50


def test_client_leaving_mid_request_does_not_harm_others(rig: Rig) -> None:
    """A client that disconnects in the middle of a request leaves the inverter serving everyone else."""
    with step("A second client sends half a header and disconnects"):
        leaver = connect(rig)
        leaver.write(mbap.encode(1, rig.station.unit, READ_MARKER)[:4])
        leaver.close()
    with step("The first client asks as usual"):
        assert rig.tcp.read_holding(40000, 2) == [0x5375, 0x6E53]


def test_fifty_connections_in_a_row_are_all_served(rig: Rig) -> None:
    """Fifty clients connecting, asking once and leaving are all answered."""
    assert rig.station.tcp is not None
    for _ in range(50):
        master = TcpMaster(open_tcp(*rig.station.tcp), rig.station.unit, TIMEOUT)
        assert master.read_holding(40000, 2) == [0x5375, 0x6E53]
        master.link.close()
