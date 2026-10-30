from collectors.records import canonicalize_url, make_record, validate_record


def test_tracking_params_are_stripped():
    assert canonicalize_url("http://www.TechCrunch.com/story/?utm_source=rss&x=1") == "https://techcrunch.com/story?x=1"


def test_record_round_trip():
    record = make_record(
        source_type="news",
        source_url="https://example.com/a",
        title="CrewAI hiring note",
        text="CrewAI posted a public engineering role.",
        publisher="Example",
        company_id="crewai",
        startup_name="CrewAI",
        published_at="2026-10-01T00:00:00Z",
        access_note="fixture",
    )
    assert validate_record(record) == []
    assert record["origin_cluster_id"]
    assert record["content_hash"]
