"""ISO week arithmetic shared by every feature builder.

Weeks are ISO-8601 weeks in UTC. A week label looks like ``2026-W46`` and spans
``[week_start, week_end)`` where ``week_start`` is Monday 00:00:00Z.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

WEEK = timedelta(days=7)


def parse_instant(value: str | datetime) -> datetime:
    """Parse an ISO-8601 timestamp into an aware UTC datetime."""
    if isinstance(value, datetime):
        instant = value
    else:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("expected an ISO-8601 timestamp")
        try:
            instant = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"not an ISO-8601 timestamp: {value!r}") from exc
    if instant.tzinfo is None:
        raise ValueError(f"timestamp must carry a timezone: {value!r}")
    return instant.astimezone(timezone.utc)


def format_instant(instant: datetime) -> str:
    """Render an aware datetime the way the shared record contract does."""
    return instant.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def week_start(instant: datetime) -> datetime:
    """Monday 00:00:00Z of the ISO week containing ``instant``."""
    instant = instant.astimezone(timezone.utc)
    midnight = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=instant.isoweekday() - 1)


def iso_week(instant: datetime) -> str:
    """ISO week label, for example ``2026-W46``."""
    year, week, _ = instant.astimezone(timezone.utc).isocalendar()
    return f"{year}-W{week:02d}"


def week_label(instant: datetime) -> tuple[str, datetime, datetime]:
    """Return ``(label, week_start, week_end)`` for the week containing ``instant``."""
    start = week_start(instant)
    return iso_week(start), start, start + WEEK


def parse_iso_week(label: str) -> datetime:
    """Inverse of :func:`iso_week`: the Monday that starts the labelled week."""
    if not isinstance(label, str) or len(label) != 8 or label[4:6] != "-W":
        raise ValueError(f"not an ISO week label: {label!r}")
    try:
        year, week = int(label[:4]), int(label[6:])
    except ValueError as exc:
        raise ValueError(f"not an ISO week label: {label!r}") from exc
    if not 1 <= week <= 53:
        raise ValueError(f"ISO week out of range: {label!r}")
    try:
        return datetime.fromisocalendar(year, week, 1).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError(f"ISO week does not exist: {label!r}") from exc


def week_range(first: str, last: str) -> list[str]:
    """Every ISO week label from ``first`` to ``last`` inclusive, in order."""
    start, end = parse_iso_week(first), parse_iso_week(last)
    if start > end:
        raise ValueError(f"week range is reversed: {first} > {last}")
    labels: list[str] = []
    cursor = start
    while cursor <= end:
        labels.append(iso_week(cursor))
        cursor += WEEK
    return labels


def weeks_back(last: str, count: int) -> list[str]:
    """The ``count`` ISO weeks ending at ``last`` inclusive."""
    if count < 1:
        raise ValueError("count must be at least 1")
    end = parse_iso_week(last)
    start = end - WEEK * (count - 1)
    return week_range(iso_week(start), last)


def covers_whole_week(start: datetime, end: datetime) -> str | None:
    """Return the ISO week label when ``(start, end]`` exactly covers one ISO week."""
    if end - start != WEEK:
        return None
    if start != week_start(start):
        return None
    return iso_week(start)
