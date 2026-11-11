"""Answers, evidence states, abstention, ablations, and latency logging."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from faisal_snapshot import SYNDICATED_ORIGIN, document_records, github_records, snapshot_records
from interface.agent import AgentConfig, TrendScoutAgent, validate_answer
from interface.evidence import (
    EvidenceConfig,
    assess_evidence,
    detect_conflicts,
    parse_amounts,
    parse_dates,
    worst_state,
)
from interface.latency import LatencyLog, StageTimings, percentile, summarize
from interface.providers import (
    ExtractiveProvider,
    build_provider,
    cite_every_sentence,
    split_claims,
)
from retrieval.passages import passages_from_records

ANCHOR = "2026-11-02T00:00:00Z"
COHORT = json.loads(Path("data/registry/cohort.json").read_text(encoding="utf-8"))
SEED = json.loads(Path("evaluation/questions.seed.json").read_text(encoding="utf-8"))["questions"]
PILOT_QUESTION = (
    "Which agent-infrastructure startups show both rising GitHub activity and new MLOps "
    "hiring during the last eight weeks?"
)


class FakeItem:
    """A minimal evidence item for the state rules."""

    def __init__(self, origin: str, text: str, source_type: str = "news", observed_at: str = ANCHOR):
        self.origin_cluster_id = origin
        self.record_id = f"record:{origin}"
        self.title = ""
        self.text = text
        self.source_type = source_type
        self.observed_at = observed_at
        self.event_at = None
        self.published_at = None


@pytest.fixture(scope="module")
def agent():
    return TrendScoutAgent(
        snapshot_records(), cohort=COHORT, config=AgentConfig(demo_mode=True)
    )


# --------------------------------------------------------------------------
# Evidence states
# --------------------------------------------------------------------------


def test_syndicated_copies_are_one_origin_not_corroboration():
    copies = [
        passage
        for passage in passages_from_records(document_records())
        if passage.origin_cluster_id == SYNDICATED_ORIGIN
    ]
    assert len(copies) == 2
    assessment = assess_evidence(copies, snapshot_anchor=ANCHOR)
    assert assessment.state == "emerging"
    assert assessment.independent_origin_count == 1


def test_two_independent_origins_are_corroborated():
    items = [FakeItem("o1", "LangChain raised a round."), FakeItem("o2", "LangChain raised a round.")]
    assert assess_evidence(items, snapshot_anchor=ANCHOR).state == "corroborated"


def test_one_document_plus_one_operational_signal_is_corroborated():
    document = passages_from_records(document_records())[0]
    operational = passages_from_records(github_records())[0]
    assert assess_evidence([document, operational], snapshot_anchor=ANCHOR).state == "corroborated"


def test_amounts_differing_beyond_tolerance_are_disputed():
    items = [FakeItem("o1", "raised $20 million"), FakeItem("o2", "raised $45 million")]
    assessment = assess_evidence(items, snapshot_anchor=ANCHOR)
    assert assessment.state == "disputed"
    assert assessment.conflicts[0].kind == "amount"
    assert "rather than resolved" in assessment.reason


def test_amounts_inside_tolerance_are_not_disputed():
    items = [FakeItem("o1", "raised $20 million"), FakeItem("o2", "raised $21 million")]
    assert assess_evidence(items, snapshot_anchor=ANCHOR).state == "corroborated"


def test_dates_differing_beyond_tolerance_are_disputed():
    items = [FakeItem("o1", "closed in March 2026"), FakeItem("o2", "closed in October 2026")]
    assessment = assess_evidence(items, snapshot_anchor=ANCHOR)
    assert assessment.state == "disputed"
    assert assessment.conflicts[0].kind == "date"


def test_a_disagreement_inside_one_origin_is_not_a_conflict():
    # Two copies of the same origin quoting different figures is a sloppy
    # syndication, not independent sources disagreeing.
    items = [FakeItem("same", "raised $20 million"), FakeItem("same", "raised $45 million")]
    assert detect_conflicts(items, config=EvidenceConfig()) == []


def test_operational_snapshots_go_stale_but_dated_articles_do_not():
    old_snapshot = passages_from_records(github_records())[0]
    far_future = "2027-06-01T00:00:00Z"
    assert assess_evidence([old_snapshot], snapshot_anchor=far_future).state == "stale"

    article = passages_from_records(document_records())[0]
    # A dated past event stays historical; it does not expire with time.
    assert assess_evidence([article], snapshot_anchor=far_future).state == "emerging"


def test_no_evidence_is_insufficient_and_names_what_is_missing():
    assessment = assess_evidence([], snapshot_anchor=ANCHOR, requires=["github", "jobs"])
    assert assessment.state == "insufficient"
    assert not assessment.supported
    assert assessment.missing_evidence == ("github", "jobs")


def test_thresholds_are_reported_with_every_assessment():
    assessment = assess_evidence([FakeItem("o1", "x")], snapshot_anchor=ANCHOR)
    assert assessment.config["minimum_independent_origins"] == 2
    assert assessment.config["amount_tolerance"] == 0.10
    assert assessment.config["stale_after_days"] == 14


def test_thresholds_are_configurable():
    items = [FakeItem("o1", "a"), FakeItem("o2", "b")]
    strict = EvidenceConfig(minimum_independent_origins=3)
    assert assess_evidence(items, snapshot_anchor=ANCHOR, config=strict).state == "emerging"


def test_the_overall_state_is_the_most_cautious_claim_state():
    assert worst_state(["corroborated", "emerging"]) == "emerging"
    assert worst_state(["corroborated", "insufficient"]) == "insufficient"
    assert worst_state([]) == "insufficient"


def test_amount_and_date_parsing():
    assert parse_amounts("raised $12 million then $1.5bn") == [12_000_000.0, 1_500_000_000.0]
    assert "2026-10-14" in parse_dates("filed 2026-10-14")
    assert "2026-10-01" in parse_dates("closed in October 2026")


# --------------------------------------------------------------------------
# Claim splitting and providers
# --------------------------------------------------------------------------


def test_a_trailing_citation_stays_attached_to_its_sentence():
    claims = split_claims("Commits rose sharply. [3] Hiring also grew. [4]")
    assert [numbers for _, numbers in claims] == [(3,), (4,)]
    assert all(text for text, _ in claims)


def test_an_uncited_sentence_is_kept_and_reported_as_uncited():
    claims = split_claims("Commits rose sharply. Hiring also grew. [4]")
    assert claims[0][1] == ()
    assert claims[1][1] == (4,)


def test_every_sentence_of_a_multi_sentence_finding_is_cited():
    text = cite_every_sentence("Evidence is emerging. What would change it: another origin.", "[1][2]")
    claims = split_claims(text)
    assert len(claims) == 2
    assert all(numbers == (1, 2) for _, numbers in claims)


def test_the_extractive_provider_invents_nothing():
    evidence = [
        {"number": 1, "kind": "passage", "title": "t", "text": "LangChain raised a Series B.", "when": ANCHOR}
    ]
    result = ExtractiveProvider().generate("what happened", evidence, context={})
    assert result.provider == "extractive"
    assert "LangChain raised a Series B" in result.text
    assert "[1]" in result.text


def test_the_extractive_provider_handles_empty_evidence():
    result = ExtractiveProvider().generate("what happened", [], context={})
    assert "does not contain evidence" in result.text


def test_providers_are_selected_by_configuration():
    assert build_provider().name == "extractive"
    assert build_provider("extractive").name == "extractive"
    anthropic = build_provider("anthropic:claude-sonnet-5-5")
    assert anthropic.name == "anthropic"
    assert anthropic.model == "claude-sonnet-5-5"
    with pytest.raises(ValueError, match="unsupported provider"):
        build_provider("gpt")


def test_the_anthropic_provider_reports_why_it_is_unavailable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    usable, reason = build_provider("anthropic").available()
    assert usable is False
    assert reason


def test_the_agent_falls_back_to_extractive_without_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    agent = TrendScoutAgent(
        snapshot_records(), cohort=COHORT, config=AgentConfig(provider="anthropic")
    )
    assert agent.provider.name == "extractive"
    assert agent.provider_fallback_reason
    answer = agent.answer("Tell me about LangSmith")
    assert answer.provider.fallback_used
    assert answer.provider.fallback_reason


# --------------------------------------------------------------------------
# Answers
# --------------------------------------------------------------------------


@pytest.mark.parametrize("question", SEED, ids=[item["question_id"] for item in SEED])
def test_every_seed_question_produces_a_valid_answer_bundle(agent, question):
    answer = agent.answer(question["question"], requires=question.get("needs", []))
    assert validate_answer(answer.as_dict()) == []


def test_the_pilot_question_finds_both_signals_with_evidence(agent):
    answer = agent.answer(PILOT_QUESTION, requires=["github", "jobs"])
    assert not answer.abstained
    text = answer.answer_text.lower()
    assert "langchain" in text
    assert "both signals" in text
    assert "mlops" in text
    # The answer must rest on cited trend evidence, not prose alone.
    trend_citations = [citation for citation in answer.citations if citation.kind == "trend"]
    assert trend_citations
    assert any(citation.detail["label"] == "rising" for citation in trend_citations)
    assert answer.unsupported_claim_count == 0


def test_an_answer_reports_the_window_it_used_and_its_anchor(agent):
    answer = agent.answer(PILOT_QUESTION)
    assert answer.time_window.basis == "relative"
    assert answer.time_window.weeks == 8
    assert answer.time_window.anchor == agent.snapshot_anchor
    assert len(answer.time_window.iso_weeks()) == 8


def test_a_question_after_the_snapshot_abstains_without_retrieving(agent):
    answer = agent.answer("Which company will have the highest valuation in 2027?")
    assert answer.abstained
    assert answer.citations == []
    assert answer.overall_state == "insufficient"
    assert "after the snapshot anchor" in answer.abstention_reason


def test_a_question_before_the_collection_window_abstains(agent):
    answer = agent.answer("Which frozen cohort company acquired Anthropic in 2024?")
    assert answer.abstained
    assert "before the collection window" in answer.abstention_reason


def test_an_answer_with_no_evidence_in_the_window_abstains_and_says_what_is_missing(agent):
    answer = agent.answer(
        "What did Browserbase announce about Stagehand in the last eight weeks?",
        requires=["news"],
    )
    if answer.abstained:
        assert answer.missing_evidence
        assert "no evidence" in answer.answer_text.lower() or answer.abstention_reason
    else:
        # If something was retrieved it must be cited, not asserted.
        assert answer.citations


def test_partial_evidence_is_qualified_rather_than_abstained(agent):
    answer = agent.answer(
        "Which investors funded startups that later increased hiring for retrieval or evaluation skills?",
        requires=["funding", "jobs"],
    )
    assert not answer.abstained
    assert answer.qualified
    assert "funding" in answer.missing_evidence
    assert "funding" in (answer.qualification or "")


def test_every_claim_carries_a_state_and_a_reason(agent):
    answer = agent.answer(PILOT_QUESTION)
    assert answer.claims
    for claim in answer.claims:
        assert claim.assessment.state
        assert claim.assessment.reason
        if claim.supported:
            assert claim.citation_numbers


def test_every_cited_record_exists_in_the_snapshot(agent):
    known = {record["record_id"] for record in snapshot_records()}
    answer = agent.answer(PILOT_QUESTION)
    for citation in answer.citations:
        assert set(citation.record_ids) <= known


def test_the_evidence_state_question_explains_what_would_change_the_label(agent):
    answer = agent.answer("Why is a company marked as emerging, and what evidence could change that label?")
    assert answer.route.intent == "evidence_state"
    assert "what would change it" in answer.answer_text.lower()


def test_a_trend_citation_says_it_is_not_a_prediction(agent):
    answer = agent.answer(PILOT_QUESTION)
    trend = next(citation for citation in answer.citations if citation.kind == "trend")
    assert "not a prediction" in (trend.text or "")


def test_an_answer_shows_a_graph_path_and_the_query_behind_it(agent):
    answer = agent.answer(PILOT_QUESTION)
    assert answer.graph_paths
    assert answer.graph_paths[0].render()
    with_template = [result for result in answer.graph_results if result.template]
    assert with_template
    assert "MATCH" in with_template[0].template.query


# --------------------------------------------------------------------------
# Ablations
# --------------------------------------------------------------------------


def test_each_retrieval_mode_runs_and_reports_itself():
    for mode in ("hybrid", "bm25", "dense", "graph_only"):
        agent = TrendScoutAgent(snapshot_records(), cohort=COHORT, config=AgentConfig(mode=mode))
        answer = agent.answer(PILOT_QUESTION)
        assert answer.config["mode"] == mode
        assert validate_answer(answer.as_dict()) == []


def test_graph_only_mode_retrieves_no_document_passages():
    agent = TrendScoutAgent(snapshot_records(), cohort=COHORT, config=AgentConfig(mode="graph_only"))
    answer = agent.answer(PILOT_QUESTION)
    assert all(citation.kind != "passage" for citation in answer.citations)


def test_disabling_graph_retrieval_removes_graph_and_trend_evidence():
    agent = TrendScoutAgent(snapshot_records(), cohort=COHORT, config=AgentConfig(use_graph=False))
    answer = agent.answer(PILOT_QUESTION)
    assert answer.config["ablations"]["graph_retrieval"] is False
    assert all(citation.kind == "passage" for citation in answer.citations)
    assert answer.graph_paths == []


def test_disabling_temporal_fields_stops_time_filtering_but_still_reports_the_window():
    timed = TrendScoutAgent(snapshot_records(), cohort=COHORT, config=AgentConfig())
    timeless = TrendScoutAgent(
        snapshot_records(), cohort=COHORT, config=AgentConfig(use_temporal_fields=False)
    )
    question = "What was announced in October 2026?"
    with_time = timed.answer(question)
    without_time = timeless.answer(question)
    assert without_time.config["ablations"]["temporal_fields"] is False
    # The window is still parsed and reported, so the condition is comparable.
    assert without_time.time_window.basis == with_time.time_window.basis
    outside = [
        citation
        for citation in without_time.citations
        if citation.kind == "passage" and not without_time.time_window.contains(citation.when)
    ]
    assert outside, "without temporal fields, evidence outside the window is reachable"


def test_disabling_corroboration_weighting_changes_ranking_not_evidence_states():
    weighted = TrendScoutAgent(snapshot_records(), cohort=COHORT, config=AgentConfig())
    plain = TrendScoutAgent(
        snapshot_records(), cohort=COHORT, config=AgentConfig(use_corroboration_weighting=False)
    )
    question = "What happened with LangChain funding?"
    with_bonus = weighted.answer(question)
    without_bonus = plain.answer(question)
    assert without_bonus.config["ablations"]["corroboration_weighting"] is False
    assert all(
        citation.detail.get("corroboration_bonus_applied") in (None, False)
        for citation in without_bonus.citations
        if citation.kind == "passage"
    )
    # Ranking may change; the ledger's rules must not.
    shared = {citation.record_ids[0] for citation in with_bonus.citations if citation.kind == "passage"} & {
        citation.record_ids[0] for citation in without_bonus.citations if citation.kind == "passage"
    }
    assert shared


def test_the_classical_router_can_be_selected_for_a_run():
    agent = TrendScoutAgent(
        snapshot_records(), cohort=COHORT, config=AgentConfig(routing_method="tfidf_logistic")
    )
    answer = agent.answer(PILOT_QUESTION)
    assert answer.route.method == "tfidf_logistic"
    assert answer.route.scores


def test_demo_mode_is_recorded_on_the_answer(agent):
    answer = agent.answer(PILOT_QUESTION)
    assert answer.snapshot["demo_mode"] is True
    assert answer.snapshot["replayed_from_snapshot"] is True
    assert answer.snapshot["graph_backend"] == "in_memory"


# --------------------------------------------------------------------------
# Latency
# --------------------------------------------------------------------------


def test_every_stage_is_timed(agent):
    answer = agent.answer(PILOT_QUESTION)
    for stage in ("parse", "route", "retrieve", "graph", "generate", "total"):
        assert stage in answer.latency
    assert answer.latency["total"] > 0


def test_stage_times_do_not_exceed_the_total(agent):
    answer = agent.answer(PILOT_QUESTION)
    parts = sum(value for key, value in answer.latency.items() if key not in {"total", "unattributed"})
    assert parts <= answer.latency["total"] + 1e-6


def test_latency_is_written_as_jsonl_and_summarized(tmp_path):
    log_path = tmp_path / "latency.jsonl"
    agent = TrendScoutAgent(
        snapshot_records(), cohort=COHORT, config=AgentConfig(), latency_log=log_path
    )
    for question in SEED:
        agent.answer(question["question"], question_id=question["question_id"])

    entries = LatencyLog(path=log_path).entries()
    assert len(entries) == len(SEED)
    summary = summarize(entries)
    assert summary["requests"] == len(SEED)
    assert summary["median_total_ms"] is not None
    assert set(summary["stages"]) >= {"parse", "route", "retrieve", "graph", "generate", "total"}
    # The proposal's secondary target.
    assert summary["meets_target"] is True


def test_percentile_uses_nearest_rank():
    assert percentile([1, 2, 3, 4, 5], 0.9) == 5
    assert percentile([], 0.5) is None
    assert percentile([7], 0.9) == 7


def test_stage_timings_report_unattributed_time():
    timings = StageTimings()
    with timings.time("parse"):
        pass
    payload = timings.as_dict()
    assert payload["unattributed"] >= 0.0
    assert payload["total"] >= payload["parse"]
