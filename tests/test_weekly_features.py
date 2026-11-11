"""Weekly GitHub, hiring, and attention features against the shared contract."""

from __future__ import annotations

import pytest

from collectors.records import validate_records
from signals.adapters import (
    AdapterError,
    GITHUB_UNAVAILABLE_METRICS,
    github_observation,
    github_observations,
)
from signals.github_features import GitHubFeatureConfig, build_github_features
from signals.job_features import (
    JobFeatureConfig,
    ROLE_FAMILY_METHOD,
    build_job_features,
    role_families,
)
from signals.news_features import build_news_features
from faisal_snapshot import (
    SYNDICATED_ORIGIN,
    document_records,
    github_records,
    job_records,
    snapshot_records,
)

LANGCHAIN_REPO = "langchain-ai/langchain"


def test_fixtures_satisfy_the_shared_record_schema():
    assert validate_records(snapshot_records()) == []


# --------------------------------------------------------------------------
# GitHub features
# --------------------------------------------------------------------------


def test_adapter_reads_vidya_github_metadata_layout():
    records = [record for record in github_records() if record["metadata"]["repository"] == LANGCHAIN_REPO]
    observations = github_observations(records)
    assert observations
    first = observations[0]
    assert first.repository == LANGCHAIN_REPO
    assert first.company_id == "langchain"
    assert first.commit_count == len(first.commit_shas)
    assert first.window_start < first.window_end
    assert first.interval == "(start, end]"
    assert first.scope == "default_branch"
    # Metrics her collector cannot supply must stay None rather than becoming 0.
    assert set(first.optional_metrics) == set(GITHUB_UNAVAILABLE_METRICS)
    assert all(value is None for value in first.optional_metrics.values())


def test_adapter_refuses_a_github_record_without_an_observation_window():
    record = dict(github_records()[0])
    metadata = dict(record["metadata"])
    metadata.pop("activity_window")
    record["metadata"] = metadata
    with pytest.raises(AdapterError, match="activity_window"):
        github_observation(record, validate=False)


def test_adapter_refuses_a_commit_count_that_disagrees_with_its_shas():
    record = dict(github_records()[0])
    metadata = {key: dict(value) if isinstance(value, dict) else value for key, value in record["metadata"].items()}
    metadata["activity_window"]["commit_count"] = 999
    record["metadata"] = metadata
    with pytest.raises(AdapterError, match="distinct SHAs"):
        github_observation(record, validate=False)


def test_mirror_repository_is_excluded_with_a_reason():
    features = build_github_features(github_records())
    excluded = features.coverage["excluded_repositories"]
    assert excluded == {"run-llama/llama_index-mirror": ["mirror"]}
    assert all(series.entity_id != "run-llama/llama_index-mirror" for series in features.series)


def test_bot_heavy_repository_is_flagged_and_split_from_human_activity():
    features = build_github_features(github_records())
    assert "crewAIInc/crewAI" in features.coverage["bot_heavy_repositories"]
    commits = features.find_series("github:commits|company=crewai|repo=crewAIInc/crewAI")
    human = features.find_series("github:human_commits|company=crewai|repo=crewAIInc/crewAI")
    week = "2026-W36"
    assert commits.point(week).value == 8.0
    # bot_share 0.75 in the fixture: six bot commits, two human.
    assert human.point(week).value == 2.0


def test_repeated_identical_snapshots_do_not_inflate_counts():
    records = github_records()
    features = build_github_features(records)
    assert features.coverage["duplicate_record_ids"], "the fixture includes an exact replay"
    assert features.coverage["observations_used"] < features.coverage["observations_received"]

    unique = {record["record_id"]: record for record in records}
    deduped = build_github_features(list(unique.values()))
    series_id = f"github:commits|company=langchain|repo={LANGCHAIN_REPO}"
    with_replay = features.find_series(series_id)
    without_replay = deduped.find_series(series_id)
    assert [point.value for point in with_replay.points] == [
        point.value for point in without_replay.points
    ]


def test_overlapping_windows_in_one_week_are_merged_by_commit_sha():
    features = build_github_features(github_records())
    week = "2026-W44"
    point = features.find_series(f"github:commits|company=langchain|repo={LANGCHAIN_REPO}").point(week)
    # The aligned window reports 29 commits and the overlapping window reports
    # 22, of which 20 are the same commits. The union is 31, not 51.
    assert point.value == 31.0
    assert len(point.record_ids) == 2
    assert any("SHA union" in note for note in point.notes)


def test_a_window_that_does_not_align_to_an_iso_week_is_flagged():
    features = build_github_features(github_records())
    assert features.coverage["approximate_week_assignments"] == [f"{LANGCHAIN_REPO}@2026-W44"]
    assert set(features.coverage["week_assignment_methods"]) == {
        "aligned_window",
        "window_end_approximate",
    }
    point = features.find_series(f"github:commits|company=langchain|repo={LANGCHAIN_REPO}").point("2026-W44")
    assert any("does not align" in note for note in point.notes)


def test_a_week_without_a_snapshot_is_unknown_rather_than_zero():
    features = build_github_features(github_records())
    series = features.find_series(f"github:commits|company=langchain|repo={LANGCHAIN_REPO}")
    missing = series.point("2026-W42")
    assert missing.value is None
    assert missing.value_state == "unknown"
    assert series.gap_policy == "unknown"
    assert "unknown rather than zero" in features.coverage["gap_policy_reason"]


def test_star_delta_is_not_reported_across_a_collection_gap():
    features = build_github_features(github_records())
    series = features.find_series(f"github:star_delta|company=langchain|repo={LANGCHAIN_REPO}")
    # 2026-W42 was never observed, so the W43 change covers two weeks and must
    # not be presented as one week of growth.
    gap_week = series.point("2026-W43")
    assert gap_week.value is None
    assert gap_week.value_state == "unknown"
    assert any("must not be reported as one week" in note for note in gap_week.notes)
    # Consecutive observed weeks do produce a delta.
    assert series.point("2026-W38").value == 70.0


def test_running_totals_are_kept_separate_from_weekly_change():
    features = build_github_features(github_records())
    stars = features.find_series(f"github:stars|company=langchain|repo={LANGCHAIN_REPO}")
    assert stars.unit == "running_total"
    assert stars.point("2026-W37").value == 4060.0
    assert "not weekly growth" in " ".join(stars.point("2026-W37").notes)


def test_company_rollup_sums_its_repositories():
    features = build_github_features(github_records())
    week = "2026-W43"
    company = features.find_series("github:commits|company=langchain").point(week).value
    repos = [
        features.find_series(f"github:commits|company=langchain|repo={name}").point(week).value
        for name in (LANGCHAIN_REPO, "langchain-ai/langgraph")
    ]
    assert company == sum(repos)
    assert company == 37.0


def test_company_rollup_marks_a_week_with_partial_repository_coverage():
    features = build_github_features(github_records())
    point = features.find_series("github:commits|company=langchain").point("2026-W36")
    # langgraph has no snapshot that early; the week is still observed for
    # langchain, but the gap is named instead of being treated as zero.
    assert point.value == 12.0
    assert any("partial week" in note for note in point.notes)


def test_metrics_the_collector_cannot_supply_are_reported_as_unavailable():
    features = build_github_features(github_records())
    assert set(features.coverage["unavailable_metrics"]) == {
        "releases",
        "issues_opened",
        "issues_closed",
        "active_contributors",
    }
    assert "discarded at collection time" in features.coverage["unavailable_metrics"]["active_contributors"]
    # They are not emitted as series unless explicitly requested.
    assert not features.by_metric("releases")

    explicit = build_github_features(
        github_records(), config=GitHubFeatureConfig(include_unavailable_metrics=True)
    )
    releases = explicit.by_metric("releases")
    assert releases
    assert all(series.availability == "not_collected" for series in releases)
    assert all(point.value is None for series in releases for point in series.points)


def test_every_observed_point_names_records_that_exist_in_the_input():
    records = github_records()
    known = {record["record_id"] for record in records}
    features = build_github_features(records)
    seen = False
    for series in features.series:
        for point in series.points:
            if point.value is None:
                continue
            assert set(point.record_ids) <= known
            seen = seen or bool(point.record_ids)
    assert seen, "at least one point must carry evidence"


def test_including_mirrors_is_opt_in():
    features = build_github_features(
        github_records(), config=GitHubFeatureConfig(include_mirrors=True)
    )
    assert "run-llama/llama_index-mirror" in features.coverage["repositories"]


def test_dropping_bot_heavy_repositories_is_opt_in():
    features = build_github_features(
        github_records(), config=GitHubFeatureConfig(drop_bot_heavy_repositories=True)
    )
    assert features.coverage["excluded_repositories"]["crewAIInc/crewAI"] == ["bot_heavy"]


# --------------------------------------------------------------------------
# Hiring features
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("MLOps Engineer", {"mlops"}),
        ("Machine Learning Operations Lead", {"mlops"}),
        ("MLOps Engineer, Deployments", {"mlops", "infrastructure"}),
        ("Evaluation Engineer, LangSmith", {"evaluation"}),
        ("Software Engineer, Retrieval", {"retrieval", "product_engineering"}),
        ("Technical Writer", {"other"}),
    ],
)
def test_role_families_use_explicit_title_phrases(title, expected):
    assert set(role_families(title)) == expected


def test_role_family_method_is_versioned_in_the_output():
    features = build_job_features(job_records())
    assert features.coverage["role_family_method"] == ROLE_FAMILY_METHOD
    assert all(
        series.metadata["role_family_method"] == ROLE_FAMILY_METHOD for series in features.series
    )


def test_mlops_hiring_appears_only_in_the_weeks_it_was_posted():
    features = build_job_features(job_records())
    open_postings = features.find_series("jobs:open_postings|company=langchain|role_family=mlops")
    assert open_postings.point("2026-W42").value == 0.0
    assert open_postings.point("2026-W43").value == 1.0
    assert open_postings.point("2026-W44").value == 2.0

    new_postings = features.find_series("jobs:new_postings|company=langchain|role_family=mlops")
    assert new_postings.point("2026-W43").value == 1.0
    assert new_postings.point("2026-W44").value == 1.0
    assert new_postings.point("2026-W43").record_ids


def test_new_postings_are_unknown_in_the_first_observed_week():
    features = build_job_features(job_records())
    series = features.find_series("jobs:new_postings|company=langchain")
    first = series.points[0]
    assert first.value is None
    assert first.value_state == "unknown"
    assert any("no posting can be called new" in note for note in first.notes)


def test_hiring_series_never_claims_a_posting_was_filled():
    features = build_job_features(job_records())
    assert {series.metric for series in features.series} == {"open_postings", "new_postings"}
    assert all(
        "not derived" in series.metadata["closed_postings"] for series in features.series
    )


def test_skill_series_are_built_from_explicit_skill_mentions():
    features = build_job_features(job_records())
    series = features.find_series("jobs:open_postings|company=langchain|skill=kubernetes")
    assert series.point("2026-W44").value == 3.0
    assert series.metadata["skill"] == "kubernetes"


def test_job_groupings_can_be_narrowed():
    features = build_job_features(
        job_records(),
        config=JobFeatureConfig(include_skills=False, families=("mlops",)),
    )
    groupings = {series.metadata.get("grouping") for series in features.series}
    assert groupings == {"all postings", "role family"}
    assert {series.metadata.get("role_family") for series in features.series} == {None, "mlops"}


def test_hiring_coverage_states_that_history_is_thin_by_construction():
    features = build_job_features(job_records())
    assert "collected prospectively" in features.coverage["history_note"]
    assert features.coverage["gap_policy"] == "unknown"


# --------------------------------------------------------------------------
# Attention features
# --------------------------------------------------------------------------


def test_syndicated_copies_count_as_one_origin():
    records = document_records()
    syndicated = [record for record in records if record["origin_cluster_id"] == SYNDICATED_ORIGIN]
    assert len(syndicated) == 2, "the fixture carries two copies of one origin"

    features = build_news_features(records)
    origins = features.find_series("news:distinct_origins|company=langchain")
    documents = features.find_series("news:documents|company=langchain")
    week = "2026-W43"
    assert origins.point(week).value == 1.0
    assert documents.point(week).value == 2.0
    assert "not independent corroboration" in features.coverage["dedup_note"]


def test_attention_weeks_inside_the_coverage_span_are_real_zeros():
    features = build_news_features(document_records())
    series = features.find_series("news:distinct_origins|company=langchain")
    assert series.gap_policy == "zero"
    quiet = series.point("2026-W41")
    assert quiet.value == 0.0
    assert quiet.value_state == "zero_by_policy"


def test_attention_uses_publication_time_when_available():
    features = build_news_features(document_records())
    assert features.coverage["time_basis"] == ["published_at"]
