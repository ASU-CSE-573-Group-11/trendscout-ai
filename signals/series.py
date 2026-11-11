"""A generic weekly series with explicit missing-week semantics.

Nothing here is GitHub-specific. A :class:`WeeklySeries` is any numeric metric
observed per ISO week for one entity, carrying the ``record_id`` values that
produced each point so a downstream trend signal stays traceable to source
evidence.

Missing weeks
-------------
A gap in a weekly series is ambiguous: either nothing happened (a true zero) or
nobody looked (unknown). Guessing wrong turns a collection gap into a fake
decline, so the series declares its policy explicitly.

``gap_policy="unknown"``
    A week with no observation is ``None`` with state ``unknown``. Correct for
    snapshot-style sources: a GitHub commit window or a job-board listing only
    tells us about the weeks a collector actually ran.

``gap_policy="zero"``
    A week with no observation inside the coverage span is ``0.0`` with state
    ``zero_by_policy``. Correct for continuously harvested feeds, where "no
    article that week" is itself an observation of absence.

Weeks outside ``coverage_start``/``coverage_end`` are never materialised under
either policy: absence of coverage is not absence of activity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Sequence

from signals.weeks import WEEK, format_instant, iso_week, parse_iso_week, week_range

GapPolicy = Literal["unknown", "zero"]
ValueState = Literal["observed", "zero_by_policy", "unknown"]

GAP_POLICIES: tuple[str, ...] = ("unknown", "zero")
VALUE_STATES: tuple[str, ...] = ("observed", "zero_by_policy", "unknown")


@dataclass(frozen=True)
class WeekPoint:
    """One week of one series."""

    iso_week: str
    value: float | None
    value_state: ValueState = "observed"
    record_ids: tuple[str, ...] = ()
    origin_cluster_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        parse_iso_week(self.iso_week)
        if self.value_state not in VALUE_STATES:
            raise ValueError(f"unsupported value state: {self.value_state}")
        if self.value_state == "unknown" and self.value is not None:
            raise ValueError("an unknown week must not carry a value")
        if self.value_state != "unknown" and self.value is None:
            raise ValueError(f"a {self.value_state} week must carry a value")

    @property
    def week_start(self) -> str:
        return format_instant(parse_iso_week(self.iso_week))

    @property
    def week_end(self) -> str:
        return format_instant(parse_iso_week(self.iso_week) + WEEK)

    def as_dict(self) -> dict[str, Any]:
        return {
            "iso_week": self.iso_week,
            "week_start": self.week_start,
            "week_end": self.week_end,
            "value": self.value,
            "value_state": self.value_state,
            "record_ids": list(self.record_ids),
            "origin_cluster_ids": list(self.origin_cluster_ids),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class WeeklySeries:
    """A metric observed per ISO week for one entity.

    ``entity_type``/``entity_id`` identify what the metric describes (a
    repository, a company, a company-and-role-family pair). ``company_id`` is
    kept separately so trend output can always be joined to the frozen cohort.
    """

    series_id: str
    metric: str
    signal_family: str
    entity_type: str
    entity_id: str
    company_id: str | None
    points: tuple[WeekPoint, ...]
    gap_policy: GapPolicy = "unknown"
    unit: str = "count"
    coverage_start: str | None = None
    coverage_end: str | None = None
    availability: str = "available"
    availability_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.series_id or not self.metric:
            raise ValueError("series_id and metric are required")
        if self.gap_policy not in GAP_POLICIES:
            raise ValueError(f"unsupported gap policy: {self.gap_policy}")
        labels = [point.iso_week for point in self.points]
        if labels != sorted(labels, key=parse_iso_week):
            raise ValueError(f"series {self.series_id} points are not in week order")
        if len(set(labels)) != len(labels):
            raise ValueError(f"series {self.series_id} has duplicate weeks")

    # -- construction ----------------------------------------------------

    @classmethod
    def from_observations(
        cls,
        *,
        series_id: str,
        metric: str,
        signal_family: str,
        entity_type: str,
        entity_id: str,
        company_id: str | None,
        observations: dict[str, WeekPoint] | Iterable[WeekPoint],
        gap_policy: GapPolicy = "unknown",
        unit: str = "count",
        coverage_start: str | None = None,
        coverage_end: str | None = None,
        availability: str = "available",
        availability_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "WeeklySeries":
        """Build a dense, gap-filled series from sparse weekly observations."""
        if isinstance(observations, dict):
            observed = dict(observations)
        else:
            observed = {}
            for point in observations:
                if point.iso_week in observed:
                    raise ValueError(f"duplicate observation for {point.iso_week}")
                observed[point.iso_week] = point

        start = coverage_start or (min(observed, key=parse_iso_week) if observed else None)
        end = coverage_end or (max(observed, key=parse_iso_week) if observed else None)
        span = set(week_range(start, end)) if start and end else set()
        outside = sorted(label for label in observed if label not in span)
        if outside:
            raise ValueError(f"observations outside the coverage span: {outside}")

        points: list[WeekPoint] = []
        if start and end:
            for label in week_range(start, end):
                if label in observed:
                    points.append(observed[label])
                elif gap_policy == "zero":
                    points.append(
                        WeekPoint(
                            iso_week=label,
                            value=0.0,
                            value_state="zero_by_policy",
                            notes=("no record observed; gap_policy=zero",),
                        )
                    )
                else:
                    points.append(
                        WeekPoint(
                            iso_week=label,
                            value=None,
                            value_state="unknown",
                            notes=("no record observed; gap_policy=unknown",),
                        )
                    )
        return cls(
            series_id=series_id,
            metric=metric,
            signal_family=signal_family,
            entity_type=entity_type,
            entity_id=entity_id,
            company_id=company_id,
            points=tuple(points),
            gap_policy=gap_policy,
            unit=unit,
            coverage_start=start,
            coverage_end=end,
            availability=availability,
            availability_reason=availability_reason,
            metadata=dict(metadata or {}),
        )

    # -- access ----------------------------------------------------------

    def __len__(self) -> int:
        return len(self.points)

    def point(self, label: str) -> WeekPoint | None:
        for candidate in self.points:
            if candidate.iso_week == label:
                return candidate
        return None

    @property
    def observed_points(self) -> tuple[WeekPoint, ...]:
        return tuple(point for point in self.points if point.value is not None)

    @property
    def observed_week_count(self) -> int:
        return len(self.observed_points)

    @property
    def record_ids(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for point in self.points:
            for record_id in point.record_ids:
                seen.setdefault(record_id, None)
        return tuple(seen)

    def window(self, weeks: Sequence[str]) -> "WeeklySeries":
        """Restrict the series to ``weeks`` without changing its identity."""
        wanted = set(weeks)
        kept = tuple(point for point in self.points if point.iso_week in wanted)
        return WeeklySeries(
            series_id=self.series_id,
            metric=self.metric,
            signal_family=self.signal_family,
            entity_type=self.entity_type,
            entity_id=self.entity_id,
            company_id=self.company_id,
            points=kept,
            gap_policy=self.gap_policy,
            unit=self.unit,
            coverage_start=kept[0].iso_week if kept else None,
            coverage_end=kept[-1].iso_week if kept else None,
            availability=self.availability,
            availability_reason=self.availability_reason,
            metadata=dict(self.metadata),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "series_id": self.series_id,
            "metric": self.metric,
            "signal_family": self.signal_family,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "company_id": self.company_id,
            "gap_policy": self.gap_policy,
            "unit": self.unit,
            "coverage_start": self.coverage_start,
            "coverage_end": self.coverage_end,
            "availability": self.availability,
            "availability_reason": self.availability_reason,
            "observed_week_count": self.observed_week_count,
            "metadata": dict(self.metadata),
            "points": [point.as_dict() for point in self.points],
        }


def unavailable_series(
    *,
    series_id: str,
    metric: str,
    signal_family: str,
    entity_type: str,
    entity_id: str,
    company_id: str | None,
    reason: str,
    weeks: Sequence[str] = (),
) -> WeeklySeries:
    """A series whose metric the upstream collector does not supply.

    Used instead of silently emitting zeros for metrics the GitHub collector
    cannot report (releases, issues opened/closed, active contributors).
    """
    points = tuple(
        WeekPoint(iso_week=label, value=None, value_state="unknown", notes=(reason,))
        for label in sorted(weeks, key=parse_iso_week)
    )
    return WeeklySeries(
        series_id=series_id,
        metric=metric,
        signal_family=signal_family,
        entity_type=entity_type,
        entity_id=entity_id,
        company_id=company_id,
        points=points,
        gap_policy="unknown",
        coverage_start=points[0].iso_week if points else None,
        coverage_end=points[-1].iso_week if points else None,
        availability="not_collected",
        availability_reason=reason,
    )


def series_from_weekly_values(
    values: dict[str, float | None],
    *,
    series_id: str,
    metric: str,
    signal_family: str = "generic",
    entity_type: str = "series",
    entity_id: str | None = None,
    company_id: str | None = None,
    gap_policy: GapPolicy = "unknown",
    unit: str = "count",
    record_ids: dict[str, Sequence[str]] | None = None,
) -> WeeklySeries:
    """Convenience builder so any caller can score a plain ``{week: value}`` map.

    This is the entry point that keeps the trend module generic: job counts by
    role family and distinct-source news counts arrive here exactly like GitHub
    commits do.
    """
    record_ids = record_ids or {}
    observations = []
    for label in sorted(values, key=parse_iso_week):
        value = values[label]
        if value is None:
            observations.append(
                WeekPoint(iso_week=label, value=None, value_state="unknown", notes=("value reported as unknown",))
            )
        else:
            observations.append(
                WeekPoint(
                    iso_week=label,
                    value=float(value),
                    value_state="observed",
                    record_ids=tuple(record_ids.get(label, ())),
                )
            )
    return WeeklySeries.from_observations(
        series_id=series_id,
        metric=metric,
        signal_family=signal_family,
        entity_type=entity_type,
        entity_id=entity_id or series_id,
        company_id=company_id,
        observations=observations,
        gap_policy=gap_policy,
        unit=unit,
    )


__all__ = [
    "GAP_POLICIES",
    "VALUE_STATES",
    "GapPolicy",
    "ValueState",
    "WeekPoint",
    "WeeklySeries",
    "series_from_weekly_values",
    "unavailable_series",
]
