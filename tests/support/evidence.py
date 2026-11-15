"""Evidence of a test run: what every test did and the bytes it exchanged with the device.

The recorder is filled by ``TapLink`` (a link that notes every byte going by) and by ``step()``.
At the end of the run ``conftest.py`` saves it to ``evidence/run-<link>.json``; the page
"Last run, replayed" shows that file.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import allure

from inverter_lab.links import Link

MAX_FRAMES = 60  # frames kept per test; the total is still counted
MERGE_WINDOW_MS = 40.0  # chunks of one frame arrive within this time


@dataclass
class Step:
    text: str
    frames: list[list[Any]] = field(default_factory=list)  # [direction, hex, milliseconds]


@dataclass
class TestRecord:
    __test__ = False  # not a test class, whatever pytest thinks of the name

    id: str
    name: str
    suite: str
    title: str
    params: str = ""
    outcome: str = "passed"
    reason: str = ""
    ms: float = 0.0
    frames: int = 0
    steps: list[Step] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "suite": self.suite,
            "title": self.title,
            "params": self.params,
            "outcome": self.outcome,
            "reason": self.reason,
            "ms": round(self.ms, 1),
            "frames": self.frames,
            "steps": [{"text": s.text, "frames": s.frames} for s in self.steps if s.text or s.frames],
        }


class Recorder:
    def __init__(self) -> None:
        self.current: TestRecord | None = None
        self.records: list[TestRecord] = []

    def start(self, record: TestRecord) -> None:
        self.current = record
        self.records.append(record)

    def step(self, text: str) -> None:
        if self.current is not None:
            self.current.steps.append(Step(text))

    def frame(self, direction: str, data: bytes) -> None:
        record = self.current
        if record is None or not data:
            return
        now_ms = (time.monotonic() - record.started) * 1000
        if not record.steps:
            record.steps.append(Step(""))
        frames = record.steps[-1].frames
        last = frames[-1] if frames else None
        if last is not None and last[0] == direction == "rx" and now_ms - last[2] < MERGE_WINDOW_MS:
            last[1] += " " + data.hex(" ").upper()  # the rest of an answer that arrived in pieces
            return
        record.frames += 1
        if sum(len(s.frames) for s in record.steps) < MAX_FRAMES:
            frames.append([direction, data.hex(" ").upper(), round(now_ms, 1)])


RECORDER = Recorder()


@contextmanager
def step(text: str) -> Iterator[None]:
    """One step of a test in plain words. Shown in the Allure report and on the replay page."""
    RECORDER.step(text)
    with allure.step(text):
        yield


class TapLink:
    """A link that records every byte that goes through it."""

    def __init__(self, inner: Link) -> None:
        self.inner = inner

    def write(self, data: bytes) -> None:
        RECORDER.frame("tx", data)
        self.inner.write(data)

    def read(self, timeout: float) -> bytes:
        data = self.inner.read(timeout)
        RECORDER.frame("rx", data)
        return data

    def reset_input(self) -> None:
        self.inner.reset_input()

    def close(self) -> None:
        self.inner.close()


def trace_pymodbus(sending: bool, data: bytes) -> bytes:
    """Hook for pymodbus ``trace_packet``: record the packet and pass it on unchanged."""
    RECORDER.frame("tx" if sending else "rx", data)
    return data


def trace_sunspec(line: str) -> None:
    """Hook for pysunspec2 ``trace_func``: its lines look like ``> 0103...`` and ``< 0103...``."""
    direction, _, payload = line.strip().partition(" ")
    try:
        data = bytes.fromhex(payload)
    except ValueError:
        return
    RECORDER.frame("tx" if direction.startswith(">") else "rx", data)
