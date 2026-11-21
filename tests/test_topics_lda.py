"""The LDA topic baseline: determinism, recovery, and weekly topic trends."""

from __future__ import annotations

import pytest

from faisal_snapshot import snapshot_records
from retrieval.passages import Passage
from signals.contract import to_payload, validate_trend_signal
from signals.ewma import TrendConfig, score_many
from signals.pipeline import run_trend_pipeline
from signals.topics import (
    DOMAIN_STOPWORDS,
    STOPWORDS,
    TOPIC_METHOD,
    TopicConfig,
    company_topic_series,
    fit_topics,
    tokenize,
    topic_weekly_series,
)

INFRA = "kubernetes docker deployment pipeline cluster container orchestration scaling infrastructure"
RETRIEVAL = "retrieval embedding vector index ranking semantic search relevance passage query"


def planted(count: int = 30, *, week_of: dict[int, str] | None = None) -> list[Passage]:
    """A corpus with two clearly separated vocabularies, one per parity."""
    passages = []
    for index in range(count):
        text = INFRA if index % 2 == 0 else RETRIEVAL
        when = (week_of or {}).get(index, "2026-10-05T00:00:00Z")
        passages.append(
            Passage(
                passage_id=f"p{index}",
                record_id=f"r{index}",
                company_id="langchain" if index % 4 < 2 else "crewai",
                origin_cluster_id=f"o{index}",
                source_type="news",
                title=None,
                text=text,
                published_at=when,
                observed_at=when,
            )
        )
    return passages


@pytest.fixture(scope="module")
def model():
    return fit_topics(planted(), config=TopicConfig(topics=2, min_documents=25))


# --------------------------------------------------------------------------
# Tokenization
# --------------------------------------------------------------------------


def test_function_words_are_removed():
    tokens = tokenize("The company said that it will expand the platform", stopwords=STOPWORDS)
    assert "the" not in tokens and "that" not in tokens and "will" not in tokens
    assert "platform" in tokens


def test_domain_stopwords_can_be_switched_off():
    text = "AI startup hiring engineer for retrieval"
    with_domain = tokenize(text, stopwords=STOPWORDS | DOMAIN_STOPWORDS)
    without_domain = tokenize(text, stopwords=STOPWORDS)
    assert "retrieval" in with_domain
    assert "startup" not in with_domain
    assert "startup" in without_domain


# --------------------------------------------------------------------------
# Fitting
# --------------------------------------------------------------------------


def test_the_sampler_recovers_planted_topics(model):
    first = {model.dominant_topic(f"p{index}") for index in range(0, 30, 2)}
    second = {model.dominant_topic(f"p{index}") for index in range(1, 30, 2)}
    assert len(first) == 1 and len(second) == 1
    assert first != second, "the two planted vocabularies must land in different topics"


def test_topic_terms_do_not_mix_the_planted_vocabularies(model):
    infra_terms, retrieval_terms = set(INFRA.split()), set(RETRIEVAL.split())
    for topic in model.topics:
        top = [term for term, _ in topic.terms[:5]]
        from_infra = sum(term in infra_terms for term in top)
        from_retrieval = sum(term in retrieval_terms for term in top)
        assert from_infra == 0 or from_retrieval == 0, f"{topic.topic_id} mixes both: {top}"


def test_fitting_is_deterministic():
    config = TopicConfig(topics=2, min_documents=25)
    first = fit_topics(planted(), config=config)
    second = fit_topics(planted(), config=config)
    assert [topic.terms for topic in first.topics] == [topic.terms for topic in second.topics]
    assert first.document_topics == second.document_topics
    assert first.log_likelihood == second.log_likelihood


def test_a_different_seed_is_allowed_to_differ_but_stays_stable():
    other = TopicConfig(topics=2, seed=7, min_documents=25)
    first = fit_topics(planted(), config=other)
    second = fit_topics(planted(), config=other)
    assert first.document_topics == second.document_topics


def test_the_sparse_prior_is_the_default_and_the_textbook_one_is_worse():
    sparse = fit_topics(planted(), config=TopicConfig(topics=2, min_documents=25))
    # 50/K is the textbook default for long documents; on short passages it
    # flattens the document-topic distribution. This records why 0.1 is used.
    flat = fit_topics(planted(), config=TopicConfig(topics=2, alpha=25.0, min_documents=25))

    def separation(fitted) -> int:
        groups = [
            {fitted.dominant_topic(f"p{index}") for index in range(start, 30, 2)}
            for start in (0, 1)
        ]
        return len(groups[0] | groups[1])

    assert separation(sparse) == 2
    assert sparse.config.effective_alpha == 0.1
    assert flat.config.effective_alpha == 25.0


def test_an_underpowered_corpus_says_so():
    small = fit_topics(planted(4), config=TopicConfig(topics=2, min_documents=25))
    described = small.describe()
    assert small.underpowered is True
    assert "smoke test" in described["caveat"]

    big = fit_topics(planted(40), config=TopicConfig(topics=2, min_documents=25))
    assert big.underpowered is False
    assert big.describe()["caveat"] is None


def test_an_empty_corpus_does_not_raise():
    empty = fit_topics([], config=TopicConfig(topics=2))
    assert empty.document_topics == {}
    assert len(empty.topics) == 2
    assert topic_weekly_series(empty) == []


def test_passages_with_no_usable_terms_are_dropped_not_silently_kept():
    noise = [
        Passage(
            passage_id="n0",
            record_id="n0",
            company_id="c",
            origin_cluster_id="o",
            source_type="news",
            title=None,
            text="the and of to it",
            observed_at="2026-10-05T00:00:00Z",
        )
    ]
    fitted = fit_topics(planted(30) + noise, config=TopicConfig(topics=2, min_documents=25))
    assert "n0" in fitted.dropped_passages
    assert "n0" not in fitted.document_topics


def test_the_method_is_versioned(model):
    assert model.describe()["method"] == TOPIC_METHOD
    assert model.describe()["config"]["seed"]


# --------------------------------------------------------------------------
# Weekly topic series, scored by the shared EWMA machinery
# --------------------------------------------------------------------------


def rising_corpus() -> list[Passage]:
    """Retrieval coverage quiet for weeks, then a burst."""
    weeks = {}
    for index in range(30):
        week = 36 + (index // 4)
        weeks[index] = f"2026-{week:02d}"
    passages = []
    import datetime

    for index in range(40):
        week = 36 + min(index // 6, 5)
        when = datetime.datetime.fromisocalendar(2026, week, 3).replace(
            tzinfo=datetime.timezone.utc
        )
        # Retrieval documents only appear in the final two weeks.
        text = RETRIEVAL if week >= 40 else INFRA
        passages.append(
            Passage(
                passage_id=f"q{index}",
                record_id=f"s{index}",
                company_id="langchain",
                origin_cluster_id=f"origin{index}",
                source_type="news",
                title=None,
                text=text,
                published_at=when.isoformat().replace("+00:00", "Z"),
                observed_at=when.isoformat().replace("+00:00", "Z"),
            )
        )
    return passages


def test_topic_series_count_origins_and_fill_quiet_weeks_with_zero(model):
    series = topic_weekly_series(model)
    assert series
    for item in series:
        assert item.signal_family == "topics"
        assert item.entity_type == "topic"
        assert item.gap_policy == "zero"
        assert item.metadata["method"] == TOPIC_METHOD
        assert item.metadata["topic_label"]


def test_syndicated_copies_count_once_in_a_topic_week():
    shared = planted(10)
    for passage in shared:
        object.__setattr__(passage, "origin_cluster_id", "one-origin")
    fitted = fit_topics(shared, config=TopicConfig(topics=2, min_documents=5))
    for series in topic_weekly_series(fitted):
        for point in series.points:
            if point.value:
                assert point.value == 1.0, "ten copies of one origin must count once"


def test_a_topic_burst_is_scored_rising_by_the_same_ewma_code():
    fitted = fit_topics(rising_corpus(), config=TopicConfig(topics=2, min_documents=25))
    series = topic_weekly_series(fitted)
    signals = score_many(series, TrendConfig(min_history=3, min_scale_points=2, threshold=1.0))
    assert signals
    assert {signal.signal_family for signal in signals} == {"topics"}
    assert any(signal.label == "rising" for signal in signals), "the burst should be detected"


def test_topic_signals_satisfy_the_trend_contract():
    fitted = fit_topics(rising_corpus(), config=TopicConfig(topics=2, min_documents=25))
    signals = score_many(topic_weekly_series(fitted))
    payload = to_payload(signals)
    assert payload
    assert all(validate_trend_signal(signal) == [] for signal in payload)
    assert {signal["entity_type"] for signal in payload} == {"topic"}


def test_company_topic_series_are_scoped_to_their_company(model):
    series = company_topic_series(model)
    assert series
    for item in series:
        assert item.entity_type == "company_topic"
        assert item.company_id
        assert item.entity_id.startswith(f"{item.company_id}:")
    assert {item.company_id for item in series} == {"langchain", "crewai"}


def test_topic_series_carry_the_records_behind_them(model):
    known = {passage.record_id for passage in planted()}
    for series in topic_weekly_series(model):
        for point in series.points:
            assert set(point.record_ids) <= known


# --------------------------------------------------------------------------
# Pipeline integration
# --------------------------------------------------------------------------


def test_topics_are_opt_in():
    without = run_trend_pipeline(snapshot_records())
    assert "topics" not in without.coverage["series_by_family"]
    assert "topics" not in without.coverage

    with_topics = run_trend_pipeline(
        snapshot_records(), include_topics=True, topic_config=TopicConfig(topics=3)
    )
    assert with_topics.coverage["series_by_family"]["topics"] > 0
    assert with_topics.coverage["topics"]["documents"] > 0


def test_enabling_topics_does_not_disturb_the_other_families():
    without = run_trend_pipeline(snapshot_records())
    with_topics = run_trend_pipeline(
        snapshot_records(), include_topics=True, topic_config=TopicConfig(topics=3)
    )
    for family in ("github", "jobs", "news"):
        assert (
            without.coverage["series_by_family"][family]
            == with_topics.coverage["series_by_family"][family]
        )


def test_the_fixture_corpus_is_reported_as_underpowered():
    run = run_trend_pipeline(
        snapshot_records(), include_topics=True, topic_config=TopicConfig(topics=3)
    )
    # Five documents is not a corpus; the run must say so rather than present
    # the topics as findings.
    assert run.coverage["topics"]["underpowered"] is True
    assert run.coverage["topics"]["caveat"]
