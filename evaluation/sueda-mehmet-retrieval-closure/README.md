# Retrieval closure

Completed by Sueda Sen and Mehmet Aksit on 23 November 2026.

This is not a Faisal Barkat Khorasi deliverable. Earlier dense runs that used `HashingEncoder` stay lexical (`semantic: false`). This directory records two separate checks:

- `semantic-answer.json`: 45 mixed records encoded with `sentence-transformers/all-MiniLM-L6-v2`. The saved dense block says `semantic: true`, dimension 384, NumPy backend.
- `neo4j-answer.json`: the same question with `graph_backend: neo4j`. Every graph row has `backend: neo4j`. The database held the five-company graph, 170 nodes and 466 edges.

The Neo4j answer state is `insufficient`. That is the recorded result, not a pass.

Rerun from the repository root after `docker compose up -d neo4j` and `pip install -r requirements-interface.txt`:

```bash
python -m graph.neo4j --graph-payload evaluation/mixed/real-graph-integration/graph.json
PYTHONPATH=. python evaluation/sueda-mehmet-retrieval-closure/run.py
```
