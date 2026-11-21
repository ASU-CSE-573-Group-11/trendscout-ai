"""Weekly GitHub activity features per repository and per cohort company.

Input is Vidya's normalized GitHub records; output is a set of
:class:`~signals.series.WeeklySeries` plus a coverage report. The series are
then scored by :mod:`signals.ewma`, which does not know they came from GitHub.

What the upstream collector actually provides
---------------------------------------------
Her collector emits **one record per repository per collection run**, covering a
trailing ``(start, end]`` commit window on the default branch. That is not a
calendar week, and three consequences shape this module:

1. **Weeks must be assigned, not assumed.** A window that exactly spans an ISO
   week is attributed to it (``aligned_window``). Any other window is
   attributed to the ISO week containing its final instant and flagged
   ``window_end_approximate``, because the collector does not expose per-commit
   dates. If a future snapshot does carry per-commit timestamps, each commit is
   placed in its own ISO week (``commit_timestamp``) and the flag disappears.
2. **Stars and forks are running totals, not weekly growth.** A weekly delta is
   the difference between consecutive *observed* weeks. When the previous ISO
   week was not observed, the delta is ``unknown`` rather than a multi-week
   change dressed up as one week.
3. **Repeated snapshots must not inflate counts.** Identical snapshots share a
   ``content_hash``; overlapping windows share commit SHAs. Deduplication is by
   content hash first and then by SHA union, so collecting twice in one week
   yields the same commit count as collecting once.

Metrics the collector cannot supply (releases, issues opened/closed, active
contributors) are reported as explicitly unavailable, with the reason, instead
of being emitted as zeros. See :data:`signals.adapters.GITHUB_UNAVAILABLE_METRICS`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Iterable, Mapping, Sequence

from signals.adapters import (
    ADAPTER_VERSION,
    GITHUB_UNAVAILABLE_METRICS,
    GitHubObservation,
    github_observations,
)
from signals.series import WeekPoint, WeeklySeries, unavailable_series
from signals.weeks import covers_whole_week, iso_week, parse_iso_week, week_range

SIGNAL_FAMILY = "github"

#: Series produced per repository and rolled up per company.
GITHUB_METRICS: tuple[str, ...] = (
    "commits",
    "human_commits",
    "star_delta",
    "open_issues_delta",
)

#: Running totals kept as their own series for context, not for alerting.
GITHUB_LEVEL_METRICS: tuple[str, ...] = ("stars", "open_issues")


@dataclass(frozen=True)
class GitHubFeatureConfig:
    """Repository-quality and aggregation controls."""

    include_forks: bool = False
    include_mirrors: bool = False
    include_archived: bool = False
    drop_bot_heavy_repositories: bool = False
    include_level_metrics: bool = True
    include_unavailable_metrics: bool = False

    def excluded_reasons(self, observation: GitHubObservation) -> tuple[str, ...]:
        flags = observation.quality_flags
        reasons: list[str] = []
        if flags.get("fork") and not self.include_forks:
            reasons.append("fork")
        if flags.get("is_mirror") and not self.include_mirrors:
            reasons.append("mirror")
        if flags.get("archived") and not self.include_archived:
            reasons.append("archived")
        if flags.get("disabled"):
            reasons.append("disabled")
        if flags.get("bot_heavy") and self.drop_bot_heavy_repositories:
            reasons.append("bot_heavy")
        return tuple(reasons)


@dataclass
class WeekAggregate:
    """Everything known about one repository in one ISO week."""

    company_id: str
    repository: str
    iso_week: str
    record_ids: list[str] = field(default_factory=list)
    origin_cluster_ids: list[str] = field(default_factory=list)
    commit_shas: set[str] = field(default_factory=set)
    commit_counts: list[int] = field(default_factory=list)
    shas_complete: bool = True
    bot_ratio: float | None = None
    stars: int | None = None
    open_issues: int | None = None
    bot_heavy: bool = False
    week_assignment: set[str] = field(default_factory=set)
    latest_observed_at: Any = None
    duplicate_record_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def commits(self) -> int:
        if self.shas_complete:
            return len(self.commit_shas)
        # Without SHAs, overlapping windows cannot be merged safely. Taking the
        # largest single window is the conservative choice: it never invents
        # activity, it only risks under-counting.
        return max(self.commit_counts or [0])

    @property
    def bot_commits(self) -> int:
        if self.bot_ratio is None:
            return 0
        return min(self.commits, round(self.commits * self.bot_ratio))

    @property
    def human_commits(self) -> int:
        return max(0, self.commits - self.bot_commits)


@dataclass
class GitHubFeatureSet:
    """Weekly GitHub series plus the coverage facts needed to read them."""

    series: list[WeeklySeries]
    coverage: dict[str, Any]

    def by_metric(self, metric: str) -> list[WeeklySeries]:
        return [item for item in self.series if item.metric == metric]

    def find_series(self, series_id: str) -> WeeklySeries:
        for item in self.series:
            if item.series_id == series_id:
                return item
        raise KeyError(f"no series {series_id!r}; built {len(self.series)} series")

    def company_series(self, metric: str | None = None) -> list[WeeklySeries]:
        return [
            item
            for item in self.series
            if item.entity_type == "company" and (metric is None or item.metric == metric)
        ]

    def repository_series(self, metric: str | None = None) -> list[WeeklySeries]:
        return [
            item
            for item in self.series
            if item.entity_type == "repository" and (metric is None or item.metric == metric)
        ]


def _repo_series_id(metric: str, company_id: str, repository: str) -> str:
    return f"{SIGNAL_FAMILY}:{metric}|company={company_id}|repo={repository}"


def _company_series_id(metric: str, company_id: str) -> str:
    return f"{SIGNAL_FAMILY}:{metric}|company={company_id}"


def assign_weeks(observation: GitHubObservation) -> list[tuple[str, set[str], str]]:
    """Place an observation's commits into ISO weeks.

    Returns ``(iso_week, commit_shas, assignment_method)`` triples. Exactly one
    triple unless per-commit timestamps are available, in which case the window
    is split across the weeks the commits actually fall in.
    """
    if observation.commit_events:
        buckets: dict[str, set[str]] = defaultdict(set)
        for sha, at in observation.commit_events:
            buckets[iso_week(at)].add(sha)
        if buckets:
            return [(label, shas, "commit_timestamp") for label, shas in sorted(buckets.items())]
        # A window with per-commit detail but no commits still observed a week.
        return [(iso_week(observation.window_end - timedelta(microseconds=1)), set(), "commit_timestamp")]

    aligned = covers_whole_week(observation.window_start, observation.window_end)
    if aligned:
        return [(aligned, set(observation.commit_shas), "aligned_window")]
    # The interval is (start, end], so the final instant belongs to the window.
    label = iso_week(observation.window_end - timedelta(microseconds=1))
    return [(label, set(observation.commit_shas), "window_end_approximate")]


def _aggregate(
    observations: Sequence[GitHubObservation], config: GitHubFeatureConfig
) -> tuple[dict[tuple[str, str, str], WeekAggregate], dict[str, Any]]:
    excluded: dict[str, list[str]] = {}
    duplicates: list[str] = []
    seen_hashes: dict[tuple[str, str], GitHubObservation] = {}
    kept: list[GitHubObservation] = []

    for observation in sorted(observations, key=lambda item: (item.observed_at, item.record_id)):
        reasons = config.excluded_reasons(observation)
        if reasons:
            excluded.setdefault(observation.repository, [])
            for reason in reasons:
                if reason not in excluded[observation.repository]:
                    excluded[observation.repository].append(reason)
            continue
        key = (observation.repository, observation.content_hash)
        if key in seen_hashes:
            duplicates.append(observation.record_id)
            continue
        seen_hashes[key] = observation
        kept.append(observation)

    aggregates: dict[tuple[str, str, str], WeekAggregate] = {}
    for observation in kept:
        for label, shas, method in assign_weeks(observation):
            key = (observation.company_id, observation.repository, label)
            aggregate = aggregates.get(key)
            if aggregate is None:
                aggregate = WeekAggregate(
                    company_id=observation.company_id,
                    repository=observation.repository,
                    iso_week=label,
                )
                aggregates[key] = aggregate
            aggregate.record_ids.append(observation.record_id)
            if observation.origin_cluster_id not in aggregate.origin_cluster_ids:
                aggregate.origin_cluster_ids.append(observation.origin_cluster_id)
            aggregate.commit_shas.update(shas)
            aggregate.commit_counts.append(observation.commit_count)
            if not observation.commit_shas and observation.commit_count:
                aggregate.shas_complete = False
                aggregate.notes.append(
                    "a contributing snapshot reported commits without SHAs; overlapping "
                    "windows cannot be merged, so the largest single window is used"
                )
            aggregate.week_assignment.add(method)
            aggregate.bot_heavy = aggregate.bot_heavy or observation.is_bot_heavy
            if aggregate.latest_observed_at is None or observation.observed_at >= aggregate.latest_observed_at:
                aggregate.latest_observed_at = observation.observed_at
                # Running totals and the bot ratio come from the most recent
                # snapshot in the week; the commit count comes from the SHA union.
                aggregate.stars = observation.stars
                aggregate.open_issues = observation.open_issues
                aggregate.bot_ratio = observation.bot_ratio

    for aggregate in aggregates.values():
        if len(aggregate.record_ids) > 1:
            aggregate.notes.append(
                f"{len(aggregate.record_ids)} snapshots contributed to this week; commits are a "
                "SHA union and running totals come from the latest snapshot"
            )
        if "window_end_approximate" in aggregate.week_assignment:
            aggregate.notes.append(
                "commit window does not align to the ISO week; attributed to the week "
                "containing the window end"
            )

    report = {
        "excluded_repositories": {name: sorted(reasons) for name, reasons in sorted(excluded.items())},
        "duplicate_record_ids": sorted(duplicates),
        "observations_used": len(kept),
        "observations_received": len(observations),
    }
    return aggregates, report


def _delta_points(
    labels: Sequence[str],
    levels: dict[str, int | None],
    aggregates: dict[str, WeekAggregate],
    *,
    metric: str,
) -> dict[str, WeekPoint]:
    """Week-over-week change of a running total.

    A delta is only emitted when the immediately preceding ISO week was also
    observed. Spanning a gap would report several weeks of growth as one week's
    growth, which is exactly the false alert this project is meant to avoid.
    """
    points: dict[str, WeekPoint] = {}
    for index, label in enumerate(labels):
        current = levels.get(label)
        if current is None or index == 0:
            continue
        previous_label = labels[index - 1]
        previous = levels.get(previous_label)
        aggregate = aggregates.get(label)
        record_ids = tuple(aggregate.record_ids) if aggregate else ()
        origins = tuple(aggregate.origin_cluster_ids) if aggregate else ()
        if previous is None:
            points[label] = WeekPoint(
                iso_week=label,
                value=None,
                value_state="unknown",
                notes=(
                    f"{metric} needs the previous week as a baseline; {previous_label} was not "
                    "observed, and a multi-week change must not be reported as one week",
                ),
            )
            continue
        points[label] = WeekPoint(
            iso_week=label,
            value=float(current - previous),
            value_state="observed",
            record_ids=record_ids,
            origin_cluster_ids=origins,
            notes=(f"difference against {previous_label}",),
        )
    return points


def _series_for_repository(
    company_id: str,
    repository: str,
    aggregates: dict[str, WeekAggregate],
    labels: Sequence[str],
    config: GitHubFeatureConfig,
) -> list[WeeklySeries]:
    series: list[WeeklySeries] = []
    base_metadata = {
        "repository": repository,
        "adapter_version": ADAPTER_VERSION,
        "week_assignment": sorted({method for item in aggregates.values() for method in item.week_assignment}),
        "bot_heavy": any(item.bot_heavy for item in aggregates.values()),
    }

    for metric, getter in (
        ("commits", lambda item: float(item.commits)),
        ("human_commits", lambda item: float(item.human_commits)),
    ):
        observations = {
            label: WeekPoint(
                iso_week=label,
                value=getter(aggregate),
                value_state="observed",
                record_ids=tuple(aggregate.record_ids),
                origin_cluster_ids=tuple(aggregate.origin_cluster_ids),
                notes=tuple(dict.fromkeys(aggregate.notes)),
            )
            for label, aggregate in aggregates.items()
        }
        series.append(
            WeeklySeries.from_observations(
                series_id=_repo_series_id(metric, company_id, repository),
                metric=metric,
                signal_family=SIGNAL_FAMILY,
                entity_type="repository",
                entity_id=repository,
                company_id=company_id,
                observations=observations,
                gap_policy="unknown",
                coverage_start=labels[0] if labels else None,
                coverage_end=labels[-1] if labels else None,
                metadata={
                    **base_metadata,
                    "bot_commits_estimated": metric == "human_commits"
                    and any(len(item.record_ids) > 1 for item in aggregates.values()),
                },
            )
        )

    star_levels = {label: aggregate.stars for label, aggregate in aggregates.items()}
    issue_levels = {label: aggregate.open_issues for label, aggregate in aggregates.items()}

    if config.include_level_metrics:
        for metric, levels in (("stars", star_levels), ("open_issues", issue_levels)):
            observations = {
                label: WeekPoint(
                    iso_week=label,
                    value=float(value),
                    value_state="observed",
                    record_ids=tuple(aggregates[label].record_ids),
                    origin_cluster_ids=tuple(aggregates[label].origin_cluster_ids),
                    notes=("running total reported by the source, not weekly growth",),
                )
                for label, value in levels.items()
                if value is not None
            }
            series.append(
                WeeklySeries.from_observations(
                    series_id=_repo_series_id(metric, company_id, repository),
                    metric=metric,
                    signal_family=SIGNAL_FAMILY,
                    entity_type="repository",
                    entity_id=repository,
                    company_id=company_id,
                    observations=observations,
                    gap_policy="unknown",
                    unit="running_total",
                    coverage_start=labels[0] if labels else None,
                    coverage_end=labels[-1] if labels else None,
                    metadata={**base_metadata, "alerting": "not recommended; this is a level, not a change"},
                )
            )

    for metric, levels in (("star_delta", star_levels), ("open_issues_delta", issue_levels)):
        series.append(
            WeeklySeries.from_observations(
                series_id=_repo_series_id(metric, company_id, repository),
                metric=metric,
                signal_family=SIGNAL_FAMILY,
                entity_type="repository",
                entity_id=repository,
                company_id=company_id,
                observations=_delta_points(labels, levels, aggregates, metric=metric),
                gap_policy="unknown",
                unit="change",
                coverage_start=labels[0] if labels else None,
                coverage_end=labels[-1] if labels else None,
                metadata=dict(base_metadata),
            )
        )

    if config.include_unavailable_metrics:
        for metric, reason in GITHUB_UNAVAILABLE_METRICS.items():
            series.append(
                unavailable_series(
                    series_id=_repo_series_id(metric, company_id, repository),
                    metric=metric,
                    signal_family=SIGNAL_FAMILY,
                    entity_type="repository",
                    entity_id=repository,
                    company_id=company_id,
                    reason=reason,
                    weeks=labels,
                )
            )
    return series


def _rollup_company(
    company_id: str,
    repo_series: Sequence[WeeklySeries],
    labels: Sequence[str],
    metric: str,
    unit: str,
) -> WeeklySeries:
    """Sum a repository-level metric to company level over observed repositories.

    A company week is observed when at least one of its repositories was
    observed. Repositories missing that week are listed in the point's notes
    rather than being treated as zero.
    """
    members = [item for item in repo_series if item.metric == metric]
    observations: dict[str, WeekPoint] = {}
    for label in labels:
        total = 0.0
        contributing: list[str] = []
        missing: list[str] = []
        record_ids: dict[str, None] = {}
        origins: dict[str, None] = {}
        for series in members:
            point = series.point(label)
            if point is None or point.value is None:
                missing.append(series.entity_id)
                continue
            total += point.value
            contributing.append(series.entity_id)
            for record_id in point.record_ids:
                record_ids.setdefault(record_id, None)
            for origin in point.origin_cluster_ids:
                origins.setdefault(origin, None)
        if not contributing:
            continue
        notes = [f"summed over {len(contributing)} repository series"]
        if missing:
            notes.append(
                "partial week: no observation for " + ", ".join(sorted(missing))
            )
        observations[label] = WeekPoint(
            iso_week=label,
            value=total,
            value_state="observed",
            record_ids=tuple(record_ids),
            origin_cluster_ids=tuple(origins),
            notes=tuple(notes),
        )
    return WeeklySeries.from_observations(
        series_id=_company_series_id(metric, company_id),
        metric=metric,
        signal_family=SIGNAL_FAMILY,
        entity_type="company",
        entity_id=company_id,
        company_id=company_id,
        observations=observations,
        gap_policy="unknown",
        unit=unit,
        coverage_start=labels[0] if labels else None,
        coverage_end=labels[-1] if labels else None,
        metadata={
            "repositories": sorted(item.entity_id for item in members),
            "aggregation": "sum over repositories observed in the week",
            "adapter_version": ADAPTER_VERSION,
        },
    )


def build_github_features(
    records: Iterable[Mapping[str, Any]] | Iterable[GitHubObservation],
    *,
    config: GitHubFeatureConfig | None = None,
    validate: bool = True,
) -> GitHubFeatureSet:
    """Build weekly GitHub series from normalized records or adapted observations."""
    config = config or GitHubFeatureConfig()
    items = list(records)
    if items and isinstance(items[0], GitHubObservation):
        observations: list[GitHubObservation] = list(items)  # type: ignore[arg-type]
    else:
        observations = github_observations(items, validate=validate)  # type: ignore[arg-type]

    aggregates, report = _aggregate(observations, config)
    labels: list[str] = []
    if aggregates:
        weeks = sorted({key[2] for key in aggregates}, key=parse_iso_week)
        labels = week_range(weeks[0], weeks[-1])

    by_repo: dict[tuple[str, str], dict[str, WeekAggregate]] = defaultdict(dict)
    for (company_id, repository, label), aggregate in aggregates.items():
        by_repo[(company_id, repository)][label] = aggregate

    series: list[WeeklySeries] = []
    for (company_id, repository), weeks_map in sorted(by_repo.items()):
        series.extend(_series_for_repository(company_id, repository, weeks_map, labels, config))

    companies = sorted({company_id for company_id, _ in by_repo})
    for company_id in companies:
        owned = [item for item in series if item.company_id == company_id and item.entity_type == "repository"]
        for metric, unit in (
            ("commits", "count"),
            ("human_commits", "count"),
            ("star_delta", "change"),
            ("open_issues_delta", "change"),
        ):
            series.append(_rollup_company(company_id, owned, labels, metric, unit))

    coverage = {
        "signal_family": SIGNAL_FAMILY,
        "adapter_version": ADAPTER_VERSION,
        "companies": companies,
        "repositories": sorted({repository for _, repository in by_repo}),
        "weeks": labels,
        "weeks_observed": sorted({key[2] for key in aggregates}, key=parse_iso_week),
        "week_assignment_methods": sorted(
            {method for aggregate in aggregates.values() for method in aggregate.week_assignment}
        ),
        "approximate_week_assignments": sorted(
            f"{key[1]}@{key[2]}"
            for key, aggregate in aggregates.items()
            if "window_end_approximate" in aggregate.week_assignment
        ),
        "bot_heavy_repositories": sorted(
            {aggregate.repository for aggregate in aggregates.values() if aggregate.bot_heavy}
        ),
        "unavailable_metrics": dict(GITHUB_UNAVAILABLE_METRICS),
        "gap_policy": "unknown",
        "gap_policy_reason": (
            "a GitHub snapshot only describes the window it covers, so a week without a "
            "snapshot is unknown rather than zero"
        ),
        **report,
    }
    return GitHubFeatureSet(series=series, coverage=coverage)


__all__ = [
    "GITHUB_LEVEL_METRICS",
    "GITHUB_METRICS",
    "GitHubFeatureConfig",
    "GitHubFeatureSet",
    "SIGNAL_FAMILY",
    "assign_weeks",
    "build_github_features",
]
