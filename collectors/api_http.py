"""API client with timeouts and rate-limit handling."""

from __future__ import annotations

import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests

from .common import CollectorError


class HttpClient:
    HOSTS = {"boards-api.greenhouse.io", "api.lever.co", "api.eu.lever.co", "api.github.com"}

    def __init__(self, *, token=None, session=None, timeout=30, attempts=3,
                 max_wait=60, sleep=time.sleep, clock=time.time):
        self.token = token
        self.session = session or requests.Session()
        self.timeout = timeout
        self.attempts = attempts
        self.max_wait = max_wait
        self.sleep = sleep
        self.clock = clock
        if attempts < 1 or timeout <= 0 or max_wait < 0:
            raise ValueError("Invalid HTTP retry configuration")

    def _delay(self, response, attempt):
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return max(0, float(retry_after))
            except ValueError:
                try:
                    dt = parsedate_to_datetime(retry_after)
                    return max(0, dt.replace(tzinfo=dt.tzinfo or timezone.utc).timestamp() - self.clock())
                except (ValueError, TypeError, OverflowError):
                    pass
        if response.headers.get("X-RateLimit-Remaining") == "0":
            try:
                return max(0, float(response.headers["X-RateLimit-Reset"]) - self.clock()) + 1
            except (KeyError, ValueError):
                pass
        # GitHub requires at least a minute for secondary limits without a reset.
        if response.status_code in {403, 429}:
            return 60
        return 2 ** attempt

    def get(self, url, *, params=None):
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.hostname not in self.HOSTS
                or parsed.username or parsed.password or parsed.port not in {None, 443}):
            raise CollectorError("Refusing an API URL outside the public-source allowlist")
        headers = {"Accept": "application/json", "User-Agent": "TrendScout-AI-coursework/0.1"}
        if parsed.hostname == "api.github.com":
            headers.update(Accept="application/vnd.github+json", **{"X-GitHub-Api-Version": "2022-11-28"})
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
        for attempt in range(self.attempts):
            try:
                response = self.session.get(url, params=params, headers=headers,
                                            timeout=self.timeout, allow_redirects=False)
            except requests.RequestException:
                if attempt + 1 == self.attempts:
                    raise CollectorError("API connection failed after bounded retries") from None
                self.sleep(min(2 ** attempt, self.max_wait))
                continue
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError:
                    raise CollectorError("API returned invalid JSON") from None
            retryable = response.status_code in {403, 429, 500, 502, 503, 504}
            if not retryable or attempt + 1 == self.attempts:
                raise CollectorError(f"API returned HTTP {response.status_code}; collection incomplete")
            delay = self._delay(response, attempt)
            if delay > self.max_wait:
                raise CollectorError(f"API rate limit requires waiting {delay:.0f}s; retry later")
            self.sleep(delay)
        raise CollectorError("API request failed")
