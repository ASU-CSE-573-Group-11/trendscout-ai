"""EWMA baseline and rolling z-score for any weekly series.

The scorer is deliberately generic: it consumes a :class:`~signals.series.WeeklySeries`
and knows nothing about GitHub, job boards, or news. The same code therefore
scores commits per repository, open MLOps postings per company, and
distinct-origin news counts.

Method
------
For each week ``t`` with an observed value ``x_t``:

1. ``baseline_t`` is the EWMA level computed from weeks strictly before ``t``,
   so the baseline is a genuine one-step-ahead prediction and never sees
   ``x_t``.
2. ``residual_t = x_t - baseline_t``.
3. ``scale_t`` is the dispersion of the trailing ``window`` residuals ending at
   ``t``, as a sample standard deviation or a MAD-based robust estimate.
4. ``z_t = residual_t / max(scale_t, min_scale)``, clipped to ``z_cap``.
5. The level is then updated: ``level = alpha * x_t + (1 - alpha) * baseline_t``.

``min_scale`` exists because count data is frequently constant for several
weeks, which drives the dispersion to zero and would otherwise make a one-commit
change look infinitely significant.

One consequence of step 3 is worth knowing when tuning: the current residual is
part of its own dispersion window, so a single outlier week in a window of ``n``
residuals scores exactly ``sqrt(n)`` however large the spike is. That bounds the
false-alert rate -- one explosive week cannot dominate the ranking -- and it
means ``threshold`` must stay below ``sqrt(window)`` to be reachable at all. The
default pair (``window=8``, ``threshold=1.5``) leaves clear headroom under
``sqrt(8) == 2.83``. A sustained change spreads across several residuals and is
not subject to this bound.

Cold start and gaps
-------------------
A week is labelled ``insufficient_history`` rather than ``flat`` whenever the
evidence cannot support a direction: the first observed week, fewer than
``min_history`` observed weeks so far, fewer than ``min_scale_points``
residuals in the trailing window, or a week whose value is unknown. Unknown
weeks never update the level and never enter the residual window, so a
collection gap cannot manufacture a decline.

Nothing in this module converts a trend score into a claim about future
performance; see ``docs/evidence-ledger.md``.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Literal, Sequence

from signals import FEATURE_VERSION
from signals.series import WeeklySeries
from signals.weeks import parse_iso_week

TrendLabel = Literal["rising", "flat", "falling", "insufficient_history"]

TREND_LABELS: tuple[str, ...] = ("rising", "flat", "falling", "insufficient_history")
SCALE_METHODS: tuple[str, ...] = ("std", "mad")

_MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class TrendConfig:
    """Tunable parameters for the EWMA baseline and the rolling z-score.

    Defaults are development-set starting points, not tuned results. Report the
    values used alongside any metric, as ``docs/evidence-ledger.md`` requires.
    """

    alpha: float = 0.3
    window: int = 8
    threshold: float = 1.5
    min_history: int = 4
    min_scale: float = 1.0
    min_scale_points: int = 3
    scale_method: str = "std"
    z_cap: float = 10.0

    def __post_init__(self) -> None:
        if not 0.0 < self.alpha <= 1.0:
            raise ValueError("alpha must be in (0, 1]")
        if self.window < 2:
            raise ValueError("window must be at least 2 weeks")
        if self.threshold <= 0:
            raise ValueError("threshold must be positive")
        if self.min_history < 2:
            raise ValueError("min_history must be at least 2 observed weeks")
        if self.min_scale <= 0:
            raise ValueError("min_scale must be positive")
        if self.min_scale_points < 2:
            raise ValueError("min_scale_points must be at least 2")
        if self.scale_method not in SCALE_METHODS:
            raise ValueError(f"unsupported scale method: {self.scale_method}")
        if self.z_cap <= 0:
            raise ValueError("z_cap must be positive")

    def fingerprint(self) -> str:
        """Stable short digest of the configuration, used in trend identifiers."""
        payload = "|".join(
            f"{key}={value}" for key, value in sorted(asdict(self).items())
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "fingerprint": self.fingerprint()}


@dataclass(frozen=True)
class TrendSignal:
    """One scored week of one series, traceable to the records behind it."""

    trend_id: str
    series_id: str
    metric: str
    signal_family: str
    entity_type: str
    entity_id: str
    company_id: str | None
    iso_week: str
    week_start: str
    week_end: str
    value: float | None
    value_state: str
    ewma_baseline: float | None
    residual: float | None
    scale: float | None
    scale_method: str
    z_score: float | None
    trend_score: float | None
    label: str
    label_reason: str
    observed_weeks_used: int
    residual_points_used: int
    gap_policy: str
    unit: str
    config: dict[str, Any]
    record_ids: tuple[str, ...]
    window_record_ids: tuple[str, ...]
    origin_cluster_ids: tuple[str, ...]
    feature_version: str = FEATURE_VERSION
    notes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("record_ids", "window_record_ids", "origin_cluster_ids", "notes"):
            payload[key] = list(payload[key])
        return payload


def _std(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _mad(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    center = _median(values)
    return _MAD_TO_SIGMA * _median([abs(value - center) for value in values])


def _scale(values: Sequence[float], method: str) -> float | None:
    return _mad(values) if method == "mad" else _std(values)


def _trend_id(series_id: str, iso_week: str, fingerprint: str) -> str:
    digest = hashlib.sha256(
        f"{series_id}\n{iso_week}\n{FEATURE_VERSION}\n{fingerprint}".encode("utf-8")
    ).hexdigest()[:20]
    return f"trend-signal:{digest}"


def score_series(series: WeeklySeries, config: TrendConfig | None = None) -> list[TrendSignal]:
    """Score every week of ``series``, oldest first.

    Returns one :class:`TrendSignal` per week present in the series, including
    unknown weeks, so a consumer can tell a gap from a genuine flat week.
    """
    config = config or TrendConfig()
    fingerprint = config.fingerprint()
    config_payload = config.as_dict()

    level: float | None = None
    observed_so_far = 0
    residual_history: list[tuple[str, float]] = []
    signals: list[TrendSignal] = []

    for point in series.points:
        baseline = level
        residual: float | None = None
        scale: float | None = None
        z_score: float | None = None
        label: str = "insufficient_history"
        reason: str
        notes: list[str] = list(point.notes)
        window_weeks: list[str] = []

        if point.value is None:
            reason = "unknown_value"
            notes.append(
                "week not observed; the level and residual window are unchanged so a "
                "collection gap cannot be read as a decline"
            )
        else:
            observed_so_far += 1
            if baseline is None:
                level = point.value
                reason = "cold_start_first_observed_week"
                notes.append("first observed week; no baseline exists yet")
            else:
                residual = point.value - baseline
                residual_history.append((point.iso_week, residual))
                window_residuals = residual_history[-config.window :]
                window_weeks = [week for week, _ in window_residuals]
                scale = _scale([value for _, value in window_residuals], config.scale_method)
                level = config.alpha * point.value + (1 - config.alpha) * baseline

                if observed_so_far < config.min_history:
                    reason = (
                        f"observed_weeks={observed_so_far} below min_history={config.min_history}"
                    )
                elif len(window_residuals) < config.min_scale_points:
                    reason = (
                        f"residual_points={len(window_residuals)} below "
                        f"min_scale_points={config.min_scale_points}"
                    )
                elif scale is None:
                    reason = "dispersion_undefined"
                else:
                    effective = max(scale, config.min_scale)
                    if effective > scale:
                        notes.append(
                            f"dispersion {scale:.4f} raised to min_scale {config.min_scale} "
                            "so a near-constant series cannot produce an extreme score"
                        )
                    raw = residual / effective
                    z_score = max(-config.z_cap, min(config.z_cap, raw))
                    if abs(raw) > config.z_cap:
                        notes.append(f"z-score clipped from {raw:.4f} to the configured cap")
                    if z_score >= config.threshold:
                        label = "rising"
                    elif z_score <= -config.threshold:
                        label = "falling"
                    else:
                        label = "flat"
                    reason = (
                        f"z={z_score:.4f} against threshold={config.threshold} "
                        f"over {len(window_residuals)} residual weeks"
                    )

        window_record_ids: dict[str, None] = {}
        origins: dict[str, None] = {}
        for week in window_weeks or [point.iso_week]:
            member = series.point(week)
            if member is None:
                continue
            for record_id in member.record_ids:
                window_record_ids.setdefault(record_id, None)
            for origin in member.origin_cluster_ids:
                origins.setdefault(origin, None)
        for origin in point.origin_cluster_ids:
            origins.setdefault(origin, None)

        signals.append(
            TrendSignal(
                trend_id=_trend_id(series.series_id, point.iso_week, fingerprint),
                series_id=series.series_id,
                metric=series.metric,
                signal_family=series.signal_family,
                entity_type=series.entity_type,
                entity_id=series.entity_id,
                company_id=series.company_id,
                iso_week=point.iso_week,
                week_start=point.week_start,
                week_end=point.week_end,
                value=point.value,
                value_state=point.value_state,
                ewma_baseline=baseline,
                residual=residual,
                scale=scale,
                scale_method=config.scale_method,
                z_score=z_score,
                trend_score=z_score,
                label=label,
                label_reason=reason,
                observed_weeks_used=observed_so_far,
                residual_points_used=len(window_weeks),
                gap_policy=series.gap_policy,
                unit=series.unit,
                config=config_payload,
                record_ids=tuple(point.record_ids),
                window_record_ids=tuple(window_record_ids),
                origin_cluster_ids=tuple(origins),
                notes=tuple(notes),
            )
        )
    return signals


def score_many(
    series: Iterable[WeeklySeries], config: TrendConfig | None = None
) -> list[TrendSignal]:
    """Score several series and return their signals sorted by week then series."""
    scored: list[TrendSignal] = []
    for item in series:
        scored.extend(score_series(item, config))
    scored.sort(key=lambda signal: (parse_iso_week(signal.iso_week), signal.series_id))
    return scored


def latest_signal(
    series: WeeklySeries, config: TrendConfig | None = None
) -> TrendSignal | None:
    """The most recent scored week, or ``None`` for an empty series."""
    signals = score_series(series, config)
    return signals[-1] if signals else None


def rising_entities(
    signals: Iterable[TrendSignal],
    *,
    weeks: Sequence[str] | None = None,
    metric: str | None = None,
) -> list[TrendSignal]:
    """Filter scored signals down to rising weeks, optionally within a window.

    This is the primitive behind questions such as "which startups show rising
    GitHub activity in the last eight weeks": callers intersect the result with
    another metric's rising set rather than re-implementing the scoring rules.
    """
    wanted = set(weeks) if weeks else None
    selected = [
        signal
        for signal in signals
        if signal.label == "rising"
        and (wanted is None or signal.iso_week in wanted)
        and (metric is None or signal.metric == metric)
    ]
    selected.sort(key=lambda signal: (-(signal.trend_score or 0.0), signal.series_id))
    return selected


__all__ = [
    "SCALE_METHODS",
    "TREND_LABELS",
    "TrendConfig",
    "TrendLabel",
    "TrendSignal",
    "latest_signal",
    "rising_entities",
    "score_many",
    "score_series",
]
