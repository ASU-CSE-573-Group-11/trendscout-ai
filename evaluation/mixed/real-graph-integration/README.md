# Real graph demo

This folder contains the reproducible real-source semantic graph demonstration.
It compares a committed offline graph with the exact payload stored in local
Neo4j, then presents the result through `demo.html`.

The demo reports observed source evidence. A public job listing is not a
completed hire, an announcement date is not automatically a financing event
date, and temporal proximity does not establish causality.

## Included files

| File | Purpose |
|---|---|
| `graph.json` | Complete storage-neutral graph payload |
| `records.ttl` | RDF/Turtle serialization of the same graph |
| `shacl-report.txt` | SHACL validation result |
| `summary.json` | Graph counts, input hashes and limitations |
| `live-neo4j-validation.json` | Payload-specific live database acceptance record |
| `demo-results.json` | Offline and live company summaries used by the page |
| `demo.html` | Static explanatory dashboard |

## 1. Open the repository

Run all setup commands from the repository root:

```bash
cd /path/to/trendscout-ai
git checkout main
git pull --ff-only
```

## 2. Create the Python environment

Python 3.9 or later is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-interface.txt
```

`requirements-interface.txt` supplies the Neo4j driver used by the live demo.

## 3. Verify the committed offline graph

This rebuilds the graph in memory from the frozen mixed-source records and
checks it against the committed JSON, Turtle and SHACL artifacts:

```bash
python -m evaluation.real_graph_integration check
```

Expected output:

```text
{"status": "ok", "mode": "check", ...}
```

Run the offline demo summary without a database:

```bash
python -m evaluation.real_graph_demo \
  --out evaluation/mixed/real-graph-integration/demo-results.json
```

## 4. Start Neo4j

The repository Docker Compose configuration exposes Neo4j Browser on port
`7474` and Bolt on port `7687`.

```bash
docker compose up -d neo4j
docker compose ps neo4j
```

Wait until the container reports a running or healthy state.

The local development defaults are:

```text
URI:      bolt://localhost:7687
Username: neo4j
Password: trendscout-dev
```

For a different environment, set variables without writing credentials into
the repository:

```bash
export NEO4J_URI='bolt://localhost:7687'
export NEO4J_USERNAME='neo4j'
export NEO4J_PASSWORD='your-local-password'
```

## 5. Load the real graph into Neo4j

The loader is idempotent: nodes are merged by stable ID and relationships are
merged by source, type and target.

```bash
python -m graph.neo4j \
  --graph-payload evaluation/mixed/real-graph-integration/graph.json
```

The result should include:

```text
"payload_node_matches": 170
"payload_edge_matches": 466
"payload_verified": true
```

Database-wide label totals can be higher because a local Neo4j database may
also contain earlier fixtures. The payload-specific match fields are the
acceptance criteria.

## 6. Run the live/offline parity demo

```bash
python -m evaluation.real_graph_demo \
  --live \
  --out evaluation/mixed/real-graph-integration/demo-results.json
```

Successful output records:

```text
"status": "offline_and_live_demo_complete"
"live_matches_offline": true
```

No password is written to `demo-results.json`.

## 7. Open the visual dashboard

Serve the folder over HTTP so the page can read `demo-results.json`:

```bash
cd evaluation/mixed/real-graph-integration
python -m http.server 8770 --bind 127.0.0.1
```

Open the following address in a browser:

```text
http://127.0.0.1:8770/demo.html
```

Keep the terminal running while viewing the page. Stop the server with
`Ctrl+C`.

## 8. Run the relevant tests

Return to the repository root and run:

```bash
cd ../../..
python -m pytest \
  tests/test_real_graph_demo.py \
  tests/test_real_graph_integration.py \
  tests/test_cypher.py \
  tests/test_rdf.py \
  tests/test_shacl.py -q
```

To run the complete project suite:

```bash
python -m pytest -q
```

## Troubleshooting

### Port 8770 is already in use

Choose another port and open the matching URL:

```bash
python -m http.server 8780 --bind 127.0.0.1
```

### Neo4j is unreachable

```bash
docker compose ps neo4j
docker compose logs --tail=100 neo4j
```

Confirm that `NEO4J_URI`, `NEO4J_USERNAME` and `NEO4J_PASSWORD` match the local
container configuration.

### The page says that demo data could not be loaded

Do not open `demo.html` directly with a `file://` URL. Start the HTTP server in
this folder and use the `http://127.0.0.1:8770/demo.html` address.

## Stop local services

Stop the dashboard with `Ctrl+C`. Stop Neo4j when it is no longer needed:

```bash
docker compose stop neo4j
```
