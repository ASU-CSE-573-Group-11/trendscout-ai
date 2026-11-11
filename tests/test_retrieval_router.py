"""Dense retrieval, hybrid fusion, time-window parsing, and query routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from faisal_snapshot import document_records, snapshot_records
from retrieval.bm25 import BM25Index
from retrieval.dense import DenseIndex, HashingEncoder, build_encoder
from retrieval.graph_queries import CypherLibrary, load_cypher_templates
from retrieval.hybrid import HybridRetriever, RetrievalConfig, fuse, limit_to_distinct_origins
from retrieval.passages import passages_from_records
from retrieval.router import (
    QueryRouter,
    TfidfLogisticIntentClassifier,
    classify_with_rules,
    detect_companies,
    detect_metrics,
    detect_role_families,
)
from retrieval.timewindow import mentions_future, parse_time_window

ANCHOR = "2026-11-02T00:00:00Z"
COHORT = json.loads(Path("data/registry/cohort.json").read_text(encoding="utf-8"))
COMPANY_IDS = [company["company_id"] for company in COHORT["companies"]]
ALIASES = {company["company_id"]: company.get("aliases", []) for company in COHORT["companies"]}


@pytest.fixture(scope="module")
def records():
    return snapshot_records()


@pytest.fixture(scope="module")
def retriever(records):
    return HybridRetriever.from_records(records)


# --------------------------------------------------------------------------
# Passages
# --------------------------------------------------------------------------


def test_passages_are_deduplicated_by_passage_id(records):
    passages = passages_from_records(records)
    ids = [passage.passage_id for passage in passages]
    assert len(ids) == len(set(ids))
    # The fixture replays one snapshot verbatim; it must not occupy two slots.
    assert len(passages) < len(records)


def test_a_passage_prefers_the_most_specific_time_available():
    passages = {passage.record_id: passage for passage in passages_from_records(document_records())}
    article = next(passage for passage in passages.values() if passage.source_type == "news")
    assert article.time_basis == "published_at"
    assert article.best_time == article.published_at


# --------------------------------------------------------------------------
# Dense index
# --------------------------------------------------------------------------


def test_the_default_encoder_is_deterministic_across_instances():
    first = HashingEncoder(dim=128).encode(["LangSmith evaluation datasets"])
    second = HashingEncoder(dim=128).encode(["LangSmith evaluation datasets"])
    assert first == second


def test_the_default_encoder_declares_that_it_is_not_semantic(records):
    index = DenseIndex.from_records(records)
    described = index.describe()
    assert described["semantic"] is False
    assert "not as dense retrieval" in described["caveat"]
    assert described["encoder"] == "hashing-384"


def test_dense_search_ranks_an_obviously_relevant_passage_first(records):
    index = DenseIndex.from_records(records)
    hits = index.search("LangSmith evaluation datasets generally available", k=3)
    assert hits
    assert "langsmith" in (hits[0]["passage"].title or "").lower()
    assert hits[0]["retriever"] == "dense"


def test_a_dense_index_round_trips_through_disk(records, tmp_path):
    index = DenseIndex.from_records(records)
    path = index.save(tmp_path / "dense.json")
    reloaded = DenseIndex.load(path)
    assert len(reloaded.passages) == len(index.passages)
    query = "multi agent orchestration"
    assert [hit["passage_id"] for hit in reloaded.search(query, k=5)] == [
        hit["passage_id"] for hit in index.search(query, k=5)
    ]


def test_loading_an_index_with_a_different_encoder_is_refused(records, tmp_path):
    path = DenseIndex.from_records(records).save(tmp_path / "dense.json")
    with pytest.raises(ValueError, match="refusing to query it"):
        DenseIndex.load(path, encoder=build_encoder("hashing:64"))


def test_an_empty_index_returns_nothing_rather_than_failing():
    assert DenseIndex.from_passages([]).search("anything") == []


# --------------------------------------------------------------------------
# Hybrid fusion
# --------------------------------------------------------------------------


def test_fusion_uses_ranks_so_score_scales_cannot_dominate():
    shared = {"passage_id": "a", "record_id": "a", "origin_cluster_id": "o1", "passage": None}
    other = {"passage_id": "b", "record_id": "b", "origin_cluster_id": "o2", "passage": None}
    # BM25 scores are large, dense scores are small; a sum would let BM25 decide
    # the ranking on its own. Under RRF the agreed document still wins.
    fused = fuse(
        {
            "bm25": [{**other, "score": 99.0}, {**shared, "score": 98.0}],
            "dense": [{**shared, "score": 0.9}, {**other, "score": 0.1}],
        }
    )
    assert fused[0]["passage_id"] == "a"
    assert fused[0]["retrievers"]["bm25"]["rank"] == 2
    assert fused[0]["retrievers"]["dense"]["rank"] == 1


def test_fusion_is_deterministic_regardless_of_retriever_order():
    hits = [
        {"passage_id": name, "record_id": name, "origin_cluster_id": name, "passage": None, "score": 1.0}
        for name in ("a", "b", "c")
    ]
    first = fuse({"bm25": hits, "dense": list(reversed(hits))})
    second = fuse({"dense": list(reversed(hits)), "bm25": hits})
    assert [hit["passage_id"] for hit in first] == [hit["passage_id"] for hit in second]


def test_origin_filtering_keeps_one_hit_per_origin():
    hits = [
        {"passage_id": "a", "record_id": "a", "origin_cluster_id": "shared", "passage": None, "score": 1.0},
        {"passage_id": "b", "record_id": "b", "origin_cluster_id": "shared", "passage": None, "score": 0.9},
        {"passage_id": "c", "record_id": "c", "origin_cluster_id": "other", "passage": None, "score": 0.8},
    ]
    kept = limit_to_distinct_origins(hits, 5)
    assert [hit["passage_id"] for hit in kept] == ["a", "c"]


def test_hybrid_search_returns_distinct_origins_by_default(retriever):
    hits = retriever.search("LangChain Series B LangSmith", k=5)
    origins = [hit["origin_cluster_id"] for hit in hits]
    assert len(origins) == len(set(origins))


def test_single_retriever_modes_use_only_that_retriever(retriever):
    query = "MLOps engineer kubernetes"
    for mode in ("bm25", "dense"):
        hits = retriever.search(query, k=5, config=RetrievalConfig(mode=mode))
        assert hits
        assert all(set(hit["retrievers"]) == {mode} for hit in hits)

    hybrid = retriever.search(query, k=5, config=RetrievalConfig(mode="hybrid"))
    assert any(len(hit["retrievers"]) == 2 for hit in hybrid)


def test_the_bm25_module_is_used_unmodified(records):
    # The hybrid retriever must not reimplement or wrap BM25 scoring; it feeds
    # the same documents to Sueda's index and fuses the ranks it returns.
    passages = passages_from_records(records)
    documents = [
        {
            "record_id": passage.passage_id,
            "origin_cluster_id": passage.origin_cluster_id,
            "title": passage.title,
            "text": passage.text,
        }
        for passage in passages
    ]
    direct = BM25Index.from_records(documents).search("LangSmith evaluation", k=5)
    retriever = HybridRetriever.from_records(records)
    through = retriever.search(
        "LangSmith evaluation", k=5, config=RetrievalConfig(mode="bm25", distinct_origins=False)
    )
    assert [hit["record_id"] for hit in direct][:3] == [hit["passage_id"] for hit in through][:3]


def test_a_persisted_index_covering_other_passages_is_refused(records):
    other = DenseIndex.from_passages(passages_from_records(document_records()))
    with pytest.raises(ValueError, match="different passage set"):
        HybridRetriever.from_records(records, dense_index=other)


# --------------------------------------------------------------------------
# Time windows
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question,weeks,basis",
    [
        ("rising activity in the last eight weeks", 8, "relative"),
        ("over the last 12 weeks", 12, "relative"),
        ("what happened in the past 3 months", 13, "relative"),
        ("news from last week", 1, "relative"),
        ("announcements in October 2026", 4, "absolute"),
        ("deals in 2026", 53, "absolute"),
    ],
)
def test_time_expressions_resolve_to_a_window(question, weeks, basis):
    window = parse_time_window(question, anchor=ANCHOR)
    assert window.weeks == weeks
    assert window.basis == basis


def test_a_relative_window_is_anchored_to_the_snapshot_not_today():
    window = parse_time_window("the last eight weeks", anchor=ANCHOR)
    assert window.anchor == ANCHOR
    assert window.start == "2026-09-14T00:00:00Z"
    # The same phrase against a different snapshot gives a different window,
    # which is the point: the anchor is data, not the wall clock.
    other = parse_time_window("the last eight weeks", anchor="2026-06-01T00:00:00Z")
    assert other.start != window.start


def test_a_question_with_no_time_expression_reports_the_full_snapshot():
    window = parse_time_window("Who invested in LangChain", anchor=ANCHOR)
    assert window.basis == "none"
    assert window.start is None
    assert window.label == "the full snapshot"


def test_window_containment_excludes_records_with_no_timestamp():
    window = parse_time_window("the last eight weeks", anchor=ANCHOR)
    assert window.contains("2026-10-20T00:00:00Z")
    assert not window.contains("2026-01-01T00:00:00Z")
    assert not window.contains(None)


def test_iso_weeks_cover_the_window():
    window = parse_time_window("the last eight weeks", anchor=ANCHOR)
    weeks = window.iso_weeks()
    assert len(weeks) == 8
    assert weeks[-1] == "2026-W45"


def test_future_references_are_detected():
    assert mentions_future("highest valuation in 2027", anchor=ANCHOR) == "2027"
    assert mentions_future("what about next quarter", anchor=ANCHOR) == "next quarter"
    assert mentions_future("what happened in October 2026", anchor=ANCHOR) is None


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def router():
    return QueryRouter(
        snapshot_anchor=ANCHOR,
        company_ids=COMPANY_IDS,
        aliases=ALIASES,
        coverage_start=f"{COHORT['study_window']['start']}T00:00:00Z",
    )


SEED = json.loads(Path("evaluation/questions.seed.json").read_text(encoding="utf-8"))["questions"]


@pytest.mark.parametrize("question", SEED, ids=[item["question_id"] for item in SEED])
def test_seed_questions_route_as_their_expected_behaviour_requires(router, question):
    decision = router.route(question["question"])
    if question["expected_behavior"] == "abstain":
        assert decision.intent == "unsupported"
        assert decision.should_abstain
    elif question["expected_behavior"] == "explain_ledger_state":
        assert decision.intent == "evidence_state"
    else:
        assert decision.intent == "mixed_temporal"
        assert decision.uses("graph") and decision.uses("documents")


def test_a_question_about_the_future_is_refused_before_retrieval(router):
    decision = router.route("Which company will have the highest valuation in 2027?")
    assert decision.intent == "unsupported"
    assert decision.strategies == ()
    assert decision.future_reference == "2027"
    assert "after the snapshot anchor" in decision.rationale


def test_a_question_before_the_collection_window_is_refused(router):
    decision = router.route("Which cohort company acquired Anthropic in 2024?")
    assert decision.intent == "unsupported"
    assert decision.matched_rules == ("before_coverage_start",)
    assert "before the collection window" in decision.rationale


def test_the_snapshot_bound_overrides_both_routing_methods(router):
    question = "Predict which startup raises in 2028"
    for method in ("rules", "tfidf_logistic"):
        assert router.route(question, method=method).intent == "unsupported"


def test_a_temporal_question_about_operational_signals_routes_to_both(router):
    decision = router.route("Which startups increased commits and hiring in the last month?")
    assert decision.intent == "mixed_temporal"
    assert set(decision.strategies) == {"graph", "documents", "trend"}
    assert "temporal_with_operational_signal" in decision.matched_rules


def test_rules_name_the_rule_that_fired():
    intent, confidence, rules, rationale = classify_with_rules("How many postings does CrewAI have?")
    assert intent == "aggregate"
    assert "aggregate_counting" in rules
    assert "aggregate_counting" in rationale
    assert 0 < confidence <= 1


def test_companies_are_detected_by_id_and_by_alias(router):
    assert router.route("What is LangSmith?").companies == ("langchain",)
    assert router.route("Tell me about CrewAI").companies == ("crewai",)
    assert router.route("Tell me about agent startups").companies == ()


def test_metrics_and_role_families_are_detected():
    assert "commits" in detect_metrics("rising GitHub activity")
    assert "new_postings" in detect_metrics("new hiring")
    assert detect_role_families("new MLOps hiring") == ("mlops",)
    assert set(detect_role_families("retrieval or evaluation skills")) == {"retrieval", "evaluation"}


def test_the_classical_classifier_separates_its_development_set():
    classifier = TfidfLogisticIntentClassifier()
    # A fit on the development set is a sanity check, not a reported result.
    assert classifier.training_accuracy() >= 0.95


def test_the_classifier_is_deterministic():
    first = TfidfLogisticIntentClassifier().predict("How many postings does CrewAI have?")
    second = TfidfLogisticIntentClassifier().predict("How many postings does CrewAI have?")
    assert first[0] == second[0]
    assert first[1] == pytest.approx(second[1])


def test_an_unsupported_routing_method_is_rejected():
    with pytest.raises(ValueError, match="unsupported routing method"):
        QueryRouter(snapshot_anchor=ANCHOR, method="transformer")


# --------------------------------------------------------------------------
# Cypher templates
# --------------------------------------------------------------------------


def test_every_graph_query_is_loaded_and_named():
    templates = load_cypher_templates()
    assert len(templates) >= 11
    assert all(template.query.strip() for template in templates)
    assert all(template.description for template in templates)


def test_every_expected_query_purpose_resolves():
    library = CypherLibrary()
    assert library.missing_purposes() == []
    temporal = library.for_purpose("temporal_multihop")
    assert temporal is not None
    assert set(temporal.parameters) == {"company_id", "observed_from", "observed_to"}


def test_binding_names_the_parameters_it_is_missing():
    template = CypherLibrary().for_purpose("temporal_multihop")
    with pytest.raises(KeyError, match="observed_to"):
        template.bind({"company_id": "langchain", "observed_from": ANCHOR})
