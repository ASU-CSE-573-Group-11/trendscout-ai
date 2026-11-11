"""Weekly attention features from documentary records, after deduplication.

The unit of attention is the **origin cluster**, not the article. Syndicated
copies share an ``origin_cluster_id`` (Sueda's clustering assigns it), and the
evidence ledger is explicit that copies of one origin are not independent
corroboration. Counting articles instead of origins would let a single press
release look like a wave of coverage.

Unlike GitHub snapshots and job boards, news and company feeds are harvested
continuously across a date range. Inside that range a week with no article is a
real observation of absence, so these series use ``gap_policy="zero"``. Outside
the range nothing is claimed at all.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from signals.adapters import ADAPTER_VERSION, DocumentObservation, document_observations
from signals.series import WeekPoint, WeeklySeries
from signals.weeks import iso_week, parse_iso_week, week_range

SIGNAL_FAMILY = "news"

NEWS_METRICS: tuple[str, ...] = ("distinct_origins", "documents", "distinct_publishers")


@dataclass(frozen=True)
class NewsFeatureConfig:
    """Coverage span and grouping controls."""

    coverage_start: str | None = None
    coverage_end: str | None = None
    include_document_counts: bool = True
    include_publisher_counts: bool = True
    source_types: tuple[str, ...] | None = None


@dataclass
class NewsFeatureSet:
    series: list[WeeklySeries]
    coverage: dict[str, Any]

    def by_metric(self, metric: str) -> list[WeeklySeries]:
        return [item for item in self.series if item.metric == metric]

    def find_series(self, series_id: str) -> WeeklySeries:
        for item in self.series:
            if item.series_id == series_id:
                return item
        raise KeyError(f"no series {series_id!r}; built {len(self.series)} series")


def _series_id(metric: str, company_id: str) -> str:
    return f"{SIGNAL_FAMILY}:{metric}|company={company_id}"


def build_news_features(
    records: Iterable[Mapping[str, Any]] | Iterable[DocumentObservation],
    *,
    config: NewsFeatureConfig | None = None,
    validate: bool = True,
) -> NewsFeatureSet:
    """Build weekly distinct-origin attention series per cohort company."""
    config = config or NewsFeatureConfig()
    items = list(records)
    if items and isinstance(items[0], DocumentObservation):
        observations: list[DocumentObservation] = list(items)  # type: ignore[arg-type]
    else:
        observations = document_observations(items, validate=validate)  # type: ignore[arg-type]
    if config.source_types:
        wanted = set(config.source_types)
        observations = [item for item in observations if item.source_type in wanted]

    by_company: dict[str, list[DocumentObservation]] = defaultdict(list)
    for observation in observations:
        if observation.company_id:
            by_company[observation.company_id].append(observation)

    all_weeks: set[str] = set()
    observed_weeks = {iso_week(item.at) for item in observations}
    span_start = config.coverage_start or (
        min(observed_weeks, key=parse_iso_week) if observed_weeks else None
    )
    span_end = config.coverage_end or (
        max(observed_weeks, key=parse_iso_week) if observed_weeks else None
    )
    labels = week_range(span_start, span_end) if span_start and span_end else []
    all_weeks.update(labels)

    series: list[WeeklySeries] = []
    time_bases: set[str] = {item.time_basis for item in observations}

    for company_id, company_observations in sorted(by_company.items()):
        weekly: dict[str, list[DocumentObservation]] = defaultdict(list)
        for observation in company_observations:
            weekly[iso_week(observation.at)].append(observation)

        metrics: list[tuple[str, str, Any]] = [
            (
                "distinct_origins",
                "independent documentary origins after deduplication",
                lambda group: len({item.origin_cluster_id for item in group}),
            )
        ]
        if config.include_document_counts:
            metrics.append(
                (
                    "documents",
                    "records before origin deduplication; kept for comparison only",
                    len,
                )
            )
        if config.include_publisher_counts:
            metrics.append(
                (
                    "distinct_publishers",
                    "distinct publishers, which may still share one origin",
                    lambda group: len({item.publisher for item in group if item.publisher}),
                )
            )

        for metric, description, counter in metrics:
            observations_map = {
                label: WeekPoint(
                    iso_week=label,
                    value=float(counter(group)),
                    value_state="observed",
                    record_ids=tuple(sorted(item.record_id for item in group)),
                    origin_cluster_ids=tuple(sorted({item.origin_cluster_id for item in group})),
                    notes=(description,),
                )
                for label, group in weekly.items()
                if label in set(labels)
            }
            series.append(
                WeeklySeries.from_observations(
                    series_id=_series_id(metric, company_id),
                    metric=metric,
                    signal_family=SIGNAL_FAMILY,
                    entity_type="company",
                    entity_id=company_id,
                    company_id=company_id,
                    observations=observations_map,
                    gap_policy="zero",
                    coverage_start=labels[0] if labels else None,
                    coverage_end=labels[-1] if labels else None,
                    metadata={
                        "adapter_version": ADAPTER_VERSION,
                        "description": description,
                        "time_basis": sorted(time_bases),
                        "dedup": "origin_cluster_id",
                    },
                )
            )

    coverage = {
        "signal_family": SIGNAL_FAMILY,
        "adapter_version": ADAPTER_VERSION,
        "companies": sorted(by_company),
        "weeks": sorted(all_weeks, key=parse_iso_week),
        "documents_received": len(observations),
        "time_basis": sorted(time_bases),
        "gap_policy": "zero",
        "gap_policy_reason": (
            "news and company feeds are harvested continuously, so inside the coverage span a "
            "week with no article is a real zero rather than a missing observation"
        ),
        "coverage_span": [span_start, span_end],
        "dedup_note": (
            "attention is counted per origin cluster; syndicated copies of one origin are not "
            "independent corroboration (docs/evidence-ledger.md)"
        ),
    }
    return NewsFeatureSet(series=series, coverage=coverage)


__all__ = [
    "NEWS_METRICS",
    "NewsFeatureConfig",
    "NewsFeatureSet",
    "SIGNAL_FAMILY",
    "build_news_features",
]
