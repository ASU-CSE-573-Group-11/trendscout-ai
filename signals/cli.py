"""Command line entry point for the weekly features and EWMA trend baseline.

Examples::

    # Score the committed fixture snapshot and write a bundle.
    python -m signals --records tests/fixtures/faisal/snapshot_records.jsonl \
        --out artifacts/trends/fixture

    # Answer the first prototype question over the last eight weeks.
    python -m signals --records tests/fixtures/faisal/snapshot_records.jsonl \
        --question rising-with-hiring --weeks 8 --hiring-family mlops

    # Emit Cypher for the evidence ledger without touching a database.
    python -m signals --records tests/fixtures/faisal/snapshot_records.jsonl \
        --cypher --max-statements 5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from retrieval.handoff import load_records_jsonl
from signals.ewma import TrendConfig
from signals.github_features import GitHubFeatureConfig
from signals.graph_export import trend_import_statements
from signals.job_features import JobFeatureConfig
from signals.topics import TopicConfig
from signals.pipeline import (
    companies_missing_signal,
    resolve_window,
    rising_with_new_hiring,
    run_trend_pipeline,
    write_trend_bundle,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m signals",
        description="Weekly GitHub/hiring/attention features and EWMA trend scoring.",
    )
    parser.add_argument(
        "--records",
        type=Path,
        required=True,
        help="Path to a records.jsonl snapshot validated against schemas/record.schema.json.",
    )
    parser.add_argument("--out", type=Path, help="Directory to write the trend bundle into.")
    parser.add_argument(
        "--question",
        choices=("rising-with-hiring", "labels", "series"),
        help="Print one canned analysis instead of the full signal list.",
    )
    parser.add_argument("--weeks", type=int, default=8, help="Relative window length in ISO weeks.")
    parser.add_argument("--last-week", help="Anchor the window on this ISO week, e.g. 2026-W44.")
    parser.add_argument("--metric", default="commits", help="Activity metric for --question.")
    parser.add_argument("--hiring-family", default="mlops", help="Role family for --question.")
    parser.add_argument(
        "--hiring-metric", default="new_postings", help="Hiring metric for --question."
    )

    trend = parser.add_argument_group("trend parameters")
    trend.add_argument("--alpha", type=float, default=TrendConfig.alpha)
    trend.add_argument("--window", type=int, default=TrendConfig.window)
    trend.add_argument("--threshold", type=float, default=TrendConfig.threshold)
    trend.add_argument("--min-history", type=int, default=TrendConfig.min_history)
    trend.add_argument("--min-scale", type=float, default=TrendConfig.min_scale)
    trend.add_argument("--scale-method", choices=("std", "mad"), default=TrendConfig.scale_method)

    quality = parser.add_argument_group("repository quality")
    quality.add_argument("--include-forks", action="store_true")
    quality.add_argument("--include-mirrors", action="store_true")
    quality.add_argument("--include-archived", action="store_true")
    quality.add_argument(
        "--drop-bot-heavy",
        action="store_true",
        help="Exclude bot-heavy repositories entirely instead of flagging them.",
    )
    topics = parser.add_argument_group("topic baseline (proposal section 3)")
    topics.add_argument(
        "--topics",
        type=int,
        help="Fit the LDA topic baseline with this many topics and emit weekly topic series.",
    )
    topics.add_argument("--topic-iterations", type=int, default=300)
    topics.add_argument("--topic-seed", type=int, default=20261110)

    quality.add_argument(
        "--include-unavailable-metrics",
        action="store_true",
        help="Emit explicitly unavailable metrics (releases, issues opened/closed, contributors).",
    )

    parser.add_argument("--cypher", action="store_true", help="Print trend-signal Cypher statements.")
    parser.add_argument("--max-statements", type=int, default=10)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser


def _trend_config(args: argparse.Namespace) -> TrendConfig:
    return TrendConfig(
        alpha=args.alpha,
        window=args.window,
        threshold=args.threshold,
        min_history=args.min_history,
        min_scale=args.min_scale,
        scale_method=args.scale_method,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    records = load_records_jsonl(args.records)

    run = run_trend_pipeline(
        records,
        config=_trend_config(args),
        github_config=GitHubFeatureConfig(
            include_forks=args.include_forks,
            include_mirrors=args.include_mirrors,
            include_archived=args.include_archived,
            drop_bot_heavy_repositories=args.drop_bot_heavy,
            include_unavailable_metrics=args.include_unavailable_metrics,
        ),
        job_config=JobFeatureConfig(),
        include_topics=bool(args.topics),
        topic_config=(
            TopicConfig(
                topics=args.topics,
                iterations=args.topic_iterations,
                seed=args.topic_seed,
            )
            if args.topics
            else None
        ),
    )

    window = resolve_window(run, weeks=args.weeks, last_week=args.last_week)
    report: dict[str, Any] = {
        "records": len(records),
        "snapshot_week": run.snapshot_week,
        "last_data_week": run.last_data_week,
        "window": window,
        "series_count": len(run.bundle.series),
        "signal_count": len(run.signals),
        "labels": run.labels(),
        "trend_config": run.config.as_dict(),
    }
    if run.bundle.topic_model is not None:
        described = run.bundle.topic_model.describe()
        report["topics"] = described
        if not args.json:
            print(f"LDA baseline: {described['documents']} documents, "
                  f"{described['vocabulary']} terms, {len(described['topics'])} topics")
            for topic in described["topics"]:
                print(f"  {topic['topic_id']} weight={topic['weight']:.3f}  {topic['label']}")
            if described["caveat"]:
                print(f"  caveat: {described['caveat']}")

    if args.question == "rising-with-hiring":
        matches = rising_with_new_hiring(
            run,
            weeks=window,
            activity_metric=args.metric,
            hiring_family=args.hiring_family,
            hiring_metric=args.hiring_metric,
        )
        report["rising_with_hiring"] = matches
        report["insufficient_history"] = companies_missing_signal(
            run, weeks=window, metric=args.metric
        )
        if not args.json:
            print(
                f"Window {window[0]}..{window[-1]} | activity={args.metric} "
                f"hiring={args.hiring_family}/{args.hiring_metric}"
                if window
                else "No window could be resolved."
            )
            if not matches:
                print("No company shows both signals in this window.")
            for match in matches:
                scores = ", ".join(
                    f"{week}={score:.2f}"
                    for week, score in zip(match["activity_weeks"], match["activity_scores"])
                    if score is not None
                )
                hiring = ", ".join(
                    f"{week}=+{int(value)}"
                    for week, value in zip(match["hiring_weeks"], match["new_postings"])
                )
                print(f"  {match['company_id']}: rising [{scores}] | new postings [{hiring}]")
                print(f"    evidence: {len(match['record_ids'])} source records")
            gaps = report["insufficient_history"]
            if gaps:
                print("  insufficient history (not evidence of decline):")
                for company_id, weeks in gaps.items():
                    print(f"    {company_id}: {', '.join(weeks)}")
    elif args.question == "series":
        report["series"] = [series.as_dict() for series in run.bundle.series]
        if not args.json:
            for series in run.bundle.series:
                observed = series.observed_week_count
                print(f"{series.series_id} [{observed}/{len(series)} weeks observed]")
    elif args.question == "labels" and not args.json:
        for label, count in run.labels().items():
            print(f"{label:24s} {count}")

    if args.cypher:
        statements = trend_import_statements(run.payload())
        report["cypher_statement_count"] = len(statements)
        if not args.json:
            print(f"\n{len(statements)} Cypher statements; first {args.max_statements}:")
            for statement, parameters in statements[: args.max_statements]:
                print(f"  {statement}")
                print(f"    params: {json.dumps(parameters, sort_keys=True)[:160]}")

    if args.out:
        paths = write_trend_bundle(run, args.out)
        report["written"] = {name: str(path) for name, path in paths.items()}
        if not args.json:
            print("\nWrote:")
            for name, path in paths.items():
                print(f"  {name}: {path}")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    elif not args.question and not args.cypher and not args.out:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
