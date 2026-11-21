"""Parse the time window a question asks about, against the snapshot date.

Everything here resolves relative to a **snapshot anchor**, never to
``datetime.now()``. ``evaluation/questions.seed.json`` requires every comparison
to run on one frozen dated snapshot; if "the last eight weeks" meant eight weeks
before today, the same question would retrieve a different window next month and
the scored results would stop being reproducible.

Recognised forms
----------------
================================  ==========================================
``last eight weeks``              relative window of 8 ISO weeks
``past 3 months``                 relative window of 3 months
``in the last quarter``           relative window of 13 weeks
``this week`` / ``last week``     single ISO week
``since September``               open-started window from a month boundary
``in October 2026`` / ``in 2026`` a named calendar month or year
================================  ==========================================

A question with no temporal expression gets a window whose ``basis`` is
``"none"``: the full snapshot. That is reported rather than hidden, because an
answer must state the window it used even when the user gave none.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from signals.weeks import WEEK, format_instant, iso_week, parse_instant, week_start

NUMBER_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "twenty": 20,
    "thirty": 30,
    "fifty": 50,
}

MONTHS: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "quarter": 91, "year": 365}

# A count is required here so that "last week" is not read as a one-week
# trailing window ending today; it falls through to _SINGLE, which resolves it
# to the previous ISO week.
_RELATIVE = re.compile(
    r"\b(?:last|past|previous|preceding|recent|trailing|over\s+the\s+last|in\s+the\s+last|within\s+the\s+last)\s+"
    r"(?P<count>\d+|" + "|".join(NUMBER_WORDS) + r")\s+"
    r"(?P<unit>day|days|week|weeks|month|months|quarter|quarters|year|years)\b",
    re.IGNORECASE,
)
_SINGLE = re.compile(
    r"\b(?P<which>this|last|past|recent|previous)\s+(?P<unit>week|month|quarter|year)\b",
    re.IGNORECASE,
)
_SINCE = re.compile(
    r"\bsince\s+(?P<month>" + "|".join(MONTHS) + r")(?:\s+(?P<year>\d{4}))?\b", re.IGNORECASE
)
_MONTH_YEAR = re.compile(
    r"\b(?:in|during|for)\s+(?P<month>" + "|".join(MONTHS) + r")(?:\s+(?P<year>\d{4}))?\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(?:in|during|for)\s+(?P<year>20\d{2})\b", re.IGNORECASE)
_FUTURE_YEAR = re.compile(r"\b(?P<year>20\d{2})\b")


@dataclass(frozen=True)
class TimeWindow:
    """A resolved window, plus how it was resolved."""

    start: str | None
    end: str
    basis: str
    expression: str | None
    anchor: str
    weeks: int | None = None
    label: str = ""

    @property
    def is_open_start(self) -> bool:
        return self.start is None

    def contains(self, timestamp: str | None) -> bool:
        """Half-open containment: ``start <= t < end``, with ``None`` excluded.

        A record with no usable timestamp cannot be shown to fall inside a
        window, so it is excluded rather than assumed current.
        """
        if not timestamp:
            return False
        instant = parse_instant(timestamp)
        if instant >= parse_instant(self.end):
            return False
        if self.start is None:
            return True
        return instant >= parse_instant(self.start)

    def iso_weeks(self) -> list[str]:
        """The ISO week labels the window covers."""
        if self.start is None:
            return []
        cursor = week_start(parse_instant(self.start))
        last = parse_instant(self.end)
        labels: list[str] = []
        while cursor < last:
            labels.append(iso_week(cursor))
            cursor += WEEK
        return labels

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "basis": self.basis,
            "expression": self.expression,
            "anchor": self.anchor,
            "weeks": self.weeks,
            "label": self.label,
            "iso_weeks": self.iso_weeks(),
        }


def _count(raw: str | None) -> int:
    if raw is None:
        return 1
    raw = raw.strip().lower()
    if raw.isdigit():
        return int(raw)
    return NUMBER_WORDS.get(raw, 1)


def _month_start(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=timezone.utc)


def _next_month(year: int, month: int) -> datetime:
    return _month_start(year + 1, 1) if month == 12 else _month_start(year, month + 1)


def full_window(anchor: datetime) -> TimeWindow:
    """The whole snapshot: no start bound, ending just after the anchor."""
    end = anchor + timedelta(seconds=1)
    return TimeWindow(
        start=None,
        end=format_instant(end),
        basis="none",
        expression=None,
        anchor=format_instant(anchor),
        weeks=None,
        label="the full snapshot",
    )


def parse_time_window(question: str, *, anchor: str | datetime) -> TimeWindow:
    """Resolve the time window a question refers to, against ``anchor``."""
    anchor_instant = parse_instant(anchor) if not isinstance(anchor, datetime) else parse_instant(anchor)
    anchor_text = format_instant(anchor_instant)
    end_text = format_instant(anchor_instant + timedelta(seconds=1))
    text = question or ""

    match = _RELATIVE.search(text)
    if match:
        unit = match.group("unit").rstrip("s").lower()
        count = _count(match.group("count"))
        if unit == "week":
            start = week_start(anchor_instant) - WEEK * (count - 1)
            weeks = count
        else:
            start = anchor_instant - timedelta(days=_UNIT_DAYS[unit] * count)
            weeks = max(1, round(_UNIT_DAYS[unit] * count / 7))
        return TimeWindow(
            start=format_instant(start),
            end=end_text,
            basis="relative",
            expression=match.group(0).strip(),
            anchor=anchor_text,
            weeks=weeks,
            label=f"the last {count} {unit}{'s' if count != 1 else ''} before {anchor_text}",
        )

    match = _SINGLE.search(text)
    if match:
        unit = match.group("unit").lower()
        which = match.group("which").lower()
        if unit == "week":
            current = week_start(anchor_instant)
            start = current if which == "this" else current - WEEK
            end = format_instant(start + WEEK)
            return TimeWindow(
                start=format_instant(start),
                end=end,
                basis="relative",
                expression=match.group(0).strip(),
                anchor=anchor_text,
                weeks=1,
                label=f"ISO week {iso_week(start)}",
            )
        # For months, quarters, and years "this/last/past/recent <unit>" all
        # mean the trailing period ending at the anchor, which is what the
        # question means in a trend setting. Only "previous" steps back a whole
        # period. The resolved bounds are reported with every answer, so the
        # reading is visible rather than assumed.
        days = _UNIT_DAYS[unit]
        if which == "previous":
            start = anchor_instant - timedelta(days=days * 2)
            end = format_instant(anchor_instant - timedelta(days=days))
            label = f"the {unit} before the {unit} ending {anchor_text}"
        else:
            start = anchor_instant - timedelta(days=days)
            end = end_text
            label = f"the trailing {unit} ending {anchor_text}"
        return TimeWindow(
            start=format_instant(start),
            end=end,
            basis="relative",
            expression=match.group(0).strip(),
            anchor=anchor_text,
            weeks=max(1, round(days / 7)),
            label=label,
        )

    match = _SINCE.search(text)
    if match:
        month = MONTHS[match.group("month").lower()]
        year = int(match.group("year")) if match.group("year") else anchor_instant.year
        if not match.group("year") and month > anchor_instant.month:
            year -= 1  # "since September" in January means the previous September
        start = _month_start(year, month)
        return TimeWindow(
            start=format_instant(start),
            end=end_text,
            basis="absolute",
            expression=match.group(0).strip(),
            anchor=anchor_text,
            weeks=max(1, round((anchor_instant - start).days / 7)),
            label=f"since {start.date().isoformat()}",
        )

    match = _MONTH_YEAR.search(text)
    if match:
        month = MONTHS[match.group("month").lower()]
        year = int(match.group("year")) if match.group("year") else anchor_instant.year
        start = _month_start(year, month)
        end = _next_month(year, month)
        return TimeWindow(
            start=format_instant(start),
            end=format_instant(end),
            basis="absolute",
            expression=match.group(0).strip(),
            anchor=anchor_text,
            weeks=max(1, round((end - start).days / 7)),
            label=f"{start.date().isoformat()} to {end.date().isoformat()}",
        )

    match = _YEAR.search(text)
    if match:
        year = int(match.group("year"))
        start = _month_start(year, 1)
        end = _month_start(year + 1, 1)
        return TimeWindow(
            start=format_instant(start),
            end=format_instant(end),
            basis="absolute",
            expression=match.group(0).strip(),
            anchor=anchor_text,
            weeks=53,
            label=f"calendar year {year}",
        )

    return full_window(anchor_instant)


def mentions_future(question: str, *, anchor: str | datetime) -> str | None:
    """Return the future reference in a question, if it asks about one.

    A question about a period after the snapshot cannot be answered from the
    snapshot at all, however good retrieval is, so the router sends it straight
    to abstention.
    """
    anchor_instant = parse_instant(anchor) if not isinstance(anchor, datetime) else parse_instant(anchor)
    for match in _FUTURE_YEAR.finditer(question or ""):
        if int(match.group("year")) > anchor_instant.year:
            return match.group("year")
    lowered = (question or "").lower()
    for phrase in ("next year", "next quarter", "next month", "next week", "going forward", "in future"):
        if phrase in lowered:
            return phrase
    return None


__all__ = [
    "MONTHS",
    "NUMBER_WORDS",
    "TimeWindow",
    "full_window",
    "mentions_future",
    "parse_time_window",
]
