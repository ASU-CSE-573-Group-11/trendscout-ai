"""Collect the proposal gaps from public pages. Nothing here is inferred.

Completed by Sueda Sen and Mehmet Aksit. A page is kept only when the HTTP
fetch succeeds. Amounts are not copied into a structured round unless the
sentence is in the fetched text. Greenhouse and Lever are queried only for
boards already in the cohort audit. Other companies stay on the ATS the audit
named.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from collectors.http import FetchError, fetch_json, fetch_text
from collectors.news import collect_news
from collectors.records import make_record, utc_now, validate_records
from collectors.rss import iter_feed
from collectors.voices import collect_voices
from signals.topics import TopicConfig, fit_topics

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
COHORT = json.loads((ROOT / "data/registry/cohort.json").read_text())
AUDIT = json.loads((ROOT / "evaluation/cohort-source-audit/board-audit.json").read_text())
SOURCES = json.loads((ROOT / "data/registry/named_sources.json").read_text())
COMPANIES = {company["company_id"]: company for company in COHORT["companies"]}

# Primary pages found by public search, then fetched. A failed fetch is recorded
# and does not become a funding event.
FUNDING_PAGES = [
    ("langchain", "https://langchain.com/blog/series-c"),
    ("llamaindex", "https://llamaindex.ai/blog/announcing-our-series-a-and-llamacloud-general-availability"),
    ("browserbase", "https://www.browserbase.com/blog/series-b-and-beyond"),
    ("e2b", "https://e2b.dev/resources/series-a"),
    ("modal", "https://modal.com/blog/announcing-our-series-b"),
    ("crewai", "https://www.insightpartners.com/ideas/crewai-launches-multi-agentic-platform-to-deliver-on-the-promise-of-generative-ai-for-enterprise/"),
    ("langfuse", "https://langfuse.com/blog/announcing-our-seed-round"),
    ("pinecone", "https://www.pinecone.io/newsroom/pinecone-raises-usd100m-in-series-b-funding-to-provide-long-term-memory-for-ai/"),
    ("weaviate", "https://www.prnewswire.com/news-releases/weaviate-raises-50-million-series-b-funding-to-meet-soaring-demand-for-ai-native-vector-database-technology-301803296.html"),
    ("chroma", "https://www.trychroma.com/blog/seed"),
    ("arize", "https://arize.com/blog/arize-ai-raises-70m-series-c/"),
    ("composio", "https://composio.dev/blog/series-a"),
    ("letta", "https://www.prnewswire.com/news-releases/berkeley-ai-research-lab-spinout-letta-raises-10m-seed-financing-led-by-felicis-to-build-ai-with-memory-302257004.html"),
    ("replicate", "https://replicate.com/blog/series-b"),
    ("sourcegraph", "https://sourcegraph.com/blog/announcing-sourcegraphs-series-d-round"),
    ("continue", "https://techcrunch.com/2025/02/26/continue-wants-to-help-developers-create-and-share-custom-ai-coding-assistants/"),
    ("deepset", "https://www.deepset.ai/news/funding-announcement-balderton-capital"),
    ("wandb", "https://wandb.ai/site/press-release/weights-biases-raises-50-million-round-led-by-daniel-gross-and-nat-friedman-announces-wb-prompts/"),
    ("browserbase", "https://www.browserbase.com/blog/series-a"),
    ("pinecone", "https://www.pinecone.io/blog/pinecone-series-a/"),
]

FUNDING_WORD = re.compile(r"\b(raised|funding|series|seed round|financing)\b", re.I)


def _company_name(company_id: str) -> str:
    return COMPANIES[company_id]["name"]


def _clip(text: str, limit: int = 4000) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def collect_boards() -> tuple[list[dict], list[dict]]:
    records: list[dict] = []
    coverage: list[dict] = []
    for company in AUDIT["companies"]:
        company_id = company["company_id"]
        boards = company.get("boards") or []
        if not boards:
            coverage.append({"company_id": company_id, "status": "no_board_in_audit", "listings": 0})
            continue
        for board in boards:
            url = board.get("api_url")
            if not url:
                coverage.append(
                    {
                        "company_id": company_id,
                        "type": board.get("type"),
                        "status": "no_api_url",
                        "listings": 0,
                    }
                )
                continue
            try:
                payload = fetch_json(url, pause_seconds=0.2)
            except FetchError as exc:
                coverage.append(
                    {
                        "company_id": company_id,
                        "type": board.get("type"),
                        "slug": board.get("slug"),
                        "status": "fetch_failed",
                        "detail": str(exc),
                        "listings": 0,
                    }
                )
                continue
            jobs = _jobs(board.get("type"), payload)
            for job in jobs:
                records.append(
                    make_record(
                        source_type="job",
                        source_url=job["url"],
                        title=job["title"],
                        text=job["text"],
                        publisher=board.get("type"),
                        company_id=company_id,
                        startup_name=_company_name(company_id),
                        event_type="job_listing",
                        published_at=job.get("published_at"),
                        access_note="Live public board API. A listing is not a hire.",
                        metadata={
                            "ats": board.get("type"),
                            "slug": board.get("slug"),
                            "external_id": job.get("external_id"),
                        },
                    )
                )
            coverage.append(
                {
                    "company_id": company_id,
                    "type": board.get("type"),
                    "slug": board.get("slug"),
                    "status": "ok",
                    "listings": len(jobs),
                }
            )
    return records, coverage


def _jobs(kind: str | None, payload: object) -> list[dict]:
    if kind == "greenhouse" and isinstance(payload, dict):
        found = []
        for job in payload.get("jobs") or []:
            found.append(
                {
                    "url": job.get("absolute_url") or "",
                    "title": job.get("title") or "Untitled listing",
                    "text": job.get("title") or "",
                    "published_at": job.get("updated_at"),
                    "external_id": str(job.get("id") or ""),
                }
            )
        return [job for job in found if job["url"]]
    if kind == "ashby" and isinstance(payload, dict):
        found = []
        for job in payload.get("jobs") or []:
            url = job.get("jobUrl") or job.get("applyUrl") or ""
            found.append(
                {
                    "url": url,
                    "title": job.get("title") or "Untitled listing",
                    "text": _clip(job.get("descriptionPlain") or job.get("title") or ""),
                    "published_at": job.get("publishedDate"),
                    "external_id": str(job.get("id") or ""),
                }
            )
        return [job for job in found if job["url"]]
    return []


def collect_funding() -> tuple[list[dict], list[dict]]:
    records: list[dict] = []
    coverage: list[dict] = []
    for company_id, url in FUNDING_PAGES:
        try:
            html = fetch_text(url, pause_seconds=0.2)
        except FetchError as exc:
            coverage.append({"company_id": company_id, "url": url, "status": "fetch_failed", "detail": str(exc)})
            continue
        text = _clip(re.sub(r"(?is)<script.*?>.*?</script>|<style.*?>.*?</style>|<[^>]+>", " ", html), 5000)
        if not FUNDING_WORD.search(text):
            coverage.append({"company_id": company_id, "url": url, "status": "fetched_but_no_funding_sentence"})
            continue
        title = _title(html) or url
        records.append(
            make_record(
                source_type="funding",
                source_url=url,
                title=title,
                text=text,
                publisher=url.split("/")[2],
                company_id=company_id,
                startup_name=_company_name(company_id),
                event_type="funding_announcement",
                access_note=(
                    "Fetched public page. The announcement date is not a financing close date. "
                    "No amount is recorded unless this text states it."
                ),
            )
        )
        coverage.append({"company_id": company_id, "url": url, "status": "kept", "chars": len(text)})
    return records, coverage


def _title(html: str) -> str | None:
    match = re.search(r"(?is)<title>(.*?)</title>", html)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()[:180]


def collect_company_posts() -> tuple[list[dict], list[dict]]:
    """Keep public posts from each company's own feed. Cap so the snapshot stays reviewable."""
    records: list[dict] = []
    coverage: list[dict] = []
    for company_id, company in COMPANIES.items():
        domain = company.get("domain")
        if not domain:
            continue
        candidates = [
            f"https://{domain}/feed",
            f"https://{domain}/blog/feed",
            f"https://{domain}/rss.xml",
            f"https://{domain}/feed.xml",
            f"https://blog.{domain}/feed",
        ]
        kept_url = None
        entries: list[dict] = []
        errors: list[str] = []
        for url in candidates:
            try:
                entries = list(iter_feed(url))
            except FetchError as exc:
                errors.append(str(exc))
                continue
            if entries:
                kept_url = url
                break
        chosen = entries[:40]
        for entry in chosen:
            if not entry.get("url"):
                continue
            records.append(
                make_record(
                    source_type="company",
                    source_url=entry["url"],
                    title=entry.get("title"),
                    text=entry.get("summary") or entry.get("title"),
                    publisher=domain,
                    company_id=company_id,
                    startup_name=company["name"],
                    event_type="company_post",
                    published_at=entry.get("published_at"),
                    access_note="Public company feed item. Retained text is the feed summary, not a full article rewrite.",
                    metadata={"feed_url": kept_url},
                )
            )
        coverage.append(
            {
                "company_id": company_id,
                "feed_url": kept_url,
                "entries_seen": len(entries),
                "entries_kept": len(chosen) if kept_url else 0,
                "status": "ok" if kept_url else "no_feed",
                "attempts": errors[:2],
            }
        )
    return records, coverage


def collect_reference() -> tuple[list[dict], list[dict]]:
    records: list[dict] = []
    coverage: list[dict] = []
    for company_id, company in COMPANIES.items():
        name = company["name"]
        domain = company.get("domain")
        wiki = _wikidata(name, domain)
        sec = _sec(name)
        coverage.append({"company_id": company_id, "wikidata": wiki["status"], "sec": sec["status"]})
        records.append(
            make_record(
                source_type="reference",
                source_url=wiki["url"],
                title=f"Wikidata search for {name}",
                text=wiki["text"],
                publisher="Wikidata",
                company_id=company_id,
                startup_name=name,
                event_type="identifier_lookup",
                access_note="Public Wikidata search. A label hit is not identity confirmation by itself.",
                metadata=wiki["metadata"],
            )
        )
        records.append(
            make_record(
                source_type="reference",
                source_url=sec["url"],
                title=f"SEC EDGAR search for {name}",
                text=sec["text"],
                publisher="SEC EDGAR",
                company_id=company_id,
                startup_name=name,
                event_type="filing_lookup",
                access_note="Public EDGAR search. Zero hits means no matching filing was returned, not that a filing cannot exist.",
                metadata=sec["metadata"],
            )
        )
    return records, coverage


def _wikidata(name: str, domain: str | None) -> dict:
    url = "https://www.wikidata.org/w/api.php"
    try:
        payload = fetch_json(
            url,
            params={"action": "wbsearchentities", "search": name, "language": "en", "format": "json", "limit": 5},
            pause_seconds=0.2,
        )
    except FetchError as exc:
        return {
            "status": "fetch_failed",
            "url": url,
            "text": str(exc),
            "metadata": {"domain": domain},
        }
    hits = payload.get("search") or []
    lines = [f"{hit.get('id')} {hit.get('label')}: {hit.get('description')}" for hit in hits]
    return {
        "status": "hits" if hits else "no_hit",
        "url": f"{url}?action=wbsearchentities&search={name}&language=en&format=json",
        "text": _clip("\n".join(lines) or f"No Wikidata label hit for {name}."),
        "metadata": {"hit_count": len(hits), "ids": [hit.get("id") for hit in hits], "domain": domain},
    }


def _sec(name: str) -> dict:
    url = "https://efts.sec.gov/LATEST/search-index"
    try:
        payload = fetch_json(
            url,
            params={"q": f'"{name}"', "dateRange": "custom", "startdt": "2020-01-01", "enddt": "2026-11-23", "forms": "10-K,8-K,S-1"},
            pause_seconds=0.3,
        )
    except FetchError as exc:
        return {"status": "fetch_failed", "url": url, "text": str(exc), "metadata": {}}
    total = ((payload.get("hits") or {}).get("total") or {}).get("value", 0)
    return {
        "status": "hits" if total else "no_hit",
        "url": f"{url}?q=%22{name}%22&forms=10-K,8-K,S-1",
        "text": f"EDGAR full-text search for {name} returned {total} hits in forms 10-K, 8-K, and S-1 from 2020-01-01 through 2026-11-23.",
        "metadata": {"hit_count": total},
    }


def run_ner(records: list[dict]) -> dict:
    sample = [record for record in records if record["source_type"] in {"funding", "news"}][:40]
    try:
        from transformers import pipeline
    except ImportError as exc:
        return {"status": "unavailable", "detail": str(exc)}
    try:
        ner = pipeline("ner", model="dslim/bert-base-NER", aggregation_strategy="simple")
    except Exception as exc:  # model download or runtime failure
        return {"status": "unavailable", "detail": str(exc)}
    rows = []
    for record in sample:
        text = (record.get("text") or "")[:400]
        if not text:
            continue
        spans = ner(text)
        rows.append(
            {
                "record_id": record["record_id"],
                "company_id": record.get("company_id"),
                "source_type": record["source_type"],
                "entities": [
                    {"text": span.get("word"), "label": span.get("entity_group"), "score": round(float(span.get("score") or 0), 3)}
                    for span in spans
                ],
            }
        )
    return {
        "status": "ran",
        "model": "dslim/bert-base-NER",
        "documents": len(rows),
        "caveat": "Model spans are not human labels and were not adjudicated.",
        "rows": rows,
    }


def main() -> None:
    OUT.mkdir(exist_ok=True)
    jobs, job_coverage = collect_boards()
    funding, funding_coverage = collect_funding()
    news, news_coverage = collect_news(SOURCES, COHORT, live=True)
    posts, post_coverage = collect_company_posts()
    voices, voice_coverage = collect_voices(SOURCES, COHORT, live=True)
    references, reference_coverage = collect_reference()
    records = jobs + funding + news + posts + voices + references
    failures = validate_records(records)
    if failures:
        raise SystemExit(f"invalid records: {failures[:5]}")
    (OUT / "records.jsonl").write_text("".join(json.dumps(record) + "\n" for record in records))
    topic_input = [record for record in records if record["source_type"] in {"news", "funding", "public_voice", "company"}]
    model = fit_topics(topic_input, config=TopicConfig(iterations=80, burn_in=20))
    ner = run_ner(records)
    prior_jobs = sum(1 for _ in (ROOT / "evaluation/cohort-job-history/records.jsonl").open())
    summary = {
        "completed_by": ["Sueda Sen", "Mehmet Aksit"],
        "observed_at": utc_now(),
        "method": "Public HTTP fetch of audited board APIs, named RSS feeds, a fixed funding-page list, Wikidata search, and EDGAR search. Failed fetches are coverage rows, not records.",
        "counts": {
            "job_listings_live": len(jobs),
            "funding_pages_kept": len(funding),
            "news": len(news),
            "company_posts": len(posts),
            "public_voice": len(voices),
            "reference": len(references),
            "records": len(records),
        },
        "proposal_targets": {
            "funding_events": "20-40",
            "job_observations": "150-300",
            "news_documents": "120-180",
        },
        "already_in_repository_before_this_run": {
            "cohort_job_history_records": prior_jobs,
            "job_cap_that_produced_147_graph_nodes": "max 25 unique listings per company",
            "funding_rounds_in_frozen_graph": 3,
        },
        "greenhouse_or_lever": {
            "greenhouse_boards_in_audit": ["browserbaseinc", "sourcegraph91"],
            "lever_boards_in_audit": [],
            "note": "No Lever slug is queried, because the audit has none. Ashby boards are collected under their own type.",
        },
        "lda": model.describe(),
        "transformer_ner": {key: value for key, value in ner.items() if key != "rows"},
        "ner_entity_count": sum(len(row["entities"]) for row in ner.get("rows", [])),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (OUT / "coverage.json").write_text(
        json.dumps(
            {
                "jobs": job_coverage,
                "funding": funding_coverage,
                "news": news_coverage,
                "company_posts": post_coverage,
                "voices": voice_coverage,
                "reference": reference_coverage,
            },
            indent=2,
        )
        + "\n"
    )
    (OUT / "ner.json").write_text(json.dumps(ner, indent=2) + "\n")
    print(json.dumps(summary["counts"], indent=2))
    print("lda_documents", summary["lda"]["documents"], "underpowered", summary["lda"]["underpowered"])
    print("ner", summary["transformer_ner"]["status"], summary["ner_entity_count"])


if __name__ == "__main__":
    main()
