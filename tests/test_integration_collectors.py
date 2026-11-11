"""Integration: sectors, and the adapter against the real collector output.

Two of these tests activate on their own once Vidya's collector lands on the
branch. They are written now rather than later because the thing worth proving
is that my adapter reads *her code's* output and not only my reproduction of
its shape, and that proof should run in CI the moment it can.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from faisal_snapshot import snapshot_records
from interface.agent import AgentConfig, TrendScoutAgent, validate_answer
from retrieval.graph_access import InMemoryGraph
from signals.job_features import role_families

ROOT = Path(__file__).resolve().parents[1]
COHORT = json.loads((ROOT / "data" / "registry" / "cohort.json").read_text(encoding="utf-8"))
COLLECTOR_FIXTURES = ROOT / "tests" / "fixtures" / "collectors"
COLLECTOR_MAIN = ROOT / "collectors" / "__main__.py"

needs_collectors = pytest.mark.skipif(
    not (COLLECTOR_MAIN.exists() and COLLECTOR_FIXTURES.exists()),
    reason="the API collectors are not on this branch yet (PR #3)",
)


# --------------------------------------------------------------------------
# Sectors, built from the frozen cohort
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def agent():
    return TrendScoutAgent(snapshot_records(), cohort=COHORT, config=AgentConfig())


def test_sectors_come_from_the_frozen_cohort(agent):
    sectors = agent.graph.sectors()
    assert sectors
    assert set(sectors) <= set(COHORT["scope"]["categories"])
    for sector_id in sectors:
        companies = agent.graph.companies_in_sector(sector_id)
        assert companies
        for company_id in companies:
            expected = next(
                item["category"] for item in COHORT["companies"] if item["company_id"] == company_id
            )
            assert expected == sector_id


def test_only_companies_with_evidence_are_sector_tagged(agent):
    tagged = {
        company_id
        for sector_id in agent.graph.sectors()
        for company_id in agent.graph.companies_in_sector(sector_id)
    }
    with_records = {record["company_id"] for record in snapshot_records() if record.get("company_id")}
    assert tagged <= with_records
    # The cohort has 18 companies; the fixture snapshot covers only a few.
    assert len(tagged) < len(COHORT["companies"])


def test_sector_attention_counts_origins_not_articles(agent):
    result = agent.graph.sector_attention(minimum_voice_origins=2)
    assert result.rows
    row = next(row for row in result.rows if row["sector_id"] == "agent_infrastructure")
    assert row["independent_voice_origins"] == len(set(row["voice_origin_ids"]))
    # The two syndicated copies in the fixture share one origin, so coverage
    # origins must be fewer than the records behind them.
    assert row["independent_voice_origins"] < len(row["record_ids"])


def test_the_sector_question_is_answered_rather_than_deferred(agent):
    answer = agent.answer(
        "Which sectors gained attention from multiple public voices and also produced operational signals?",
        requires=["public_voice", "github_or_jobs"],
    )
    assert validate_answer(answer.as_dict()) == []
    assert not answer.abstained
    text = answer.answer_text.lower()
    assert "sector" in text
    assert "no sector nodes" not in text
    assert any("qualifies" in claim.text.lower() for claim in answer.claims)


def test_a_graph_without_a_cohort_says_so_instead_of_guessing():
    graph = InMemoryGraph.from_records(snapshot_records())
    assert graph.sectors() == []
    result = graph.sector_attention()
    assert result.rows == []
    assert "no Sector nodes" in (result.note or "")


# --------------------------------------------------------------------------
# Role families, corrected against the collector's real job titles
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Machine Learning Engineer", "machine_learning"),
        ("ML Engineer", "machine_learning"),
        ("Applied Scientist", "machine_learning"),
        ("Data Engineer", "data"),
        ("Platform Engineer", "infrastructure"),
    ],
)
def test_real_collector_job_titles_land_in_a_family(title, expected):
    assert expected in role_families(title)


def test_modelling_roles_are_not_confused_with_operations_roles():
    assert "mlops" not in role_families("Machine Learning Engineer")
    assert "machine_learning" not in role_families("MLOps Engineer")


# --------------------------------------------------------------------------
# The adapter against the collector's own output
# --------------------------------------------------------------------------


@needs_collectors
def test_the_adapter_reads_output_produced_by_the_collector_itself(tmp_path):
    """Replay the collector's fixtures with its own code, then adapt the result.

    This is the test that retires the synthetic fixtures: it proves the feature
    builders consume what the collector actually writes, not a reproduction of
    its shape.
    """
    from collectors.records import validate_records
    from signals.adapters import github_observations, job_observations
    from signals.pipeline import run_trend_pipeline

    produced: list[dict] = []
    for name in ("github", "greenhouse", "lever"):
        fixture = COLLECTOR_FIXTURES / f"{name}.json"
        if not fixture.exists():
            continue
        completed = subprocess.run(
            [sys.executable, "-m", "collectors", "--replay", str(fixture), "--output-dir", str(tmp_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
    for path in sorted(tmp_path.glob("*/records.jsonl")):
        produced += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert produced, "the collector produced no records"
    assert validate_records(produced) == []

    github = github_observations(produced)
    jobs = job_observations(produced)
    assert github or jobs

    for observation in github:
        assert observation.commit_count == len(observation.commit_shas)
        assert observation.window_start < observation.window_end
        assert observation.human_commit_count + observation.bot_commit_count <= observation.commit_count
    for observation in jobs:
        assert observation.posting_id
        assert role_families(observation.role_normalized)

    run = run_trend_pipeline(produced)
    assert run.bundle.series
    assert run.signals


@needs_collectors
def test_the_interface_answers_over_collector_produced_records(tmp_path):
    from collectors.records import validate_records

    fixture = COLLECTOR_FIXTURES / "github.json"
    completed = subprocess.run(
        [sys.executable, "-m", "collectors", "--replay", str(fixture), "--output-dir", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    records = [
        json.loads(line)
        for path in tmp_path.glob("*/records.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert validate_records(records) == []
    agent = TrendScoutAgent(records, cohort=COHORT, config=AgentConfig())
    answer = agent.answer("What repository activity is there?")
    assert validate_answer(answer.as_dict()) == []


# --------------------------------------------------------------------------
# The real dense encoder, when it is installed
# --------------------------------------------------------------------------


def _sentence_transformers_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(
    not _sentence_transformers_available(),
    reason="sentence-transformers is an optional dependency",
)
def test_the_real_encoder_is_semantic_and_drops_the_caveat():
    from retrieval.dense import DenseIndex, build_encoder

    encoder = build_encoder("sentence-transformers/all-MiniLM-L6-v2")
    index = DenseIndex.from_records(snapshot_records(), encoder=encoder)
    described = index.describe()
    assert described["semantic"] is True
    assert described["caveat"] is None

    # The paraphrase case the lexical fallback cannot reach: the query shares no
    # content word with the postings it should find.
    hits = index.search("who is hiring for search relevance work", k=3)
    titles = " ".join((hit["passage"].title or "").lower() for hit in hits)
    assert "retrieval" in titles
