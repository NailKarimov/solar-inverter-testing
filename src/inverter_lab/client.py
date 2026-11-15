"""A small Modbus master: asks one device and checks every answer before it believes it.

``RtuMaster`` talks over a serial link, ``TcpMaster`` over a TCP connection. Both expose the same four
calls, so a test does not care which one it holds.

An answer is accepted only if its checksum, its address and its function code fit the request.
Anything else is thrown away and, if retries are allowed, the request is sent again. A damaged answer
is never turned into data.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Protocol

from inverter_lab import mbap, pdu, rtu
from inverter_lab.links import Link


class NoResponse(TimeoutError):
    """The device did not answer in time."""


class BadResponse(Exception):
    """Something came back, but it is not a valid answer to the request."""


class Master(Protocol):
    unit: int

    def read_holding(self, address: int, count: int = 1) -> list[int]: ...

    def read_input(self, address: int, count: int = 1) -> list[int]: ...

    def write_register(self, address: int, value: int) -> None: ...

    def write_registers(self, address: int, values: Sequence[int]) -> None: ...


class _Master:
    def __init__(self, link: Link, unit: int, timeout: float, retries: int) -> None:
        self.link = link
        self.unit = unit
        self.timeout = timeout
        self.retries = retries
        self.rejected = 0  # answers thrown away because they were damaged or missing

    def read_holding(self, address: int, count: int = 1) -> list[int]:
        return self.call(pdu.read_request(pdu.Function.READ_HOLDING, address, count))

    def read_input(self, address: int, count: int = 1) -> list[int]:
        return self.call(pdu.read_request(pdu.Function.READ_INPUT, address, count))

    def write_register(self, address: int, value: int) -> None:
        self.call(pdu.write_single_request(address, value))

    def write_registers(self, address: int, values: Sequence[int]) -> None:
        self.call(pdu.write_multiple_request(address, values))

    def call(self, request: bytes) -> list[int]:
        """Send a request PDU and return the registers of the answer. Retries damaged or missing answers."""
        failure: Exception = NoResponse("no attempt made")
        for _ in range(self.retries + 1):
            try:
                return pdu.parse_response(request, self.exchange(request))
            except pdu.MalformedPdu as exc:
                failure = BadResponse(str(exc))
            except (NoResponse, BadResponse) as exc:
                failure = exc
            self.rejected += 1
        raise failure

    def exchange(self, request: bytes) -> bytes:
        raise NotImplementedError


class RtuMaster(_Master):
    def __init__(self, link: Link, unit: int = 1, timeout: float = 1.0, retries: int = 0, gap: float = 0.05) -> None:
        super().__init__(link, unit, timeout, retries)
        self.gap = gap  # silence that separates frames

    def exchange(self, request: bytes) -> bytes:
        """One request, one answer. Returns the PDU of the answer."""
        self.link.reset_input()
        self.link.write(rtu.encode(self.unit, request))
        buf = b""
        deadline = time.monotonic() + self.timeout
        while (need := rtu.response_length(buf)) is None or len(buf) < need:
            left = deadline - time.monotonic()
            if left <= 0:
                if not buf:
                    raise NoResponse(f"no answer within {self.timeout} s")
                self._wait_for_silence()
                raise BadResponse(f"incomplete answer: {buf.hex(' ')}")
            buf += self.link.read(left)
        try:
            unit, response = rtu.decode(buf[:need])
        except rtu.FrameError as exc:
            self._wait_for_silence()
            raise BadResponse(str(exc)) from exc
        if unit != self.unit:
            raise BadResponse(f"answer from unit {unit}, asked unit {self.unit}")
        return response

    def raw(self, data: bytes, timeout: float | None = None) -> bytes:
        """Put ``data`` on the line as it is and return whatever comes back before the line goes quiet."""
        self.link.reset_input()
        self.link.write(data)
        return self.listen(self.timeout if timeout is None else timeout)

    def listen(self, timeout: float) -> bytes:
        """Bytes that arrive within ``timeout``, up to the first silence after them."""
        buf = self.link.read(timeout)
        while buf:
            more = self.link.read(self.gap)
            if not more:
                break
            buf += more
        return buf

    def broadcast(self, request: bytes) -> None:
        """Send a request to address 0. Every device carries it out; none answers."""
        self.link.write(rtu.encode(rtu.BROADCAST, request))

    def _wait_for_silence(self) -> None:
        while self.link.read(self.gap):
            pass


class TcpMaster(_Master):
    def __init__(self, link: Link, unit: int = 1, timeout: float = 1.0, retries: int = 0) -> None:
        super().__init__(link, unit, timeout, retries)
        self.transaction = 0

    def exchange(self, request: bytes) -> bytes:
        self.transaction = (self.transaction + 1) & 0xFFFF
        self.link.write(mbap.encode(self.transaction, self.unit, request))
        return self.receive(self.transaction)

    def receive(self, transaction: int) -> bytes:
        """The PDU of the answer that carries ``transaction``."""
        buf = b""
        deadline = time.monotonic() + self.timeout
        while True:
            if len(buf) >= mbap.HEADER_SIZE:
                got, protocol, length, unit = mbap.decode_header(buf[: mbap.HEADER_SIZE])
                if protocol != mbap.PROTOCOL_ID or length < 2:
                    raise BadResponse(f"not a Modbus TCP header: {buf[: mbap.HEADER_SIZE].hex(' ')}")
                end = mbap.HEADER_SIZE + length - 1
                if len(buf) >= end:
                    if got != transaction:
                        raise BadResponse(f"answer to transaction {got}, expected {transaction}")
                    if unit != self.unit:
                        raise BadResponse(f"answer from unit {unit}, asked unit {self.unit}")
                    return buf[mbap.HEADER_SIZE : end]
            left = deadline - time.monotonic()
            if left <= 0:
                if not buf:
                    raise NoResponse(f"no answer within {self.timeout} s")
                raise BadResponse(f"incomplete answer: {buf.hex(' ')}")
            buf += self.link.read(left)

    def raw(self, data: bytes, timeout: float | None = None) -> bytes:
        """Send ``data`` as it is and return the bytes that come back within ``timeout``."""
        self.link.write(data)
        buf = self.link.read(self.timeout if timeout is None else timeout)
        while buf:
            more = self.link.read(0.05)
            if not more:
                break
            buf += more
        return buf
