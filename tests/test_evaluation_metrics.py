"""Scoring of answer bundles: ranking metrics, abstention, and thresholds."""

from __future__ import annotations

import json

import pytest

from evaluation.metrics import (
    ConditionReport,
    check_thresholds,
    cited_items,
    condition_name,
    load_qrels,
    load_seed_expectations,
    load_thresholds,
    ndcg_at_k,
    precision_at_k,
    qrels_are_illustrative,
    recall_at_k,
    reciprocal_rank,
    score_condition,
    score_trend_ranking,
)
from faisal_snapshot import snapshot_records
from interface.agent import AgentConfig, TrendScoutAgent

SEED = json.loads(__import__("pathlib").Path("evaluation/questions.seed.json").read_text(encoding="utf-8"))["questions"]


def bundle(
    question_id: str,
    *,
    records: list[str],
    abstained: bool = False,
    claims: int = 2,
    unsupported: int = 0,
    latency: float = 100.0,
    mode: str = "hybrid",
) -> dict:
    return {
        "question": question_id,
        "question_id": question_id,
        "abstained": abstained,
        "claims": [
            {"text": f"c{index}", "supported": index >= unsupported}
            for index in range(claims)
        ],
        "citations": [
            {
                "number": index + 1,
                "kind": "passage",
                "record_ids": [record_id],
                "origin_cluster_ids": [f"origin-{record_id}"],
                "source_type": "news",
            }
            for index, record_id in enumerate(records)
        ],
        "latency": {"total": latency},
        "config": {"mode": mode, "routing_method": "rules", "ablations": {}},
    }


# --------------------------------------------------------------------------
# Ranking primitives
# --------------------------------------------------------------------------


def test_precision_divides_by_k_not_by_the_number_retrieved():
    # Two citations, both relevant, is not Precision@5 of 1.0.
    assert precision_at_k(["a", "b"], {"a": 2, "b": 2}, 5) == pytest.approx(0.4)
    assert precision_at_k(["a", "b", "c", "d", "e"], {"a": 2, "b": 1}, 5) == pytest.approx(0.4)


def test_recall_is_none_when_nothing_is_relevant():
    assert recall_at_k(["a"], {}, 5) is None
    assert recall_at_k(["a"], {"a": 0}, 5) is None
    assert recall_at_k(["a"], {"a": 1, "b": 1}, 5) == pytest.approx(0.5)


def test_reciprocal_rank_uses_the_first_relevant_position():
    assert reciprocal_rank(["x", "y", "a"], {"a": 1}) == pytest.approx(1 / 3)
    assert reciprocal_rank(["a"], {"a": 1}) == 1.0
    assert reciprocal_rank(["x"], {"a": 1}) == 0.0


def test_ndcg_rewards_putting_the_better_document_first():
    relevant = {"a": 3, "b": 1}
    good = ndcg_at_k(["a", "b"], relevant, 5)
    worse = ndcg_at_k(["b", "a"], relevant, 5)
    assert good == 1.0
    assert worse < good


def test_ndcg_is_none_without_relevant_items():
    assert ndcg_at_k(["a"], {"a": 0}, 5) is None


# --------------------------------------------------------------------------
# Scoring a condition
# --------------------------------------------------------------------------


def test_without_labels_retrieval_metrics_are_null_not_zero():
    report = score_condition([bundle("q1", records=["r1"])], condition="hybrid")
    assert report.retrieval["precision_at_5"] is None
    assert report.retrieval["mrr"] is None
    assert any("null rather than zero" in note for note in report.notes)


def test_unjudged_questions_are_excluded_and_counted():
    bundles = [bundle("q1", records=["r1"]), bundle("q2", records=["r2"])]
    report = score_condition(bundles, condition="hybrid", qrels={"q1": {"r1": 2}})
    assert report.judged_questions == 1
    assert report.questions == 2
    assert any("unjudged" in note for note in report.notes)
    assert report.retrieval["precision_at_5"] == pytest.approx(0.2)


def test_claim_support_and_unsupported_rates_need_no_labels():
    bundles = [bundle("q1", records=["r1"], claims=4, unsupported=1)]
    report = score_condition(bundles, condition="hybrid")
    assert report.answer_quality["claim_support_rate"] == pytest.approx(0.75)
    assert report.answer_quality["unsupported_claim_rate"] == pytest.approx(0.25)


def test_abstention_accuracy_uses_the_seed_expectations():
    expectations = {"q-abstain": "abstain", "q-answer": "answer_with_valid_time_path"}
    bundles = [
        bundle("q-abstain", records=[], abstained=True, claims=0),
        bundle("q-answer", records=["r1"]),
    ]
    report = score_condition(bundles, condition="hybrid", expectations=expectations)
    assert report.abstention["accuracy"] == 1.0
    assert report.abstention["correct_abstentions"] == 1
    assert report.abstention["missed_abstentions"] == []
    assert report.abstention["false_abstentions"] == []


def test_a_missed_abstention_is_named():
    expectations = {"q-abstain": "abstain"}
    report = score_condition(
        [bundle("q-abstain", records=["r1"], abstained=False)],
        condition="hybrid",
        expectations=expectations,
    )
    assert report.abstention["missed_abstentions"] == ["q-abstain"]
    assert report.abstention["accuracy"] == 0.0


def test_a_false_abstention_is_named():
    expectations = {"q-answer": "answer_with_valid_time_path"}
    report = score_condition(
        [bundle("q-answer", records=[], abstained=True, claims=0)],
        condition="hybrid",
        expectations=expectations,
    )
    assert report.abstention["false_abstentions"] == ["q-answer"]
    assert report.abstention["accuracy"] == 0.0


def test_only_passage_citations_count_as_retrieved():
    payload = bundle("q1", records=["r1"])
    payload["citations"].append(
        {
            "number": 99,
            "kind": "trend",
            "record_ids": ["r-trend"],
            "origin_cluster_ids": ["o-trend"],
            "source_type": "github",
        }
    )
    # A trend signal is derived evidence, not something retrieval ranked.
    assert cited_items(payload) == ["r1"]


def test_origin_matching_credits_a_copy_of_a_relevant_origin():
    payload = bundle("q1", records=["r1"])
    by_record = score_condition([payload], condition="c", qrels={"q1": {"r1": 2}}, match="record")
    by_origin = score_condition([payload], condition="c", qrels={"q1": {"r1": 2}}, match="origin")
    assert by_record.retrieval["mrr"] == 1.0
    assert by_origin.retrieval["mrr"] == 1.0


def test_condition_names_include_the_ablations():
    assert condition_name({"config": {"mode": "bm25", "ablations": {}}}) == "bm25"
    assert (
        condition_name(
            {
                "config": {
                    "mode": "hybrid",
                    "routing_method": "tfidf_logistic",
                    "ablations": {"graph_retrieval": False, "temporal_fields": False},
                }
            }
        )
        == "hybrid+tfidf_logistic+no-graph+no-temporal"
    )


# --------------------------------------------------------------------------
# Thresholds
# --------------------------------------------------------------------------


def test_thresholds_come_from_the_seed_question_file():
    thresholds = load_thresholds()
    assert thresholds["unsupported_claims_max"] == 0.10
    assert thresholds["median_latency_seconds_max"] == 8


def test_threshold_checks_pass_and_fail_correctly():
    good = ConditionReport(
        condition="c",
        questions=1,
        judged_questions=1,
        answer_quality={"unsupported_claim_rate": 0.0, "claim_support_rate": 1.0},
        latency={"median_ms": 2000.0},
    )
    assert all(check["passed"] for check in check_thresholds(good, load_thresholds()))

    bad = ConditionReport(
        condition="c",
        questions=1,
        judged_questions=1,
        answer_quality={"unsupported_claim_rate": 0.4, "claim_support_rate": 0.5},
        latency={"median_ms": 20000.0},
    )
    assert all(check["passed"] is False for check in check_thresholds(bad, load_thresholds()))


def test_a_missing_metric_is_not_a_pass():
    empty = ConditionReport(condition="c", questions=0, judged_questions=0)
    checks = check_thresholds(empty, load_thresholds())
    assert all(check["passed"] is None for check in checks)


# --------------------------------------------------------------------------
# Label files
# --------------------------------------------------------------------------


def test_the_example_label_file_declares_itself_illustrative(tmp_path):
    from pathlib import Path

    path = Path("evaluation/qrels.example.json")
    illustrative, why = qrels_are_illustrative(path)
    assert illustrative is True
    assert "circular" in why
    assert load_qrels(path)


def test_negative_grades_are_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"qrels": {"q1": {"r1": -1}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="negative grade"):
        load_qrels(path)


# --------------------------------------------------------------------------
# Trend ranking
# --------------------------------------------------------------------------


def test_trend_precision_and_false_alert_rate():
    signals = [
        {"metric": "commits", "entity_type": "company", "iso_week": "2026-W43", "entity_id": "langchain", "trend_score": 2.5, "label": "rising"},
        {"metric": "commits", "entity_type": "company", "iso_week": "2026-W43", "entity_id": "crewai", "trend_score": 2.0, "label": "rising"},
        {"metric": "commits", "entity_type": "company", "iso_week": "2026-W43", "entity_id": "llamaindex", "trend_score": 0.1, "label": "flat"},
    ]
    result = score_trend_ranking(signals, {"2026-W43": ["langchain"]}, k=2)
    assert result["precision_at_2"] == pytest.approx(0.5)
    assert result["rising_alerts"] == 2
    assert result["false_alerts"] == 1
    assert result["false_alert_rate"] == pytest.approx(0.5)


def test_trend_ranking_skips_weeks_with_no_signals():
    result = score_trend_ranking([], {"2026-W43": ["langchain"]}, k=5)
    assert result["weeks_scored"] == []
    assert result["precision_at_5"] is None


# --------------------------------------------------------------------------
# End to end against real bundles
# --------------------------------------------------------------------------


def test_real_answer_bundles_score_and_abstain_correctly():
    cohort = json.loads(
        __import__("pathlib").Path("data/registry/cohort.json").read_text(encoding="utf-8")
    )
    agent = TrendScoutAgent(snapshot_records(), cohort=cohort, config=AgentConfig())
    bundles = [
        agent.answer(
            item["question"], requires=item.get("needs", []), question_id=item["question_id"]
        ).as_dict()
        for item in SEED[:6]
    ]
    report = score_condition(
        bundles, condition="hybrid", expectations=load_seed_expectations()
    )
    assert report.questions == 6
    # Both insufficient-evidence seed questions must abstain, and nothing else.
    assert report.abstention["accuracy"] == 1.0
    assert report.abstention["correct_abstentions"] == 2
    assert report.answer_quality["unsupported_claim_rate"] == 0.0
    checks = {check["metric"]: check for check in check_thresholds(report, load_thresholds())}
    assert checks["unsupported_claim_rate"]["passed"] is True
    assert checks["median_latency_seconds"]["passed"] is True
