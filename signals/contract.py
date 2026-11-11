"""Validation and serialization for the trend-signal contract.

Trend output is a shared artifact: Mehmet's evidence ledger links signals back
to source records, and Sueda's evaluation reads them for the trend-ranking
metric. The schema in ``schemas/trend_signal.schema.json`` is therefore treated
exactly like ``schemas/record.schema.json`` -- validated, not assumed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from signals.ewma import TrendSignal

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "trend_signal.schema.json"


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validator() -> Draft202012Validator:
    return Draft202012Validator(load_schema(), format_checker=FormatChecker())


def validate_trend_signal(signal: Mapping[str, Any]) -> list[str]:
    """Return human-readable schema errors for one signal, empty when valid."""
    return [error.message for error in validator().iter_errors(signal)]


def validate_trend_signals(signals: Iterable[Mapping[str, Any]]) -> list[tuple[str, str]]:
    """Return ``(trend_id, message)`` pairs for every invalid signal."""
    failures: list[tuple[str, str]] = []
    check = validator()
    for signal in signals:
        trend_id = str(signal.get("trend_id") or "<missing>")
        for error in check.iter_errors(signal):
            failures.append((trend_id, error.message))
    return failures


def to_payload(signals: Iterable[TrendSignal]) -> list[dict[str, Any]]:
    """Serialize signals and fail loudly if any of them breaks the contract."""
    payload = [signal.as_dict() for signal in signals]
    failures = validate_trend_signals(payload)
    if failures:
        raise ValueError(f"trend signals violate the shared contract: {failures[:5]}")
    return payload


def write_trend_signals(signals: Iterable[TrendSignal], path: Path) -> Path:
    """Write validated signals as JSON Lines, matching the records.jsonl style."""
    payload = to_payload(signals)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(signal, ensure_ascii=True, sort_keys=True) + "\n" for signal in payload),
        encoding="utf-8",
    )
    return path


def read_trend_signals(path: Path) -> list[dict[str, Any]]:
    """Load a trend-signal snapshot and fail loudly on invalid lines."""
    signals: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            signal = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {path} line {line_number}: {exc}") from exc
        errors = validate_trend_signal(signal)
        if errors:
            raise ValueError(f"invalid trend signal in {path} line {line_number}: {errors}")
        signals.append(signal)
    return signals


__all__ = [
    "SCHEMA_PATH",
    "load_schema",
    "read_trend_signals",
    "to_payload",
    "validate_trend_signal",
    "validate_trend_signals",
    "write_trend_signals",
]
