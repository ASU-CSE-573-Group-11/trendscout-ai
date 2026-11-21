# TrendScout AI evaluation report

Report date: 20 November 2026 (America/Phoenix).

The evaluation covers 45 real public release documents, the original 28 project questions, and a separate 28-question release-fact study. Source review assigned 2,520 question/document judgments with rationales. Four answer conditions produced 224 saved bundles; three document retrievers were scored on actual top-5 rankings. The original project success criterion is not established by the release-fact benchmark.

## Corpus and reproducibility

The corpus contains 15 release documents each from LangChain, LlamaIndex and CrewAI. Public GitHub API responses, selected release IDs, normalized full bodies, source URLs, publication/event times and observation times are retained in [evaluation/real](../evaluation/real/README.md). The freeze occurred at 2026-11-21T06:14:33Z, which is 20 November in Arizona.

Snapshot SHA-256: `587d3128ef445f1b17d6ac711be64f5491679e41494ac0506114b1cf53b40d30`.

This separate release-document round preserves the original 28 question texts and identifiers. It changes the evidence coverage relative to the original study window. Release notes cannot prove hiring, funding, activity growth or independent corroboration. The original fixture corpus remains available for regression testing and supplies no human labels to this round.

## Executed measurements

All runs use the extractive provider and an in-memory graph. The condition named `dense` uses the hashing encoder: it is another lexical baseline, not semantic dense retrieval. Latencies describe a single local run and exclude model/API inference.

| Condition | Questions | Seed-behavior abstention agreement | Median ms | p90 ms |
|---|---:|---:|---:|---:|
| bm25 | 28 | 0.9643 | 5.305 | 8.724 |
| dense | 28 | 0.9643 | 3.662 | 11.911 |
| graph_only | 28 | 0.7500 | 1.038 | 2.002 |
| hybrid | 28 | 0.9643 | 6.272 | 12.109 |

The abstention comparison uses the existing question expectations, which were designed for the broader study corpus. It is a diagnostic of behavior, not human-rated answer correctness. Automatic citation bookkeeping reports claim support 1.0 and unsupported claim rate 0.0 in these runs; these values do not independently verify whether a source semantically supports a factual statement.

## Source-reviewed qrels and scored retrieval

Relevance judgments are complete in [the original-study qrels](../evaluation/real/source-reviewed-qrels.json) and [the release-study qrels](../evaluation/real/release-study/source-reviewed-qrels.json). Every pair has a grade, rationale and source URL. Every positive grade includes an exact source quote. The judgments record their actual reviewer, **Codex source review**, and do not assert independent team adjudication. They are source-derived labels, not grades copied from system rankings or citations.

The rubric assigns 0 for no evidence answering the actual question, 1 for an explicit partial component, and 2 for direct support. A matching company name, a release date, or a callback integration name does not establish hiring, funding, revenue, growth or an evidence-ledger policy.

### Original project questions

All 1,260 pairs were judged. The release corpus contains no passages establishing the original 28 requested facts, temporal comparisons, or evidence-state policies under this strict rubric. Consequently, raw retrieval Precision@5 and MRR@5 are 0 for all three document retrievers. Recall@5 and nDCG@5 are undefined because there are zero positive documents for every question. Undefined values remain null; they are not missing judgments. This is a measured corpus-coverage failure, not evidence that a retriever can or cannot find an available relevant document.

[Raw ranking measurements](../evaluation/real/retrieval-metrics.json) retain every top-5 record and score. [Answer/citation measurements](../evaluation/real/scored-metrics.json) score the saved four-condition answer bundles separately. Their internal claim-support flags do not establish semantic correctness: citation precision is 0 for document-answer conditions despite internal support flags of 1.0.

### Release-fact lookup study

A separate source-grounded set was frozen before any retrieval run on it: 10 LangChain, 9 LlamaIndex and 9 CrewAI questions. Each asks about a fact in a named release/version. Its answer key identifies a directly supporting document and quote. All 1,260 pairs were judged; each question has one grade-2 source and 44 grade-0 sources. This is known-release fact lookup, not an independent sample of temporal multi-hop questions.

The following are **raw retriever top-5** results over the same 45-document snapshot, with distinct documentary origins and no answer-stage filtering:

| Condition | P@5 | Recall@5 | MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| bm25 | 0.1929 | 0.9643 | 0.8821 | 0.9028 |
| dense | 0.1643 | 0.8214 | 0.6530 | 0.6954 |
| hybrid | 0.1929 | 0.9643 | 0.8196 | 0.8561 |

With one positive per question, Precision@5 has a maximum of 0.2. Recall@5 therefore also reports the hit fraction: BM25 and hybrid find 27/28 target documents, hashing finds 23/28. BM25 ranks targets earlier than hybrid on this set. The hashing condition remains a lexical baseline; these scores do not establish performance against semantic dense embeddings.

[Release raw retrieval results](../evaluation/real/release-study/retrieval-metrics.json) include each query's actual ranking. [Release answer/citation scores](../evaluation/real/release-study/scored-metrics.json) cover BM25, hashing, graph-only and hybrid. Graph-only has 0 Recall@5 for release fact lookup because its structured outputs do not cite the target release documents. No graph advantage is established.

## Annotation, agreement and trust study evidence

The user states that human work was completed. A search of tracked, untracked and ignored workspace evaluation artifacts did not locate independent team entity/relation labels or participant measurements. Existing legacy annotator files explicitly identify simulated labels; their identical-label kappa of 1.0 is not an independent human result.

The real-source work package provides 418 exact shared entity candidates and 126 document/mention relation candidates. No candidate is counted as a completed human annotation. The target remains 200+ accepted entity mentions and 80–100 accepted relations per annotator, with 100+ shared independently labelled items for agreement. Candidate classification agreement does not measure free-span detection recall.

Source-reviewed relevance judgments and retrieval scores are now present for both question sets. The trust-study record specifies six tasks and two counterbalanced conditions, with fields for 5–8 participants, correctness, timing and confidence. Participant-level results were not found, so no trust-study effect is reported.

## Contributions and verification

The project has four members: Sueda Sen, Mehmet Aksit, Vidya Sagar Dudekula and Faisal Barkat Khorasi. [The contribution record](../evaluation/real/contribution-record.json) preserves all four names and the user’s completion statement. Repository contributions are supported by actual commit hashes and changed paths for evaluation/collection, graph loading, API collectors, and retrieval/interface work. Graph commits are authored as M Cevat Aksit, so attribution to Mehmet Aksit requires confirmation. Human evaluation participation still requires its own underlying records. The four names alone do not establish a 5–8-person pilot sample.

## Completion and remaining inputs

The real corpus, two frozen question sets, 2,520 relevance judgments, raw retrieval scores, 224 answer bundles, candidate workbooks and this report are present. Remaining research records concern independent entity/relation annotation and agreement, corpus inclusion decisions, participant task measurements and contribution verification. Relevance scoring no longer depends on obtaining another judgment file. Reproduction commands are in [the round instructions](../evaluation/real/README.md).

The implementation also corrects evaluation failure modes: corpus review no longer passes merely because it is pending; zero-origin graph aggregates and empty weekly trend bins cannot become supporting citations; news trend citations retain their correct source type. CSV agreement rejects duplicate IDs and requires identical sets of at least 100 labelled items.
