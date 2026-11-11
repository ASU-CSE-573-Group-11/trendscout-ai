"""Weekly hiring features per company and role family.

These series feed the same EWMA scorer as the GitHub features, which is the
point of keeping :mod:`signals.series` and :mod:`signals.ewma` generic: the
prototype question "which agent-infrastructure startups show both rising GitHub
activity and new MLOps hiring during the last eight weeks" is answered by
intersecting two scored series families, not by special-casing either one.

Role families
-------------
Families are assigned from explicitly matched phrases in the normalized job
title, mirroring the explicit-mention rule Vidya's skill extraction already
uses. Nothing is inferred from seniority, team, or description prose, and a
posting may belong to several families (an "ML Platform Engineer" is both
``mlops`` and ``infrastructure``). The vocabulary is versioned so a later
change is visible in the output.

Job data is collected prospectively, so these series start thin on purpose.
A board snapshot describes only the weeks a collector ran, so a week without a
snapshot is ``unknown``: treating it as zero would read a missed run as a
hiring freeze.

What is deliberately *not* produced
-----------------------------------
There is no ``closed_postings`` metric. A posting that disappears from a board
may have been filled, withdrawn, reposted, or hidden by a collection failure,
and Vidya's collector documentation is explicit that missing jobs must not be
read as filled positions.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from signals.adapters import ADAPTER_VERSION, JobObservation, job_observations
from signals.series import WeekPoint, WeeklySeries
from signals.weeks import iso_week, parse_iso_week, week_range

SIGNAL_FAMILY = "jobs"
ROLE_FAMILY_METHOD = "explicit_title_phrases_v1"

OTHER_FAMILY = "other"

#: Explicit title phrases per role family. Order does not matter; a posting
#: joins every family it matches.
ROLE_FAMILY_PATTERNS: dict[str, tuple[str, ...]] = {
    "mlops": (
        r"\bmlops\b",
        r"\bml ops\b",
        r"\bmachine learning operations\b",
        r"\bml infrastructure\b",
        r"\bml platform\b",
        r"\bmachine learning infrastructure\b",
        r"\bmachine learning platform\b",
        r"\bmodel deployment\b",
    ),
    "retrieval": (
        r"\bretrieval\b",
        r"\binformation retrieval\b",
        r"\bsearch\b",
        r"\brag\b",
        r"\bvector search\b",
        r"\branking\b",
    ),
    "evaluation": (
        r"\bevaluation\b",
        r"\bevaluations\b",
        r"\bevals?\b",
        r"\bbenchmarking\b",
        r"\bquality engineer\b",
    ),
    "research": (
        r"\bresearch\b",
        r"\bresearch scientist\b",
        r"\bresearch engineer\b",
    ),
    "infrastructure": (
        r"\binfrastructure\b",
        r"\bplatform\b",
        r"\bsite reliability\b",
        r"\bsre\b",
        r"\bdevops\b",
        r"\bdeployments?\b",
    ),
    "developer_relations": (
        r"\bdeveloper advocate\b",
        r"\bdeveloper relations\b",
        r"\bdevrel\b",
        r"\bcommunity\b",
        r"\bdocumentation engineer\b",
    ),
    "product_engineering": (
        r"\bsoftware engineer\b",
        r"\bbackend engineer\b",
        r"\bfrontend engineer\b",
        r"\bfull.?stack\b",
        r"\bproduct engineer\b",
    ),
    "data": (
        r"\bdata engineer\b",
        r"\bdata scientist\b",
        r"\banalytics\b",
    ),
    "go_to_market": (
        r"\bsales\b",
        r"\bmarketing\b",
        r"\baccount executive\b",
        r"\bsolutions? engineer\b",
    ),
}

_COMPILED: dict[str, tuple[re.Pattern[str], ...]] = {
    family: tuple(re.compile(pattern) for pattern in patterns)
    for family, patterns in ROLE_FAMILY_PATTERNS.items()
}

JOB_METRICS: tuple[str, ...] = ("open_postings", "new_postings")


def role_families(role_normalized: str) -> tuple[str, ...]:
    """Every role family whose vocabulary is explicitly present in the title."""
    text = " ".join((role_normalized or "").casefold().split())
    matched = tuple(
        family for family, patterns in sorted(_COMPILED.items())
        if any(pattern.search(text) for pattern in patterns)
    )
    return matched or (OTHER_FAMILY,)


@dataclass(frozen=True)
class JobFeatureConfig:
    """Which groupings to build."""

    include_role_families: bool = True
    include_skills: bool = True
    include_company_totals: bool = True
    families: tuple[str, ...] | None = None


@dataclass
class JobFeatureSet:
    """Weekly hiring series plus the coverage facts needed to read them."""

    series: list[WeeklySeries]
    coverage: dict[str, Any]

    def by_metric(self, metric: str) -> list[WeeklySeries]:
        return [item for item in self.series if item.metric == metric]

    def find_series(self, series_id: str) -> WeeklySeries:
        for item in self.series:
            if item.series_id == series_id:
                return item
        raise KeyError(f"no series {series_id!r}; built {len(self.series)} series")

    def for_family(self, family: str, metric: str | None = None) -> list[WeeklySeries]:
        return [
            item
            for item in self.series
            if item.metadata.get("role_family") == family
            and (metric is None or item.metric == metric)
        ]


def _series_id(metric: str, company_id: str, *, family: str | None = None, skill: str | None = None) -> str:
    parts = [f"{SIGNAL_FAMILY}:{metric}", f"company={company_id}"]
    if family:
        parts.append(f"role_family={family}")
    if skill:
        parts.append(f"skill={skill}")
    return "|".join(parts)


def _postings_by_week(
    observations: Sequence[JobObservation],
) -> tuple[dict[str, dict[str, JobObservation]], list[str]]:
    """Group postings by ISO week, keeping the latest observation per posting."""
    weeks: dict[str, dict[str, JobObservation]] = defaultdict(dict)
    for observation in sorted(observations, key=lambda item: (item.observed_at, item.record_id)):
        label = iso_week(observation.observed_at)
        # Several snapshots in one week: the posting is counted once, and the
        # latest observation of it wins.
        weeks[label][observation.posting_id] = observation
    labels = sorted(weeks, key=parse_iso_week)
    return weeks, labels


def _count_series(
    *,
    series_id: str,
    metric: str,
    company_id: str,
    entity_type: str,
    entity_id: str,
    weeks: dict[str, dict[str, JobObservation]],
    labels: Sequence[str],
    observed_labels: Sequence[str],
    selector,
    metadata: dict[str, Any],
) -> list[WeeklySeries]:
    """Build the open-postings and new-postings series for one grouping."""
    selected: dict[str, dict[str, JobObservation]] = {
        label: {
            posting_id: observation
            for posting_id, observation in postings.items()
            if selector(observation)
        }
        for label, postings in weeks.items()
    }

    open_points: dict[str, WeekPoint] = {}
    for label in observed_labels:
        postings = selected.get(label, {})
        open_points[label] = WeekPoint(
            iso_week=label,
            value=float(len(postings)),
            value_state="observed",
            record_ids=tuple(sorted(item.record_id for item in postings.values())),
            origin_cluster_ids=tuple(sorted({item.origin_cluster_id for item in postings.values()})),
            notes=("distinct postings listed on the board during the week",),
        )

    new_points: dict[str, WeekPoint] = {}
    for index, label in enumerate(observed_labels):
        if index == 0:
            new_points[label] = WeekPoint(
                iso_week=label,
                value=None,
                value_state="unknown",
                notes=(
                    "first observed week: nothing is known about what was already listed, "
                    "so no posting can be called new",
                ),
            )
            continue
        previous_label = observed_labels[index - 1]
        # "New this week" is only meaningful against the immediately preceding
        # ISO week. Across a gap, a posting first seen now may have appeared in
        # the unobserved weeks between.
        if len(week_range(previous_label, label)) != 2:
            new_points[label] = WeekPoint(
                iso_week=label,
                value=None,
                value_state="unknown",
                notes=(
                    f"the previous observed week is {previous_label}; a posting first seen after a "
                    "collection gap cannot be dated to this week",
                ),
            )
            continue
        previous_ids = set(selected.get(previous_label, {}))
        current = selected.get(label, {})
        fresh = {
            posting_id: observation
            for posting_id, observation in current.items()
            if posting_id not in previous_ids
        }
        new_points[label] = WeekPoint(
            iso_week=label,
            value=float(len(fresh)),
            value_state="observed",
            record_ids=tuple(sorted(item.record_id for item in fresh.values())),
            origin_cluster_ids=tuple(sorted({item.origin_cluster_id for item in fresh.values()})),
            notes=(f"postings absent from {previous_label} and present in {label}",),
        )

    shared = {
        **metadata,
        "adapter_version": ADAPTER_VERSION,
        "role_family_method": ROLE_FAMILY_METHOD,
        "closed_postings": (
            "not derived: a posting leaving a board may have been filled, withdrawn, reposted, "
            "or missed by a failed collection run"
        ),
    }
    built: list[WeeklySeries] = []
    for metric_name, points, unit in (
        ("open_postings", open_points, "count"),
        ("new_postings", new_points, "count"),
    ):
        built.append(
            WeeklySeries.from_observations(
                series_id=series_id.replace(f"{SIGNAL_FAMILY}:{metric}", f"{SIGNAL_FAMILY}:{metric_name}"),
                metric=metric_name,
                signal_family=SIGNAL_FAMILY,
                entity_type=entity_type,
                entity_id=entity_id,
                company_id=company_id,
                observations=points,
                gap_policy="unknown",
                unit=unit,
                coverage_start=labels[0] if labels else None,
                coverage_end=labels[-1] if labels else None,
                metadata=shared,
            )
        )
    return built


def build_job_features(
    records: Iterable[Mapping[str, Any]] | Iterable[JobObservation],
    *,
    config: JobFeatureConfig | None = None,
    validate: bool = True,
) -> JobFeatureSet:
    """Build weekly hiring series from normalized job records."""
    config = config or JobFeatureConfig()
    items = list(records)
    if items and isinstance(items[0], JobObservation):
        observations: list[JobObservation] = list(items)  # type: ignore[arg-type]
    else:
        observations = job_observations(items, validate=validate)  # type: ignore[arg-type]

    by_company: dict[str, list[JobObservation]] = defaultdict(list)
    for observation in observations:
        by_company[observation.company_id].append(observation)

    series: list[WeeklySeries] = []
    families_seen: set[str] = set()
    skills_seen: set[str] = set()
    all_weeks: set[str] = set()

    for company_id, company_observations in sorted(by_company.items()):
        weeks, observed_labels = _postings_by_week(company_observations)
        if not observed_labels:
            continue
        labels = week_range(observed_labels[0], observed_labels[-1])
        all_weeks.update(labels)

        company_families: dict[str, set[str]] = defaultdict(set)
        for observation in company_observations:
            for family in role_families(observation.role_normalized):
                company_families[family].add(observation.posting_id)
                families_seen.add(family)
            skills_seen.update(observation.skills)

        if config.include_company_totals:
            series.extend(
                _count_series(
                    series_id=_series_id("open_postings", company_id),
                    metric="open_postings",
                    company_id=company_id,
                    entity_type="company",
                    entity_id=company_id,
                    weeks=weeks,
                    labels=labels,
                    observed_labels=observed_labels,
                    selector=lambda observation: True,
                    metadata={"grouping": "all postings"},
                )
            )

        if config.include_role_families:
            wanted = set(config.families) if config.families else set(company_families)
            for family in sorted(wanted & set(company_families)):
                series.extend(
                    _count_series(
                        series_id=_series_id("open_postings", company_id, family=family),
                        metric="open_postings",
                        company_id=company_id,
                        entity_type="company_role_family",
                        entity_id=f"{company_id}:{family}",
                        weeks=weeks,
                        labels=labels,
                        observed_labels=observed_labels,
                        selector=(
                            lambda observation, family=family: family in role_families(observation.role_normalized)
                        ),
                        metadata={"grouping": "role family", "role_family": family},
                    )
                )

        if config.include_skills:
            company_skills = sorted({skill for item in company_observations for skill in item.skills})
            for skill in company_skills:
                series.extend(
                    _count_series(
                        series_id=_series_id("open_postings", company_id, skill=skill),
                        metric="open_postings",
                        company_id=company_id,
                        entity_type="company_skill",
                        entity_id=f"{company_id}:{skill}",
                        weeks=weeks,
                        labels=labels,
                        observed_labels=observed_labels,
                        selector=lambda observation, skill=skill: skill in observation.skills,
                        metadata={"grouping": "explicitly mentioned skill", "skill": skill},
                    )
                )

    coverage = {
        "signal_family": SIGNAL_FAMILY,
        "adapter_version": ADAPTER_VERSION,
        "role_family_method": ROLE_FAMILY_METHOD,
        "role_families": sorted(families_seen),
        "skills": sorted(skills_seen),
        "companies": sorted(by_company),
        "weeks": sorted(all_weeks, key=parse_iso_week),
        "postings_received": len(observations),
        "gap_policy": "unknown",
        "gap_policy_reason": (
            "a job-board snapshot describes only the weeks a collector ran; a week without a "
            "snapshot is unknown, not a hiring freeze"
        ),
        "history_note": (
            "job data is collected prospectively, so these series are short by construction and "
            "will report insufficient_history until min_history weeks exist"
        ),
    }
    return JobFeatureSet(series=series, coverage=coverage)


__all__ = [
    "JOB_METRICS",
    "OTHER_FAMILY",
    "ROLE_FAMILY_METHOD",
    "ROLE_FAMILY_PATTERNS",
    "JobFeatureConfig",
    "JobFeatureSet",
    "SIGNAL_FAMILY",
    "build_job_features",
    "role_families",
]
