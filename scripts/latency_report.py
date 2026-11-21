"""Report median and p90 latency per stage from an interface latency log.

Usage::

    python scripts/latency_report.py artifacts/latency.jsonl
    python scripts/latency_report.py artifacts/latency.jsonl --mode hybrid --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interface.latency import LatencyLog, summarize  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="JSONL latency log written by the interface.")
    parser.add_argument("--mode", help="Only include entries from this retrieval mode.")
    parser.add_argument("--intent", help="Only include entries with this routed intent.")
    parser.add_argument("--target-ms", type=float, default=8000.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not args.log.exists():
        raise SystemExit(f"latency log not found: {args.log}")

    entries = LatencyLog(path=args.log).entries()
    if args.mode:
        entries = [entry for entry in entries if entry.get("mode") == args.mode]
    if args.intent:
        entries = [entry for entry in entries if entry.get("intent") == args.intent]
    if not entries:
        raise SystemExit("no entries matched the filters")

    summary = summarize(entries, target_median_ms=args.target_ms)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    print(f"{summary['requests']} requests from {args.log}")
    if args.mode or args.intent:
        print(f"filters: mode={args.mode or 'any'} intent={args.intent or 'any'}")
    print(f"{'stage':<16}{'count':>7}{'median ms':>12}{'p90 ms':>10}{'max ms':>10}")
    for stage, values in summary["stages"].items():
        print(
            f"{stage:<16}{values['count']:>7}{values['median_ms']:>12.1f}"
            f"{values['p90_ms']:>10.1f}{values['max_ms']:>10.1f}"
        )
    verdict = {True: "met", False: "MISSED", None: "unknown"}[summary["meets_target"]]
    print(
        f"\nmedian total {summary['median_total_ms']} ms against a "
        f"{summary['target_median_ms']} ms target: {verdict}"
    )
    by_intent: dict[str, int] = {}
    for entry in entries:
        by_intent[str(entry.get("intent"))] = by_intent.get(str(entry.get("intent")), 0) + 1
    print("intents: " + ", ".join(f"{key}={value}" for key, value in sorted(by_intent.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
