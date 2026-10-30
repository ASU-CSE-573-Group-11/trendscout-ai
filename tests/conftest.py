from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def feed_bodies() -> dict[str, str]:
    return {
        "techcrunch_ai": (FIXTURES / "techcrunch.xml").read_text(encoding="utf-8"),
        "venturebeat_ai": (FIXTURES / "venturebeat.xml").read_text(encoding="utf-8"),
        "the_batch": "<rss version='2.0'><channel><title>The Batch</title></channel></rss>",
        "latent_space": "<rss version='2.0'><channel><title>Latent Space</title></channel></rss>",
        "simon_willison": (FIXTURES / "simon.xml").read_text(encoding="utf-8"),
    }


@pytest.fixture
def company_feed_bodies() -> dict[str, str]:
    body = (FIXTURES / "langchain-blog.xml").read_text(encoding="utf-8")
    return {"langchain": body}
