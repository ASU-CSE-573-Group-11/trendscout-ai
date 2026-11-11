"""Per-stage latency timing, written to JSON Lines.

The proposal's secondary target is a median response under eight seconds, and
"median response" is only actionable if the stages are separated: parsing,
routing, retrieval, the graph query, and generation fail slowly for different
reasons.

Timings use ``time.perf_counter`` and are recorded in milliseconds. Nothing here
is sampled or averaged at write time; the raw per-request record is kept so
``scripts/latency_report.py`` can compute the median and p90 afterwards from
whatever slice is of interest.
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

STAGES: tuple[str, ...] = ("parse", "route", "retrieve", "graph", "generate")


@dataclass
class StageTimings:
    """Accumulated stage durations for one request."""

    stages: dict[str, float] = field(default_factory=dict)
    started: float = field(default_factory=time.perf_counter)

    def time(self, stage: str) -> "_StageContext":
        return _StageContext(self, stage)

    def add(self, stage: str, milliseconds: float) -> None:
        self.stages[stage] = self.stages.get(stage, 0.0) + milliseconds

    @property
    def total_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000.0

    def as_dict(self) -> dict[str, float]:
        payload = {stage: round(value, 3) for stage, value in self.stages.items()}
        payload["total"] = round(self.total_ms, 3)
        # The parts need not sum to the total; the gap is orchestration and is
        # reported rather than hidden inside a stage.
        payload["unattributed"] = round(
            max(0.0, payload["total"] - sum(value for key, value in payload.items() if key != "total")),
            3,
        )
        return payload


class _StageContext:
    def __init__(self, timings: StageTimings, stage: str) -> None:
        self._timings = timings
        self._stage = stage
        self._start = 0.0

    def __enter__(self) -> "_StageContext":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._timings.add(self._stage, (time.perf_counter() - self._start) * 1000.0)


@dataclass
class LatencyLog:
    """Append-only JSONL latency log."""

    path: Path
    enabled: bool = True

    def record(self, entry: Mapping[str, Any]) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=True, sort_keys=True, default=str)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Nearest-rank percentile, which needs no interpolation choice."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = max(0, min(len(ordered) - 1, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def summarize(entries: Iterable[Mapping[str, Any]], *, target_median_ms: float = 8000.0) -> dict[str, Any]:
    """Median and p90 per stage, plus whether the latency target is met."""
    entries = list(entries)
    per_stage: dict[str, list[float]] = {}
    for entry in entries:
        timings = entry.get("latency") or {}
        for stage, value in timings.items():
            if isinstance(value, (int, float)):
                per_stage.setdefault(stage, []).append(float(value))

    summary: dict[str, Any] = {
        "requests": len(entries),
        "target_median_ms": target_median_ms,
        "stages": {},
    }
    for stage, values in sorted(per_stage.items()):
        summary["stages"][stage] = {
            "count": len(values),
            "median_ms": round(statistics.median(values), 3),
            "p90_ms": round(percentile(values, 0.90) or 0.0, 3),
            "max_ms": round(max(values), 3),
        }
    totals = per_stage.get("total", [])
    if totals:
        median_total = statistics.median(totals)
        summary["median_total_ms"] = round(median_total, 3)
        summary["p90_total_ms"] = round(percentile(totals, 0.90) or 0.0, 3)
        summary["meets_target"] = median_total <= target_median_ms
    else:
        summary["median_total_ms"] = None
        summary["p90_total_ms"] = None
        summary["meets_target"] = None
    return summary


__all__ = ["STAGES", "LatencyLog", "StageTimings", "percentile", "summarize"]
