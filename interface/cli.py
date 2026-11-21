"""Command line interface for the conversational agent and the evaluation runs.

Every retrieval condition and ablation the evaluation needs is a flag here, so
Sueda and Mehmet can produce the comparison conditions without editing code::

    # Ask one question, with citations, evidence states, and the graph path.
    python -m interface --demo --question \
        "Which agent-infrastructure startups show both rising GitHub activity and new MLOps hiring during the last eight weeks?"

    # Retrieval conditions, one per run.
    python -m interface --demo --seed-questions --mode bm25
    python -m interface --demo --seed-questions --mode dense
    python -m interface --demo --seed-questions --mode graph_only
    python -m interface --demo --seed-questions --mode hybrid

    # Ablations.
    python -m interface --demo --seed-questions --no-graph
    python -m interface --demo --seed-questions --no-temporal-fields
    python -m interface --demo --seed-questions --no-corroboration-weighting

    # The classical router baseline instead of the rules.
    python -m interface --demo --seed-questions --routing tfidf_logistic

    # Latency: run the seed set and report medians.
    python -m interface --demo --seed-questions --latency-log artifacts/latency.jsonl
    python scripts/latency_report.py artifacts/latency.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from interface.agent import AgentConfig, Answer, TrendScoutAgent, validate_answer
from interface.evidence import EvidenceConfig
from interface.latency import summarize
from retrieval.handoff import load_records_jsonl

ROOT = Path(__file__).resolve().parents[1]
DEMO_SNAPSHOT = ROOT / "tests" / "fixtures" / "faisal" / "snapshot_records.jsonl"
SEED_QUESTIONS = ROOT / "evaluation" / "questions.seed.json"
COHORT = ROOT / "data" / "registry" / "cohort.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m interface",
        description="Ask TrendScout AI a question over a frozen snapshot.",
    )
    source = parser.add_argument_group("snapshot")
    source.add_argument("--records", type=Path, help="A records.jsonl snapshot to answer from.")
    source.add_argument(
        "--demo",
        action="store_true",
        help="Replay the committed fixture snapshot. Works with no live source and no API key.",
    )
    source.add_argument("--cohort", type=Path, default=COHORT)

    ask = parser.add_argument_group("question")
    ask.add_argument("--question", help="A single question to answer.")
    ask.add_argument(
        "--seed-questions",
        action="store_true",
        help="Answer every question in evaluation/questions.seed.json.",
    )
    ask.add_argument("--requires", nargs="*", default=[], help="Evidence kinds this question needs.")
    ask.add_argument("-k", type=int, default=5, help="Passages to retrieve.")

    retrieval = parser.add_argument_group("retrieval condition")
    retrieval.add_argument(
        "--mode",
        choices=("hybrid", "bm25", "dense", "graph_only"),
        default="hybrid",
        help="Retrieval condition for the evaluation comparison.",
    )
    retrieval.add_argument("--encoder", help="Dense encoder: hashing, hashing:512, or a model name.")
    retrieval.add_argument("--routing", choices=("rules", "tfidf_logistic"), default="rules")
    retrieval.add_argument(
        "--keep-duplicate-origins",
        action="store_true",
        help="Allow several hits from one origin cluster (off by default).",
    )

    ablation = parser.add_argument_group("ablations")
    ablation.add_argument("--no-graph", action="store_true", help="Disable graph retrieval.")
    ablation.add_argument(
        "--no-temporal-fields",
        action="store_true",
        help="Disable time filtering and staleness; the window is still reported.",
    )
    ablation.add_argument(
        "--no-corroboration-weighting",
        action="store_true",
        help="Disable the corroboration ranking bonus (does not change evidence states).",
    )

    answer = parser.add_argument_group("answer")
    answer.add_argument(
        "--provider",
        help="extractive (default) or anthropic[:model]. Falls back to extractive with no API key.",
    )
    answer.add_argument("--min-origins", type=int, default=EvidenceConfig.minimum_independent_origins)
    answer.add_argument("--stale-after-days", type=int, help="Override the staleness threshold.")

    output = parser.add_argument_group("output")
    output.add_argument("--json", action="store_true", help="Print full answer bundles as JSON.")
    output.add_argument("--out", type=Path, help="Write answer bundles to this JSONL file.")
    output.add_argument("--latency-log", type=Path, help="Append per-stage latency to this JSONL file.")
    output.add_argument("--describe", action="store_true", help="Print the agent configuration and exit.")
    output.add_argument(
        "--validate",
        action="store_true",
        help="Validate every answer against schemas/answer.schema.json and fail on error.",
    )
    return parser


def _evidence_config(args: argparse.Namespace) -> EvidenceConfig:
    if args.stale_after_days:
        return EvidenceConfig(
            minimum_independent_origins=args.min_origins,
            refresh_window_days=args.stale_after_days,
            allowed_missed_refresh_windows=1,
        )
    return EvidenceConfig(minimum_independent_origins=args.min_origins)


def _agent(args: argparse.Namespace) -> TrendScoutAgent:
    if args.demo:
        records_path = DEMO_SNAPSHOT
    elif args.records:
        records_path = args.records
    else:
        raise SystemExit("choose a snapshot: --demo for the committed fixture, or --records PATH")
    if not records_path.exists():
        raise SystemExit(f"snapshot not found: {records_path}")

    records = load_records_jsonl(records_path)
    cohort = json.loads(args.cohort.read_text(encoding="utf-8")) if args.cohort.exists() else {}
    config = AgentConfig(
        mode=args.mode,
        k=args.k,
        routing_method=args.routing,
        provider=args.provider,
        encoder=args.encoder,
        distinct_origins=not args.keep_duplicate_origins,
        use_graph=not args.no_graph,
        use_temporal_fields=not args.no_temporal_fields,
        use_corroboration_weighting=not args.no_corroboration_weighting,
        demo_mode=bool(args.demo),
    )
    return TrendScoutAgent(
        records,
        config=config,
        evidence_config=_evidence_config(args),
        cohort=cohort,
        latency_log=args.latency_log,
        snapshot_id=f"{records_path.name}@{len(records)}records",
    )


def print_answer(answer: Answer) -> None:
    print("\n" + "=" * 78)
    print(f"Q: {answer.question}")
    print(
        f"   intent={answer.route.intent} ({answer.route.method}, confidence "
        f"{answer.route.confidence:.2f})"
    )
    print(f"   window: {answer.time_window.label}")
    if answer.time_window.start:
        print(f"           {answer.time_window.start} .. {answer.time_window.end}")
    print(f"   evidence state: {answer.overall_state}")
    print("-" * 78)
    print(answer.answer_text)
    if answer.abstained:
        print(f"\n[abstained] {answer.abstention_reason}")
    if answer.qualification:
        print(f"\n[qualified] {answer.qualification}")
    if answer.missing_evidence:
        print(f"[missing]   {', '.join(answer.missing_evidence)}")

    if answer.claims:
        print("\nClaims and evidence states:")
        for index, claim in enumerate(answer.claims, start=1):
            marker = " " if claim.supported else "!"
            citations = "".join(f"[{number}]" for number in claim.citation_numbers) or "[uncited]"
            print(f" {marker}{index}. {claim.assessment.state:<13} {citations} {claim.text[:92]}")
            if not claim.supported:
                print(f"       unsupported: {claim.assessment.reason}")

    if answer.citations:
        print("\nCitations:")
        for citation in answer.citations:
            where = citation.source_url or citation.detail.get("cypher_name") or citation.detail.get("series_id") or ""
            print(
                f" [{citation.number}] {citation.kind:<8} {citation.source_type or '-':<12} "
                f"{(citation.title or '')[:52]:<52} {citation.when or '-'}"
            )
            if where:
                print(f"      {where}")

    if answer.graph_paths:
        print("\nGraph path:")
        for path in answer.graph_paths[:3]:
            print(f"  {path.render()}")

    print(f"\nLatency (ms): {json.dumps(answer.latency, sort_keys=True)}")
    provider = answer.provider
    note = f" (fallback: {provider.fallback_reason})" if provider.fallback_used else ""
    print(f"Provider: {provider.provider}{'/' + provider.model if provider.model else ''}{note}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    agent = _agent(args)

    if args.describe:
        print(json.dumps(agent.describe(), indent=2, sort_keys=True, default=str))
        return 0

    questions: list[dict[str, Any]] = []
    if args.question:
        questions.append({"question_id": "cli", "question": args.question, "needs": args.requires})
    if args.seed_questions:
        seed = json.loads(SEED_QUESTIONS.read_text(encoding="utf-8"))
        questions.extend(
            {
                "question_id": item["question_id"],
                "question": item["question"],
                "needs": item.get("needs", []),
                "expected_behavior": item.get("expected_behavior"),
            }
            for item in seed["questions"]
        )
    if not questions:
        raise SystemExit("nothing to do: pass --question TEXT or --seed-questions")

    answers: list[Answer] = []
    failures: list[tuple[str, list[str]]] = []
    for item in questions:
        answer = agent.answer(
            item["question"], requires=item.get("needs", []), k=args.k, question_id=item["question_id"]
        )
        answers.append(answer)
        if args.validate:
            errors = validate_answer(answer.as_dict())
            if errors:
                failures.append((item["question_id"], errors))
        if args.json:
            print(json.dumps(answer.as_dict(), indent=2, sort_keys=True, default=str))
        else:
            print_answer(answer)
            if item.get("expected_behavior"):
                print(f"Seed expectation: {item['expected_behavior']}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            "".join(
                json.dumps(answer.as_dict(), sort_keys=True, default=str) + "\n" for answer in answers
            ),
            encoding="utf-8",
        )
        print(f"\nWrote {len(answers)} answer bundle(s) to {args.out}")

    if len(answers) > 1 and not args.json:
        entries = [{"latency": answer.latency} for answer in answers]
        summary = summarize(entries, target_median_ms=agent.config.target_median_ms)
        print("\n" + "=" * 78)
        print(
            f"{summary['requests']} questions | median total "
            f"{summary['median_total_ms']} ms | p90 {summary['p90_total_ms']} ms | "
            f"target {summary['target_median_ms']} ms | meets target: {summary['meets_target']}"
        )
        abstained = sum(1 for answer in answers if answer.abstained)
        qualified = sum(1 for answer in answers if answer.qualified)
        unsupported = sum(answer.unsupported_claim_count for answer in answers)
        claims = sum(len(answer.claims) for answer in answers)
        print(
            f"abstained {abstained}/{len(answers)} | qualified {qualified}/{len(answers)} | "
            f"unsupported claims {unsupported}/{claims}"
        )

    if failures:
        print("\nSchema validation failed:", file=sys.stderr)
        for question_id, errors in failures:
            print(f"  {question_id}: {errors[:3]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
