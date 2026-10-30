from __future__ import annotations

import os
from typing import Any

from collectors.cohort import included_companies
from collectors.http import FetchError, fetch_json
from collectors.records import make_record

YOUTUBE_SEARCH = "https://www.googleapis.com/youtube/v3/search"


def collect_youtube(
    cohort: dict[str, Any],
    *,
    api_key: str | None = None,
    max_results: int = 5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    key = api_key or os.environ.get("YOUTUBE_API_KEY")
    records: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    if not key:
        coverage.append(
            {
                "source_id": "youtube_data_api_v3",
                "status": "skipped",
                "detail": "YOUTUBE_API_KEY is not set. Public video metadata was not collected.",
            }
        )
        return records, coverage

    for company in included_companies(cohort):
        query = company.get("youtube_query") or company["name"]
        source_id = f"youtube:{company['company_id']}"
        try:
            payload = fetch_json(
                YOUTUBE_SEARCH,
                params={
                    "part": "snippet",
                    "q": query,
                    "type": "video",
                    "maxResults": max_results,
                    "key": key,
                },
            )
        except FetchError as exc:
            coverage.append({"source_id": source_id, "status": "unavailable", "detail": str(exc)})
            continue

        items = payload.get("items") or []
        kept = 0
        for item in items:
            video_id = (item.get("id") or {}).get("videoId")
            snippet = item.get("snippet") or {}
            if not video_id:
                continue
            url = f"https://www.youtube.com/watch?v={video_id}"
            title = snippet.get("title")
            description = snippet.get("description")
            records.append(
                make_record(
                    source_type="public_voice",
                    source_url=url,
                    title=title,
                    text=description,
                    publisher=snippet.get("channelTitle"),
                    company_id=company["company_id"],
                    startup_name=company["name"],
                    event_type="public_video",
                    published_at=snippet.get("publishedAt"),
                    access_note=(
                        "YouTube Data API v3 public video metadata only. "
                        "No private viewer, watch, or identity data is stored."
                    ),
                    metadata={
                        "video_id": video_id,
                        "channel_id": snippet.get("channelId"),
                        "channel_title": snippet.get("channelTitle"),
                        "query": query,
                    },
                )
            )
            kept += 1
        coverage.append(
            {
                "source_id": source_id,
                "status": "ok",
                "entries_seen": len(items),
                "entries_kept": kept,
            }
        )
    return records, coverage
