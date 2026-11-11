"""Scoring for the answer bundles the interface emits.

Owner note: ``evaluation/`` is Sueda's module and the evaluation *design* is
hers. This file is scaffolding so that the moment relevance labels exist the
scored run is one command rather than new code, and so the metrics that need no
labels can be reported today. She owns the labels, the thresholds, and the
interpretation, and is free to replace any of this.

What needs labels and what does not
-----------------------------------
Three of the proposal's metric families can be computed from an answer bundle
alone, because the bundle already records what the system did:

* abstention accuracy, against ``expected_behavior`` in the seed questions;
* claim-support rate and unsupported-claim rate, from each claim's ``supported``
  flag;
* median and p90 latency.

The retrieval family (Precision@k, Recall@k, MRR, nDCG@k) and citation
precision need human judgements. Supply them with ``--qrels``; without them
those metrics are reported as ``null`` and the unjudged count is stated, rather
than being filled with a default that would read as a result.

Judging unit
------------
Relevance is judged per ``record_id``. ``--match origin`` instead credits a
citation whose ``origin_cluster_id`` matches a relevant record's origin, which
is the right unit when syndicated copies of one story are all acceptable
evidence. Both are reported so the choice is visible.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
SEED_QUESTIONS = ROOT / "evaluation" / "questions.seed.json"

#: Metrics that cannot be computed without human relevance judgements.
NEEDS_LABELS: tuple[str, ...] = (
    "precision_at_k",
    "recall_at_k",
    "mrr",
    "ndcg_at_k",
    "citation_precision",
)


# ---------------------------------------------------------------------------
# Ranking metrics
# ---------------------------------------------------------------------------


def precision_at_k(retrieved: Sequence[str], relevant: Mapping[str, float], k: int) -> float:
    """Fraction of the top ``k`` results that are relevant.

    The denominator is ``k``, not the number retrieved: an answer that cites
    two documents and gets both right has not achieved Precision@5 of 1.0.
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    top = retrieved[:k]
    hits = sum(1 for item in top if relevant.get(item, 0) > 0)
    return hits / k


def recall_at_k(retrieved: Sequence[str], relevant: Mapping[str, float], k: int) -> float | None:
    """Fraction of all relevant items that appear in the top ``k``.

    ``None`` when the question has no relevant items, which is not a score of
    zero: there was nothing to find.
    """
    positives = {item for item, grade in relevant.items() if grade > 0}
    if not positives:
        return None
    found = sum(1 for item in retrieved[:k] if item in positives)
    return found / len(positives)


def reciprocal_rank(retrieved: Sequence[str], relevant: Mapping[str, float]) -> float:
    """1/rank of the first relevant result, or 0 when none is retrieved."""
    for index, item in enumerate(retrieved, start=1):
        if relevant.get(item, 0) > 0:
            return 1.0 / index
    return 0.0


def dcg(grades: Sequence[float]) -> float:
    return sum((2**grade - 1) / math.log2(index + 1) for index, grade in enumerate(grades, start=1))


def ndcg_at_k(retrieved: Sequence[str], relevant: Mapping[str, float], k: int) -> float | None:
    """Graded nDCG@k. ``None`` when the question has no relevant items."""
    ideal_grades = sorted((grade for grade in relevant.values() if grade > 0), reverse=True)[:k]
    if not ideal_grades:
        return None
    ideal = dcg(ideal_grades)
    if ideal == 0:
        return None
    actual = dcg([float(relevant.get(item, 0)) for item in retrieved[:k]])
    return actual / ideal


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def load_answers(path: Path) -> list[dict[str, Any]]:
    """Load answer bundles written by ``python -m interface --out``."""
    bundles = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            bundles.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid answer bundle in {path} line {number}: {exc}") from exc
    return bundles


def qrels_are_illustrative(path: Path) -> tuple[bool, str]:
    """Whether a label file declares itself a demonstration rather than judgements.

    A placeholder label file is the easiest way for a number to escape into a
    report as though it were measured, so the flag is machine-readable and the
    runner refuses to print quietly over it.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    return bool(payload.get("illustrative")), str(payload.get("why_illustrative") or "")


def load_qrels(path: Path) -> dict[str, dict[str, float]]:
    """Load relevance judgements.

    Format::

        {
          "judged_by": "two annotators, adjudicated",
          "snapshot": "...",
          "qrels": {
            "<question_id>": {"<record_id>": 2, "<record_id>": 1}
          }
        }

    Grades are non-negative numbers; 0 means judged and not relevant, which is
    different from absent (unjudged).
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("qrels", payload)
    if not isinstance(raw, dict):
        raise ValueError(f"{path} does not contain a qrels object")
    qrels: dict[str, dict[str, float]] = {}
    for question_id, judgements in raw.items():
        if not isinstance(judgements, dict):
            raise ValueError(f"qrels for {question_id!r} must map record ids to grades")
        parsed: dict[str, float] = {}
        for record_id, grade in judgements.items():
            value = float(grade)
            if value < 0:
                raise ValueError(f"negative grade for {question_id}/{record_id}")
            parsed[record_id] = value
        qrels[question_id] = parsed
    return qrels


def load_seed_expectations(path: Path | None = None) -> dict[str, str]:
    """``question_id -> expected_behavior`` from the seed question set."""
    path = path or SEED_QUESTIONS
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        item["question_id"]: item.get("expected_behavior", "")
        for item in payload.get("questions", [])
    }


def load_thresholds(path: Path | None = None) -> dict[str, float]:
    path = path or SEED_QUESTIONS
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload.get("metrics", {}).get("success_thresholds", {}))


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class ConditionReport:
    """Scores for one retrieval condition."""

    condition: str
    questions: int
    judged_questions: int
    retrieval: dict[str, float | None] = field(default_factory=dict)
    answer_quality: dict[str, float | None] = field(default_factory=dict)
    abstention: dict[str, Any] = field(default_factory=dict)
    latency: dict[str, float | None] = field(default_factory=dict)
    per_question: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "questions": self.questions,
            "judged_questions": self.judged_questions,
            "retrieval": self.retrieval,
            "answer_quality": self.answer_quality,
            "abstention": self.abstention,
            "latency": self.latency,
            "notes": self.notes,
            "per_question": self.per_question,
        }


def condition_name(bundle: Mapping[str, Any]) -> str:
    """A readable label for the condition a bundle was produced under."""
    config = bundle.get("config") or {}
    ablations = config.get("ablations") or {}
    parts = [str(config.get("mode", "unknown"))]
    if config.get("routing_method") and config["routing_method"] != "rules":
        parts.append(config["routing_method"])
    for key, label in (
        ("graph_retrieval", "no-graph"),
        ("temporal_fields", "no-temporal"),
        ("corroboration_weighting", "no-corroboration"),
    ):
        if ablations.get(key) is False:
            parts.append(label)
    return "+".join(parts)


def cited_items(bundle: Mapping[str, Any], *, match: str = "record") -> list[str]:
    """The retrieved items of a bundle, in citation order.

    Only passage citations are scored. Trend and graph citations are derived
    evidence rather than retrieved documents, so including them would inflate
    a retrieval metric with things retrieval never ranked.
    """
    items: list[str] = []
    seen: set[str] = set()
    for citation in bundle.get("citations") or []:
        if citation.get("kind") != "passage":
            continue
        keys = (
            citation.get("origin_cluster_ids") or []
            if match == "origin"
            else citation.get("record_ids") or []
        )
        for key in keys:
            if key not in seen:
                seen.add(key)
                items.append(key)
    return items


def _origin_qrels(
    qrels: Mapping[str, float], bundles: Iterable[Mapping[str, Any]]
) -> dict[str, float]:
    """Project record-level judgements onto origin clusters."""
    mapping: dict[str, float] = {}
    for bundle in bundles:
        for citation in bundle.get("citations") or []:
            origins = citation.get("origin_cluster_ids") or []
            for record_id in citation.get("record_ids") or []:
                grade = qrels.get(record_id)
                if grade is None:
                    continue
                for origin in origins:
                    mapping[origin] = max(mapping.get(origin, 0.0), grade)
    return mapping


def score_condition(
    bundles: Sequence[Mapping[str, Any]],
    *,
    condition: str,
    qrels: Mapping[str, Mapping[str, float]] | None = None,
    k: int = 5,
    match: str = "record",
    expectations: Mapping[str, str] | None = None,
) -> ConditionReport:
    """Score every answer bundle produced under one condition."""
    expectations = expectations or {}
    qrels = qrels or {}

    precisions: list[float] = []
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    citation_precisions: list[float] = []

    supported_claims = total_claims = 0
    abstained = should_abstain = correct_abstentions = 0
    false_abstentions: list[str] = []
    missed_abstentions: list[str] = []
    totals: list[float] = []
    per_question: list[dict[str, Any]] = []
    judged = 0

    for bundle in bundles:
        question_id = str(
            bundle.get("question_id")
            or (bundle.get("route") or {}).get("question_id")
            or bundle.get("question", "")[:60]
        )
        latency = (bundle.get("latency") or {}).get("total")
        if isinstance(latency, (int, float)):
            totals.append(float(latency))

        claims = bundle.get("claims") or []
        total_claims += len(claims)
        supported_claims += sum(1 for claim in claims if claim.get("supported"))

        expected = expectations.get(question_id, "")
        is_abstention_case = expected == "abstain"
        did_abstain = bool(bundle.get("abstained"))
        abstained += int(did_abstain)
        should_abstain += int(is_abstention_case)
        if is_abstention_case and did_abstain:
            correct_abstentions += 1
        elif is_abstention_case and not did_abstain:
            missed_abstentions.append(question_id)
        elif not is_abstention_case and did_abstain:
            false_abstentions.append(question_id)

        entry: dict[str, Any] = {
            "question_id": question_id,
            "abstained": did_abstain,
            "expected_behavior": expected or None,
            "claims": len(claims),
            "unsupported_claims": sum(1 for claim in claims if not claim.get("supported")),
            "latency_ms": latency,
        }

        question_qrels = qrels.get(question_id)
        if question_qrels:
            judged += 1
            effective = (
                _origin_qrels(question_qrels, [bundle]) if match == "origin" else dict(question_qrels)
            )
            retrieved = cited_items(bundle, match=match)
            precision = precision_at_k(retrieved, effective, k)
            recall = recall_at_k(retrieved, effective, k)
            rank = reciprocal_rank(retrieved, effective)
            gain = ndcg_at_k(retrieved, effective, k)

            precisions.append(precision)
            if recall is not None:
                recalls.append(recall)
            reciprocal_ranks.append(rank)
            if gain is not None:
                ndcgs.append(gain)

            scored = [item for item in retrieved if item in effective]
            if scored:
                citation_precisions.append(
                    sum(1 for item in scored if effective[item] > 0) / len(scored)
                )
            entry.update(
                {
                    f"precision_at_{k}": round(precision, 4),
                    f"recall_at_{k}": None if recall is None else round(recall, 4),
                    "reciprocal_rank": round(rank, 4),
                    f"ndcg_at_{k}": None if gain is None else round(gain, 4),
                    "retrieved": len(retrieved),
                }
            )
        per_question.append(entry)

    def mean(values: Sequence[float]) -> float | None:
        return round(statistics.mean(values), 4) if values else None

    report = ConditionReport(
        condition=condition,
        questions=len(bundles),
        judged_questions=judged,
        retrieval={
            f"precision_at_{k}": mean(precisions),
            f"recall_at_{k}": mean(recalls),
            "mrr": mean(reciprocal_ranks),
            f"ndcg_at_{k}": mean(ndcgs),
        },
        answer_quality={
            "claims": total_claims,
            "claim_support_rate": round(supported_claims / total_claims, 4) if total_claims else None,
            "unsupported_claim_rate": round(1 - supported_claims / total_claims, 4)
            if total_claims
            else None,
            "citation_precision": mean(citation_precisions),
        },
        abstention={
            "abstained": abstained,
            "should_abstain": should_abstain,
            "correct_abstentions": correct_abstentions,
            "false_abstentions": false_abstentions,
            "missed_abstentions": missed_abstentions,
            "accuracy": round(
                (correct_abstentions + (len(bundles) - should_abstain - len(false_abstentions)))
                / len(bundles),
                4,
            )
            if bundles
            else None,
        },
        latency={
            "median_ms": round(statistics.median(totals), 3) if totals else None,
            "p90_ms": round(sorted(totals)[min(len(totals) - 1, round(0.9 * (len(totals) - 1)))], 3)
            if totals
            else None,
            "max_ms": round(max(totals), 3) if totals else None,
        },
        per_question=per_question,
    )

    if judged == 0:
        report.notes.append(
            "no relevance judgements supplied, so Precision@k, Recall@k, MRR, nDCG@k and "
            "citation precision are null rather than zero"
        )
    elif judged < len(bundles):
        report.notes.append(
            f"{len(bundles) - judged} of {len(bundles)} questions are unjudged and are excluded "
            "from the retrieval metrics"
        )
    if not expectations:
        report.notes.append(
            "no seed expectations supplied, so abstention accuracy treats every question as one "
            "that should be answered"
        )
    return report


def check_thresholds(
    report: ConditionReport, thresholds: Mapping[str, float]
) -> list[dict[str, Any]]:
    """Compare a report against the proposal's success thresholds."""
    checks: list[dict[str, Any]] = []

    def add(name: str, value: float | None, limit: float | None, comparison: str) -> None:
        if limit is None:
            return
        passed = None
        if value is not None:
            passed = value <= limit if comparison == "max" else value >= limit
        checks.append(
            {
                "metric": name,
                "value": value,
                "threshold": limit,
                "comparison": comparison,
                "passed": passed,
            }
        )

    add(
        "unsupported_claim_rate",
        report.answer_quality.get("unsupported_claim_rate"),
        thresholds.get("unsupported_claims_max"),
        "max",
    )
    add(
        "claim_support_rate",
        report.answer_quality.get("claim_support_rate"),
        thresholds.get("factual_claims_with_valid_evidence_min"),
        "min",
    )
    median = report.latency.get("median_ms")
    add(
        "median_latency_seconds",
        None if median is None else round(median / 1000.0, 4),
        thresholds.get("median_latency_seconds_max"),
        "max",
    )
    return checks


# ---------------------------------------------------------------------------
# Trend ranking
# ---------------------------------------------------------------------------


def score_trend_ranking(
    signals: Sequence[Mapping[str, Any]],
    rubric: Mapping[str, Sequence[str]],
    *,
    k: int = 5,
    metric: str = "commits",
    entity_type: str = "company",
) -> dict[str, Any]:
    """Precision@k and false-alert rate for the weekly trend ranking.

    ``rubric`` maps an ISO week to the entities a human judged as genuinely
    trending that week. Precision@k scores the top ``k`` by trend score;
    the false-alert rate is the share of ``rising`` labels not in the rubric.
    """
    by_week: dict[str, list[Mapping[str, Any]]] = {}
    for signal in signals:
        if signal.get("metric") != metric or signal.get("entity_type") != entity_type:
            continue
        by_week.setdefault(str(signal.get("iso_week")), []).append(signal)

    precisions: list[float] = []
    alerts = false_alerts = 0
    weeks_scored: list[str] = []

    for week, judged in sorted(rubric.items()):
        candidates = by_week.get(week, [])
        if not candidates:
            continue
        weeks_scored.append(week)
        ranked = sorted(
            candidates,
            key=lambda item: (-(item.get("trend_score") or 0.0), str(item.get("entity_id"))),
        )
        top = [str(item.get("entity_id")) for item in ranked[:k]]
        expected = set(judged)
        precisions.append(sum(1 for entity in top if entity in expected) / k)
        for signal in candidates:
            if signal.get("label") == "rising":
                alerts += 1
                if str(signal.get("entity_id")) not in expected:
                    false_alerts += 1

    return {
        "metric": metric,
        "weeks_scored": weeks_scored,
        f"precision_at_{k}": round(statistics.mean(precisions), 4) if precisions else None,
        "rising_alerts": alerts,
        "false_alerts": false_alerts,
        "false_alert_rate": round(false_alerts / alerts, 4) if alerts else None,
    }


__all__ = [
    "NEEDS_LABELS",
    "ConditionReport",
    "check_thresholds",
    "cited_items",
    "condition_name",
    "dcg",
    "load_answers",
    "load_qrels",
    "qrels_are_illustrative",
    "load_seed_expectations",
    "load_thresholds",
    "ndcg_at_k",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank",
    "score_condition",
    "score_trend_ranking",
]
