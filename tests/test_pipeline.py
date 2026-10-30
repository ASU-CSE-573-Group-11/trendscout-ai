from collectors.cohort import included_companies, load_cohort
from collectors.origin import independent_origin_count
from collectors.pipeline import run_sueda_collection
from collectors.records import validate_records
from retrieval.bm25 import BM25Index
from retrieval.handoff import graph_evidence, load_records_jsonl, search_snapshot


def test_cohort_is_frozen_and_balanced():
    cohort = load_cohort()
    companies = included_companies(cohort)
    assert cohort["frozen_at"] == "2026-10-30"
    assert 15 <= len(companies) <= 20
    categories = {company["category"] for company in companies}
    assert categories == {"agent_infrastructure", "developer_tools"}
    assert all(company.get("github_repos") or company.get("greenhouse_board") or company.get("lever_site") for company in companies)


def test_offline_pipeline_validates_and_clusters(feed_bodies, company_feed_bodies):
    result = run_sueda_collection(
        live=False,
        feed_bodies=feed_bodies,
        company_feed_bodies=company_feed_bodies,
    )
    assert result["rejected"] == []
    assert validate_records(result["accepted"]) == []
    assert result["stats"]["accepted_count"] >= 3

    news = [record for record in result["accepted"] if record["source_type"] == "news"]
    assert len(news) == 2
    assert independent_origin_count(news) == 1
    assert news[0]["origin_cluster_id"] == news[1]["origin_cluster_id"]

    voices = [record for record in result["accepted"] if record["source_type"] == "public_voice"]
    assert len(voices) == 1
    assert voices[0]["company_id"] == "llamaindex"
    assert voices[0]["event_type"] == "interview"

    company = [record for record in result["accepted"] if record["source_type"] == "company"]
    assert company and company[0]["company_id"] == "langchain"

    yc = [record for record in result["accepted"] if record["source_type"] == "reference"]
    assert len(yc) == len([item for item in load_cohort()["companies"] if item.get("yc_url")])


def test_repeated_collection_does_not_inflate_counts(feed_bodies, company_feed_bodies):
    first = run_sueda_collection(live=False, feed_bodies=feed_bodies, company_feed_bodies=company_feed_bodies)
    second = run_sueda_collection(live=False, feed_bodies=feed_bodies, company_feed_bodies=company_feed_bodies)
    assert {record["record_id"] for record in first["accepted"]} == {
        record["record_id"] for record in second["accepted"]
    }
    assert first["stats"]["independent_origins"] == second["stats"]["independent_origins"]


def test_bm25_ranks_langchain_query(feed_bodies, company_feed_bodies):
    result = run_sueda_collection(live=False, feed_bodies=feed_bodies, company_feed_bodies=company_feed_bodies)
    hits = BM25Index.from_records(result["accepted"]).search("LangSmith Engine testing", k=3)
    assert hits
    assert "langsmith" in (hits[0]["record"]["title"] or "").lower() + (hits[0]["record"]["text"] or "").lower()


def test_snapshot_handoff_preserves_records_and_graph_provenance(
    feed_bodies, company_feed_bodies, tmp_path
):
    result = run_sueda_collection(
        live=False,
        feed_bodies=feed_bodies,
        company_feed_bodies=company_feed_bodies,
    )
    from collectors.pipeline import write_collection_bundle

    write_collection_bundle(result, tmp_path / "bundle")
    loaded = load_records_jsonl(tmp_path / "bundle" / "records.jsonl")
    assert {record["record_id"] for record in loaded} == {
        record["record_id"] for record in result["accepted"]
    }
    evidence = graph_evidence(loaded[0])
    assert evidence["record_id"] == loaded[0]["record_id"]
    assert evidence["origin_cluster_id"] == loaded[0]["origin_cluster_id"]
    assert evidence["observed_at"]


def test_snapshot_search_can_limit_results_to_independent_origins(
    feed_bodies, company_feed_bodies
):
    result = run_sueda_collection(
        live=False,
        feed_bodies=feed_bodies,
        company_feed_bodies=company_feed_bodies,
    )
    hits = search_snapshot(result["accepted"], "LangSmith Engine testing", k=5)
    assert len({hit["origin_cluster_id"] for hit in hits}) == len(hits)
