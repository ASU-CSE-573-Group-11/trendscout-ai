"""Read-only Greenhouse, Lever, and GitHub adapters."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import quote

from .common import (CollectorError, job_fields, make_record, plain_text,
                     required_text, source_id, utc_timestamp, validate_records)


def target_name(value: str, *, repository=False) -> str:
    pattern = r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+" if repository else r"[A-Za-z0-9_-]+"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise CollectorError("Expected owner/repo" if repository else "Expected a board slug")
    if any(part in {".", ".."} for part in value.split("/")):
        raise CollectorError("Invalid target")
    return value


def object_list(value, label):
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise CollectorError(f"Expected a list of objects for {label}")
    return value


def instant(value):
    return datetime.fromisoformat(utc_timestamp(value).replace("Z", "+00:00"))


def snapshot_header(source, target, company_id, company_name, observed_at=None,
                    origin_cluster_id=None):
    return {
        "snapshot_version": 2, "source": source,
        "target": target_name(target, repository=source == "github"),
        "company_id": required_text(company_id, "company_id"),
        "company_name": required_text(company_name, "company_name"),
        "observed_at": utc_timestamp(observed_at),
        "origin_cluster_id": origin_cluster_id,
    }


class GreenhouseCollector:
    def collect(self, client, header):
        url = f"https://boards-api.greenhouse.io/v1/boards/{header['target']}/jobs"
        payload = client.get(url, params={"content": "true"})
        return {**header, "payload": payload, "coverage": {"api_url": url, "pages": 1}}

    def normalize(self, snapshot):
        payload = snapshot["payload"]
        if not isinstance(payload, dict) or "jobs" not in payload:
            raise CollectorError("Greenhouse response is missing jobs")
        jobs = object_list(payload["jobs"], "Greenhouse jobs")
        total = (payload.get("meta") or {}).get("total")
        if total is not None and total != len(jobs):
            raise CollectorError("Greenhouse job count disagrees with meta.total")
        records = []
        for job in jobs:
            title = required_text(job.get("title"), "job title")
            description = plain_text(job.get("content"))
            location = (job.get("location") or {}).get("name")
            metadata = {
                **job_fields(title, description), "location": location,
                "departments": sorted(required_text(item.get("name"), "department name")
                                      for item in object_list(job.get("departments") or [], "departments")),
                "source_updated_at": utc_timestamp(job["updated_at"]) if job.get("updated_at") else None,
            }
            # updated_at does not establish a publication date.
            records.append(make_record(snapshot, source_id(job.get("id")),
                                       job.get("absolute_url"),
                                       "\n".join(part for part in (title, location, description) if part),
                                       metadata, source_type="job", event_type="job_snapshot"))
        return records


class LeverCollector:
    def __init__(self, *, region="global", page_size=100, max_pages=100):
        if region not in {"global", "eu"} or not 1 <= page_size <= 100 or max_pages < 1:
            raise CollectorError("Invalid Lever pagination or region")
        self.region, self.page_size, self.max_pages = region, page_size, max_pages

    def collect(self, client, header):
        host = "api.eu.lever.co" if self.region == "eu" else "api.lever.co"
        url = f"https://{host}/v0/postings/{header['target']}"
        pages, seen = [], set()
        for page in range(self.max_pages):
            batch = object_list(client.get(url, params={"mode": "json", "skip": page * self.page_size,
                                                       "limit": self.page_size}), "Lever postings")
            ids = {source_id(job.get("id")) for job in batch}
            if seen.intersection(ids) or len(ids) != len(batch):
                raise CollectorError("Lever pagination repeated job IDs; retry the changing board")
            seen.update(ids)
            pages.append(batch)
            if len(batch) < self.page_size:
                return {**header, "payload": pages,
                        "coverage": {"api_url": url, "pages": len(pages), "region": self.region}}
        raise CollectorError("Lever page limit reached; no complete snapshot was produced")

    def normalize(self, snapshot):
        if not isinstance(snapshot["payload"], list):
            raise CollectorError("Lever snapshot must contain a list of pages")
        records = []
        for page in snapshot["payload"]:
            for job in object_list(page, "Lever page"):
                title = required_text(job.get("text"), "job title")
                sections = [plain_text(job.get("descriptionPlain") or job.get("description"))]
                for item in object_list(job.get("lists") or [], "Lever description lists"):
                    sections.extend([plain_text(item.get("text")), plain_text(item.get("content"))])
                sections.append(plain_text(job.get("additionalPlain") or job.get("additional")))
                description = "\n".join(section for section in sections if section)
                categories = job.get("categories") or {}
                if not isinstance(categories, dict):
                    raise CollectorError("Invalid Lever categories")
                metadata = {**job_fields(title, description),
                            "location": categories.get("location"),
                            "team": categories.get("team"),
                            "department": categories.get("department"),
                            "commitment": categories.get("commitment"),
                            "workplace_type": job.get("workplaceType")}
                records.append(make_record(snapshot, source_id(job.get("id")), job.get("hostedUrl"),
                                           "\n".join(part for part in (title, metadata["location"], description) if part),
                                           metadata, source_type="job", event_type="job_snapshot"))
        return records


class GitHubCollector:
    """Repository counters and default-branch commit activity."""

    def __init__(self, *, window_days=7, page_size=100, max_pages=100):
        if not 1 <= window_days <= 365 or not 1 <= page_size <= 100 or max_pages < 1:
            raise CollectorError("Invalid GitHub window or pagination")
        self.window_days, self.page_size, self.max_pages = window_days, page_size, max_pages

    def collect(self, client, header):
        url = f"https://api.github.com/repos/{header['target']}"
        repo = client.get(url)
        if not isinstance(repo, dict) or repo.get("private") is not False:
            raise CollectorError("GitHub collector accepts explicitly public repositories only")
        branch = required_text(repo.get("default_branch"), "default_branch")
        until = header["observed_at"]
        since = utc_timestamp((datetime.fromisoformat(until.replace("Z", "+00:00"))
                               - timedelta(days=self.window_days)).isoformat())
        # Repository size alone cannot tell us whether it has any branches.
        branches = object_list(client.get(f"{url}/branches", params={"per_page": 1}), "branches")
        commits, seen = [], set()
        pages = 0
        if branches:
            # Pin pagination to one tip so new pushes do not shift the results.
            tip = client.get(f"{url}/branches/{quote(branch, safe='')}")
            tip_sha = required_text(tip["commit"].get("sha"), "default branch SHA")
            for page in range(1, self.max_pages + 1):
                batch = object_list(client.get(f"{url}/commits", params={
                    "sha": tip_sha, "since": since, "until": until,
                    "per_page": self.page_size, "page": page}), "GitHub commits")
                pages += 1
                for commit in batch:
                    sha = required_text(commit.get("sha"), "commit SHA")
                    if sha in seen:
                        raise CollectorError("GitHub pagination repeated commits")
                    seen.add(sha)
                    timestamp = utc_timestamp(commit["commit"]["committer"]["date"])
                    # Use (since, until] to avoid counting boundary commits twice.
                    if not instant(since) < instant(timestamp) <= instant(until):
                        continue
                    author = commit.get("author") or {}
                    author_type = author.get("type")
                    commits.append({"sha": sha, "committed_at": timestamp,
                                    "author_type": author_type if author_type in {"Bot", "User"} else "Unknown"})
                if len(batch) < self.page_size:
                    break
            else:
                raise CollectorError("GitHub page limit reached; commit coverage is incomplete")
        else:
            tip_sha = None
        # Keep repository fields, not author profiles or commit messages.
        keys = ("id", "full_name", "html_url", "description", "private", "fork", "archived",
                "disabled", "mirror_url", "stargazers_count", "forks_count", "open_issues_count",
                "language", "topics", "pushed_at", "updated_at", "default_branch", "license")
        retained_repo = {key: repo.get(key) for key in keys}
        return {**header, "payload": {"repository": retained_repo, "commits": commits},
                "coverage": {"api_url": url, "commit_pages": pages,
                             "window_start": since, "window_end": until,
                             "interval": "(start, end]", "default_branch_sha": tip_sha,
                             "commit_scope": "default_branch", "window_days": self.window_days,
                             "raw_policy": "repository fields and commits stripped of personal data"}}

    def normalize(self, snapshot):
        payload = snapshot["payload"]
        repo = payload["repository"]
        if repo.get("private") is not False:
            raise CollectorError("Private GitHub data is not allowed")
        commits = object_list(payload["commits"], "minimized commits")
        if len({commit["sha"] for commit in commits}) != len(commits):
            raise CollectorError("Duplicate commits in snapshot")
        coverage = snapshot["coverage"]
        since, until = utc_timestamp(coverage["window_start"]), utc_timestamp(coverage["window_end"])
        if instant(since) >= instant(until):
            raise CollectorError("Invalid GitHub observation window")
        for commit in commits:
            if not instant(since) < instant(commit["committed_at"]) <= instant(until):
                raise CollectorError("Commit outside the observation window")
        bot_count = sum(commit.get("author_type") == "Bot" for commit in commits)
        unknown_count = sum(commit.get("author_type") not in {"User", "Bot"} for commit in commits)
        counters = {}
        for name in ("stargazers_count", "forks_count", "open_issues_count"):
            value = repo.get(name)
            if type(value) is not int or value < 0:
                raise CollectorError(f"Missing or invalid GitHub counter: {name}")
            counters[name] = value
        flags = {name: repo.get(name) for name in ("fork", "archived", "disabled")}
        flags.update(is_mirror=bool(repo.get("mirror_url")),
                     bot_heavy=bool(commits) and bot_count / len(commits) >= 0.5)
        metadata = {
            "repository": required_text(repo.get("full_name"), "repository full_name"),
            **counters, "language": repo.get("language"),
            "topics": sorted(repo.get("topics") or []),
            "license_spdx": (repo.get("license") or {}).get("spdx_id"),
            "quality_flags": flags, "default_branch": repo.get("default_branch"),
            "source_updated_at": utc_timestamp(repo["updated_at"]) if repo.get("updated_at") else None,
            "source_pushed_at": utc_timestamp(repo["pushed_at"]) if repo.get("pushed_at") else None,
            "activity_window": {"start": since, "end": until, "interval": "(start, end]",
                                "scope": "default_branch", "commit_count": len(commits),
                                "bot_commit_count": bot_count, "unknown_author_count": unknown_count,
                                "commit_shas": sorted(commit["sha"] for commit in commits)},
        }
        # Keep derived metrics out of the quoted source passage.
        text = repo.get("description") or ""
        return [make_record(snapshot, source_id(repo.get("id")), repo.get("html_url"), text,
                            metadata, source_type="github", event_type="repository_snapshot")]


COLLECTORS = {"greenhouse": GreenhouseCollector, "lever": LeverCollector, "github": GitHubCollector}


def normalize(snapshot):
    """Replay a saved snapshot and validate the current shared schema."""
    if not isinstance(snapshot, dict):
        raise CollectorError("Snapshot must be an object")
    try:
        if snapshot.get("snapshot_version") not in {1, 2} or snapshot.get("source") not in COLLECTORS:
            raise CollectorError("Unsupported snapshot version or source")
        snapshot_header(snapshot["source"], snapshot["target"], snapshot["company_id"],
                        snapshot["company_name"], snapshot["observed_at"], snapshot.get("origin_cluster_id"))
        return validate_records(COLLECTORS[snapshot["source"]]().normalize(snapshot))
    except (KeyError, TypeError, AttributeError) as exc:
        raise CollectorError(f"Malformed {snapshot.get('source', 'unknown')} snapshot") from exc
