"""Build the visual page ``docs/solar-inverter.html`` from ``site/`` and the evidence of the last run.

    python scripts/build_pages.py            # data + page
    python scripts/build_pages.py --check    # also fail if a test or a mutant has no Russian title

What it produces:

- ``site/data/map.js``       the SunSpec map and the simulator block, exported from the Python source
- ``site/data/run.js``       the last test run on every link, slimmed down for the page
- ``site/data/mutants.js``   the result of the mutation check
- ``site/test/vectors.json`` conversations with the Python simulator; ``site/test/twin.test.mjs`` replays
                             them against the JavaScript twin and compares every byte
- ``docs/solar-inverter.html``  one self-contained file: styles, scripts and data inlined

The page works from GitHub Pages, from a clone (double click) and as a published artifact.
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from inverter_lab import __version__, pdu, rtu  # noqa: E402
from inverter_lab.device import (  # noqa: E402
    CONTROL_RANGES,
    HEAT_OFF,
    MAX_ADVANCE_S,
    SIM_ADVANCE,
    SIM_AMBIENT,
    SIM_BASE,
    SIM_CLOCK_MIN,
    SIM_CLOUD,
    SIM_GRID,
    SIM_HEAT,
    SIM_MAGIC,
    SIM_RESET,
    SIM_RESET_KEY,
    SIM_TIME_SCALE,
    InverterDevice,
)
from inverter_lab.server import RtuServer  # noqa: E402
from inverter_lab.sunspec import (  # noqa: E402
    BASE_ADDRESS,
    EVENT_NAMES,
    MARKER,
    MODELS,
    NOT_IMPLEMENTED,
    SIGNED,
    STATE_NAMES,
    Layout,
)

SITE = ROOT / "site"
DATA = SITE / "data"
EVIDENCE = ROOT / "evidence"
OUT = ROOT / "docs" / "solar-inverter.html"
LINKS = ("memory", "socat", "tcp")
PAGE_FRAMES = 24  # frames kept per test on the page

SIM_NAMES = [
    "SIM_ID",
    "SIM_CLOCK_MIN",
    "SIM_CLOCK_SEC",
    "SIM_ADVANCE",
    "SIM_CLOUD",
    "SIM_AMBIENT",
    "SIM_GRID",
    "SIM_HEAT",
    "SIM_TIME_SCALE",
    "SIM_RESET",
    "SIM_FRAMES_OK",
    "SIM_CRC_ERRORS",
    "SIM_FRAMING_ERRORS",
    "SIM_EXCEPTIONS",
    "SIM_OTHER_UNIT",
    "SIM_BROADCASTS",
]


def js(name: str, value: Any) -> str:
    return f"window.{name} = {json.dumps(value, ensure_ascii=False, separators=(',', ':'))};\n"


# ---- the map --------------------------------------------------------------------------------------


def export_map() -> dict[str, Any]:
    layout = Layout()
    return {
        "version": __version__,
        "base": BASE_ADDRESS,
        "marker": list(MARKER),
        "size": layout.size,
        "models": [
            {
                "id": model.id,
                "name": model.name,
                "label": model.label,
                "length": model.length,
                "address": layout.model_address[model.id],
                "points": [
                    {
                        "name": p.name,
                        "type": p.type,
                        "size": p.size,
                        "sf": p.sf,
                        "writable": p.writable,
                        "units": p.units,
                        "label": p.label,
                    }
                    for p in model.points
                ],
            }
            for model in MODELS
        ],
        "notImplemented": NOT_IMPLEMENTED,
        "signed": list(SIGNED),
        "states": {str(k): v for k, v in STATE_NAMES.items()},
        "events": {str(k): v for k, v in EVENT_NAMES.items()},
        "ranges": {k: list(v) for k, v in CONTROL_RANGES.items()},
        "sim": {
            "base": SIM_BASE,
            "names": SIM_NAMES,
            "magic": SIM_MAGIC,
            "resetKey": SIM_RESET_KEY,
            "heatOff": HEAT_OFF,
            "maxAdvance": MAX_ADVANCE_S,
        },
    }


# ---- conversations for the twin ---------------------------------------------------------------------


class _Capture:
    """A link that keeps what the server writes."""

    def __init__(self) -> None:
        self.sent: bytes | None = None

    def write(self, data: bytes) -> None:
        self.sent = data

    def read(self, timeout: float) -> bytes:
        return b""

    def reset_input(self) -> None:
        pass

    def close(self) -> None:
        pass


class _Talk:
    """Record a conversation with a fresh Python device."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.device = InverterDevice(1)
        self.capture = _Capture()
        self.server = RtuServer(self.capture, self.device)
        self.steps: list[list[str | None]] = []
        self.layout = Layout()

    def pdu(self, request: bytes) -> bytes:
        answer = self.device.respond(request)
        self.steps.append(["pdu", request.hex(), answer.hex()])
        return answer

    def frame(self, frame: bytes) -> None:
        self.capture.sent = None
        self.server._on_frame(frame)
        self.steps.append(["rtu", frame.hex(), self.capture.sent.hex() if self.capture.sent is not None else None])

    def sim(self, offset: int, value: int) -> None:
        self.pdu(pdu.write_single_request(SIM_BASE + offset, value & 0xFFFF))

    def clock(self, hhmm: str) -> None:
        hours, _, mins = hhmm.partition(":")
        self.sim(SIM_CLOCK_MIN, int(hours) * 60 + int(mins))

    def advance(self, seconds: int) -> None:
        self.sim(SIM_ADVANCE, seconds)

    def control(self, name: str, value: int) -> None:
        self.pdu(pdu.write_single_request(self.layout.entry(123, name).address, value & 0xFFFF))

    def read_all(self) -> None:
        self.pdu(pdu.read_request(3, BASE_ADDRESS, 125))
        self.pdu(pdu.read_request(3, BASE_ADDRESS + 125, self.layout.size - 125))
        self.pdu(pdu.read_request(3, SIM_BASE, 16))

    def read_inverter(self) -> None:
        self.pdu(pdu.read_request(3, self.layout.model_address[101], 52))

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "steps": self.steps}


def record_vectors() -> list[dict[str, Any]]:
    talks: list[_Talk] = []

    t = _Talk("a clear day, every half hour")
    for half in range(48):
        t.clock(f"{half // 2:02d}:{30 * (half % 2):02d}")
        t.advance(90)
        t.read_all()
    talks.append(t)

    t = _Talk("clouds from 0 to 100 %")
    t.advance(60)
    for cloud in range(0, 101, 10):
        t.sim(SIM_CLOUD, cloud)
        t.advance(30)
        t.read_all()
    talks.append(t)

    t = _Talk("power limit with a ramp and a revert timeout")
    t.advance(60)
    t.pdu(pdu.write_multiple_request(t.layout.entry(123, "WMaxLimPct").address, [50, 0, 30, 10, 1]))
    for _ in range(45):
        t.advance(1)
        t.read_inverter()
    t.read_all()
    talks.append(t)

    t = _Talk("grid outage and the wait after it")
    t.advance(60)
    t.sim(SIM_GRID, 0)
    for _ in range(3):
        t.advance(1)
        t.read_inverter()
    t.sim(SIM_GRID, 1)
    for _ in range(90):
        t.advance(1)
        t.read_inverter()
    talks.append(t)

    t = _Talk("overheating, cooling, frost and a hot cabinet")
    t.advance(60)
    for tenth in (949, 950, 760, 751, 750):
        t.sim(SIM_HEAT, tenth)
        t.advance(30)
        t.read_all()
    t.sim(SIM_HEAT, HEAT_OFF)
    t.sim(SIM_AMBIENT, -150)
    t.clock("01:00")
    t.advance(3600)
    t.read_all()
    t.sim(SIM_AMBIENT, 600)
    t.clock("12:00")
    for _ in range(12):
        t.advance(600)
        t.read_all()
    talks.append(t)

    t = _Talk("disconnect with a timeout")
    t.advance(60)
    t.control("Conn_RvrtTms", 30)
    t.control("Conn", 0)
    for _ in range(70):
        t.advance(1)
        t.read_inverter()
    talks.append(t)

    t = _Talk("dawn: start-up and soft start")
    t.clock("04:40")
    for _ in range(240):
        t.advance(10)
        t.read_inverter()
    talks.append(t)

    t = _Talk("requests that must be refused")
    limit = t.layout.entry(123, "WMaxLimPct").address
    watts = t.layout.entry(101, "W").address
    for request in (
        bytes([0x2B, 0x0E, 0x01, 0x00]),
        pdu.read_request(3, BASE_ADDRESS, 0),
        pdu.read_request(3, BASE_ADDRESS, 126),
        pdu.read_request(3, BASE_ADDRESS - 1, 2),
        pdu.read_request(3, BASE_ADDRESS + t.layout.size - 1, 2),
        pdu.read_request(4, BASE_ADDRESS, 4),
        pdu.read_request(3, 0, 1),
        pdu.read_request(3, SIM_BASE + 15, 2),
        pdu.write_single_request(watts, 1),
        pdu.write_single_request(BASE_ADDRESS, 1),
        pdu.write_single_request(limit, 101),
        pdu.write_multiple_request(limit, [50, 0, 30, 10, 2]),
        pdu.write_multiple_request(limit - 1, [1, 50, 0, 0, 0, 1, 100]),
        pdu.write_multiple_request(limit, [50, 0, 30, 10, 1])[:-1],
        pdu.write_single_request(SIM_BASE + SIM_RESET, 1),
        pdu.write_single_request(SIM_BASE, 1),
        pdu.write_single_request(SIM_BASE + SIM_CLOUD, 101),
        pdu.write_single_request(SIM_BASE + SIM_TIME_SCALE, 600),
        bytes([0x03, 0x9C]),
    ):
        t.pdu(request)
        t.read_all()
    t.sim(SIM_RESET, SIM_RESET_KEY)
    t.read_all()
    talks.append(t)

    t = _Talk("serial frames: good, damaged, foreign, broadcast")
    good = rtu.encode(1, pdu.read_request(3, watts, 2))
    t.frame(good)
    t.frame(good[:-1] + bytes([good[-1] ^ 0x01]))
    t.frame(rtu.encode(2, pdu.read_request(3, watts, 2)))
    t.frame(rtu.encode(0, pdu.write_single_request(SIM_BASE + SIM_CLOUD, 40)))
    t.frame(rtu.encode(0, pdu.read_request(3, watts, 2)))
    t.frame(rtu.encode(1, bytes([0x2B, 0x0E])))
    t.frame(rtu.encode(1, pdu.read_request(3, SIM_BASE, 16)))
    talks.append(t)

    rng = random.Random(20261115)
    t = _Talk("four hundred random commands")
    writable = [t.layout.entry(123, name).address for name in CONTROL_RANGES]
    for _ in range(400):
        roll = rng.random()
        if roll < 0.30:
            t.advance(rng.choice([1, 1, 2, 5, 17, 60, 300, 1800]))
        elif roll < 0.40:
            t.sim(SIM_CLOCK_MIN, rng.randrange(0, 1440))
        elif roll < 0.50:
            t.sim(SIM_CLOUD, rng.randrange(0, 101))
        elif roll < 0.56:
            t.sim(SIM_GRID, rng.randrange(0, 2))
        elif roll < 0.62:
            t.sim(SIM_HEAT, rng.choice([HEAT_OFF, HEAT_OFF, 700, 749, 750, 949, 950, 1000]))
        elif roll < 0.68:
            t.sim(SIM_AMBIENT, rng.randrange(-400, 701))
        elif roll < 0.86:
            address = rng.choice(writable)
            t.pdu(pdu.write_single_request(address, rng.choice([0, 1, 2, 10, 30, 50, 100, 101, 600, 3600, 3601])))
        elif roll < 0.92:
            values = [rng.randrange(0, 101), 0, rng.choice([0, 5, 30]), rng.choice([0, 4, 10]), rng.randrange(0, 2)]
            t.pdu(pdu.write_multiple_request(limit, values))
        else:
            t.pdu(pdu.read_request(rng.choice([3, 4]), rng.randrange(39990, 40190), rng.randrange(0, 130)))
        if rng.random() < 0.5:
            t.read_all()
        else:
            t.read_inverter()
    talks.append(t)

    return [talk.as_dict() for talk in talks]


# ---- the last run -----------------------------------------------------------------------------------


def load_run() -> dict[str, Any]:
    """Merge ``evidence/run-<link>.json`` into one record per test with an outcome per link."""
    metas: dict[str, Any] = {}
    tests: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for link in LINKS:
        path = EVIDENCE / f"run-{link}.json"
        if not path.exists():
            continue
        run = json.loads(path.read_text())
        metas[link] = run["meta"]
        for test in run["tests"]:
            key = test["id"]
            if key not in tests:
                order.append(key)
                tests[key] = {
                    "suite": test["suite"],
                    "name": test["name"],
                    "params": test["params"],
                    "title": test["title"],
                    "links": {},
                }
            entry = tests[key]
            entry["links"][link] = {"o": test["outcome"][0], "ms": test["ms"], "n": test["frames"]}
            if test["outcome"] == "failed":
                entry["links"][link]["why"] = test["reason"]
            if test["outcome"] == "skipped":
                entry.setdefault("skip", {})[link] = test["reason"]
            # Keep the conversation of the first link on which the test ran.
            if test["outcome"] != "skipped" and "steps" not in entry:
                kept = 0
                steps = []
                for step in test["steps"]:
                    frames = step["frames"][: max(0, PAGE_FRAMES - kept)]
                    kept += len(frames)
                    steps.append({"text": step["text"], "frames": [[f[0], f[1].replace(" ", "")] for f in frames]})
                entry["steps"] = steps
                entry["via"] = link
    return {"meta": metas, "tests": [tests[key] for key in order]}


def load_mutants() -> dict[str, Any]:
    path = EVIDENCE / "mutants.json"
    if not path.exists():
        return {"meta": {}, "mutants": []}
    data: dict[str, Any] = json.loads(path.read_text())
    for mutant in data["mutants"]:
        mutant["killers"] = [{"name": k["name"], "suite": k["suite"]} for k in mutant["killers"][:6]]
    return data


# ---- the page ---------------------------------------------------------------------------------------

INCLUDE = re.compile(r"<!--\s*include:\s*(\S+)\s*-->")


def assemble() -> str:
    def include(match: re.Match[str]) -> str:
        path = SITE / match.group(1)
        text = path.read_text()
        if path.suffix == ".css":
            return f"<style>\n{text}</style>"
        if path.suffix == ".js":
            return "<script>\n" + text.replace("</script", "<\\/script") + "</script>"
        return INCLUDE.sub(include, text)

    return INCLUDE.sub(include, (SITE / "shell.html").read_text())


def check_translations(run: dict[str, Any], mutants: dict[str, Any]) -> list[str]:
    ru = json.loads((SITE / "i18n" / "ru.json").read_text())
    missing = sorted({t["name"] for t in run["tests"]} - set(ru["tests"]))
    missing += sorted({m["id"] for m in mutants["mutants"]} - set(ru["mutants"]))
    missing += sorted({t["suite"] for t in run["tests"]} - set(ru["suites"]))
    patterns = [re.compile(p) for p, _ in ru["steps"]]
    texts = {s["text"] for t in run["tests"] for s in t.get("steps", []) if s["text"]}
    missing += sorted(text for text in texts if not any(p.fullmatch(text) for p in patterns))
    return missing


def main(argv: list[str]) -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    (SITE / "test").mkdir(exist_ok=True)
    run = load_run()
    mutants = load_mutants()
    (DATA / "map.js").write_text(js("SIM_MAP", export_map()))
    (DATA / "run.js").write_text(js("RUN_DATA", run))
    (DATA / "mutants.js").write_text(js("MUTANT_DATA", mutants))
    ru = json.loads((SITE / "i18n" / "ru.json").read_text())
    (DATA / "ru.js").write_text(js("RU_DATA", ru))
    (SITE / "test" / "vectors.json").write_text(json.dumps(record_vectors(), separators=(",", ":")) + "\n")
    if "--check" in argv:
        missing = check_translations(run, mutants)
        if missing:
            print("no Russian text for:\n  " + "\n  ".join(missing), file=sys.stderr)
            return 1
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(assemble())
    size = OUT.stat().st_size / 1024
    print(f"{OUT.relative_to(ROOT)}: {size:.0f} KB, {len(run['tests'])} tests, {len(mutants['mutants'])} mutants")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
