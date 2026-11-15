"""The device on the bus: a Modbus RTU server on a serial link and a Modbus TCP server on a socket.

The RTU server behaves like firmware on a real line:

- it answers only its own address, and never answers a broadcast (address 0)
- a frame with a wrong CRC is dropped without an answer, and so is everything up to the next silence
- bytes that never become a frame are dropped when the line goes quiet
"""

from __future__ import annotations

import socket
import threading
import time

from inverter_lab import mbap, rtu
from inverter_lab.crc import crc_ok
from inverter_lab.device import InverterDevice
from inverter_lab.links import Link, LinkClosed
from inverter_lab.pdu import Function

IDLE_GAP = 0.03  # seconds of silence that end a frame; generous because USB adapters deliver in bursts
WRITE_FUNCTIONS = (Function.WRITE_SINGLE, Function.WRITE_MULTIPLE)
POLL = 0.05  # how often the TCP threads check whether the server is stopping


class RtuServer:
    def __init__(self, link: Link, device: InverterDevice, idle_gap: float = IDLE_GAP) -> None:
        self.link = link
        self.device = device
        self.idle_gap = idle_gap
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="rtu-server", daemon=True)

    def start(self) -> RtuServer:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        buf = b""
        resync = False  # after a damaged frame nothing is trusted until the line goes quiet
        while not self._stop.is_set():
            try:
                chunk = self.link.read(self.idle_gap)
            except LinkClosed:
                return
            if not chunk:
                if buf:
                    self._on_silence(buf)
                buf = b""
                resync = False
                continue
            if resync:
                continue
            buf += chunk
            while len(buf) >= 2 and buf[1] in rtu.KNOWN_FUNCTIONS:
                need = rtu.request_length(buf)
                if need is None or len(buf) < need:
                    break
                frame, buf = buf[:need], buf[need:]
                if not self._on_frame(frame):
                    buf = b""
                    resync = True
            if len(buf) > rtu.MAX_FRAME:
                self._count("framing_errors")
                buf = b""
                resync = True

    def _on_silence(self, buf: bytes) -> None:
        """The line went quiet with bytes left over: an unknown function, or not a frame at all."""
        if len(buf) >= rtu.MIN_FRAME and buf[1] not in rtu.KNOWN_FUNCTIONS and crc_ok(buf):
            self._on_frame(buf)
        else:
            self._count("framing_errors")

    def _on_frame(self, frame: bytes) -> bool:
        """Handle one complete frame. False if its checksum is wrong."""
        if not crc_ok(frame):
            self._count("crc_errors")
            return False
        unit, pdu = frame[0], frame[1:-2]
        if unit == rtu.BROADCAST:
            self._count("broadcasts")
            if pdu[0] in WRITE_FUNCTIONS:
                self.device.respond(pdu)  # carried out, never answered
        elif unit != self.device.unit:
            self._count("other_unit")
        else:
            self.link.write(rtu.encode(unit, self.device.respond(pdu)))
        return True

    def _count(self, counter: str) -> None:
        with self.device.lock:
            setattr(self.device.diag, counter, getattr(self.device.diag, counter) + 1)


class TcpServer:
    """Modbus TCP: every connection gets its own thread; requests on a connection are answered in order."""

    def __init__(self, device: InverterDevice, host: str = "127.0.0.1", port: int = 0) -> None:
        self.device = device
        self._listener = socket.create_server((host, port))
        self._listener.settimeout(POLL)
        self.host = host
        self.port: int = self._listener.getsockname()[1]
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._accept = threading.Thread(target=self._accept_loop, name="tcp-server", daemon=True)

    def start(self) -> TcpServer:
        self._accept.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._accept.join(timeout=2)
        self._listener.close()
        for thread in self._threads:
            thread.join(timeout=2)

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            thread = threading.Thread(target=self._serve, args=(conn,), name="tcp-conn", daemon=True)
            self._threads.append(thread)
            thread.start()

    def _receive(self, conn: socket.socket, size: int) -> bytes | None:
        """Exactly ``size`` bytes, or None if the client left or the server is stopping."""
        buf = b""
        while len(buf) < size:
            if self._stop.is_set():
                return None
            try:
                chunk = conn.recv(size - len(buf))
            except TimeoutError:
                continue
            except OSError:
                return None
            if not chunk:
                return None
            buf += chunk
        return buf

    def _serve(self, conn: socket.socket) -> None:
        conn.settimeout(POLL)
        with conn:
            while True:
                header = self._receive(conn, mbap.HEADER_SIZE)
                if header is None:
                    return
                transaction, protocol, length, unit = mbap.decode_header(header)
                if protocol != mbap.PROTOCOL_ID or not 2 <= length <= mbap.MAX_PDU + 1:
                    self._count("framing_errors")
                    return  # not Modbus: the stream cannot be trusted any more, so close it
                pdu = self._receive(conn, length - 1)
                if pdu is None:
                    return
                if unit != self.device.unit:
                    self._count("other_unit")
                    continue
                try:
                    conn.sendall(mbap.encode(transaction, unit, self.device.respond(pdu)))
                except OSError:
                    return

    def _count(self, counter: str) -> None:
        with self.device.lock:
            setattr(self.device.diag, counter, getattr(self.device.diag, counter) + 1)


class RealTimeClock:
    """Moves the simulated clock while the device runs as a stand-alone demo (``time_scale`` > 0)."""

    def __init__(self, device: InverterDevice, period: float = 0.1) -> None:
        self.device = device
        self.period = period
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="sim-clock", daemon=True)

    def start(self) -> RealTimeClock:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        carry = 0.0
        last = time.monotonic()
        while not self._stop.wait(self.period):
            now = time.monotonic()
            carry = self.device.tick_real_time(now - last, carry)
            last = now
