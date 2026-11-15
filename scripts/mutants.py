"""Mutation check: plant one bug at a time and make sure the test suite notices.

    python scripts/mutants.py              # every mutant
    python scripts/mutants.py M21 M23      # only these

Each mutant is one small change to the source, applied to a private copy of the project. The whole
suite then runs against the copy. A mutant is "caught" if at least one test fails. A control run
with no change must pass, otherwise the result means nothing.

Writes ``evidence/mutants.json`` (shown on the "Bug hunt" page) and ``mutants-result.md``.
Exit code 1 if a mutant survives or the control run fails.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "src/inverter_lab/"


@dataclass(frozen=True)
class Mutant:
    id: str
    area: str  # wire | map | sun | safety | control | client
    file: str
    old: str
    new: str
    title: str  # what is broken, in plain words
    link: str = "memory"


MUTANTS = [
    Mutant(
        "M01",
        "wire",
        "crc.py",
        "INIT = 0xFFFF",
        "INIT = 0x0000",
        "The checksum is calculated from the wrong starting value",
    ),
    Mutant(
        "M02",
        "wire",
        "crc.py",
        'crc16(body).to_bytes(2, "little")',
        'crc16(body).to_bytes(2, "big")',
        "The two checksum bytes are sent in the wrong order",
    ),
    Mutant(
        "M03",
        "wire",
        "server.py",
        '        if not crc_ok(frame):\n            self._count("crc_errors")\n            return False',
        '        if False:\n            self._count("crc_errors")\n            return False',
        "The inverter stops checking the checksum and obeys damaged requests",
    ),
    Mutant(
        "M04",
        "wire",
        "server.py",
        "        elif unit != self.device.unit:\n            self._count",
        "        elif False:\n            self._count",
        "The inverter answers requests addressed to other devices",
    ),
    Mutant(
        "M05",
        "wire",
        "server.py",
        "        if unit == rtu.BROADCAST:",
        "        if False:",
        "Commands sent to all devices at once are ignored",
    ),
    Mutant(
        "M06",
        "wire",
        "server.py",
        '                buf = b""\n                resync = False\n                continue',
        "                resync = False\n                continue",
        "Half a request is not forgotten and spoils the next one",
    ),
    Mutant(
        "M07",
        "wire",
        "pdu.py",
        "MAX_READ = 125",
        "MAX_READ = 126",
        "A read of 126 registers, one more than the protocol allows, is accepted",
    ),
    Mutant(
        "M08",
        "wire",
        "sunspec.py",
        "address + count <= self.base + self.size",
        "address + count <= self.base + self.size + 1",
        "A read may run one register past the end of the map",
    ),
    Mutant(
        "M09",
        "wire",
        "device.py",
        "        except IllegalAddress:\n            return exception_response(function, ExceptionCode.ILLEGAL_DATA_ADDRESS)",
        "        except IllegalAddress:\n            return exception_response(function, ExceptionCode.ILLEGAL_DATA_VALUE)",
        "A request for a missing register is refused with the wrong reason code",
    ),
    Mutant(
        "M10",
        "wire",
        "server.py",
        "mbap.encode(transaction, unit, self.device.respond(pdu))",
        "mbap.encode(0, unit, self.device.respond(pdu))",
        "Network answers lose the number that ties them to their request",
        link="tcp",
    ),
    Mutant(
        "M11",
        "wire",
        "server.py",
        "if protocol != mbap.PROTOCOL_ID or not 2 <= length <= mbap.MAX_PDU + 1:",
        "if not 2 <= length <= mbap.MAX_PDU + 1:",
        "The network port accepts traffic that is not Modbus",
        link="tcp",
    ),
    Mutant(
        "M12",
        "map",
        "sunspec.py",
        'MARKER = (0x5375, 0x6E53)  # "Su", "nS"',
        'MARKER = (0x5375, 0x6E73)  # "Su", "ns"',
        'The map starts with "Suns" instead of "SunS"',
    ),
    Mutant(
        "M13",
        "map",
        "sunspec.py",
        "registers += [model.id, model.length]",
        "registers += [model.id, model.length + 1]",
        "Every model announces a length one register too long",
    ),
    Mutant(
        "M14",
        "map",
        "inverter.py",
        '(101, "A_SF"): -2,',
        '(101, "A_SF"): -1,',
        "The current is reported ten times too high (wrong scale factor)",
    ),
    Mutant(
        "M15",
        "map",
        "sunspec.py",
        "    if point.type in SIGNED and number >= 0x8000:\n        number -= 0x10000\n",
        "",
        "Temperatures below zero are read as huge positive numbers",
    ),
    Mutant(
        "M16",
        "map",
        "sunspec.py",
        '    "uint16": 0xFFFF,',
        '    "uint16": 0x0000,',
        'Values the inverter does not have read as zero instead of "not implemented"',
    ),
    Mutant(
        "M17",
        "control",
        "device.py",
        "            if entry is None or not entry.point.writable:",
        "            if entry is None:",
        "Read-only registers no longer refuse writes cleanly",
    ),
    Mutant(
        "M18",
        "control",
        "device.py",
        "        for name, value in changes.items():\n"
        "            low, high = CONTROL_RANGES[name]\n"
        "            if not low <= value <= high:\n"
        "                raise IllegalValue(name)\n"
        "        self.inverter.write_controls(changes)",
        "        self.inverter.write_controls(changes)\n"
        "        for name, value in changes.items():\n"
        "            low, high = CONTROL_RANGES[name]\n"
        "            if not low <= value <= high:\n"
        "                raise IllegalValue(name)",
        "A refused command is carried out anyway before it is refused",
    ),
    Mutant(
        "M19",
        "control",
        "device.py",
        "            SIM_RESET: lambda v: v == SIM_RESET_KEY,",
        "            SIM_RESET: lambda v: True,",
        "A reset is carried out without its key",
    ),
    Mutant(
        "M20",
        "sun",
        "inverter.py",
        "            unconstrained = RATED_W  # clipping at the nameplate",
        "            pass",
        "At full sun the inverter reports a power limit that nobody set",
    ),
    Mutant(
        "M21",
        "safety",
        "inverter.py",
        "        if not self.grid_ok:\n            events |= EVT_GRID_DISCONNECT",
        "        if False:\n            events |= EVT_GRID_DISCONNECT",
        "The inverter keeps feeding in when the grid is down",
    ),
    Mutant(
        "M22",
        "safety",
        "inverter.py",
        "RECONNECT_S = 60  # wait after the grid returns",
        "RECONNECT_S = 6  # wait after the grid returns",
        "After an outage the inverter reconnects after 6 seconds instead of 60",
    ),
    Mutant(
        "M23",
        "control",
        "inverter.py",
        "        target = limit_w if limit_w < unconstrained else unconstrained",
        "        target = unconstrained",
        "The inverter ignores the power limit",
    ),
    Mutant(
        "M24",
        "control",
        "inverter.py",
        "            if self.limit_age >= self.limit_rvrt_s:",
        "            if False:",
        "A limit that nobody renews stays in force for ever",
    ),
    Mutant(
        "M25",
        "control",
        "inverter.py",
        "            self.limit_age = 0  # every write of the limit restarts the revert timer\n",
        "",
        "Renewing a limit does not restart its timer",
    ),
    Mutant(
        "M26",
        "safety",
        "inverter.py",
        "        if self.sink_c >= TRIP_C:",
        "        if self.sink_c > TRIP_C:",
        "The over-temperature trip is off by a hair: 95.0 degrees does not trip",
    ),
    Mutant(
        "M27",
        "safety",
        "inverter.py",
        "        elif self.sink_c <= RESET_C:",
        "        else:",
        "After overheating the inverter restarts while it is still hot",
    ),
    Mutant(
        "M28",
        "sun",
        "inverter.py",
        "        self.energy_wh += self.ac_w / 3600.0",
        "        self.energy_wh += self.dc_w / 3600.0",
        "The energy counter counts the power before losses: 3 % too much",
    ),
    Mutant(
        "M29",
        "sun",
        "inverter.py",
        "EFFICIENCY = 0.975",
        "EFFICIENCY = 0.985",
        "Conversion losses are understated by one percent",
    ),
    Mutant(
        "M30",
        "sun",
        "inverter.py",
        "            self.ac_w += RAMP_W_PER_S  # power rises gently and falls at once",
        "            self.ac_w = target",
        "No soft start: the power jumps to full in one step",
    ),
    Mutant(
        "M31",
        "safety",
        "inverter.py",
        "STARTUP_S = 20  # grid checks before feeding in",
        "STARTUP_S = 0  # grid checks before feeding in",
        "The inverter skips the grid checks before it starts",
    ),
    Mutant(
        "M32",
        "control",
        "inverter.py",
        "        elif not self.conn:",
        "        elif False:",
        "The inverter ignores the disconnect command",
    ),
    Mutant(
        "M33",
        "sun",
        "inverter.py",
        "STOP_W = 30.0  # below this the inverter goes back to sleep",
        "STOP_W = 60.0  # below this the inverter goes back to sleep",
        "The inverter gives up too early in weak evening light",
    ),
    Mutant(
        "M34",
        "sun",
        "inverter.py",
        "        self.clock = (self.clock + 1) % DAY_S",
        "        self.clock = self.clock + 1",
        "The clock runs past midnight and the next morning never comes",
    ),
    Mutant(
        "M35",
        "sun",
        "inverter.py",
        "CLOUD_LOSS = 0.75",
        "CLOUD_LOSS = 0.50",
        "Clouds dim the light less than the datasheet says",
    ),
    Mutant(
        "M36",
        "client",
        "rtu.py",
        "    if not crc_ok(frame):\n        raise FrameError(f\"wrong CRC: {frame.hex(' ')}\")\n",
        "",
        "The client stops checking the checksum of answers",
    ),
    Mutant(
        "M37",
        "client",
        "client.py",
        "            except (NoResponse, BadResponse) as exc:\n                failure = exc",
        "            except (NoResponse, BadResponse, pdu.ModbusException) as exc:\n                failure = exc",
        "The client repeats a request the device has already refused",
    ),
    Mutant(
        "M38",
        "client",
        "client.py",
        '        if unit != self.unit:\n            raise BadResponse(f"answer from unit {unit}, asked unit {self.unit}")\n        return response',
        "        return response",
        "The client accepts an answer from another device",
    ),
]

IGNORE = shutil.ignore_patterns(
    ".venv", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis", "evidence", "allure-*"
)


def run_suite(workdir: Path, link: str) -> tuple[bool, list[dict[str, str]], float]:
    """Run the suite in ``workdir``. Returns (passed, failed tests, seconds)."""
    env = {
        **os.environ,
        "LINK": link,
        "PYTHONDONTWRITEBYTECODE": "1",
        "FUZZ_EXAMPLES": os.getenv("MUTANT_FUZZ_EXAMPLES", "15"),
        "EVIDENCE": "1",
    }
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "not bench and not pages"],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
    )
    seconds = time.monotonic() - started
    failed: list[dict[str, str]] = []
    evidence = workdir / "evidence" / f"run-{link}.json"
    if evidence.exists():
        for test in json.loads(evidence.read_text())["tests"]:
            if test["outcome"] == "failed":
                failed.append({"id": test["id"], "name": test["name"], "title": test["title"], "suite": test["suite"]})
    if result.returncode not in (0, 1):  # 1 = tests failed; anything else is a broken run
        failed.append({"id": "pytest", "name": "pytest", "title": result.stdout[-400:], "suite": "pytest"})
    return result.returncode == 0, failed, seconds


def check(mutant: Mutant | None, tmp: Path, link: str) -> dict[str, object]:
    name = mutant.id if mutant else f"control-{link}"
    work = tmp / name
    shutil.copytree(ROOT, work, ignore=IGNORE)
    if mutant:
        target = work / SRC / mutant.file
        text = target.read_text()
        if text.count(mutant.old) != 1:
            raise SystemExit(f"{mutant.id}: pattern found {text.count(mutant.old)} times in {mutant.file}, expected 1")
        target.write_text(text.replace(mutant.old, mutant.new))
    passed, failed, seconds = run_suite(work, link)
    shutil.rmtree(work, ignore_errors=True)
    return {"passed": passed, "failed": failed, "seconds": round(seconds, 1)}


def main(argv: list[str]) -> int:
    chosen = [m for m in MUTANTS if not argv or m.id in argv]
    links = sorted({m.link for m in chosen})
    workers = int(os.getenv("MUTANT_WORKERS", str(min(4, os.cpu_count() or 2))))
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="mutants-") as tmp_name, ThreadPoolExecutor(workers) as pool:
        tmp = Path(tmp_name)
        controls = {link: pool.submit(check, None, tmp, link) for link in links}
        futures = {m.id: pool.submit(check, m, tmp, m.link) for m in chosen}
        control_ok = True
        for link, future in controls.items():
            outcome = future.result()
            print(f"control ({link}): {'passed' if outcome['passed'] else 'FAILED'} in {outcome['seconds']} s")
            if not outcome["passed"]:
                control_ok = False
                print(json.dumps(outcome["failed"], indent=1)[:2000], file=sys.stderr)
        results = []
        for mutant in chosen:
            outcome = futures[mutant.id].result()
            failed = outcome["failed"]
            assert isinstance(failed, list)
            caught = not outcome["passed"]
            print(
                f"{mutant.id}: {'caught by ' + str(len(failed)) + ' tests' if caught else 'SURVIVED'} - {mutant.title}"
            )
            results.append(
                {
                    "id": mutant.id,
                    "area": mutant.area,
                    "file": SRC + mutant.file,
                    "title": mutant.title,
                    "link": mutant.link,
                    "old": mutant.old.strip("\n"),
                    "new": mutant.new.strip("\n"),
                    "caught": caught,
                    "killers": failed[:12],
                    "killer_count": len(failed),
                    "seconds": outcome["seconds"],
                }
            )

    survived = [r for r in results if not r["caught"]]
    total = len(results)
    meta = {
        "finished": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": os.getenv("GITHUB_SHA", "")[:7],
        "total": total,
        "caught": total - len(survived),
        "control": control_ok,
        "seconds": round(time.monotonic() - started),
    }
    out = ROOT / "evidence"
    out.mkdir(exist_ok=True)
    payload = {"meta": meta, "mutants": results}
    (out / "mutants.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")

    lines = [
        "# Mutation check",
        "",
        f"**{meta['caught']}/{total} planted bugs caught.** "
        f"Control run without a planted bug: {'passed' if control_ok else 'FAILED'}.",
        "",
        "| Id | File | Planted bug | Link | Result | Tests that failed |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        verdict = "caught" if r["caught"] else "**survived**"
        lines.append(f"| {r['id']} | `{r['file']}` | {r['title']} | {r['link']} | {verdict} | {r['killer_count']} |")
    (ROOT / "mutants-result.md").write_text("\n".join(lines) + "\n")
    print(f"{meta['caught']}/{total} caught in {meta['seconds']} s")
    return 1 if survived or not control_ok else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
