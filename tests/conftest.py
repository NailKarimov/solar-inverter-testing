"""Fixtures and hooks shared by all tests.

``LINK`` decides how the tests reach the inverter:

- ``memory`` (default)              Modbus RTU over an in-process pair of sockets
- ``socat``                         Modbus RTU over two virtual serial ports made by socat
- ``tcp``                           Modbus TCP on 127.0.0.1
- ``serial://PORT?baud=9600``       the bench: Modbus RTU through a USB-RS485 adapter; the simulator
                                    runs in another process on a second adapter (see bench/README.md)

Every test has a docstring: one plain sentence saying what it proves. The sentence becomes the title
in the Allure report and on the replay page. The run is saved to ``evidence/run-<link>.json``.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import allure
import pytest

from inverter_lab import __version__
from inverter_lab.client import RtuMaster, TcpMaster
from inverter_lab.device import InverterDevice
from inverter_lab.links import Link, SerialLink, memory_pair, open_serial, open_tcp, parse_target
from inverter_lab.reader import SunSpecReader
from inverter_lab.server import RtuServer, TcpServer
from support.evidence import RECORDER, TapLink, TestRecord
from support.sim import SimControl

LINK = os.getenv("LINK", "memory")
KIND = "serial" if LINK.startswith("serial://") else LINK
if KIND not in ("memory", "socat", "tcp", "serial"):
    raise pytest.UsageError(f"LINK={LINK!r}: use memory, socat, tcp or serial://PORT?baud=9600")
UNIT = int(os.getenv("UNIT", "1"))
TIMEOUT = float(os.getenv("TIMEOUT", "2.0" if KIND == "serial" else "1.0"))
SILENCE = float(os.getenv("SILENCE", "0.25"))  # how long to listen before calling the line silent
ROOT = Path(__file__).resolve().parent.parent

SKIP_RULES: tuple[tuple[str, Callable[[], bool], str], ...] = (
    ("once", lambda: KIND != "memory", "does not use a link: runs once, in the in-memory run"),
    ("rtu", lambda: KIND == "tcp", "serial-line framing: does not apply to Modbus TCP"),
    ("tcp", lambda: KIND != "tcp", "Modbus TCP only: run with LINK=tcp"),
    ("port", lambda: KIND == "memory", "a third-party client needs a real port: run with LINK=socat or LINK=tcp"),
    ("bench", lambda: KIND != "serial", "needs the bench: run with LINK=serial://PORT"),
    ("internal", lambda: KIND == "serial", "reads the simulator's memory: not possible on the bench"),
)


@dataclass
class Station:
    """Where the device is and how a client can reach it."""

    kind: str
    unit: int
    device: InverterDevice | None  # None on the bench: the simulator runs in another process
    serial_port: str | None = None
    baud: int = 9600
    tcp: tuple[str, int] | None = None
    client_link: Link | None = None


@dataclass
class Rig:
    """A station plus this project's own client, already connected."""

    station: Station
    master: RtuMaster | TcpMaster
    sunspec: SunSpecReader
    sim: SimControl

    @property
    def kind(self) -> str:
        return self.station.kind

    @property
    def rtu(self) -> RtuMaster:
        assert isinstance(self.master, RtuMaster), "this test needs a serial line: mark it with @pytest.mark.rtu"
        return self.master

    @property
    def tcp(self) -> TcpMaster:
        assert isinstance(self.master, TcpMaster), "this test needs Modbus TCP: mark it with @pytest.mark.tcp"
        return self.master


# ---- collection: plain titles and link-dependent skips ---------------------------------------


def plain_title(item: pytest.Item) -> str:
    doc = getattr(getattr(item, "function", None), "__doc__", None) or ""
    return " ".join(doc.strip().split("\n\n")[0].split())


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    untitled = [item.nodeid for item in items if not plain_title(item)]
    if untitled:
        raise pytest.UsageError("tests without a one-sentence docstring:\n  " + "\n  ".join(untitled))
    for item in items:
        for marker, applies, reason in SKIP_RULES:
            if marker in item.keywords and applies():
                item.add_marker(pytest.mark.skip(reason=reason))
                break


# ---- evidence ---------------------------------------------------------------------------------


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> Iterator[None]:
    name = getattr(item, "originalname", None) or item.name
    params = item.name[len(name) :].strip("[]") if item.name != name else ""
    suite = Path(str(item.fspath)).stem
    RECORDER.start(TestRecord(id=item.nodeid, name=name, suite=suite, title=plain_title(item), params=params))
    yield
    RECORDER.current = None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Iterator[None]:
    outcome = yield
    report = outcome.get_result()  # type: ignore[attr-defined]
    record = RECORDER.current
    if record is None:
        return
    if report.when == "call":
        record.ms = report.duration * 1000
    if report.skipped and record.outcome == "passed":
        record.outcome = "skipped"
        longrepr = report.longrepr
        record.reason = str(longrepr[2] if isinstance(longrepr, tuple) else longrepr).removeprefix("Skipped: ")
    elif report.failed:
        record.outcome = "failed"
        record.reason = str(call.excinfo.value).splitlines()[0][:300] if call.excinfo else report.when


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    records = RECORDER.records
    if not records or os.getenv("EVIDENCE", "1") == "0":
        return
    counts = {key: sum(r.outcome == key for r in records) for key in ("passed", "failed", "skipped")}
    meta = {
        "link": KIND,
        "target": LINK if KIND == "serial" else KIND,
        "finished": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "version": __version__,
        "python": platform.python_version(),
        "commit": os.getenv("GITHUB_SHA", "")[:7],
        "run": os.getenv("GITHUB_RUN_NUMBER", ""),
        "tests": len(records),
        **counts,
        "frames": sum(r.frames for r in records),
    }
    out = ROOT / "evidence"
    out.mkdir(exist_ok=True)
    payload = {"meta": meta, "tests": [r.as_dict() for r in records]}
    (out / f"run-{KIND}.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


@pytest.fixture(autouse=True)
def _report_labels(request: pytest.FixtureRequest) -> None:
    allure.dynamic.title(plain_title(request.node))
    allure.dynamic.parameter("link", KIND)
    allure.dynamic.parent_suite(f"Link: {KIND}")


# ---- the device and the ways to reach it ------------------------------------------------------


@pytest.fixture(scope="session")
def socat_ports() -> Iterator[tuple[str, str]]:
    """Two virtual serial ports joined by a virtual cable."""
    if shutil.which("socat") is None:
        pytest.skip("socat is not installed")
    tmp = Path(tempfile.mkdtemp(prefix="inverter-"))
    a, b = tmp / "ttyClient", tmp / "ttyDevice"
    proc = subprocess.Popen(["socat", "-d0", f"pty,raw,echo=0,link={a}", f"pty,raw,echo=0,link={b}"])
    deadline = time.monotonic() + 5
    while not (a.exists() and b.exists()):
        if time.monotonic() > deadline:
            proc.kill()
            pytest.fail("socat did not create the virtual ports")
        time.sleep(0.05)
    yield str(a), str(b)
    proc.terminate()
    proc.wait(timeout=5)
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def station(request: pytest.FixtureRequest) -> Iterator[Station]:
    """A freshly started inverter for every test (on the bench: the one at the end of the cable)."""
    if KIND == "memory":
        client, side = memory_pair()
        device = InverterDevice(UNIT)
        server = RtuServer(side, device).start()
        yield Station(KIND, UNIT, device, client_link=client)
        server.stop()
        client.close()
        side.close()
    elif KIND == "socat":
        port_client, port_device = request.getfixturevalue("socat_ports")
        side_serial = SerialLink(port_device)
        device = InverterDevice(UNIT)
        server = RtuServer(side_serial, device).start()
        yield Station(KIND, UNIT, device, serial_port=port_client)
        server.stop()
        side_serial.close()
    elif KIND == "tcp":
        device = InverterDevice(UNIT)
        tcp_server = TcpServer(device).start()
        yield Station(KIND, UNIT, device, tcp=(tcp_server.host, tcp_server.port))
        tcp_server.stop()
    else:
        _, target = parse_target(LINK)
        port, _, query = target.partition("?")
        baud = int(dict(pair.split("=") for pair in query.split("&") if "=" in pair).get("baud", "9600"))
        probe = RtuMaster(open_serial(target), UNIT, timeout=TIMEOUT)
        try:
            sim = SimControl(probe)
            sim.require_simulator()
            sim.reset()
        finally:
            probe.link.close()
        yield Station(KIND, UNIT, None, serial_port=port, baud=baud)


@pytest.fixture
def rig(station: Station) -> Iterator[Rig]:
    """The inverter with this project's own Modbus client connected and every byte recorded."""
    link: Link
    if station.client_link is not None:
        link = station.client_link
    elif station.tcp is not None:
        link = open_tcp(*station.tcp)
    else:
        assert station.serial_port is not None
        link = open_serial(f"{station.serial_port}?baud={station.baud}")
    tap = TapLink(link)
    master: RtuMaster | TcpMaster
    master = TcpMaster(tap, station.unit, TIMEOUT) if station.kind == "tcp" else RtuMaster(tap, station.unit, TIMEOUT)
    yield Rig(station, master, SunSpecReader(master), SimControl(master))
    if station.client_link is None:
        link.close()
