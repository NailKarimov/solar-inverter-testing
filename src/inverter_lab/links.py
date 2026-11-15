"""Byte links between the tests and the device: an in-memory pair, a serial port, a TCP socket.

Every link has the same four methods, so the same client code runs on all of them.
"""

from __future__ import annotations

import contextlib
import socket
from typing import Protocol
from urllib.parse import parse_qs, urlsplit


class LinkClosed(ConnectionError):
    """The other side closed the link."""


class Link(Protocol):
    def write(self, data: bytes) -> None: ...

    def read(self, timeout: float) -> bytes:
        """Bytes that arrived within ``timeout`` seconds (at least one), or ``b""`` if none did."""
        ...

    def reset_input(self) -> None: ...

    def close(self) -> None: ...


class SocketLink:
    """One end of a socket: half of ``socket.socketpair()`` or a TCP connection."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock

    def write(self, data: bytes) -> None:
        try:
            self._sock.sendall(data)
        except OSError as exc:
            raise LinkClosed(str(exc)) from exc

    def read(self, timeout: float) -> bytes:
        self._sock.settimeout(max(timeout, 0.001))
        try:
            data = self._sock.recv(4096)
        except TimeoutError:
            return b""
        except OSError as exc:
            raise LinkClosed(str(exc)) from exc
        if not data:
            raise LinkClosed("closed by the other side")
        return data

    def reset_input(self) -> None:
        self._sock.setblocking(False)
        try:
            while self._sock.recv(4096):
                pass
        except OSError:
            pass
        finally:
            self._sock.setblocking(True)

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._sock.shutdown(socket.SHUT_RDWR)
        self._sock.close()


class SerialLink:
    """A serial port through pyserial: a socat pseudo-terminal or a USB-RS485 adapter."""

    def __init__(self, port: str, baudrate: int = 9600, parity: str = "N") -> None:
        import serial  # imported here so the in-memory link works without pyserial

        self._port = serial.Serial(port, baudrate=baudrate, parity=parity, bytesize=8, stopbits=1, timeout=0)

    def write(self, data: bytes) -> None:
        self._port.write(data)
        self._port.flush()

    def read(self, timeout: float) -> bytes:
        self._port.timeout = max(timeout, 0.001)
        data = self._port.read(1)
        if data and self._port.in_waiting:
            data += self._port.read(self._port.in_waiting)
        return bytes(data)

    def reset_input(self) -> None:
        self._port.reset_input_buffer()

    def close(self) -> None:
        self._port.close()


def memory_pair() -> tuple[SocketLink, SocketLink]:
    """Two connected links inside one process: a perfect cable."""
    a, b = socket.socketpair()
    return SocketLink(a), SocketLink(b)


def open_serial(url: str) -> SerialLink:
    """``/dev/ttyUSB0?baud=9600&parity=N`` or ``COM5?baud=19200``."""
    port, _, query = url.partition("?")
    options = parse_qs(query)
    baud = int(options.get("baud", ["9600"])[0])
    parity = options.get("parity", ["N"])[0].upper()
    return SerialLink(port, baudrate=baud, parity=parity)


def open_tcp(host: str, port: int, timeout: float = 3.0) -> SocketLink:
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return SocketLink(sock)


def parse_target(url: str) -> tuple[str, str]:
    """Split ``tcp://host:port`` or ``serial:///dev/ttyUSB0?baud=9600`` into kind and the rest."""
    parts = urlsplit(url)
    if parts.scheme == "tcp":
        return "tcp", parts.netloc
    if parts.scheme == "serial":
        rest = (parts.netloc + parts.path) if parts.netloc else parts.path
        return "serial", rest + (f"?{parts.query}" if parts.query else "")
    raise ValueError(f"unknown link {url!r}: use tcp://host:port or serial://PORT?baud=9600")
