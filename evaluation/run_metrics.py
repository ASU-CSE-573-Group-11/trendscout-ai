"""Score answer bundles and compare retrieval conditions side by side.

Produce the bundles first, one file per condition::

    for mode in hybrid bm25 dense graph_only; do
      python -m interface --demo --seed-questions --mode $mode \
          --out artifacts/answers-$mode.jsonl
    done

Then score them::

    python evaluation/run_metrics.py artifacts/answers-*.jsonl
    python evaluation/run_metrics.py artifacts/answers-*.jsonl --qrels evaluation/qrels.example.json
    python evaluation/run_metrics.py artifacts/answers-hybrid.jsonl --match origin --json

Without ``--qrels`` the retrieval metrics print as ``n/a``: they need human
judgements, and a zero there would read as a measured result.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.metrics import (  # noqa: E402
    check_thresholds,
    condition_name,
    load_answers,
    load_qrels,
    load_seed_expectations,
    load_thresholds,
    qrels_are_illustrative,
    score_condition,
    score_trend_ranking,
)


def _format(value: Any, width: int = 9, places: int = 3) -> str:
    if value is None:
        return "n/a".rjust(width)
    if isinstance(value, float):
        return f"{value:.{places}f}".rjust(width)
    return str(value).rjust(width)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("answers", nargs="+", type=Path, help="Answer-bundle JSONL files.")
    parser.add_argument("--qrels", type=Path, help="Relevance judgements.")
    parser.add_argument("--questions", type=Path, help="Seed questions (default: the repo's).")
    parser.add_argument("-k", type=int, default=5, help="Cut-off for the ranking metrics.")
    parser.add_argument(
        "--match",
        choices=("record", "origin"),
        default="record",
        help="Judge relevance per record, or credit any copy of a relevant origin.",
    )
    parser.add_argument("--trend-signals", type=Path, help="trend_signals.jsonl for trend ranking.")
    parser.add_argument("--trend-rubric", type=Path, help="Weekly rubric: {iso_week: [entity, ...]}.")
    parser.add_argument("--json", action="store_true", help="Print the full report as JSON.")
    parser.add_argument("--out", type=Path, help="Write the JSON report here.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.qrels:
        if not args.qrels.exists():
            raise SystemExit(
                f"qrels file not found: {args.qrels}. "
                "Complete human adjudication and create evaluation/adjudicated-qrels.json "
                "before running a scored retrieval evaluation."
            )
        qrels = load_qrels(args.qrels)
        illustrative, why = qrels_are_illustrative(args.qrels)
    else:
        qrels = {}
        illustrative, why = False, ""
    expectations = load_seed_expectations(args.questions)
    thresholds = load_thresholds(args.questions)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in args.answers:
        if not path.exists():
            raise SystemExit(f"answer file not found: {path}")
        for bundle in load_answers(path):
            grouped[condition_name(bundle)].append(bundle)
    if not grouped:
        raise SystemExit("no answer bundles found")

    reports = [
        score_condition(
            bundles,
            condition=condition,
            qrels=qrels,
            k=args.k,
            match=args.match,
            expectations=expectations,
        )
        for condition, bundles in sorted(grouped.items())
    ]

    payload: dict[str, Any] = {
        "k": args.k,
        "match": args.match,
        "qrels_supplied": bool(qrels),
        "qrels_illustrative": illustrative,
        "qrels_warning": why or None,
        "judged_questions_available": len(qrels),
        "thresholds": thresholds,
        "conditions": [report.as_dict() for report in reports],
        "threshold_checks": {
            report.condition: check_thresholds(report, thresholds) for report in reports
        },
    }

    if args.trend_signals and args.trend_rubric:
        signals = [
            json.loads(line)
            for line in args.trend_signals.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        rubric_payload = json.loads(args.trend_rubric.read_text(encoding="utf-8"))
        rubric = rubric_payload.get("rubric", rubric_payload)
        payload["trend_ranking"] = score_trend_ranking(signals, rubric, k=args.k)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    k = args.k
    print(f"Scoring {sum(len(items) for items in grouped.values())} answer bundles "
          f"across {len(reports)} condition(s), k={k}, match={args.match}")
    if not qrels:
        print("No relevance judgements supplied: retrieval metrics are n/a, not zero.")
    if illustrative:
        banner = "!" * 78
        print("")
        print(banner)
        print("ILLUSTRATIVE LABELS - DO NOT REPORT THESE RETRIEVAL NUMBERS")
        if why:
            print(why)
        print(banner)
    print()
    header = (
        f"{'condition':<26}{'P@'+str(k):>9}{'R@'+str(k):>9}{'MRR':>9}"
        f"{'nDCG@'+str(k):>10}{'cite P':>9}{'support':>9}{'unsup':>9}{'abst':>7}{'med ms':>9}"
    )
    print(header)
    print("-" * len(header))
    for report in reports:
        print(
            f"{report.condition:<26}"
            f"{_format(report.retrieval.get(f'precision_at_{k}'))}"
            f"{_format(report.retrieval.get(f'recall_at_{k}'))}"
            f"{_format(report.retrieval.get('mrr'))}"
            f"{_format(report.retrieval.get(f'ndcg_at_{k}'), width=10)}"
            f"{_format(report.answer_quality.get('citation_precision'))}"
            f"{_format(report.answer_quality.get('claim_support_rate'))}"
            f"{_format(report.answer_quality.get('unsupported_claim_rate'))}"
            f"{_format(report.abstention.get('accuracy'), width=7, places=2)}"
            f"{_format(report.latency.get('median_ms'), places=1)}"
        )

    print("\nAgainst the proposal's success thresholds:")
    for report in reports:
        checks = payload["threshold_checks"][report.condition]
        for check in checks:
            status = {True: "pass", False: "FAIL", None: "n/a"}[check["passed"]]
            value = "n/a" if check["value"] is None else f"{check['value']:.4f}"
            print(
                f"  {report.condition:<26}{check['metric']:<28}{value:>10}  "
                f"({check['comparison']} {check['threshold']})  {status}"
            )

    for report in reports:
        if report.abstention.get("missed_abstentions"):
            print(
                f"\n{report.condition}: answered when it should have abstained -> "
                f"{', '.join(report.abstention['missed_abstentions'])}"
            )
        if report.abstention.get("false_abstentions"):
            print(
                f"{report.condition}: abstained when it should have answered -> "
                f"{', '.join(report.abstention['false_abstentions'])}"
            )
        for note in report.notes:
            print(f"  note ({report.condition}): {note}")

    if "trend_ranking" in payload:
        trend = payload["trend_ranking"]
        print(
            f"\nTrend ranking on {len(trend['weeks_scored'])} week(s): "
            f"P@{k}={trend[f'precision_at_{k}']}, "
            f"false-alert rate={trend['false_alert_rate']} "
            f"({trend['false_alerts']}/{trend['rising_alerts']} rising alerts)"
        )

    if args.out:
        print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
