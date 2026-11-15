"""The official SunSpec model definitions, as shipped with pysunspec2.

They are the independent source the hand-written map in ``inverter_lab.sunspec`` is checked against.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import sunspec2


@dataclass(frozen=True)
class OfficialPoint:
    name: str
    type: str
    size: int
    offset: int  # registers from the start of the model, counting the ID and L registers
    sf: str | None
    mandatory: bool
    writable: bool
    symbols: dict[str, int]


@cache
def official_model(model_id: int) -> dict[str, Any]:
    path = Path(sunspec2.__file__).parent / "models" / "json" / f"model_{model_id}.json"
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def official_points(model_id: int) -> list[OfficialPoint]:
    """The points of a model after its ID and L registers."""
    points = []
    offset = 0
    for raw in official_model(model_id)["group"]["points"]:
        size = int(raw.get("size", 1))
        if raw["name"] not in ("ID", "L"):
            sf = raw.get("sf")
            points.append(
                OfficialPoint(
                    name=raw["name"],
                    type=raw["type"],
                    size=size,
                    offset=offset,
                    sf=sf if isinstance(sf, str) else None,
                    mandatory=raw.get("mandatory") == "M",
                    writable=raw.get("access") == "RW",
                    symbols={s["name"]: int(s["value"]) for s in raw.get("symbols", [])},
                )
            )
        offset += size
    return points


def official_length(model_id: int) -> int:
    return sum(p.size for p in official_points(model_id))
