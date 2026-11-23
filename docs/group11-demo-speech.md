# Group 11 speech — 23 November 2026

About 12 minutes. Sueda speaks the study. Mehmet drives the page and the graph.
Slides: `docs/Group11-Project5-FA26-Group-DEMO-Presentation.pptx`
Live page: http://127.0.0.1:8770/demo.html

## 0:00 — Cover (Sueda, 30 seconds)

Group 11. TrendScout AI: evidence-calibrated temporal market intelligence.
Members: Sueda Sen, Mehmet Aksit, Vidya Sagar Dudekula, Faisal Barkat Khorasi.
This is the 23 November demo.

## 0:30 — Problem (Sueda, 70 seconds)

Public funding posts, job boards, and repositories repeat the same announcement and disagree on the date.
A chatbot will still produce one confident sentence.
We keep the claim, the time, and the source separate from that sentence.
If the evidence is one origin, the answer is qualified. If it is missing, we abstain.
A job listing is not a hire. An announcement date is not a financing close.

## 1:40 — Architecture (Mehmet, 80 seconds)

Collectors write a normalized record: URL, hash, publisher, observation time.
The evidence ledger assigns emerging, corroborated, stale, or disputed.
Neo4j holds the graph. The live database has to match the committed file.
RDF, SHACL, and SPARQL check that file. The demo runs Cypher.
Passages sit in BM25 and a hashing index.
The sentence you hear is extractive. The model does not choose the evidence state.

## 3:00 — Algorithms (Mehmet, 70 seconds)

One independent origin is emerging. Two independent origins, or a document plus an operational signal, is corroborated.
Stale means a newer snapshot supersedes the claim, two refresh windows are missed, or valid-to expires. A past event does not become stale only because time passes.
The trend method is an EWMA, s_t = 0.4 x_t + 0.6 s_t−1, and a rolling z-score on the previous eight weeks, excluding week t.
A candidate alert needs z at least 2, a rising EWMA, and two independent clusters. That is the method. We are not reporting a measured alert rate.
Retrieval conditions are BM25, hashing dense, and hybrid. Hashing is lexical.
Material disagreement is an amount off by more than 10 percent, or a date off by more than 7 days.

## 4:10 — Data (Sueda, 70 seconds)

Eighteen companies are frozen in the cohort file.
The page you will see is five of them: 45 records, 170 nodes, 466 relationships.
The full cohort graph is 866 nodes and 2,308 edges. SHACL passes, and live Neo4j matches that file.
Official job-list history is paired for 15 of 18 companies. CrewAI, Replicate, and Weights & Biases do not have a second complete board.
Mehmet and I labeled independently. Cohen’s kappa is 1.0 on entities and relations.
The pilot has 30 of 30 responses, five people, six tasks each.

## 5:20 — Findings (Sueda, 100 seconds)

Stay on the evaluation slides, then leave them up while the page opens.
Release-fact lookup: 28 questions, one supporting document each, so Precision@5 cannot exceed 0.2.
BM25 finds 27 of 28. Recall@5 is 96.4 percent. MRR@5 is 88.2 percent.
Hashing dense finds 23 of 28. Recall@5 is 82.1 percent.
Hybrid also finds 27 of 28, and it ranks the target later than BM25.
That dense column is hashing. It is not a sentence transformer.
The original 28 project questions have Precision@5 of 0. The corpus has no passage that establishes them. Recall@5 is undefined.
We have not measured temporal multi-hop accuracy, trend Precision@5, or whether evidence states change a person’s judgment.
An automatic unsupported-claim rate of 0 does not prove the sentence is true.

## 7:30 — Live page (Mehmet, 3 minutes)

Open http://127.0.0.1:8770/demo.html
The first screen is the finding. Left side is the headline. Right side is 27, 23, and 27.
Say: live Neo4j matches the committed graph.
Scroll to The frozen graph.
Drag the canvas. Scroll to zoom. Click a startup.
Press LangChain. The neighborhood is that company’s listings, repository, round, and linked skills.
Press Show claims only if someone asks where the claim nodes are. They are real, and they clutter the picture.
The bars under the canvas are coverage of this snapshot, not a ranking.

## 10:30 — Plan and repository (Sueda, 70 seconds)

I froze the cohort and ran the evaluation.
Mehmet built the ontology, Neo4j, RDF, and this graph.
The collectors, the weekly features, EWMA, and the interface are in the repository.
The December report still has to measure temporal accuracy and trend Precision@5.
That report is due 9 December. It is separate from this demo.
The repository is https://github.com/ASU-CSE-573-Group-11/trendscout-ai
Leave the last slide up.
