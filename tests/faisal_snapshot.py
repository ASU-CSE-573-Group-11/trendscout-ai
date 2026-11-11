"""Loaders for the fixture snapshot used by the trend and retrieval tests.

Not a test module. The fixtures reproduce the record layout of Vidya's
``vidya/api-collectors`` branch; regenerate them with
``python scripts/build_faisal_fixtures.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures" / "faisal"

GITHUB_RECORDS = FIXTURES / "github_records.jsonl"
JOB_RECORDS = FIXTURES / "job_records.jsonl"
DOCUMENT_RECORDS = FIXTURES / "document_records.jsonl"
SNAPSHOT_RECORDS = FIXTURES / "snapshot_records.jsonl"
SNAPSHOT_MANIFEST = FIXTURES / "snapshot.json"

#: The two syndicated fixture articles share this origin cluster.
SYNDICATED_ORIGIN = "faisalfixture0001"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def github_records() -> list[dict[str, Any]]:
    return load_jsonl(GITHUB_RECORDS)


def job_records() -> list[dict[str, Any]]:
    return load_jsonl(JOB_RECORDS)


def document_records() -> list[dict[str, Any]]:
    return load_jsonl(DOCUMENT_RECORDS)


def snapshot_records() -> list[dict[str, Any]]:
    return load_jsonl(SNAPSHOT_RECORDS)


def manifest() -> dict[str, Any]:
    return json.loads(SNAPSHOT_MANIFEST.read_text(encoding="utf-8"))
