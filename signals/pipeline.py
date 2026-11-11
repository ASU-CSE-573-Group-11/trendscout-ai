"""Build every weekly series from one snapshot and score it.

This is the Milestone A entry point: normalized records in, validated trend
signals out, with a coverage report that states what was and was not observed.
The output bundle mirrors Sueda's ``write_collection_bundle`` layout so the two
are read the same way.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from signals import FEATURE_VERSION
from signals.contract import to_payload, write_trend_signals
from signals.ewma import TrendConfig, TrendSignal, score_many
from signals.github_features import GitHubFeatureConfig, build_github_features
from signals.job_features import JobFeatureConfig, build_job_features
from signals.news_features import NewsFeatureConfig, build_news_features
from signals.series import WeeklySeries
from signals.topics import TopicConfig
from signals.weeks import iso_week, parse_instant, parse_iso_week, weeks_back


@dataclass
class FeatureBundle:
    """Every series built from one snapshot, with per-family coverage."""

    series: list[WeeklySeries] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    topic_model: Any = None

    def by_family(self, signal_family: str) -> list[WeeklySeries]:
        return [item for item in self.series if item.signal_family == signal_family]

    def by_metric(self, metric: str) -> list[WeeklySeries]:
        return [item for item in self.series if item.metric == metric]

    def find(self, series_id: str) -> WeeklySeries | None:
        for item in self.series:
            if item.series_id == series_id:
                return item
        return None


def build_feature_bundle(
    records: Iterable[Mapping[str, Any]],
    *,
    github_config: GitHubFeatureConfig | None = None,
    job_config: JobFeatureConfig | None = None,
    news_config: NewsFeatureConfig | None = None,
    topic_config: "TopicConfig | None" = None,
    include_topics: bool = False,
    validate: bool = True,
) -> FeatureBundle:
    """Build GitHub, hiring, attention, and optionally topic series."""
    records = list(records)
    github = build_github_features(records, config=github_config, validate=validate)
    jobs = build_job_features(records, config=job_config, validate=validate)
    news = build_news_features(records, config=news_config, validate=validate)

    series = [*github.series, *jobs.series, *news.series]

    # Topics are the proposal's lightweight trend-discovery baseline and are
    # opt-in: fitting a model changes the series set, and the other three
    # families should stay comparable between runs that do and do not use it.
    topic_model = None
    if include_topics or topic_config is not None:
        from signals.topics import TopicConfig, company_topic_series, fit_topics, topic_weekly_series

        topic_model = fit_topics(records, config=topic_config or TopicConfig())
        series.extend(topic_weekly_series(topic_model))
        series.extend(company_topic_series(topic_model))
    by_type: dict[str, int] = defaultdict(int)
    for record in records:
        by_type[str(record.get("source_type"))] += 1

    coverage = {
        "feature_version": FEATURE_VERSION,
        "records_received": len(records),
        "records_by_source_type": dict(sorted(by_type.items())),
        "series_count": len(series),
        "series_by_family": {
            family: len([item for item in series if item.signal_family == family])
            for family in sorted({item.signal_family for item in series})
        },
        "github": github.coverage,
        "jobs": jobs.coverage,
        "news": news.coverage,
    }
    if topic_model is not None:
        coverage["topics"] = topic_model.describe()
    return FeatureBundle(series=series, coverage=coverage, topic_model=topic_model)


def snapshot_week(records: Iterable[Mapping[str, Any]]) -> str | None:
    """The ISO week of the newest observation in a snapshot.

    Relative windows such as "the last eight weeks" are resolved against this,
    never against today's date: a frozen snapshot must answer the same question
    the same way next month.
    """
    latest = None
    for record in records:
        observed = record.get("observed_at")
        if not observed:
            continue
        instant = parse_instant(observed)
        if latest is None or instant > latest:
            latest = instant
    return iso_week(latest) if latest else None


@dataclass
class TrendRun:
    """Scored output for one snapshot."""

    signals: list[TrendSignal]
    bundle: FeatureBundle
    config: TrendConfig
    snapshot_week: str | None
    coverage: dict[str, Any]

    def payload(self) -> list[dict[str, Any]]:
        return to_payload(self.signals)

    def for_week(self, label: str) -> list[TrendSignal]:
        return [signal for signal in self.signals if signal.iso_week == label]

    @property
    def last_data_week(self) -> str | None:
        """The newest ISO week that any series actually observed.

        This differs from :attr:`snapshot_week` whenever the final collection
        window closes on a Monday boundary: the observation timestamp then falls
        in the following ISO week, which holds no data. Relative windows anchor
        here so "the last eight weeks" means eight weeks of evidence.
        """
        observed = [
            signal.iso_week for signal in self.signals if signal.value_state != "unknown"
        ]
        return max(observed, key=parse_iso_week) if observed else None

    def labels(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for signal in self.signals:
            counts[signal.label] += 1
        return dict(sorted(counts.items()))


def run_trend_pipeline(
    records: Iterable[Mapping[str, Any]],
    *,
    config: TrendConfig | None = None,
    github_config: GitHubFeatureConfig | None = None,
    job_config: JobFeatureConfig | None = None,
    news_config: NewsFeatureConfig | None = None,
    topic_config: "TopicConfig | None" = None,
    include_topics: bool = False,
    validate: bool = True,
) -> TrendRun:
    """Build and score every weekly series in one snapshot."""
    records = list(records)
    config = config or TrendConfig()
    bundle = build_feature_bundle(
        records,
        github_config=github_config,
        job_config=job_config,
        news_config=news_config,
        topic_config=topic_config,
        include_topics=include_topics,
        validate=validate,
    )
    signals = score_many(bundle.series, config)
    week = snapshot_week(records)
    coverage = {
        **bundle.coverage,
        "snapshot_week": week,
        "trend_config": config.as_dict(),
        "signal_count": len(signals),
        "labels": {},
    }
    run = TrendRun(
        signals=signals, bundle=bundle, config=config, snapshot_week=week, coverage=coverage
    )
    run.coverage["labels"] = run.labels()
    run.coverage["last_data_week"] = run.last_data_week
    return run


def write_trend_bundle(run: TrendRun, output_dir: Path) -> dict[str, Path]:
    """Write a trend run the way Sueda's collection bundle is written."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "trend_signals": write_trend_signals(run.signals, output_dir / "trend_signals.jsonl"),
        "series": output_dir / "series.json",
        "coverage": output_dir / "coverage.json",
    }
    paths["series"].write_text(
        json.dumps([series.as_dict() for series in run.bundle.series], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    paths["coverage"].write_text(json.dumps(run.coverage, indent=2, sort_keys=True), encoding="utf-8")
    return paths


# ---------------------------------------------------------------------------
# Cross-family selection used by the prototype questions.
# ---------------------------------------------------------------------------


def resolve_window(
    run: TrendRun, *, weeks: int = 8, last_week: str | None = None
) -> list[str]:
    """The ISO weeks of a relative window, anchored to the snapshot's evidence."""
    anchor = last_week or run.last_data_week or run.snapshot_week
    if not anchor:
        return []
    return weeks_back(anchor, weeks)


def rising_with_new_hiring(
    run: TrendRun,
    *,
    weeks: Sequence[str] | None = None,
    activity_metric: str = "commits",
    hiring_family: str = "mlops",
    hiring_metric: str = "new_postings",
    window_weeks: int = 8,
) -> list[dict[str, Any]]:
    """Companies with rising development activity *and* new hiring in a window.

    This answers the proposal's first prototype question without hard-coding it
    into the trend engine. "Rising" is the scored label on the activity series;
    "new hiring" is a positive observed count on the role-family series, because
    a role family that did not exist before has no baseline to rise against.

    Every returned company carries the record ids behind both halves of the
    answer, so an answer can cite them and abstain when they are missing.
    """
    window = list(weeks or resolve_window(run, weeks=window_weeks))
    wanted = set(window)
    activity: dict[str, list[TrendSignal]] = defaultdict(list)
    hiring: dict[str, list[TrendSignal]] = defaultdict(list)

    for signal in run.signals:
        if signal.company_id is None or signal.iso_week not in wanted:
            continue
        if (
            signal.signal_family == "github"
            and signal.entity_type == "company"
            and signal.metric == activity_metric
            and signal.label == "rising"
        ):
            activity[signal.company_id].append(signal)
        elif (
            signal.signal_family == "jobs"
            and signal.metric == hiring_metric
            and signal.entity_id.endswith(f":{hiring_family}")
            and signal.value is not None
            and signal.value > 0
        ):
            hiring[signal.company_id].append(signal)

    results: list[dict[str, Any]] = []
    for company_id in sorted(set(activity) & set(hiring)):
        activity_signals = sorted(activity[company_id], key=lambda item: item.iso_week)
        hiring_signals = sorted(hiring[company_id], key=lambda item: item.iso_week)
        record_ids: dict[str, None] = {}
        for signal in activity_signals + hiring_signals:
            for record_id in signal.record_ids:
                record_ids.setdefault(record_id, None)
        results.append(
            {
                "company_id": company_id,
                "window": window,
                "activity_metric": activity_metric,
                "hiring_family": hiring_family,
                "hiring_metric": hiring_metric,
                "activity_weeks": [signal.iso_week for signal in activity_signals],
                "activity_scores": [signal.trend_score for signal in activity_signals],
                "hiring_weeks": [signal.iso_week for signal in hiring_signals],
                "new_postings": [signal.value for signal in hiring_signals],
                "record_ids": list(record_ids),
                "trend_ids": [signal.trend_id for signal in activity_signals + hiring_signals],
            }
        )
    results.sort(key=lambda item: (-max(score or 0.0 for score in item["activity_scores"]), item["company_id"]))
    return results


def companies_missing_signal(
    run: TrendRun,
    *,
    weeks: Sequence[str] | None = None,
    metric: str = "commits",
    window_weeks: int = 8,
) -> dict[str, list[str]]:
    """Per company, the windowed weeks whose label is ``insufficient_history``.

    The interface uses this to name the missing evidence when it abstains,
    rather than reporting an absence of signal as an absence of activity.
    """
    window = set(weeks or resolve_window(run, weeks=window_weeks))
    gaps: dict[str, list[str]] = defaultdict(list)
    for signal in run.signals:
        if (
            signal.company_id
            and signal.metric == metric
            and signal.entity_type == "company"
            and signal.iso_week in window
            and signal.label == "insufficient_history"
        ):
            gaps[signal.company_id].append(signal.iso_week)
    return {
        company_id: sorted(labels, key=parse_iso_week) for company_id, labels in sorted(gaps.items())
    }


__all__ = [
    "FeatureBundle",
    "TrendRun",
    "build_feature_bundle",
    "companies_missing_signal",
    "resolve_window",
    "rising_with_new_hiring",
    "run_trend_pipeline",
    "snapshot_week",
    "write_trend_bundle",
]
