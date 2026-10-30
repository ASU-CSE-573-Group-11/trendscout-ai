from __future__ import annotations

import json
import time
from typing import Any

import requests

USER_AGENT = (
    "TrendScoutAI-CSE573-Group11/0.1 "
    "(coursework; https://github.com/ASU-CSE-573-Group-11/trendscout-ai)"
)
DEFAULT_TIMEOUT = 30


class FetchError(RuntimeError):
    pass


def fetch_text(url: str, *, pause_seconds: float = 0.4) -> str:
    if pause_seconds:
        time.sleep(pause_seconds)
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise FetchError(f"failed to fetch {url}: {exc}") from exc
    return response.text


def fetch_json(url: str, *, params: dict[str, Any] | None = None, pause_seconds: float = 0.4) -> Any:
    if pause_seconds:
        time.sleep(pause_seconds)
    try:
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, json.JSONDecodeError) as exc:
        raise FetchError(f"failed to fetch JSON {url}: {exc}") from exc
