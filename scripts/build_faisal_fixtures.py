"""Regenerate the fixtures for the weekly-features, trend, and retrieval tests.

Vidya's PR #3 (``vidya/api-collectors``) is not merged yet, so these fixtures
reproduce her record layout rather than her code: the same top-level fields, the
same ``metadata.activity_window`` and ``metadata.quality_flags`` structure, and
the same identity rule (``record_id`` = source identity plus a digest of the
normalized evidence, with observation time deliberately excluded so an
unchanged snapshot keeps its id).

When her PR merges, these files are replaced by a real ``records.jsonl`` run and
nothing else has to change: :mod:`signals.adapters` already reads her layout.

Usage::

    python scripts/build_faisal_fixtures.py

The fixtures are synthetic. Company ids come from the frozen cohort in
``data/registry/cohort.json`` so the output joins to it, but no figure here is a
measurement of a real company.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors.records import canonicalize_url, sha256_text  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "faisal"

COLLECTOR_VERSION = "api-collectors/0.2.0"
WEEK = timedelta(days=7)

# Monday 00:00:00Z that starts ISO week 2026-W36.
FIRST_WEEK = datetime.fromisocalendar(2026, 36, 1).replace(tzinfo=timezone.utc)


def utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fake_sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:40]


def make_record(
    *,
    source: str,
    target: str,
    item_id: str,
    company_id: str,
    company_name: str,
    url: str,
    text: str,
    metadata: dict[str, Any],
    source_type: str,
    event_type: str,
    observed_at: str,
    published_at: str | None = None,
) -> dict[str, Any]:
    """Mirror of ``collectors.common.make_record`` on Vidya's branch."""
    identity = f"{source}:{target}:{item_id}"
    canonical = canonicalize_url(url)
    metadata = {
        **metadata,
        "collector": source,
        "source_record_id": identity,
        "source_control_group": f"company:{company_id}",
    }
    record = {
        "source_type": source_type,
        "source_url": canonical,
        "publisher": company_name,
        "startup_name": company_name,
        "company_id": company_id,
        "origin_cluster_id": sha256_text(canonical)[:16],
        "title": metadata.get("title") or metadata.get("repository"),
        "collector_version": COLLECTOR_VERSION,
        "event_type": event_type,
        "event_at": None,
        "published_at": published_at,
        "text": text,
        "access_note": "Public read-only API; no applicant or private-profile data.",
        "metadata": metadata,
    }
    canonical_json = json.dumps(
        record, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    record.update(record_id=f"{identity}:{digest}", content_hash=digest, observed_at=observed_at)
    return record


def github_record(
    *,
    company_id: str,
    company_name: str,
    repository: str,
    repo_id: int,
    window_start: datetime,
    window_end: datetime,
    commit_seeds: list[str],
    bot_commits: int,
    stars: int,
    forks: int,
    open_issues: int,
    description: str,
    flags: dict[str, Any] | None = None,
    language: str = "Python",
    topics: list[str] | None = None,
) -> dict[str, Any]:
    shas = sorted(fake_sha(f"{repository}:{seed}") for seed in commit_seeds)
    quality_flags = {
        "fork": False,
        "archived": False,
        "disabled": False,
        "is_mirror": False,
        "bot_heavy": bool(shas) and bot_commits / len(shas) >= 0.5,
    }
    quality_flags.update(flags or {})
    metadata = {
        "repository": repository,
        "stargazers_count": stars,
        "forks_count": forks,
        "open_issues_count": open_issues,
        "language": language,
        "topics": sorted(topics or ["agents", "developer-tools"]),
        "license_spdx": "MIT",
        "quality_flags": quality_flags,
        "default_branch": "main",
        "source_updated_at": utc(window_end),
        "source_pushed_at": utc(window_end - timedelta(hours=3)),
        "activity_window": {
            "start": utc(window_start),
            "end": utc(window_end),
            "interval": "(start, end]",
            "scope": "default_branch",
            "commit_count": len(shas),
            "bot_commit_count": bot_commits,
            "unknown_author_count": 0,
            "commit_shas": shas,
        },
    }
    return make_record(
        source="github",
        target=repository,
        item_id=str(repo_id),
        company_id=company_id,
        company_name=company_name,
        url=f"https://github.com/{repository}",
        text=description,
        metadata=metadata,
        source_type="github",
        event_type="repository_snapshot",
        observed_at=utc(window_end),
    )


def job_record(
    *,
    company_id: str,
    company_name: str,
    board: str,
    job_id: str,
    title: str,
    description: str,
    skills: list[str],
    location: str,
    team: str,
    observed_at: datetime,
    collector: str = "greenhouse",
) -> dict[str, Any]:
    metadata = {
        "title": title,
        "role_normalized": " ".join(title.casefold().split()),
        "skills": sorted(skills),
        "skill_extraction_method": "explicit_mentions_v1",
        "location": location,
        "departments": [team],
        "team": team,
        "source_updated_at": utc(observed_at),
    }
    return make_record(
        source=collector,
        target=board,
        item_id=job_id,
        company_id=company_id,
        company_name=company_name,
        url=f"https://boards.example.com/{board}/jobs/{job_id}",
        text="\n".join([title, location, description]),
        metadata=metadata,
        source_type="job",
        event_type="job_snapshot",
        observed_at=utc(observed_at),
    )


def news_record(
    *,
    company_id: str,
    company_name: str,
    publisher: str,
    slug: str,
    title: str,
    text: str,
    published_at: datetime,
    source_type: str = "news",
    origin_override: str | None = None,
) -> dict[str, Any]:
    url = f"https://{publisher.lower().replace(' ', '')}.example.com/{slug}"
    record = make_record(
        source="news",
        target=publisher.lower().replace(" ", "-"),
        item_id=slug,
        company_id=company_id,
        company_name=publisher,
        url=url,
        text=text,
        metadata={"title": title, "startup": company_name},
        source_type=source_type,
        event_type="coverage",
        observed_at=utc(published_at + timedelta(hours=6)),
        published_at=utc(published_at),
    )
    record["startup_name"] = company_name
    if origin_override:
        record["origin_cluster_id"] = origin_override
    return record


# --------------------------------------------------------------------------
# GitHub: nine ISO weeks, one missing week, a double collection, a mirror,
# a bot-heavy repository, and one window that does not align to an ISO week.
# --------------------------------------------------------------------------

GITHUB_PLAN: dict[str, dict[str, Any]] = {
    "langchain-ai/langchain": {
        "company_id": "langchain",
        "company_name": "LangChain",
        "repo_id": 101,
        "description": "Agent orchestration framework with LangGraph and LangSmith.",
        "commits": {36: 12, 37: 11, 38: 13, 39: 12, 40: 14, 41: 12, 43: 31, 44: 29},
        "stars": {36: 4000, 37: 4060, 38: 4130, 39: 4190, 40: 4250, 41: 4300, 43: 4700, 44: 4900},
        "issues": {36: 120, 37: 124, 38: 119, 39: 125, 40: 130, 41: 128, 43: 160, 44: 171},
        "bot_share": 0.0,
    },
    "langchain-ai/langgraph": {
        "company_id": "langchain",
        "company_name": "LangChain",
        "repo_id": 102,
        "description": "Stateful agent graphs for LangChain.",
        "commits": {41: 4, 43: 6, 44: 9},
        "stars": {41: 300, 43: 320, 44: 355},
        "issues": {41: 20, 43: 22, 44: 25},
        "bot_share": 0.0,
    },
    "run-llama/llama_index": {
        "company_id": "llamaindex",
        "company_name": "LlamaIndex",
        "repo_id": 201,
        "description": "Data framework for RAG and document agents.",
        "commits": {36: 9, 37: 10, 38: 9, 39: 10, 40: 9, 41: 10, 43: 9, 44: 10},
        "stars": {36: 2500, 37: 2520, 38: 2540, 39: 2560, 40: 2580, 41: 2600, 43: 2640, 44: 2660},
        "issues": {36: 80, 37: 81, 38: 80, 39: 82, 40: 81, 41: 83, 43: 82, 44: 84},
        "bot_share": 0.0,
    },
    "run-llama/llama_index-mirror": {
        "company_id": "llamaindex",
        "company_name": "LlamaIndex",
        "repo_id": 202,
        "description": "Read-only mirror of llama_index.",
        "commits": {36: 9, 37: 10, 38: 9, 39: 10, 40: 9, 41: 10, 43: 9, 44: 10},
        "stars": {36: 10, 37: 10, 38: 10, 39: 10, 40: 10, 41: 10, 43: 10, 44: 10},
        "issues": {36: 0, 37: 0, 38: 0, 39: 0, 40: 0, 41: 0, 43: 0, 44: 0},
        "bot_share": 0.0,
        "flags": {"is_mirror": True},
    },
    "crewAIInc/crewAI": {
        "company_id": "crewai",
        "company_name": "CrewAI",
        "repo_id": 301,
        "description": "Role-based multi-agent orchestration.",
        "commits": {36: 8, 37: 8, 38: 9, 39: 8, 40: 8, 41: 9, 43: 20, 44: 22},
        "stars": {36: 900, 37: 905, 38: 912, 39: 918, 40: 925, 41: 930, 43: 980, 44: 1010},
        "issues": {36: 40, 37: 41, 38: 40, 39: 42, 40: 41, 41: 43, 43: 50, 44: 52},
        "bot_share": 0.75,
    },
}


def build_github_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for repository, plan in GITHUB_PLAN.items():
        for week, commits in sorted(plan["commits"].items()):
            start = datetime.fromisocalendar(2026, week, 1).replace(tzinfo=timezone.utc)
            end = start + WEEK
            bot = int(round(commits * plan["bot_share"]))
            records.append(
                github_record(
                    company_id=plan["company_id"],
                    company_name=plan["company_name"],
                    repository=repository,
                    repo_id=plan["repo_id"],
                    window_start=start,
                    window_end=end,
                    commit_seeds=[f"w{week}-c{index}" for index in range(commits)],
                    bot_commits=bot,
                    stars=plan["stars"][week],
                    forks=plan["stars"][week] // 10,
                    open_issues=plan["issues"][week],
                    description=plan["description"],
                    flags=plan.get("flags"),
                )
            )

    # A second collection inside ISO week 2026-W44 for langchain: a trailing
    # seven-day window that is NOT ISO-aligned and that re-reports commits
    # already seen. The SHA union must keep the weekly count honest (31, not
    # 29 + 22), and the week assignment must be flagged as approximate.
    plan = GITHUB_PLAN["langchain-ai/langchain"]
    mid_end = datetime.fromisocalendar(2026, 44, 5).replace(tzinfo=timezone.utc) + timedelta(hours=12)
    records.append(
        github_record(
            company_id=plan["company_id"],
            company_name=plan["company_name"],
            repository="langchain-ai/langchain",
            repo_id=plan["repo_id"],
            window_start=mid_end - WEEK,
            window_end=mid_end,
            commit_seeds=[f"w44-c{index}" for index in range(20)] + ["w44-extra-1", "w44-extra-2"],
            bot_commits=0,
            stars=4880,
            forks=488,
            open_issues=168,
            description=plan["description"],
        )
    )

    # An exact replay of the final aligned langchain snapshot. Identical
    # evidence keeps the same record_id and content_hash, so collecting twice
    # must not inflate any weekly count.
    replay = [
        record
        for record in records
        if record["metadata"]["repository"] == "langchain-ai/langchain"
        and record["metadata"]["activity_window"]["start"]
        == utc(datetime.fromisocalendar(2026, 44, 1).replace(tzinfo=timezone.utc))
    ]
    records.extend(json.loads(json.dumps(record)) for record in replay)
    return records


# --------------------------------------------------------------------------
# Jobs: weekly board snapshots. MLOps hiring appears at LangChain in W43/W44
# (new postings), CrewAI posts a retrieval role, LlamaIndex stays flat.
# --------------------------------------------------------------------------

JOB_PLAN: list[dict[str, Any]] = [
    {
        "company_id": "langchain",
        "company_name": "LangChain",
        "board": "langchain",
        "jobs": {
            "4001": ("Senior Software Engineer, Platform", ["python", "kubernetes"], "Platform", 36, 44),
            "4002": ("Developer Advocate", ["python"], "Community", 36, 44),
            "4003": ("MLOps Engineer", ["python", "kubernetes", "docker"], "Infrastructure", 43, 44),
            "4004": ("Machine Learning Operations Lead", ["python", "kubernetes"], "Infrastructure", 44, 44),
            "4005": ("Evaluation Engineer, LangSmith", ["python", "sql"], "Evaluation", 44, 44),
        },
    },
    {
        "company_id": "llamaindex",
        "company_name": "LlamaIndex",
        "board": "llamaindex",
        "jobs": {
            "5001": ("Software Engineer, Retrieval", ["python"], "Core", 36, 44),
            "5002": ("Technical Writer", [], "Docs", 36, 44),
        },
    },
    {
        "company_id": "crewai",
        "company_name": "CrewAI",
        "board": "crewai",
        "jobs": {
            "6001": ("Backend Engineer", ["python", "docker"], "Engineering", 36, 44),
            "6002": ("Retrieval Engineer", ["python", "pytorch"], "Research", 42, 44),
            "6003": ("MLOps Engineer, Deployments", ["python", "kubernetes"], "Infrastructure", 44, 44),
        },
    },
]

JOB_WEEKS = [36, 37, 38, 39, 40, 41, 42, 43, 44]


def build_job_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for company in JOB_PLAN:
        for week in JOB_WEEKS:
            observed = datetime.fromisocalendar(2026, week, 2).replace(tzinfo=timezone.utc) + timedelta(hours=9)
            for job_id, (title, skills, team, first, last) in company["jobs"].items():
                if not first <= week <= last:
                    continue
                records.append(
                    job_record(
                        company_id=company["company_id"],
                        company_name=company["company_name"],
                        board=company["board"],
                        job_id=job_id,
                        title=title,
                        description=(
                            f"We are hiring a {title} to work on agent infrastructure. "
                            f"Skills: {', '.join(skills) or 'none listed'}."
                        ),
                        skills=skills,
                        location="Remote",
                        team=team,
                        observed_at=observed,
                    )
                )
    return records


# --------------------------------------------------------------------------
# Documents: news and company posts, including two syndicated copies that
# share an origin cluster so distinct-origin counting can be tested.
# --------------------------------------------------------------------------

SYNDICATED_ORIGIN = "faisalfixture0001"

DOCUMENT_PLAN: list[dict[str, Any]] = [
    {
        "company_id": "langchain",
        "company_name": "LangChain",
        "publisher": "TechCrunch",
        "slug": "langchain-raises-series-b",
        "title": "LangChain raises a Series B to expand LangSmith",
        "text": (
            "LangChain said it raised a Series B led by an existing investor to expand LangSmith, "
            "its observability product for agent applications. The company said the round closed in "
            "October 2026 and that it will grow its platform and evaluation teams."
        ),
        "week": 43,
        "day": 2,
        "origin": SYNDICATED_ORIGIN,
    },
    {
        "company_id": "langchain",
        "company_name": "LangChain",
        "publisher": "VentureBeat",
        "slug": "langchain-series-b-syndicated",
        "title": "LangChain raises a Series B to expand LangSmith",
        "text": (
            "LangChain said it raised a Series B led by an existing investor to expand LangSmith, "
            "its observability product for agent applications. The round closed in October 2026."
        ),
        "week": 43,
        "day": 3,
        "origin": SYNDICATED_ORIGIN,
    },
    {
        "company_id": "langchain",
        "company_name": "LangChain",
        "publisher": "LangChain Blog",
        "slug": "langsmith-evaluation-update",
        "title": "LangSmith evaluation datasets are now generally available",
        "text": (
            "We are making LangSmith evaluation datasets generally available. Teams can now run "
            "offline evaluations against saved traces and compare retrieval configurations."
        ),
        "week": 44,
        "day": 1,
        "source_type": "company",
    },
    {
        "company_id": "llamaindex",
        "company_name": "LlamaIndex",
        "publisher": "The Batch",
        "slug": "llamaindex-document-agents",
        "title": "LlamaIndex pushes document agents for enterprise retrieval",
        "text": (
            "LlamaIndex described a document-agent pattern for enterprise retrieval, combining "
            "structured indexes with agent planning over long documents."
        ),
        "week": 40,
        "day": 4,
    },
    {
        "company_id": "crewai",
        "company_name": "CrewAI",
        "publisher": "Latent Space",
        "slug": "crewai-multi-agent-orchestration",
        "title": "CrewAI on role-based multi-agent orchestration",
        "text": (
            "CrewAI discussed role-based orchestration for multi-agent systems and the operational "
            "cost of running many agents in production."
        ),
        "week": 44,
        "day": 2,
        "source_type": "public_voice",
    },
]


def build_document_records() -> list[dict[str, Any]]:
    records = []
    for plan in DOCUMENT_PLAN:
        published = datetime.fromisocalendar(2026, plan["week"], plan["day"]).replace(
            tzinfo=timezone.utc
        ) + timedelta(hours=14)
        records.append(
            news_record(
                company_id=plan["company_id"],
                company_name=plan["company_name"],
                publisher=plan["publisher"],
                slug=plan["slug"],
                title=plan["title"],
                text=plan["text"],
                published_at=published,
                source_type=plan.get("source_type", "news"),
                origin_override=plan.get("origin"),
            )
        )
    return records


def write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    print(f"wrote {len(records):4d} records -> {path.relative_to(ROOT)}")


def main() -> None:
    from collectors.records import validate_records

    github = build_github_records()
    jobs = build_job_records()
    documents = build_document_records()
    combined = github + jobs + documents

    failures = validate_records(combined)
    if failures:
        raise SystemExit(f"generated invalid fixtures: {failures[:5]}")

    write_jsonl(github, OUT / "github_records.jsonl")
    write_jsonl(jobs, OUT / "job_records.jsonl")
    write_jsonl(documents, OUT / "document_records.jsonl")
    write_jsonl(combined, OUT / "snapshot_records.jsonl")
    (OUT / "snapshot.json").write_text(
        json.dumps(
            {
                "snapshot_id": "faisal-fixture-2026-W44",
                "generated_by": "scripts/build_faisal_fixtures.py",
                "snapshot_date": "2026-11-02T00:00:00Z",
                "snapshot_week": "2026-W44",
                "synthetic": True,
                "note": (
                    "Synthetic records in the layout of Vidya's api-collectors branch. Replace with "
                    "a real records.jsonl run once PR #3 merges."
                ),
                "counts": {"github": len(github), "jobs": len(jobs), "documents": len(documents)},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote snapshot manifest -> {(OUT / 'snapshot.json').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
