"""Adapters from shared source records to the observations the features need.

This module is the *only* place that knows how Vidya's collectors lay out
``metadata``. Every feature builder downstream consumes the dataclasses defined
here, so moving from her PR fixtures to her live ``records.jsonl`` output is a
change of input path, and any rename inside her metadata is a change to one
mapping table in this file.

The adapters are strict on purpose. A record that claims to be a GitHub
snapshot but lacks a usable observation window raises
:class:`AdapterError` rather than silently contributing a zero, because a
fabricated zero becomes a fabricated decline once the trend scorer sees it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping

from collectors.records import validate_record
from signals.weeks import parse_instant

ADAPTER_VERSION = "signals-adapter/1.0.0"

# Vidya's GitHub metadata keys. Rename here if her collector renames them.
GITHUB_FIELDS: dict[str, str] = {
    "repository": "repository",
    "stars": "stargazers_count",
    "forks": "forks_count",
    "open_issues": "open_issues_count",
    "quality_flags": "quality_flags",
    "activity_window": "activity_window",
    "language": "language",
    "topics": "topics",
    "default_branch": "default_branch",
    "pushed_at": "source_pushed_at",
}

# Keys inside metadata["activity_window"].
GITHUB_WINDOW_FIELDS: dict[str, str] = {
    "start": "start",
    "end": "end",
    "interval": "interval",
    "scope": "scope",
    "commits": "commit_count",
    "bot_commits": "bot_commit_count",
    "unknown_authors": "unknown_author_count",
    "commit_shas": "commit_shas",
}

# Metrics the GitHub collector does not report, with the reason it does not.
# Kept here rather than in the feature builder so one table explains every gap.
GITHUB_UNAVAILABLE_METRICS: dict[str, str] = {
    "releases": (
        "not collected: the GitHub collector reads repository fields, branches, and "
        "commits only; the releases endpoint is not requested"
    ),
    "issues_opened": (
        "not collected: only the current open_issues_count counter is retained, which "
        "includes pull requests and cannot be split into opened and closed events"
    ),
    "issues_closed": (
        "not collected: only the current open_issues_count counter is retained, which "
        "includes pull requests and cannot be split into opened and closed events"
    ),
    "active_contributors": (
        "not collected by policy: commit author names, emails, and profiles are "
        "discarded at collection time, so distinct contributors cannot be counted"
    ),
}

# Optional keys read when present, so a later collector change needs no new code.
GITHUB_OPTIONAL_METRIC_FIELDS: dict[str, str] = {
    "releases": "release_count",
    "issues_opened": "issues_opened_count",
    "issues_closed": "issues_closed_count",
    "active_contributors": "active_contributor_count",
}

# Vidya's job metadata keys.
JOB_FIELDS: dict[str, str] = {
    "title": "title",
    "role_normalized": "role_normalized",
    "skills": "skills",
    "location": "location",
    "team": "team",
    "department": "department",
    "departments": "departments",
    "source_record_id": "source_record_id",
    "skill_method": "skill_extraction_method",
}

DOCUMENT_SOURCE_TYPES: frozenset[str] = frozenset({"news", "company", "public_voice", "funding"})


class AdapterError(ValueError):
    """A record cannot be interpreted as the observation it claims to be."""


@dataclass(frozen=True)
class GitHubObservation:
    """One repository snapshot covering ``(window_start, window_end]``."""

    record_id: str
    company_id: str
    repository: str
    origin_cluster_id: str
    content_hash: str
    observed_at: datetime
    window_start: datetime
    window_end: datetime
    interval: str
    scope: str
    commit_count: int
    bot_commit_count: int
    unknown_author_count: int
    commit_shas: tuple[str, ...]
    stars: int | None
    forks: int | None
    open_issues: int | None
    quality_flags: dict[str, Any] = field(default_factory=dict)
    optional_metrics: dict[str, int | None] = field(default_factory=dict)
    commit_events: tuple[tuple[str, datetime], ...] | None = None

    @property
    def human_commit_count(self) -> int:
        """Commits not attributed to a GitHub bot account.

        Unknown-author commits count as human: treating an unknown account as a
        bot would quietly delete real activity.
        """
        return max(0, self.commit_count - self.bot_commit_count)

    @property
    def bot_ratio(self) -> float | None:
        if not self.commit_count:
            return None
        return self.bot_commit_count / self.commit_count

    @property
    def is_excluded(self) -> bool:
        """True for repositories that should not contribute activity features."""
        flags = self.quality_flags
        return bool(
            flags.get("is_mirror") or flags.get("archived") or flags.get("disabled") or flags.get("fork")
        )

    @property
    def exclusion_reasons(self) -> tuple[str, ...]:
        flags = self.quality_flags
        reasons = []
        for key, reason in (
            ("is_mirror", "mirror repository"),
            ("archived", "archived repository"),
            ("disabled", "disabled repository"),
            ("fork", "fork of another repository"),
        ):
            if flags.get(key):
                reasons.append(reason)
        return tuple(reasons)

    @property
    def is_bot_heavy(self) -> bool:
        return bool(self.quality_flags.get("bot_heavy"))


@dataclass(frozen=True)
class JobObservation:
    """One job posting as listed at ``observed_at``."""

    record_id: str
    company_id: str
    origin_cluster_id: str
    content_hash: str
    observed_at: datetime
    posting_id: str
    title: str
    role_normalized: str
    skills: tuple[str, ...]
    location: str | None
    team: str | None
    collector: str | None


@dataclass(frozen=True)
class DocumentObservation:
    """One documentary record placed in time for weekly attention counts."""

    record_id: str
    company_id: str | None
    origin_cluster_id: str
    content_hash: str
    source_type: str
    publisher: str | None
    at: datetime
    time_basis: str


def _require_valid(record: Mapping[str, Any]) -> None:
    errors = validate_record(record)
    if errors:
        raise AdapterError(
            f"record {record.get('record_id')!r} does not satisfy the shared schema: {errors}"
        )


def _int_or_none(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdapterError(f"{label} must be an integer, got {value!r}")
    if value < 0:
        raise AdapterError(f"{label} must not be negative, got {value}")
    return value


def _required_int(value: Any, label: str) -> int:
    parsed = _int_or_none(value, label)
    if parsed is None:
        raise AdapterError(f"{label} is required")
    return parsed


def github_observation(record: Mapping[str, Any], *, validate: bool = True) -> GitHubObservation:
    """Interpret one GitHub source record as a repository activity observation."""
    if validate:
        _require_valid(record)
    if record.get("source_type") != "github":
        raise AdapterError(f"record {record.get('record_id')!r} is not a GitHub record")
    metadata = record.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise AdapterError(f"record {record.get('record_id')!r} has no metadata object")

    repository = metadata.get(GITHUB_FIELDS["repository"])
    if not isinstance(repository, str) or not repository.strip():
        raise AdapterError(f"record {record.get('record_id')!r} has no repository name")

    window = metadata.get(GITHUB_FIELDS["activity_window"])
    if not isinstance(window, dict):
        raise AdapterError(
            f"record {record.get('record_id')!r} has no activity_window; weekly features need "
            "an explicit observation window, and inventing one would fabricate activity"
        )

    start = parse_instant(window[GITHUB_WINDOW_FIELDS["start"]])
    end = parse_instant(window[GITHUB_WINDOW_FIELDS["end"]])
    if start >= end:
        raise AdapterError(f"record {record.get('record_id')!r} has an empty activity window")

    shas_raw = window.get(GITHUB_WINDOW_FIELDS["commit_shas"]) or []
    if not isinstance(shas_raw, list) or any(not isinstance(item, str) for item in shas_raw):
        raise AdapterError(f"record {record.get('record_id')!r} has malformed commit_shas")
    commit_shas = tuple(sorted(set(shas_raw)))

    commit_count = _required_int(window.get(GITHUB_WINDOW_FIELDS["commits"]), "commit_count")
    if commit_shas and len(commit_shas) != commit_count:
        raise AdapterError(
            f"record {record.get('record_id')!r} reports {commit_count} commits but "
            f"{len(commit_shas)} distinct SHAs"
        )

    commit_events: tuple[tuple[str, datetime], ...] | None = None
    events_raw = window.get("commits") or window.get("commit_events")
    if isinstance(events_raw, list) and events_raw and all(isinstance(item, dict) for item in events_raw):
        parsed_events = []
        for item in events_raw:
            sha = item.get("sha")
            at = item.get("committed_at") or item.get("at")
            if not isinstance(sha, str) or at is None:
                raise AdapterError(
                    f"record {record.get('record_id')!r} has a malformed commit event"
                )
            parsed_events.append((sha, parse_instant(at)))
        commit_events = tuple(sorted(set(parsed_events)))

    quality_flags = metadata.get(GITHUB_FIELDS["quality_flags"]) or {}
    if not isinstance(quality_flags, dict):
        raise AdapterError(f"record {record.get('record_id')!r} has malformed quality_flags")

    optional_metrics = {
        name: _int_or_none(metadata.get(key), name)
        for name, key in GITHUB_OPTIONAL_METRIC_FIELDS.items()
    }

    company_id = record.get("company_id")
    if not isinstance(company_id, str) or not company_id.strip():
        raise AdapterError(
            f"GitHub record {record.get('record_id')!r} has no company_id; weekly features "
            "are reported per cohort company"
        )

    return GitHubObservation(
        record_id=record["record_id"],
        company_id=company_id,
        repository=repository.strip(),
        origin_cluster_id=record["origin_cluster_id"],
        content_hash=record["content_hash"],
        observed_at=parse_instant(record["observed_at"]),
        window_start=start,
        window_end=end,
        interval=str(window.get(GITHUB_WINDOW_FIELDS["interval"]) or "(start, end]"),
        scope=str(window.get(GITHUB_WINDOW_FIELDS["scope"]) or "default_branch"),
        commit_count=commit_count,
        bot_commit_count=_int_or_none(window.get(GITHUB_WINDOW_FIELDS["bot_commits"]), "bot_commit_count") or 0,
        unknown_author_count=_int_or_none(
            window.get(GITHUB_WINDOW_FIELDS["unknown_authors"]), "unknown_author_count"
        )
        or 0,
        commit_shas=commit_shas,
        stars=_int_or_none(metadata.get(GITHUB_FIELDS["stars"]), "stargazers_count"),
        forks=_int_or_none(metadata.get(GITHUB_FIELDS["forks"]), "forks_count"),
        open_issues=_int_or_none(metadata.get(GITHUB_FIELDS["open_issues"]), "open_issues_count"),
        quality_flags=dict(quality_flags),
        optional_metrics=optional_metrics,
        commit_events=commit_events,
    )


def job_observation(record: Mapping[str, Any], *, validate: bool = True) -> JobObservation:
    """Interpret one job source record as a posting observation."""
    if validate:
        _require_valid(record)
    if record.get("source_type") != "job":
        raise AdapterError(f"record {record.get('record_id')!r} is not a job record")
    metadata = record.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise AdapterError(f"record {record.get('record_id')!r} has no metadata object")

    title = metadata.get(JOB_FIELDS["title"]) or record.get("title") or ""
    if not isinstance(title, str) or not title.strip():
        raise AdapterError(f"job record {record.get('record_id')!r} has no title")
    role_normalized = metadata.get(JOB_FIELDS["role_normalized"])
    if not isinstance(role_normalized, str) or not role_normalized.strip():
        role_normalized = " ".join(title.casefold().split())

    skills_raw = metadata.get(JOB_FIELDS["skills"]) or []
    if not isinstance(skills_raw, list) or any(not isinstance(item, str) for item in skills_raw):
        raise AdapterError(f"job record {record.get('record_id')!r} has malformed skills")

    company_id = record.get("company_id")
    if not isinstance(company_id, str) or not company_id.strip():
        raise AdapterError(f"job record {record.get('record_id')!r} has no company_id")

    # The stable posting identity: unchanged postings keep it across snapshots,
    # which is what makes "new this week" meaningful rather than a re-listing.
    posting_id = metadata.get(JOB_FIELDS["source_record_id"]) or record["record_id"]

    return JobObservation(
        record_id=record["record_id"],
        company_id=company_id,
        origin_cluster_id=record["origin_cluster_id"],
        content_hash=record["content_hash"],
        observed_at=parse_instant(record["observed_at"]),
        posting_id=str(posting_id),
        title=title.strip(),
        role_normalized=" ".join(role_normalized.casefold().split()),
        skills=tuple(sorted({item.strip().casefold() for item in skills_raw if item.strip()})),
        location=metadata.get(JOB_FIELDS["location"]),
        team=metadata.get(JOB_FIELDS["team"]) or metadata.get(JOB_FIELDS["department"]),
        collector=metadata.get("collector"),
    )


def document_observation(record: Mapping[str, Any], *, validate: bool = True) -> DocumentObservation:
    """Place one documentary record in time for weekly attention counts.

    Publication time is preferred; observation time is the documented fallback,
    and ``time_basis`` records which clock was used so the three clocks in
    ``evaluation/annotation_guidelines.json`` stay distinguishable.
    """
    if validate:
        _require_valid(record)
    source_type = record.get("source_type")
    if source_type not in DOCUMENT_SOURCE_TYPES:
        raise AdapterError(
            f"record {record.get('record_id')!r} has source_type {source_type!r}, which is not a "
            f"documentary type {sorted(DOCUMENT_SOURCE_TYPES)}"
        )
    for key, basis in (("event_at", "event_at"), ("published_at", "published_at"), ("observed_at", "observed_at")):
        value = record.get(key)
        if value:
            return DocumentObservation(
                record_id=record["record_id"],
                company_id=record.get("company_id"),
                origin_cluster_id=record["origin_cluster_id"],
                content_hash=record["content_hash"],
                source_type=str(source_type),
                publisher=record.get("publisher"),
                at=parse_instant(value),
                time_basis=basis,
            )
    raise AdapterError(f"record {record.get('record_id')!r} carries no usable timestamp")


def github_observations(
    records: Iterable[Mapping[str, Any]], *, validate: bool = True
) -> list[GitHubObservation]:
    """Adapt every GitHub record in ``records``, ignoring other source types."""
    return [
        github_observation(record, validate=validate)
        for record in records
        if record.get("source_type") == "github"
    ]


def job_observations(
    records: Iterable[Mapping[str, Any]], *, validate: bool = True
) -> list[JobObservation]:
    """Adapt every job record in ``records``, ignoring other source types."""
    return [
        job_observation(record, validate=validate)
        for record in records
        if record.get("source_type") == "job"
    ]


def document_observations(
    records: Iterable[Mapping[str, Any]], *, validate: bool = True
) -> list[DocumentObservation]:
    """Adapt every documentary record in ``records``, ignoring other source types."""
    return [
        document_observation(record, validate=validate)
        for record in records
        if record.get("source_type") in DOCUMENT_SOURCE_TYPES
    ]


__all__ = [
    "ADAPTER_VERSION",
    "AdapterError",
    "DOCUMENT_SOURCE_TYPES",
    "DocumentObservation",
    "GITHUB_UNAVAILABLE_METRICS",
    "GitHubObservation",
    "JobObservation",
    "document_observation",
    "document_observations",
    "github_observation",
    "github_observations",
    "job_observation",
    "job_observations",
]
