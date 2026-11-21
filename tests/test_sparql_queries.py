from pathlib import Path

from rdflib import Graph, Literal, RDF
from rdflib.namespace import XSD
from rdflib.plugins.sparql.parser import parseQuery

from graph.rdf import TS


ROOT = Path(__file__).resolve().parents[1]
QUERY_ROOT = ROOT / "graph" / "sparql"


def _query(name: str) -> str:
    return (QUERY_ROOT / name).read_text(encoding="utf-8")


def _add(graph: Graph, subject, rdf_type, **properties):
    graph.add((subject, RDF.type, rdf_type))
    for predicate, value in properties.items():
        graph.add((subject, TS[predicate], value))


def test_every_competency_query_is_independently_parseable():
    query_files = sorted(QUERY_ROOT.glob("*.rq"))
    assert [path.name for path in query_files] == [
        "claim_independent_origins.rq",
        "funding_to_hiring.rq",
        "repository_claim_provenance.rq",
        "startup_evidence.rq",
        "technology_skill_demand.rq",
    ]
    for path in query_files:
        parseQuery(path.read_text(encoding="utf-8"))


def test_startup_evidence_query_filters_company_and_observation_window():
    graph = Graph()
    startup = TS["startup/langchain"]
    publisher = TS["publisher/example"]
    record = TS["source-record/in-window"]
    _add(graph, startup, TS.Startup, companyId=Literal("langchain"))
    _add(graph, publisher, TS.Publisher)
    _add(
        graph,
        record,
        TS.SourceRecord,
        observedAt=Literal("2026-10-20T00:00:00Z", datatype=XSD.dateTime),
        sourceUrl=Literal("https://example.com/story", datatype=XSD.anyURI),
    )
    graph.add((record, TS.about, startup))
    graph.add((record, TS.publishedBy, publisher))

    rows = list(
        graph.query(
            _query("startup_evidence.rq"),
            initBindings={
                "companyId": Literal("langchain"),
                "observedFrom": Literal("2026-10-01T00:00:00Z", datatype=XSD.dateTime),
                "observedTo": Literal("2026-11-01T00:00:00Z", datatype=XSD.dateTime),
            },
        )
    )
    assert len(rows) == 1
    assert rows[0].record == record


def test_funding_to_hiring_query_returns_ordered_observations_without_causal_inference():
    graph = Graph()
    startup = TS["startup/example"]
    investor = TS["investor/example"]
    round_iri = TS["funding-round/example"]
    posting = TS["job-posting/example"]
    _add(graph, startup, TS.Startup, companyId=Literal("example"))
    _add(graph, investor, TS.Investor)
    _add(
        graph,
        round_iri,
        TS.FundingRound,
        eventAt=Literal("2026-10-01T00:00:00Z", datatype=XSD.dateTime),
    )
    _add(
        graph,
        posting,
        TS.JobPosting,
        observedAt=Literal("2026-10-15T00:00:00Z", datatype=XSD.dateTime),
    )
    graph.add((startup, TS.hasJobPosting, posting))
    graph.add((round_iri, TS.fundingOf, startup))
    graph.add((investor, TS.participatedIn, round_iri))

    rows = list(
        graph.query(
            _query("funding_to_hiring.rq"),
            initBindings={
                "companyId": Literal("example"),
                "fundedFrom": Literal("2026-09-01T00:00:00Z", datatype=XSD.dateTime),
                "fundedTo": Literal("2026-11-01T00:00:00Z", datatype=XSD.dateTime),
                "jobObservedFrom": Literal("2026-10-01T00:00:00Z", datatype=XSD.dateTime),
                "jobObservedTo": Literal("2026-11-01T00:00:00Z", datatype=XSD.dateTime),
            },
        )
    )
    assert [(row.investor, row.round, row.posting) for row in rows] == [
        (investor, round_iri, posting)
    ]


def test_claim_query_counts_distinct_origins_not_duplicate_records():
    graph = Graph()
    startup = TS["startup/example"]
    claim = TS["claim/example"]
    _add(graph, startup, TS.Startup, companyId=Literal("example"))
    _add(graph, claim, TS.Claim, state=Literal("corroborated"))
    for suffix, origin in (("a", "origin-1"), ("b", "origin-1"), ("c", "origin-2")):
        record = TS[f"source-record/{suffix}"]
        _add(graph, record, TS.SourceRecord, originClusterId=Literal(origin))
        graph.add((record, TS.about, startup))
        graph.add((record, TS.supports, claim))

    rows = list(
        graph.query(
            _query("claim_independent_origins.rq"),
            initBindings={
                "companyId": Literal("example"),
                "state": Literal("corroborated"),
                "minimumOrigins": Literal(2, datatype=XSD.integer),
            },
        )
    )
    assert len(rows) == 1
    assert rows[0].claim == claim
    assert int(rows[0].independentOrigins) == 2


def test_technology_skill_query_requires_both_normalized_links():
    graph = Graph()
    startup = TS["startup/example"]
    posting = TS["job-posting/example"]
    technology = TS["technology/python"]
    skill = TS["skill/retrieval"]
    _add(graph, startup, TS.Startup, companyId=Literal("example"))
    _add(graph, posting, TS.JobPosting)
    _add(graph, technology, TS.Technology)
    _add(graph, skill, TS.Skill)
    graph.add((startup, TS.hasJobPosting, posting))
    graph.add((posting, TS.usesTechnology, technology))
    graph.add((posting, TS.requiresSkill, skill))

    rows = list(
        graph.query(
            _query("technology_skill_demand.rq"),
            initBindings={"companyId": Literal("example")},
        )
    )
    assert [(row.posting, row.technology, row.skill) for row in rows] == [
        (posting, technology, skill)
    ]
