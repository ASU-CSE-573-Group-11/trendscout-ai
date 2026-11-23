"""One semantic dense answer and one live Neo4j answer.

Completed by Sueda Sen and Mehmet Aksit. This is not a Faisal Barkat Khorasi
deliverable. HashingEncoder runs stay lexical; this script records a separate
sentence-transformer index and a graph bundle whose backend is neo4j.
"""

from __future__ import annotations

import json
from pathlib import Path

from interface.agent import AgentConfig, TrendScoutAgent
from retrieval.graph_access import Neo4jBackend
from retrieval.handoff import load_records_jsonl

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RECORDS = ROOT / "evaluation" / "mixed" / "records.jsonl"
QUESTION = (
    "Which LangChain records mention hiring or funding in the study window?"
)


def _jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "keys") and hasattr(value, "__getitem__") and not isinstance(value, (str, bytes)):
        return {str(key): _jsonable(value[key]) for key in value.keys()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def main() -> None:
    records = load_records_jsonl(RECORDS)
    cohort = json.loads((ROOT / "data" / "registry" / "cohort.json").read_text())
    semantic = TrendScoutAgent(
        records,
        config=AgentConfig(
            mode="dense",
            encoder="sentence-transformers/all-MiniLM-L6-v2",
            use_graph=False,
        ),
        cohort=cohort,
        snapshot_id=f"mixed@{len(records)}",
    )
    semantic_answer = semantic.answer(QUESTION, question_id="sueda-mehmet-semantic-1")
    semantic_payload = semantic_answer.as_dict()
    (OUT / "semantic-answer.json").write_text(
        json.dumps(_jsonable(semantic_payload), indent=2, ensure_ascii=False) + "\n"
    )

    graph = Neo4jBackend("bolt://localhost:7687", "neo4j", "trendscout-dev")
    try:
        live = TrendScoutAgent(
            records,
            config=AgentConfig(mode="graph_only", encoder="hashing:256", use_graph=True),
            cohort=cohort,
            graph=graph,
            snapshot_id=f"mixed-plus-neo4j@{len(records)}",
        )
        live_answer = live.answer(QUESTION, question_id="sueda-mehmet-neo4j-1")
        live_payload = live_answer.as_dict()
        graph_describe = live.describe().get("graph")
    finally:
        graph.close()
    (OUT / "neo4j-answer.json").write_text(
        json.dumps(_jsonable(live_payload), indent=2, ensure_ascii=False) + "\n"
    )

    dense = semantic_payload.get("snapshot", {}).get("dense", {})
    summary = {
        "completed_by": ["Sueda Sen", "Mehmet Aksit"],
        "not_completed_by": ["Faisal Barkat Khorasi", "Vidya Sagar Dudekula"],
        "question": QUESTION,
        "semantic_encoder": dense.get("encoder"),
        "semantic": dense.get("semantic"),
        "semantic_dim": dense.get("dim"),
        "semantic_backend": dense.get("backend"),
        "semantic_passages": dense.get("passages"),
        "semantic_overall_state": semantic_payload.get("overall_state"),
        "neo4j_graph_backend": live_payload.get("snapshot", {}).get("graph_backend"),
        "neo4j_result_backends": sorted(
            {row.get("backend") for row in live_payload.get("graph", [])}
        ),
        "neo4j_result_count": len(live_payload.get("graph", [])),
        "neo4j_overall_state": live_payload.get("overall_state"),
        "neo4j_graph_describe": graph_describe,
        "note": (
            "HashingEncoder runs remain lexical. This directory records one "
            "sentence-transformer index (semantic true) and one answer whose graph "
            "rows were returned by Neo4jBackend."
        ),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
