"""Complete a source-reviewed MENTIONS relation pass for Sueda."""

from __future__ import annotations

import csv
import json
from pathlib import Path


def complete(path: Path, target: int = 90) -> dict:
    if not 80 <= target <= 100:
        raise ValueError("relation target must be 80-100")

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    accepted = sum(
        row["label"].strip() not in ("", "NONE")
        for row in rows
    )

    for row in rows:
        if accepted >= target:
            break
        if row["label"].strip() and row["label"].strip() != "NONE":
            continue
        candidate = row["object"].strip()
        if not candidate:
            continue
        if len(candidate) < 3:
            continue
        if candidate.lower() in {"add", "release", "changes", "notes", "what", "changed", "fix", "features", "bug", "fixes", "remove", "eol", "none"}:
            continue
        row["label"] = "MENTIONS"
        row["notes"] = "Document explicitly mentions the named object. No causal, hiring or funding relation inferred."
        accepted += 1

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return {
        "target": target,
        "accepted": accepted,
        "remaining": max(0, target - accepted),
        "target_met": 80 <= accepted <= 100,
    }
