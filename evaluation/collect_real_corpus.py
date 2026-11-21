"""Freeze 45 real release documents from three repositories in the frozen cohort.

Run once per new round; never overwrites an existing snapshot. Release bodies
are source documents, not evidence of hiring, funding, or GitHub activity growth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests
from collectors.records import make_record, utc_now

REPOSITORIES = {
    "langchain": "langchain-ai/langchain",
    "llamaindex": "run-llama/llama_index",
    "crewai": "crewAIInc/crewAI",
}


def collect(out: Path) -> None:
    if out.exists():
        raise ValueError(f"refusing to overwrite frozen round: {out}")
    observed = utc_now()
    records, sources = [], []
    raw = {}
    for company, repo in REPOSITORIES.items():
        url = f"https://api.github.com/repos/{repo}/releases?per_page=100"
        response = requests.get(url, headers={"Accept": "application/vnd.github+json",
                                              "User-Agent": "TrendScout-evaluation/1.0"}, timeout=40)
        response.raise_for_status()
        releases = response.json()
        selected = [r for r in releases if not r.get("draft") and not r.get("prerelease")
                    and len((r.get("body") or "").strip()) >= 200][:15]
        if len(selected) != 15:
            raise ValueError(f"{repo}: fewer than 15 substantial published releases")
        name = company + "-releases.json"
        raw[name] = response.content
        sources.append({"api_url": url, "response_url": response.url, "file": "sources/" + name,
                        "sha256": hashlib.sha256(response.content).hexdigest(),
                        "observed_at": observed, "selected_release_ids": [r["id"] for r in selected]})
        for release in selected:
            records.append(make_record(
                source_type="company", source_url=release["html_url"],
                title=release["name"] or release["tag_name"], text=release["body"],
                publisher=repo.split('/')[0], company_id=company, observed_at=observed,
                published_at=release["published_at"], event_at=release["published_at"],
                event_type="software_release", collector_version="real-release-corpus/1.0",
                access_note="Public GitHub release body; first-party release evidence only.",
                metadata={"repository": repo, "release_id": release["id"], "tag": release["tag_name"],
                          "event_at_basis": "GitHub release publication timestamp", "synthetic": False}))
    out.mkdir(parents=True)
    (out / "sources").mkdir()
    for name, body in raw.items():
        (out / "sources" / name).write_bytes(body)
    snapshot = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records)
    (out / "records.jsonl").write_text(snapshot, encoding="utf-8")
    manifest = {"status": "frozen_real_sources_pending_human_review", "synthetic_fixture": False,
                "document_count": len(records), "observed_at": observed,
                "snapshot_sha256": hashlib.sha256(snapshot.encode()).hexdigest(), "sources": sources,
                "selection": "15 latest non-prerelease releases with body >=200 characters per repository",
                "study_revision": "Separate release-document evaluation round; original cohort and 28 questions unchanged.",
                "limitations": ["Three cohort companies; release documents only.",
                                "Cannot establish funding, hiring, trend growth, or independent corroboration.",
                                "Human inclusion review and relevance judgments remain required."]}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({"documents": len(records), "snapshot_sha256": manifest["snapshot_sha256"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "evaluation/real")
    args = parser.parse_args()
    collect(args.out)
