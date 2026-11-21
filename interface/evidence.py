"""Assign an evidence state to each claim an answer makes.

The rules come from ``docs/evidence-ledger.md`` and are applied per claim, not
per answer, so one well-supported sentence cannot lend its standing to a
neighbouring sentence that nothing supports.

================  ====================================================
``corroborated``  at least two independent origins, or one documentary
                  origin plus one operational signal
``emerging``      one independent origin or one operational signal, and
                  nothing contradicting it
``disputed``      independent origins disagree on an amount by more than
                  the tolerance, or on a date by more than the tolerance
``stale``         the supporting operational snapshots are older than the
                  allowed number of missed refresh windows
``insufficient``  nothing supports the claim; the answer must qualify or
                  abstain and say what is missing
================  ====================================================

Two rules in that document are easy to get wrong and are implemented
explicitly. Copies that share an ``origin_cluster_id`` are **one** origin, so
syndication cannot manufacture corroboration or a conflict. And a dated past
event does not become stale merely because time has passed -- staleness applies
to snapshot-style operational evidence whose refresh windows were missed, not to
an article about something that happened in October.

Thresholds are defaults for a development set, reported with every assessment,
as the evidence-ledger document requires.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Iterable, Mapping, Sequence

from signals.weeks import parse_instant

EVIDENCE_STATES: tuple[str, ...] = (
    "corroborated",
    "emerging",
    "disputed",
    "stale",
    "insufficient",
)

#: Source types that are documentary rather than operational signals.
DOCUMENTARY_TYPES: frozenset[str] = frozenset({"news", "company", "public_voice", "reference", "funding"})
#: Source types that are operational signals.
OPERATIONAL_TYPES: frozenset[str] = frozenset({"github", "job"})

_MULTIPLIERS = {
    "k": 1_000.0,
    "thousand": 1_000.0,
    "m": 1_000_000.0,
    "mm": 1_000_000.0,
    "million": 1_000_000.0,
    "b": 1_000_000_000.0,
    "bn": 1_000_000_000.0,
    "billion": 1_000_000_000.0,
}

_AMOUNT = re.compile(
    r"\$\s?(?P<value>\d[\d,]*(?:\.\d+)?)\s?(?P<unit>k|thousand|mm?|million|bn?|billion)?\b",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"\b(?P<year>20\d{2})-(?P<month>\d{2})-(?P<day>\d{2})\b")
_MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_TEXT_DATE = re.compile(
    r"\b(?P<month>" + "|".join(_MONTH_NAMES) + r")\s+(?:(?P<day>\d{1,2}),?\s+)?(?P<year>20\d{2})\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EvidenceConfig:
    """Thresholds, reported with every assessment so results stay explainable."""

    minimum_independent_origins: int = 2
    amount_tolerance: float = 0.10
    date_tolerance_days: int = 7
    refresh_window_days: int = 7
    allowed_missed_refresh_windows: int = 2

    @property
    def stale_after_days(self) -> int:
        return self.refresh_window_days * self.allowed_missed_refresh_windows

    def as_dict(self) -> dict[str, Any]:
        return {
            "minimum_independent_origins": self.minimum_independent_origins,
            "amount_tolerance": self.amount_tolerance,
            "date_tolerance_days": self.date_tolerance_days,
            "refresh_window_days": self.refresh_window_days,
            "allowed_missed_refresh_windows": self.allowed_missed_refresh_windows,
            "stale_after_days": self.stale_after_days,
        }


@dataclass(frozen=True)
class Conflict:
    """A material disagreement between independent origins."""

    kind: str
    detail: str
    origins: tuple[str, ...]
    values: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "detail": self.detail,
            "origins": list(self.origins),
            "values": list(self.values),
        }


@dataclass(frozen=True)
class EvidenceAssessment:
    """The state of one claim and the counts behind it."""

    state: str
    reason: str
    independent_origins: tuple[str, ...]
    documentary_origins: tuple[str, ...]
    operational_origins: tuple[str, ...]
    record_ids: tuple[str, ...]
    conflicts: tuple[Conflict, ...] = ()
    latest_observed_at: str | None = None
    newest_event_at: str | None = None
    age_days: float | None = None
    missing_evidence: tuple[str, ...] = ()
    config: Mapping[str, Any] = field(default_factory=dict)

    @property
    def independent_origin_count(self) -> int:
        return len(self.independent_origins)

    @property
    def supported(self) -> bool:
        return self.state != "insufficient"

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "reason": self.reason,
            "independent_origins": list(self.independent_origins),
            "independent_origin_count": self.independent_origin_count,
            "documentary_origins": list(self.documentary_origins),
            "operational_origins": list(self.operational_origins),
            "record_ids": list(self.record_ids),
            "conflicts": [conflict.as_dict() for conflict in self.conflicts],
            "latest_observed_at": self.latest_observed_at,
            "newest_event_at": self.newest_event_at,
            "age_days": self.age_days,
            "missing_evidence": list(self.missing_evidence),
            "config": dict(self.config),
        }


def parse_amounts(text: str) -> list[float]:
    """Monetary amounts in a passage, normalized to a plain number."""
    amounts: list[float] = []
    for match in _AMOUNT.finditer(text or ""):
        try:
            value = float(match.group("value").replace(",", ""))
        except ValueError:  # pragma: no cover - guarded by the pattern
            continue
        unit = (match.group("unit") or "").lower()
        amounts.append(value * _MULTIPLIERS.get(unit, 1.0))
    return amounts


def parse_dates(text: str) -> list[str]:
    """Dates in a passage as ISO strings, month-only dates as the first."""
    found: list[str] = []
    for match in _ISO_DATE.finditer(text or ""):
        found.append(f"{match.group('year')}-{match.group('month')}-{match.group('day')}")
    for match in _TEXT_DATE.finditer(text or ""):
        month = _MONTH_NAMES.index(match.group("month").lower()) + 1
        day = int(match.group("day") or 1)
        found.append(f"{match.group('year')}-{month:02d}-{day:02d}")
    return sorted(set(found))


def _origins_of(item: Mapping[str, Any] | Any) -> tuple[str, ...]:
    """Every origin cluster an evidence item rests on.

    Most items rest on one. A trend signal rests on all the origins of the
    records it was computed from, and reporting only the first would undercount
    corroboration; inventing a synthetic origin for it would overcount.
    """
    plural = _field(item, "origin_cluster_ids")
    if plural:
        return tuple(dict.fromkeys(str(value) for value in plural))
    single = _field(item, "origin_cluster_id")
    return (str(single),) if single else ()


def _origin_of(item: Mapping[str, Any] | Any) -> str:
    origins = _origins_of(item)
    if not origins:
        raise KeyError("evidence item carries no origin_cluster_id")
    return origins[0]


def _field(item: Mapping[str, Any] | Any, name: str) -> Any:
    if hasattr(item, name):
        return getattr(item, name)
    if isinstance(item, Mapping):
        return item.get(name)
    return None


def detect_conflicts(
    supporting: Sequence[Any], *, config: EvidenceConfig
) -> list[Conflict]:
    """Find amount or date disagreements **between distinct origins**.

    Two copies of one origin saying the same thing differently is not a
    conflict, so comparison is per origin: each origin contributes the values
    found in its passages, and only cross-origin spread counts.
    """
    amounts_by_origin: dict[str, list[float]] = {}
    dates_by_origin: dict[str, list[str]] = {}
    for item in supporting:
        origin = _origin_of(item)
        text = f"{_field(item, 'title') or ''} {_field(item, 'text') or ''}"
        amounts = parse_amounts(text)
        dates = parse_dates(text)
        if amounts:
            amounts_by_origin.setdefault(origin, []).extend(amounts)
        if dates:
            dates_by_origin.setdefault(origin, []).extend(dates)

    conflicts: list[Conflict] = []
    if len(amounts_by_origin) >= 2:
        representative = {origin: max(values) for origin, values in amounts_by_origin.items()}
        smallest = min(representative.values())
        largest = max(representative.values())
        if smallest > 0 and (largest - smallest) / smallest > config.amount_tolerance:
            conflicts.append(
                Conflict(
                    kind="amount",
                    detail=(
                        f"independent origins report amounts differing by "
                        f"{(largest - smallest) / smallest:.0%}, above the "
                        f"{config.amount_tolerance:.0%} tolerance"
                    ),
                    origins=tuple(sorted(representative)),
                    values=tuple(f"{value:.0f}" for value in sorted(representative.values())),
                )
            )

    if len(dates_by_origin) >= 2:
        representative_dates = {origin: min(values) for origin, values in dates_by_origin.items()}
        ordered = sorted(representative_dates.values())
        spread = (
            parse_instant(f"{ordered[-1]}T00:00:00Z") - parse_instant(f"{ordered[0]}T00:00:00Z")
        ).days
        if spread > config.date_tolerance_days:
            conflicts.append(
                Conflict(
                    kind="date",
                    detail=(
                        f"independent origins report dates {spread} days apart, above the "
                        f"{config.date_tolerance_days}-day tolerance"
                    ),
                    origins=tuple(sorted(representative_dates)),
                    values=tuple(ordered),
                )
            )
    return conflicts


def assess_evidence(
    supporting: Iterable[Any],
    *,
    snapshot_anchor: str,
    config: EvidenceConfig | None = None,
    requires: Sequence[str] = (),
) -> EvidenceAssessment:
    """Assign an evidence state to a claim from the evidence supporting it.

    ``supporting`` holds passages, trend signals, or plain mappings; each must
    carry ``origin_cluster_id`` and ``source_type``. ``requires`` names the
    evidence kinds a question needs (for example ``("github", "jobs")`` from the
    seed questions), so an answer that is missing one can say which.
    """
    config = config or EvidenceConfig()
    items = list(supporting)
    if not items:
        return EvidenceAssessment(
            state="insufficient",
            reason="no retrieved evidence supports this claim",
            independent_origins=(),
            documentary_origins=(),
            operational_origins=(),
            record_ids=(),
            missing_evidence=tuple(requires) or ("any supporting record",),
            config=config.as_dict(),
        )

    documentary: dict[str, None] = {}
    operational: dict[str, None] = {}
    origins: dict[str, None] = {}
    record_ids: dict[str, None] = {}
    observed: list[str] = []
    events: list[str] = []

    for item in items:
        item_origins = _origins_of(item)
        source_type = str(_field(item, "source_type") or "")
        for origin in item_origins:
            origins.setdefault(origin, None)
            if source_type in OPERATIONAL_TYPES:
                operational.setdefault(origin, None)
            elif source_type in DOCUMENTARY_TYPES:
                documentary.setdefault(origin, None)
        record_id = _field(item, "record_id")
        if record_id:
            record_ids.setdefault(record_id, None)
        for name, bucket in (("observed_at", observed), ("event_at", events), ("published_at", events)):
            value = _field(item, name)
            if value:
                bucket.append(value)

    latest_observed = max(observed) if observed else None
    newest_event = max(events) if events else None
    anchor = parse_instant(snapshot_anchor)
    age_days: float | None = None
    if latest_observed:
        age_days = (anchor - parse_instant(latest_observed)).total_seconds() / 86400.0

    conflicts = detect_conflicts(items, config=config)
    missing = tuple(
        kind
        for kind in requires
        if not _requirement_met(kind, documentary=set(documentary), operational=set(operational), items=items)
    )

    if conflicts:
        return EvidenceAssessment(
            state="disputed",
            reason="; ".join(conflict.detail for conflict in conflicts)
            + " -- the conflict is shown rather than resolved",
            independent_origins=tuple(origins),
            documentary_origins=tuple(documentary),
            operational_origins=tuple(operational),
            record_ids=tuple(record_ids),
            conflicts=tuple(conflicts),
            latest_observed_at=latest_observed,
            newest_event_at=newest_event,
            age_days=age_days,
            missing_evidence=missing,
            config=config.as_dict(),
        )

    # Staleness applies to operational snapshots only. A dated past event stays
    # historical; it does not expire because the snapshot got older.
    only_operational = bool(operational) and not documentary
    if (
        only_operational
        and age_days is not None
        and age_days > config.stale_after_days
    ):
        return EvidenceAssessment(
            state="stale",
            reason=(
                f"the newest supporting snapshot is {age_days:.1f} days old, beyond "
                f"{config.allowed_missed_refresh_windows} missed refresh windows of "
                f"{config.refresh_window_days} days"
            ),
            independent_origins=tuple(origins),
            documentary_origins=tuple(documentary),
            operational_origins=tuple(operational),
            record_ids=tuple(record_ids),
            latest_observed_at=latest_observed,
            newest_event_at=newest_event,
            age_days=age_days,
            missing_evidence=missing,
            config=config.as_dict(),
        )

    if len(origins) >= config.minimum_independent_origins:
        reason = (
            f"{len(origins)} independent origins support this claim, at or above the "
            f"configured minimum of {config.minimum_independent_origins}"
        )
        state = "corroborated"
    elif documentary and operational:
        reason = "one documentary origin and one operational signal support this claim"
        state = "corroborated"
    else:
        kind = "operational signal" if operational else "documentary origin"
        reason = f"a single {kind} supports this claim and nothing contradicts it"
        state = "emerging"

    return EvidenceAssessment(
        state=state,
        reason=reason,
        independent_origins=tuple(origins),
        documentary_origins=tuple(documentary),
        operational_origins=tuple(operational),
        record_ids=tuple(record_ids),
        latest_observed_at=latest_observed,
        newest_event_at=newest_event,
        age_days=age_days,
        missing_evidence=missing,
        config=config.as_dict(),
    )


def _requirement_met(
    kind: str, *, documentary: set[str], operational: set[str], items: Sequence[Any]
) -> bool:
    source_types = {str(_field(item, "source_type") or "") for item in items}
    kinds = {
        "github": {"github"},
        "jobs": {"job"},
        "job": {"job"},
        "funding": {"funding", "news", "company"},
        "news": {"news"},
        "public_voice": {"public_voice"},
        "github_or_jobs": {"github", "job"},
        "documentary": set(DOCUMENTARY_TYPES),
        "operational": set(OPERATIONAL_TYPES),
        "evidence_ledger": set(),
    }
    wanted = kinds.get(kind)
    if wanted is None:
        return True
    if not wanted:
        # evidence_ledger: satisfied when any evidence exists to describe.
        return bool(items)
    return bool(source_types & wanted)


def worst_state(states: Iterable[str]) -> str:
    """The state an overall answer should carry, given its claims' states.

    Ordered by how much caution the answer needs, worst first: an answer with
    one insufficient claim is not a corroborated answer.
    """
    order = ("insufficient", "disputed", "stale", "emerging", "corroborated")
    present = [state for state in states if state in order]
    if not present:
        return "insufficient"
    return min(present, key=order.index)


__all__ = [
    "DOCUMENTARY_TYPES",
    "EVIDENCE_STATES",
    "OPERATIONAL_TYPES",
    "Conflict",
    "EvidenceAssessment",
    "EvidenceConfig",
    "assess_evidence",
    "detect_conflicts",
    "parse_amounts",
    "parse_dates",
    "worst_state",
]
