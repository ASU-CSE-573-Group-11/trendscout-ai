"""EWMA baseline, rolling z-score, gap handling, and the trend contract."""

from __future__ import annotations

import pytest

from faisal_snapshot import github_records, job_records, snapshot_records
from signals.contract import (
    read_trend_signals,
    to_payload,
    validate_trend_signal,
    write_trend_signals,
)
from signals.ewma import (
    TrendConfig,
    latest_signal,
    rising_entities,
    score_many,
    score_series,
)
from signals.pipeline import (
    companies_missing_signal,
    resolve_window,
    rising_with_new_hiring,
    run_trend_pipeline,
    write_trend_bundle,
)
from signals.series import WeekPoint, WeeklySeries, series_from_weekly_values
from signals.weeks import week_range, weeks_back


def steady(count: int, value: float = 10.0, first_week: int = 30) -> dict[str, float]:
    return {
        label: value
        for label in week_range(f"2026-W{first_week:02d}", f"2026-W{first_week + count - 1:02d}")
    }


# --------------------------------------------------------------------------
# Series semantics
# --------------------------------------------------------------------------


def test_missing_weeks_are_materialized_according_to_the_declared_policy():
    unknown = series_from_weekly_values(
        {"2026-W30": 1.0, "2026-W33": 4.0}, series_id="u", metric="commits", gap_policy="unknown"
    )
    assert [point.value for point in unknown.points] == [1.0, None, None, 4.0]
    assert [point.value_state for point in unknown.points] == [
        "observed",
        "unknown",
        "unknown",
        "observed",
    ]

    zeroed = series_from_weekly_values(
        {"2026-W30": 1.0, "2026-W33": 4.0}, series_id="z", metric="documents", gap_policy="zero"
    )
    assert [point.value for point in zeroed.points] == [1.0, 0.0, 0.0, 4.0]
    assert zeroed.points[1].value_state == "zero_by_policy"


def test_a_series_never_materializes_weeks_outside_its_coverage_span():
    series = series_from_weekly_values({"2026-W30": 1.0}, series_id="s", metric="commits")
    assert [point.iso_week for point in series.points] == ["2026-W30"]


def test_an_unknown_week_cannot_carry_a_value():
    with pytest.raises(ValueError, match="unknown week"):
        WeekPoint(iso_week="2026-W30", value=3.0, value_state="unknown")


def test_points_must_be_in_week_order():
    with pytest.raises(ValueError, match="week order"):
        WeeklySeries(
            series_id="s",
            metric="commits",
            signal_family="github",
            entity_type="series",
            entity_id="s",
            company_id=None,
            points=(WeekPoint("2026-W33", 1.0), WeekPoint("2026-W30", 1.0)),
        )


# --------------------------------------------------------------------------
# Scoring behaviour
# --------------------------------------------------------------------------


def test_the_first_observed_week_has_no_baseline_and_no_score():
    signals = score_series(series_from_weekly_values(steady(6), series_id="s", metric="commits"))
    first = signals[0]
    assert first.ewma_baseline is None
    assert first.trend_score is None
    assert first.label == "insufficient_history"
    assert first.label_reason == "cold_start_first_observed_week"


def test_short_history_is_labelled_insufficient_rather_than_flat():
    config = TrendConfig(min_history=4)
    signals = score_series(
        series_from_weekly_values(steady(3), series_id="s", metric="commits"), config
    )
    assert [signal.label for signal in signals] == ["insufficient_history"] * 3
    assert all(signal.trend_score is None for signal in signals)
    assert "below min_history" in signals[2].label_reason


def test_the_baseline_never_sees_the_current_week():
    values = {**steady(5, 10.0), "2026-W35": 40.0}
    signals = score_series(series_from_weekly_values(values, series_id="s", metric="commits"))
    spike = signals[-1]
    assert spike.value == 40.0
    # The baseline is the level from the five preceding weeks of 10.
    assert spike.ewma_baseline == pytest.approx(10.0)
    assert spike.residual == pytest.approx(30.0)


def test_a_sustained_step_up_is_labelled_rising():
    values = {**steady(6, 10.0), "2026-W36": 11.0, "2026-W37": 30.0}
    signals = score_series(series_from_weekly_values(values, series_id="s", metric="commits"))
    assert signals[-1].label == "rising"
    assert signals[-1].trend_score > 1.5


def test_a_sustained_step_down_is_labelled_falling():
    values = {**{label: 30.0 for label in week_range("2026-W30", "2026-W35")}, "2026-W36": 28.0, "2026-W37": 4.0}
    signals = score_series(series_from_weekly_values(values, series_id="s", metric="commits"))
    assert signals[-1].label == "falling"
    assert signals[-1].trend_score < -1.5


def test_a_constant_series_is_flat_and_not_an_alert():
    signals = score_series(series_from_weekly_values(steady(10), series_id="s", metric="commits"))
    scored = [signal for signal in signals if signal.trend_score is not None]
    assert scored
    assert all(signal.label == "flat" for signal in scored)
    assert all(signal.trend_score == pytest.approx(0.0) for signal in scored)


def test_the_min_scale_floor_stops_a_near_constant_series_from_exploding():
    values = {**steady(8, 10.0), "2026-W38": 11.0}
    loose = score_series(
        series_from_weekly_values(values, series_id="s", metric="commits"),
        TrendConfig(min_scale=1.0),
    )[-1]
    assert loose.label == "flat"
    assert abs(loose.trend_score) <= 1.5
    assert any("min_scale" in note for note in loose.notes)


def test_a_score_is_clipped_to_the_configured_cap():
    values = {**steady(8, 10.0), "2026-W38": 10_000.0}
    signal = score_series(
        series_from_weekly_values(values, series_id="s", metric="commits"),
        TrendConfig(z_cap=2.0),
    )[-1]
    assert signal.trend_score == 2.0
    assert any("clipped" in note for note in signal.notes)


@pytest.mark.parametrize("window", [4, 8, 12])
def test_a_single_week_spike_saturates_at_the_square_root_of_the_window(window):
    """A one-week spike cannot score arbitrarily high.

    The current residual is part of its own dispersion window, so for a window
    of ``n`` residuals a lone outlier of any size scores exactly ``sqrt(n)``.
    This bounds the false-alert rate and is the reason ``threshold`` must stay
    below ``sqrt(window)`` to be reachable at all.
    """
    weeks = week_range("2026-W20", f"2026-W{19 + window:02d}")
    values = {label: 10.0 for label in weeks}
    values[f"2026-W{20 + window:02d}"] = 1_000_000.0
    signal = score_series(
        series_from_weekly_values(values, series_id="s", metric="commits"),
        TrendConfig(window=window, z_cap=1000.0),
    )[-1]
    assert signal.residual_points_used == window
    assert signal.trend_score == pytest.approx(window**0.5, rel=1e-6)


def test_an_unknown_week_neither_scores_nor_moves_the_baseline():
    values = {**steady(6, 10.0), "2026-W36": None, "2026-W37": 10.0}
    signals = score_series(series_from_weekly_values(values, series_id="s", metric="commits"))
    gap = next(signal for signal in signals if signal.iso_week == "2026-W36")
    after = next(signal for signal in signals if signal.iso_week == "2026-W37")
    assert gap.value is None
    assert gap.trend_score is None
    assert gap.label == "insufficient_history"
    assert gap.label_reason == "unknown_value"
    # The level carried across the gap unchanged.
    assert after.ewma_baseline == pytest.approx(gap.ewma_baseline)
    assert any("cannot be read as a decline" in note for note in gap.notes)


def test_a_collection_gap_does_not_produce_a_falling_label():
    values = {label: 10.0 for label in week_range("2026-W30", "2026-W40")}
    values["2026-W38"] = None
    values["2026-W39"] = None
    signals = score_series(series_from_weekly_values(values, series_id="s", metric="commits"))
    assert all(signal.label != "falling" for signal in signals)


def test_the_robust_scale_option_is_available():
    values = {**steady(8, 10.0), "2026-W38": 25.0}
    series = series_from_weekly_values(values, series_id="s", metric="commits")
    assert score_series(series, TrendConfig(scale_method="mad"))[-1].scale_method == "mad"


def test_configuration_is_validated():
    with pytest.raises(ValueError, match="alpha"):
        TrendConfig(alpha=0.0)
    with pytest.raises(ValueError, match="window"):
        TrendConfig(window=1)
    with pytest.raises(ValueError, match="threshold"):
        TrendConfig(threshold=0.0)
    with pytest.raises(ValueError, match="scale method"):
        TrendConfig(scale_method="variance")


# --------------------------------------------------------------------------
# Traceability and the shared contract
# --------------------------------------------------------------------------


def test_every_signal_carries_the_records_it_was_computed_from():
    records = github_records()
    known = {record["record_id"] for record in records}
    run = run_trend_pipeline(records)
    traced = 0
    for signal in run.signals:
        assert set(signal.record_ids) <= known
        assert set(signal.window_record_ids) <= known
        if signal.value_state == "observed" and signal.signal_family == "github":
            if signal.metric in {"commits", "human_commits"}:
                assert signal.record_ids, f"{signal.series_id}@{signal.iso_week} has no evidence"
                traced += 1
    assert traced


def test_the_scoring_window_records_include_the_baseline_weeks():
    run = run_trend_pipeline(github_records())
    scored = [
        signal
        for signal in run.signals
        if signal.metric == "commits" and signal.trend_score is not None and signal.residual_points_used > 2
    ]
    assert scored
    signal = scored[-1]
    assert set(signal.record_ids) <= set(signal.window_record_ids)
    assert len(signal.window_record_ids) > len(signal.record_ids)


def test_signals_validate_against_the_trend_contract():
    run = run_trend_pipeline(snapshot_records())
    payload = to_payload(run.signals)
    assert len(payload) == len(run.signals)
    assert all(validate_trend_signal(signal) == [] for signal in payload)


def test_the_contract_rejects_an_unsupported_label():
    run = run_trend_pipeline(github_records())
    broken = {**to_payload(run.signals[:1])[0], "label": "spiking"}
    assert validate_trend_signal(broken)


def test_the_contract_rejects_an_unknown_field():
    run = run_trend_pipeline(github_records())
    broken = {**to_payload(run.signals[:1])[0], "confidence": 0.9}
    assert validate_trend_signal(broken)


def test_trend_ids_are_deterministic_and_track_the_configuration():
    series = series_from_weekly_values(steady(6), series_id="s", metric="commits")
    first = score_series(series, TrendConfig())
    again = score_series(series, TrendConfig())
    assert [signal.trend_id for signal in first] == [signal.trend_id for signal in again]

    retuned = score_series(series, TrendConfig(alpha=0.5))
    assert [signal.trend_id for signal in first] != [signal.trend_id for signal in retuned]


def test_the_configuration_is_reported_with_every_signal():
    signal = latest_signal(
        series_from_weekly_values(steady(6), series_id="s", metric="commits"),
        TrendConfig(alpha=0.4, window=6, threshold=2.0),
    )
    assert signal.config["alpha"] == 0.4
    assert signal.config["window"] == 6
    assert signal.config["threshold"] == 2.0
    assert signal.config["fingerprint"]


def test_a_trend_bundle_round_trips_through_jsonl(tmp_path):
    run = run_trend_pipeline(snapshot_records())
    paths = write_trend_bundle(run, tmp_path / "bundle")
    reloaded = read_trend_signals(paths["trend_signals"])
    assert len(reloaded) == len(run.signals)
    assert {signal["trend_id"] for signal in reloaded} == {
        signal.trend_id for signal in run.signals
    }
    assert paths["coverage"].exists()
    assert paths["series"].exists()


def test_writing_refuses_signals_that_break_the_contract(tmp_path):
    run = run_trend_pipeline(github_records())
    bad = run.signals[0]
    object.__setattr__(bad, "label", "spiking")
    with pytest.raises(ValueError, match="shared contract"):
        write_trend_signals([bad], tmp_path / "bad.jsonl")


# --------------------------------------------------------------------------
# The scorer is generic over any weekly series
# --------------------------------------------------------------------------


def test_the_same_scorer_handles_github_hiring_and_attention_series():
    run = run_trend_pipeline(snapshot_records())
    families = {signal.signal_family for signal in run.signals}
    assert families == {"github", "jobs", "news"}
    assert all(signal.feature_version for signal in run.signals)


def test_a_hiring_series_is_scored_without_any_github_specific_code():
    hiring = [
        series
        for series in run_trend_pipeline(job_records()).bundle.series
        if series.metric == "open_postings"
    ]
    assert hiring
    signals = score_many(hiring)
    assert signals
    assert {signal.signal_family for signal in signals} == {"jobs"}


def test_rising_entities_filters_scored_signals():
    run = run_trend_pipeline(github_records())
    window = resolve_window(run, weeks=8)
    rising = rising_entities(run.signals, weeks=window, metric="commits")
    assert rising
    assert all(signal.label == "rising" for signal in rising)
    assert all(signal.iso_week in set(window) for signal in rising)
    scores = [signal.trend_score for signal in rising]
    assert scores == sorted(scores, reverse=True)


# --------------------------------------------------------------------------
# The prototype question
# --------------------------------------------------------------------------


def test_relative_windows_resolve_against_the_snapshot_not_today():
    run = run_trend_pipeline(snapshot_records())
    window = resolve_window(run, weeks=8)
    assert len(window) == 8
    assert window == weeks_back(run.last_data_week, 8)
    assert window[-1] == "2026-W44"


def test_rising_activity_plus_new_hiring_identifies_the_expected_companies():
    run = run_trend_pipeline(snapshot_records())
    matches = rising_with_new_hiring(run, window_weeks=8)
    assert [match["company_id"] for match in matches] == ["crewai", "langchain"] or [
        match["company_id"] for match in matches
    ] == ["langchain", "crewai"]
    by_company = {match["company_id"]: match for match in matches}
    # LlamaIndex has flat commits and no MLOps posting, so it must not appear.
    assert "llamaindex" not in by_company
    langchain = by_company["langchain"]
    assert langchain["hiring_family"] == "mlops"
    assert all(value > 0 for value in langchain["new_postings"])
    assert langchain["record_ids"]
    assert langchain["trend_ids"]


def test_insufficient_history_is_reported_separately_from_absence_of_activity():
    run = run_trend_pipeline(snapshot_records())
    gaps = companies_missing_signal(run, window_weeks=8)
    assert "2026-W42" in gaps["langchain"], "the unobserved week must be named, not ignored"
