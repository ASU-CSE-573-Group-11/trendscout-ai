from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from pyshacl import validate
from rdflib import Graph

from graph.rdf import graph_to_rdf

ROOT = Path(__file__).resolve().parents[1]
SHAPES_PATH = ROOT / "ontology" / "shapes.ttl"


def load_shapes(path: Path | None = None) -> Graph:
    shapes = Graph()
    shapes.parse(path or SHAPES_PATH, format="turtle")
    return shapes


def validate_records(
    records: Iterable[dict[str, Any]],
    *,
    shapes_path: Path | None = None,
) -> tuple[bool, Graph, str]:
    """Validate record-derived RDF against the repository SHACL shapes."""
    return validate_graph(graph_to_rdf(records), shapes_path=shapes_path)


def validate_graph(
    data_graph: Graph,
    *,
    shapes_path: Path | None = None,
) -> tuple[bool, Graph, str]:
    """Validate an RDF graph against the repository SHACL shapes."""
    conforms, report_graph, report_text = validate(
        data_graph,
        shacl_graph=load_shapes(shapes_path),
        inference="rdfs",
        abort_on_first=False,
        meta_shacl=True,
        advanced=False,
    )
    return bool(conforms), report_graph, report_text
