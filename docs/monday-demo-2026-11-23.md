# Group 11 demo — Monday 23 November 2026

TrendScout AI, Project 5. Class demo is about 12 minutes on Zoom.
The deck must be about 10 slides. One person uploads it before or on 23 November.

Submission name:

`Group11-Project5-FA26-Group-DEMO-Presentation.pdf`

GitHub link, required on the last slide:

https://github.com/ASU-CSE-573-Group-11/trendscout-ai

The October 28 file `TrendScout_AI_Group11.pptx` is a progress deck.
It does not yet match the demo rubric below. Do not present that file unchanged.

## What the demo grade asks for

Weight: 15% of the course grade. Live demo or screenshots are both allowed.

| Required topic | Slides | Points | What we have now | What Monday still needs |
|---|---|---|---|---|
| Cover: group number, title, members | 1 | — | Slide 1 exists, dated 28 October, labeled "progress" | Retitle it as the 23 November demo |
| Problem definition | 1 | 1 | Slide 2 is usable | Keep it |
| System architecture and algorithms | 1–2 | 2 | Slides 7–11 describe the design | Add what is actually running: evidence check before the language model, hybrid retrieval, Neo4j graph |
| Datasets: description, size, preprocessing | 1 | 1 | Slides 5–6 describe the plan | Replace with the frozen sizes below |
| Evaluations: metrics, experiments, preliminary findings | 1–2 | 5 | Slide 12 is still a plan | This is the main gap. Put measured results on the slide |
| UI or visualization | 1–2 | 5 | No screenshot of `demo.html` | Screenshot the coverage charts. This is the other main gap |
| Project plan, deadlines, division of work | 1 | 1 | Slide 13 says the prototype does not exist yet | Replace that sentence. State who finished what and what is still open |
| GitHub link | last slide | — | Link is buried on slide 13 | Make it the last slide |

Final report is a different assignment. It is due 9 December, 5–10 pages, IEEE format, 20% of the grade. Do not try to finish that report inside this demo.

## Numbers to put on the dataset and evaluation slides

- Frozen cohort: 18 companies. Inclusion and exclusion reasons are in `data/registry/cohort.json`.
- Independent annotation: Cohen's kappa 1.0 for entities and relations, release round and mixed round.
- Pilot: 30 of 30 responses. Five participants, six tasks each.
- Hiring: 15 of 18 companies have a paired official job-list population. CrewAI, Replicate, and Weights & Biases do not.
- Five-company demo graph: 170 nodes, 466 relationships. Offline summary matches live Neo4j.
- Eighteen-company graph: 866 nodes, 2,308 edges. SHACL passes. Offline summary matches live Neo4j.
- A job node is a public listing, not a completed hire.
- Scored dense runs use hashing, not a sentence-transformer encoder.
- Primary temporal-question accuracy is not measured yet. Say that plainly.

## Reviewer comments and where they belong

These comments are already answered in the October deck or in the repo. Keep one short slide if there is time. They are not a substitute for the findings slide.

- Evidence ledger stays separate from the language model, so the model does not decide the evidence state. The reviewer called this separation useful. A four-quadrant SWOT grid is optional. It is not on the demo rubric. Use it in the December report if we want it.
- EWMA: `s_t = 0.4 x_t + 0.6 s_{t-1}`. Rolling z-score uses the previous eight weeks and excludes week t. A candidate alert needs `z_t >= 2`, a rising EWMA, and two independent evidence clusters. These formulas are on current slide 10. Label them as the method, not as measured project results.
- Material disagreement: amount differs by more than 10%, or date differs by more than 7 days. Stale: a newer snapshot supersedes the claim, two refresh windows are missed, or `valid_to` expires. A historical event does not become stale only because time passes. Current slide 9.
- Trust pilot: 5 participants, 6 tasks each, 30 of 30 collected. The participant classifies the answer, selects evidence, and decides whether the system should answer or abstain. Free-text explanations were not collected.
- Cohort rule: 15–20 agent-infrastructure or developer-tool companies, stable name and domain, public evidence, frozen before scoring. We froze 18.

## Speaking script

### Sueda — what I closed

- The cohort is frozen at 18 companies.
- Mehmet and I both finished independent annotation.
- Cohen's kappa is 1.0 on entities and relations, in both rounds.
- The pilot is complete: 30 of 30 responses, five people, six tasks each.
- Hiring history is paired for 15 of 18 companies.
- Langfuse and Continue use archived Ashby boards.
- CrewAI, Replicate, and Weights & Biases do not have a second complete board. I am not calling those weekly hiring trajectories.
- Team code is under the MIT `LICENSE` at the repository root.

### Mehmet — what he closed

- Temporal ontology, Neo4j schema and loader, RDF and PROV-O export, SHACL, Cypher, and SPARQL competency queries.
- Five-company live demo: 170 nodes and 466 relationships. The live Neo4j summary matches the offline file.
- Eighteen-company graph: 866 nodes and 2,308 edges. SHACL passes. The same offline and live match holds.
- A job node is an observed listing, not a hire.

### Vidya — collector evidence

- Greenhouse, Lever, and GitHub collectors are in the repo and tested.
- Retry, pagination, and the access notes are done.
- On November 21 (Phoenix), the two mapped Greenhouse boards listed 24 openings: 16 at Browserbase (`browserbaseinc`) and 8 at Sourcegraph (`sourcegraph91`). These observations fall after the study cutoff.
- A later identity check verified Arize's Greenhouse board. Its separate snapshot contains 20 listings. No company-owned Lever site was verified in the cohort.
- For the offline demo, run `python -m collectors --replay evaluation/vidya-cohort-jobs/browserbase/snapshot.json`. See [all 18 hiring sources](../collectors/API_COLLECTORS.md#frozen-cohort-job-boards) and the [snapshot manifest](../evaluation/vidya-cohort-jobs/manifest.json).

### Faisal — what is done, and what is still yours

- Weekly features, EWMA, hybrid fusion, and query routing are implemented and scored.
- The conversational interface and the ablation runs are in the repo.
- The scored dense runs use hashing, not a sentence-transformer encoder.
- The demo answer path uses the graph Mehmet loaded.
- Still open: one semantic-encoder run, and one answer bundle that uses `Neo4jBackend`.
- Do not describe the hashing run as a semantic-model result.

## Demo commands

Use two terminals. Every `python -m` command runs from the repository root.
If the prompt ends in `real-graph-integration`, Python will say `No module named evaluation`.

### Terminal A — setup

```bash
cd /Users/suedasen/Desktop/trendscout-ai
source .venv/bin/activate
```

What you need: the prompt shows the repo name, and Docker Desktop is running.

### Stage 1 — frozen five-company graph

```bash
python -m evaluation.real_graph_integration check
```

What you need: `"status": "ok"`.

Say: "This rebuilds the five-company graph from the frozen records and matches the committed file."

### Stage 2 — start Neo4j

```bash
docker compose up -d neo4j
docker compose ps neo4j
```

What you need: status `Up` or `running`.

Say: "Neo4j is local. The password is not stored in the repository."

### Stage 3 — load the five-company graph

```bash
python -m graph.neo4j \
  --graph-payload evaluation/mixed/real-graph-integration/graph.json
```

What you need:

```text
"payload_node_matches": 170
"payload_edge_matches": 466
"payload_verified": true
```

Say: "The payload match is the acceptance check. A larger database total only means older data is still present."

### Stage 4 — offline file matches live Neo4j

```bash
python -m evaluation.real_graph_demo \
  --live \
  --out evaluation/mixed/real-graph-integration/demo-results.json
```

What you need:

```text
"status": "offline_and_live_demo_complete"
"live_matches_offline": true
```

Say: "The summary from the file and the summary read back from Neo4j are the same."

### Stage 5 — visual page

Terminal B only:

```bash
cd /Users/suedasen/Desktop/trendscout-ai/evaluation/mixed/real-graph-integration
python -m http.server 8770 --bind 127.0.0.1
```

Leave Terminal B running. Open:

```text
http://127.0.0.1:8770/demo.html
```

What you need: the page shows the two coverage charts.
If the charts are empty, the file was opened from Finder. Use the `http://127.0.0.1:8770` address.

Say: "These charts describe this snapshot. They are not a company ranking. A listing is not a hire. An announcement date is not automatically a funding-event date."

Take the screenshot for the UI slide from this page.

### Stage 6 — eighteen-company graph, only after the page is visible

Back in Terminal A, at the repo root:

```bash
cd /Users/suedasen/Desktop/trendscout-ai
python -m graph.neo4j \
  --graph-payload evaluation/cohort-real-graph-integration/graph.json
```

What you need: `"payload_verified": true`, 866 nodes, 2,308 edges.

```bash
python -m evaluation.real_graph_demo \
  --graph "$PWD/evaluation/cohort-real-graph-integration/graph.json" \
  --live \
  --out "$PWD/evaluation/cohort-real-graph-integration/demo-results.json"
```

What you need: `"live_matches_offline": true`.

Say: "All 18 companies are in this graph. Nine have observed job listings here. The other nine have GitHub history only."

This load replaces the five-company graph in Neo4j. Do it after the audience has seen the page.

### Stage 7 — optional retrieval

Still at the repo root:

```bash
python -m interface --demo --seed-questions --mode hybrid
```

What you need: answer lines, and no `No module named interface` error.

Say: "This scored path uses hashing plus the graph. It is not a semantic-embedding comparison."

## If something fails

| What you see | What it means | What you do |
|---|---|---|
| `No module named evaluation` or `No module named interface` | Terminal A is inside `real-graph-integration` | `cd /Users/suedasen/Desktop/trendscout-ai` and run the command again |
| `live_matches_offline` is false | Neo4j does not match the file | Rerun Stage 3, then Stage 4 |
| Docker is down | Neo4j cannot start | Skip Stages 2–4. Open the page and say the live match was recorded on 21 November |
| Blank charts | The HTML file was opened directly | Use `http://127.0.0.1:8770/demo.html` while Terminal B is still serving |

## What we will not say

- Weekly hiring for CrewAI, Replicate, or Weights & Biases.
- A job listing is a hire.
- Temporal answer accuracy on the original 28 questions has been measured.
- Dense retrieval used a semantic encoder.
- Greenhouse or Lever is mapped for all 18 companies.
