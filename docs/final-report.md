# TrendScout AI evaluation report

Report date: 21 November 2026 (America/Phoenix).
Source capture clocks and archive dates below are retained in UTC.

Latest hiring follow-up: paired complete official-list populations cover **13/18**
companies. Four further companies have restricted directory or parent-brand-title
comparisons; CrewAI has a current board and dated advertisement pages without a
complete historical stock baseline. See the
[population-scoped review](../evaluation/remaining-history-discovery/review.json).

Current pilot collection counts and measured time/confidence summaries are in
[the validated response summary](../evaluation/real/pilot-session/response-summary.json).
Collection is complete: 30 validated responses from five participants, each
with six tasks and three tasks per condition. The recorded second review and
team source-assisted adjudication now support final grading of observed fields.
Explanation-dependent criteria remain unmeasured. Refresh the summary with
`python -m evaluation.pilot_analysis` as participants continue.

The evaluation covers 45 real public release documents, the original 28 project questions, and a separate 28-question release-fact study. Source review assigned 2,520 question/document judgments with rationales. Four answer conditions produced 224 saved bundles; three document retrievers were scored on actual top-5 rankings. The original project success criterion is not established by the release-fact benchmark.

## Corpus and reproducibility

The later [cohort identity source check](../evaluation/cohort-identity-review/manifest.json)
accounts for all 18 frozen companies and checks all 11 configured YC URLs.
Three current profiles support the frozen company name and official domain:
Langfuse, Continue and Replicate. Seven configured URLs return 404; the other
seven companies have no YC URL assertion. The Modal URL identifies a different
auto-commerce company and is excluded through a source-grounded review. The
separate `usable-profiles.json` lists only supported current profile links.
No company is inferred to be a non-YC company merely because a page is absent.
Frozen membership and all earlier source/experiment snapshots are unchanged.

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

Relevance judgments are complete in [the original-study qrels](../evaluation/real/source-reviewed-qrels.json) and [the release-study qrels](../evaluation/real/release-study/source-reviewed-qrels.json). Every pair has a grade, rationale and source URL. Every positive grade includes an exact source quote. The judgments are recorded as **Source review**; separate team adjudication is not recorded. They are source-derived labels, not grades copied from system rankings or citations.

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

The release-study Sueda worksheet columns now contain a first source review prepared on behalf of the assigned owner. All 418 entity and 126 relation candidates have decisions; headings and unsupported fragments are rejected. There are 142 accepted seed entity mentions and 358 additional exact spans, plus a separate 90-fact documentary MENTIONS sample. The second-review labels and participant measurements remain absent. The review does not attest personal independent annotation. Legacy annotator files contain 94 shared labels with pending review; their agreement value of 1.0 does not meet the required minimum of 100 shared independently labelled items. Both legacy corpus-review files have 45 completed decisions; those decisions apply to the fixture corpus, not the active release-document corpus.

The real-source work package provides 418 exact shared entity candidates and 126 document/mention relation candidates. No candidate is counted as a completed human annotation. The target remains 200+ accepted entity mentions and 80–100 accepted relations per annotator, with 100+ shared independently labelled items for agreement. Candidate classification agreement does not measure free-span detection recall.

Source-reviewed relevance judgments and retrieval scores are now present for both question sets. The trust-study record specifies six tasks and two counterbalanced conditions, with fields for 5–8 participants, correctness, timing and confidence. Participant-level results were not found, so no trust-study effect is reported.

## Contributions and verification

The project has four members: Sueda Sen, Mehmet Aksit, Vidya Sagar Dudekula and Faisal Barkat Khorasi. [The contribution record](../evaluation/real/contribution-record.json) preserves all four names and the user’s completion statement. Repository contributions are supported by actual commit hashes and changed paths for evaluation/collection, graph loading, API collectors, and retrieval/interface work. GitHub links the graph commits authored as M Cevat Aksit to mcaksit; the team explicitly confirmed that mcaksit is Mehmet Aksit. All four project account mappings are recorded in evaluation/submission/contributor-identities.json. Human evaluation participation still requires its own underlying records. The four names alone do not establish a 5–8-person pilot sample.

## Completion and remaining inputs

The real corpus, two frozen question sets, 2,520 relevance judgments, raw retrieval scores, 224 answer bundles, candidate workbooks and this report are present. Remaining research records concern independent entity/relation annotation and agreement, corpus inclusion decisions, participant task measurements and contribution verification. Relevance scoring no longer depends on obtaining another judgment file. Reproduction commands are in [the round instructions](../evaluation/real/README.md).

The implementation also corrects evaluation failure modes: corpus review no longer passes merely because it is pending; zero-origin graph aggregates and empty weekly trend bins cannot become supporting citations; news trend citations retain their correct source type. CSV agreement rejects duplicate IDs and requires identical sets of at least 100 labelled items.

## Mixed-source follow-up integration

A [separate mixed-source round](../evaluation/mixed/README.md) now preserves the
original 28 questions while adding three funding announcements, 18 current job
postings, and 24 weekly GitHub observations reconstructed from dated commits.
This extends observation beyond the original freeze and does not retroactively
change either release-document study above.

Four retrieval conditions and three ablations produced 196 additional answer
bundles. The source excerpts were exported into 45 ledger entries, a graph
with 124 nodes and 180 edges, and RDF; SHACL validation conforms. The extraction
inventory contains 374 exact-offset entity predictions and 374 MENTIONS
relations, requiring review. These are extraction outputs rather than gold
annotations.

A separate [real semantic graph projection](../evaluation/mixed/real-graph-integration/summary.json)
keeps that original experiment frozen while projecting the same 45 retained
records into 170 nodes and 466 relationships. It contains 45 source-excerpt
Claims, 4 source-reviewed Investors, 3 explicitly named FundingRounds, 18 public
JobPostings, 3 Repositories, 10 Skills and 8 Technologies, alongside provenance
nodes. The complete RDF graph conforms to expanded SHACL shapes. A live local
Neo4j acceptance check matched all 170 payload IDs and all 466 payload
relationships. Database totals are higher because earlier fixture/source nodes
remain in the same local database. Public listings are not treated as completed
hires; unknown funding event dates remain absent; Investors are not assigned to
specific FundingRounds without a retained source link; Claims remain emerging
source excerpts rather than independent semantic gold.

A component-only rubric assigns 1 to explicit relevant evidence components and
0 otherwise, with no grade-2 labels. Ten of 28 questions have such components.
Hybrid raw P@5 is 0.1714 and MRR@5 is 0.2321 under this rubric. These results
cannot be compared directly with the earlier strict full-question relevance
scores. Current boards do not establish historical hiring growth, and the
funding/job records do not establish a causal path. Primary temporal success
remains unmeasured. The runs use hashing, extraction, and an in-memory graph.

The annotation-record search covered 18 local/cached remote refs, historical
label files, and matching nearby project files. It found legacy corpus decisions
and at most 94 shared legacy JSON labels, with no completed entity/relation CSV
labels. Independent agreement therefore remains null; the two annotators'
records and attestations are still required.

## Sueda documentary collection and review handoff

The [Sueda completion report](../evaluation/submission/sueda-completion.json) accompanies an additional replay-verified feed
snapshot with 584 records and a 136-document study slice dated 1 November 2025
through 20 November 2026. The full archive contains 565 company documents, two
news records, six public-voice records, and 11 unverified registry assertions.
Fifteen public-voice feeds were curated; current matching coverage is reported
separately from feed availability. Archived voice matches are outside the dated
slice and supply context only. The study slice has 135 company documents and
one news record. These populations are not represented as balanced independent
cross-source evidence.

The collection corrects RSS publication-date loss, invalid-feed success, common
word/company confusion, duplicate feed discoveries, headline-only origin
merging, and unverified YC page assertions. Five BM25 smoke queries have saved
source URLs and scores. They are reproducibility checks, not a relevance study.

The first source review fills 45 corpus decisions and 1,260 release-study
relevance grades in Sueda's columns. Independent second-review and final
adjudication columns are preserved. Six pilot task keys, a frozen evidence
policy, and a frozen five-person task plan are prepared. Five consent reports
are recorded with their reporting method. Actual responses, elapsed times and
confidence are now retained in the separate pilot session; current progress is
linked above. Correctness and pilot effects have not been inferred. Offline verification is available with
`python -m evaluation.verify_sueda_delivery`.

## Final artifact verification

The separate [dated evidence extension](../evaluation/sueda-evidence-extension/README.md)
adds five public-voice articles within the study window (eight company-linked
passages, two publishers). It also preserves two complete LangChain Ashby board
observations: 104 listed postings on 21 October 2026 and 102 on 21 November.
There are 26 newly observed and 28 no longer observed posting IDs, a net change
of −2. Capture and retrieval clocks remain separate and source bodies are
checksummed for offline replay. This is a posting-count comparison for one
company, not hiring growth, hires, funding causality, or a complete weekly
cohort trend. Earlier frozen experiments and scores are unchanged. Independent
entity/relation agreement remains open. Pilot collection and observed-field grading are finalized below.

On 21 November, both release-study score reports and raw ranking reports were
recomputed against the current source-review files. Qrels fingerprints now
match the actual inputs. The 224 saved answers retain their original bytes
and latency observations; verification checks their hashes, schemas, complete
question coverage, and recomputed answer/citation metrics.

The first-review revision 2 packet unifies 776 entity candidates (500 accepted)
and 100 relation candidates (90 accepted) across the same 45 documents. The
common candidate list has empty label/note fields. Its manifest binds it to
the original source snapshot and candidate seed, and fingerprints the reviewed
worksheets. The original shared candidate files and Mehmet's worksheet values
are preserved. This is an explicit source-review revision, not a retrospective
claim of independent annotation or full semantic relation extraction.

## Pilot enrollment and submission review update

Five consent reports have been recorded: P05 explicitly self-consented and
reported that all four team members approve participation. The record preserves
these different reporting methods. The first collection checkpoint contains
five participant responses with measured times and confidence ratings.
No correctness or treatment-effect result is asserted. A frozen
counterbalanced assignment table and saved-answer stimuli are available;
randomization applies only to condition blocks and task order. There is no
fifth synthetic participant and no simulated result in the empirical dataset.

The [submission review](submission-review.md) records verified commit/path
references, dependency/source license inventory, and a live access check.
The repository is private; GitHub's protection endpoint returned HTTP 403 under
the current plan/visibility, so server-side enforcement is not asserted.
The local archive preserves open research inputs and is not a complete-study
or redistribution-clearance certification.

## Cohort-wide historical coverage follow-up

The separate `evaluation/cohort-history-v2` freeze reconstructs eight complete
ISO weeks of available default-branch commits for all 18 cohort companies,
producing 144 weekly records. Pagination is pinned to each observed branch tip;
the source snapshots retain commit identities and dates while omitting messages
and author profiles. Historical stars, forks and issue counts remain unknown.
An explicit source revision uses `modal-labs/modal-client`, identified in
[Modal's SDK documentation](https://modal.com/docs/sdk/go/latest/intro), after
the frozen `modal-labs/modal` target was unavailable. The initial 17-company
collection remains intact. The revision preserves cohort membership and all
earlier experiments. Eight zero-commit weeks in a selected public repository
are not evidence that the company itself stopped operating.

The careers audit records all 18 companies. Nine boards linked from official
company pages provide current listed-posting counts; two have verified archive
captures inside the expanded study window. The normalized job dataset contains
393 observations, not 393 independent postings or companies. LangChain has
104→102 listed postings between 21 October and 21 November (net −2), while
Modal has 51→52 between 20 and 21 November (net +1). The intervals differ and
must not be pooled as equivalent growth measurements. Missing historical job
coverage for the other 16 companies stays unknown. Two Sourcegraph captures
predate the study window and are excluded from in-window comparisons. Boards
of acquiring parent companies are not attributed wholesale to cohort companies.

Archive payload hashes, CDX selection, and Memento capture clocks support
offline replay. The weekly feature pipeline is executed on both follow-up
datasets. These additions improve source coverage; they do not establish
funding-to-hiring causality, completed hires, independent agreement, or pilot
effects. The [completion report](../evaluation/submission/sueda-completion.json)
contains company-by-company coverage and actual study readiness. Independent
personal annotation is still unattested, paired agreement is not estimable,
and collection is now complete at 30/30 task responses. Consent reports and
observed task submissions are counted separately.

```bash
.venv/bin/python -m evaluation.cohort_history replay --out evaluation/cohort-history-v2
.venv/bin/python -m evaluation.cohort_jobs replay
.venv/bin/python -m evaluation.sueda_completion
```

## Sueda mixed-round source review and archive extension

The mixed-source first-review worksheets now contain 276 entity decisions
(118 accepted), 108 relation decisions (33 accepted documentary `MENTIONS`),
45 existing inclusion decisions and 1,260 component-relevance grades (195
positive component judgments). Rejected candidates include headings and partial
ordinary phrases. Source offsets, original row fields, source quotations and
the other reviewer's records were checked before applying the changes.
Original worksheets and the decision plan are retained in
`evaluation/mixed/sueda-source-review/`. This is team-authorized source review,
not a declaration of two independent personal annotation passes. Corpus and
relevance final/adjudication columns are unchanged. Earlier saved answers,
retrieval scores and source snapshots are unchanged.

A separate in-window prefix archive lookup found a query-variant LangChain
board capture from 5 October 2026. Its 102 listed postings extend the observed
sequence to 102 (5 October), 104 (21 October), and 102 (21 November). Comparing
5 October to 21 November gives 38 newly observed and 38 no longer observed IDs,
with 64 retained. Listing counts are therefore unchanged across those endpoints.
The extension adds 102 observations to the earlier 393: the combined job data
has 495 observations. It extends one company's history and does not increase
the two-company historical coverage count. Missing companies and weeks stay
unknown. Memento capture time and payload hashes support offline replay with
`python -m evaluation.archive_followup replay`.

An English loopback-only pilot console now renders the frozen task views,
records participant-entered responses and measures server elapsed time. It
does not supply participant answers or correctness grades. The measured period
includes interruptions. The shared answer text can already contain evidence
state words in both conditions, so this design measures supplemental panel
presentation rather than presence/absence of all state language. Independent
task-key review, adjudication and observed-field grading are finalized below.

## Completed participant-response collection

All 30 assigned task responses are now recorded and validated. P01–P05 each
completed six distinct tasks in the planned order, with three tasks per
condition. Checks cover recorded consent, assignment identity, stimulus hashes,
unique tasks, source-number validity, positive finite elapsed time and confidence
ratings. The team explicitly confirmed participant attribution; the identifying
map is retained outside the submission archive and the empirical data uses
pseudonymous participant codes.

| Display condition | Participants | Task responses | Mean elapsed seconds | Median elapsed seconds | Mean confidence (1–5) |
|---|---:|---:|---:|---:|---:|
| Citations only | 5 | 15 | 13.63 | 10.73 | 3.60 |
| Citations plus state/path panels | 5 | 15 | 13.07 | 13.43 | 3.73 |

Across all responses, mean elapsed time is 13.35 seconds, median elapsed time
11.82 seconds and mean confidence 3.67/5. Comparing each participant's two
condition means gives an average observed time difference of −0.56 seconds
(state/path minus citations only), with a median participant difference of
+1.37 seconds. The average observed confidence difference is +0.13 points.
These are descriptive differences across five participants, not 30 independent
participants or evidence of a causal improvement. Task sets differ between
conditions, the shared answers can already contain state language, and elapsed
time includes interruptions. No significance or causal-effect claim is made.

Raw responses are preserved. The form did not collect free-text explanations,
so explanation-dependent rubric criteria cannot be inferred from the selected
action. The final grading below preserves those criteria as unmeasured.
Collection and observed-field grading are complete; the broader research evaluation is
not marked complete. Reproduce the current summary with
`python -m evaluation.pilot_analysis`.

## Recorded second task-key review

A personal second task-key review by Sueda Sen is now recorded with six
decisions, source-basis selections and a self-confirmation of independent entry.
The reviewer also participated in the pilot; this is not an external-assessor
review. All six recorded states differ from the initial source key. The supplied
rationale text is “Excellent” for every task and does not identify task-specific
supporting evidence. The recorded judgments are preserved unchanged.

The [source-based adjudication proposal](../evaluation/real/pilot-session/task-key-adjudication-proposal.json)
documents each disagreement against the frozen 45 software-release records and
shared policy. The source snapshot does not establish the requested hiring,
funding-to-hiring, independent voice, acquisition or future-valuation claims.
The emerging-policy question additionally needs an explanatory interpretation
that was not captured in the categorical participant form. The report retains
the source-key and second-review alternatives for sensitivity analysis. The team
accepted the source-based resolution for the final key; both original reviews
remain intact. This review does not complete
the separate entity/relation annotation agreement requirement.

## Final pilot grading

The project session accepted the presented source-based resolution. All six
key disagreements are resolved in
[`task-key-adjudication.json`](../evaluation/real/pilot-session/task-key-adjudication.json),
with the original rubric wording and source fingerprints preserved. The method
is team source-assisted adjudication following a recorded blind second review;
no external independent assessor is claimed. The 30 participant decisions,
confidence ratings and measured durations are unchanged. An exact snapshot
documents an earlier metadata-only `grading_status` update.

| Prespecified criterion | Correct | Assessed | Unmeasured | Result |
|---|---:|---:|---:|---|
| Participant evidence-state classification | 1 | 30 | 0 | 3.33% |
| Evidence explanation | — | 0 | 30 | Not measured |
| Abstention/action behavior | 1 | 17 | 13 | 5.88% of assessable responses |

These are participant-task scores against the frozen pilot key, not overall
model accuracy or original temporal-question success. Qualifying and policy
explanations were not collected; they are neither inferred nor counted as
failures. Earlier preliminary source scores are backed up. The verified final
scores in [`final-grading.json`](../evaluation/real/pilot-session/final-grading.json)
are authoritative for this pilot. A legacy integration command reuses these
scores instead of turning unmeasured criteria into false values.

This pilot phase is finalized for its observed fields. Missing explanatory
measurements remain an explicit protocol limitation. Independent entity/relation
agreement, broader historical hiring coverage and project-wide submission
requirements remain separate. Verify without modifying participant records:

```bash
.venv/bin/python -m evaluation.finalize_pilot verify
.venv/bin/python -m evaluation.pilot_analysis
```

## Question-level evidence coverage follow-up (21 November 2026)

The [coverage inventory](../evaluation/submission/question-coverage.json) maps all
28 original questions to frozen evidence components, explicit requirements and
remaining limitations. Its 789 record references comprise 144 weekly commit
records, 495 complete-board job observations, 3 selected LlamaIndex job records,
8 company-associated passages from 5 public-voice articles, 136 dated documentary
records and 3 funding pages. Record counts do not measure relevance, independent
origins or answer accuracy. The selected LlamaIndex postings are not a complete
board. Existing corpora, qrels, participant submissions and benchmark scores are
unchanged.

Fifteen questions have partial evidence; two support bounded descriptive commit
calculations. Five concern evidence-state policy and six support abstention or
entity clarification within this corpus. These categories are coverage judgments,
not gold labels or a success percentage. At this inventory freeze, comparable historical ATS boards covered two companies.
The later official career-list follow-up below adds LlamaIndex as a third company;
funding event dates still require source-level normalization.

For CrewAI, first versus last complete weekly commits are 12 versus 40; the first
four weeks total 90 and the last four total 221. This supports a precisely bounded
increase in default-branch commits, without claiming a monotonic or statistically
significant trend. For “last month,” the descriptive proxy compares the first two
and last two of the last four complete ISO weeks. Decreases occur for Arize
(−99), Browserbase (−9), Chroma (−2), Composio (−26), CrewAI (−53), LangChain
(−15), Pinecone (−55) and Weights & Biases (−14). These are commit-count differences,
not percentages, hires or company-wide performance. The calculation retains all
18 companies, including zero-count weeks, directly from raw records rather than
summing overlapping repository and company series. The existing derived series
omits Sourcegraph; the raw-based coverage calculation includes its eight observed
zero-count weeks without modifying that older signal output.

| Question | Coverage assessment | Remaining constraint / interpretation |
|---|---|---|
| Which agent-infrastructure startups show both rising GitHub activity and new MLOps hiring in the last eight weeks? | partial evidence | Only LangChain and Modal have comparable board snapshots; role-specific increases and an eight-week hiring baseline are not established. |
| Which investors funded startups that later increased hiring for retrieval or evaluation skills? | partial evidence | Funding event dates and comparable skill-specific before/after job stocks are not established cohort-wide. |
| Which sectors gained attention from multiple public voices and also produced operational signals? | partial evidence | Five articles from two publishers are selected coverage, without a stable attention baseline or adjudicated sector/claim independence. |
| Why is a company marked as emerging, and what evidence could change that label? | policy only | The policy is available; this coverage inventory does not establish a named company ledger state. |
| Which frozen cohort company acquired Anthropic in 2024? | abstention supported | The retained corpus does not establish this acquisition; absence here is not proof of worldwide non-occurrence. |
| Which company in the cohort will have the highest valuation in 2027? | abstention supported | Observed sources cannot establish the requested future outcome. |
| Did LangChain commit activity and hiring both rise since September? | partial evidence | Commit windows begin September 21; the earliest retained board snapshot is October 5, so the full September comparison is unavailable. |
| Did CrewAI repository activity rise during the last eight weeks? | bounded operational calculation | Endpoint and half-window comparisons measure different aspects; neither is a statistical trend test or a measure of all repository activity. |
| Which startups combined hiring and repository growth over the last ten weeks? | partial evidence | Only eight complete commit weeks are retained; ten-week paired hiring baselines are unavailable. |
| Did companies that raised funding later increase hiring for retrieval or evaluation roles? | partial evidence | Publication or retrieval time cannot substitute for funding event time; current role mentions alone do not show hiring increases. |
| Which cohort sectors received attention from at least two independent origins? | partial evidence | Publisher diversity is observable, but company passages are not independent documents and claim-level independence/sector labels are not adjudicated. |
| Which companies showed declining repository activity during the last month? | bounded operational calculation | Use the last four complete ISO weeks, first two versus last two; this is a bounded descriptive proxy, not a rolling calendar month or company-wide slowdown. |
| Did LlamaIndex add retrieval roles in the latest observed quarter? | partial evidence | Two archived official career lists and a current list show specific-role stock declining from 8 to 2. They do not establish quarter-wide retrieval-role additions without role-level source review. |
| How did news and public-voice coverage of E2B sandbox infrastructure change over the frozen window? | partial evidence | Dated commentary is available; a stable before/after news and voice collection baseline is not. |
| Did Browserbase combine rising GitHub activity with public attention to browser automation? | partial evidence | Commit history exists; the selected voice extension has no Browserbase passage. Broader documentary mentions require claim-specific review. |
| Did Composio increase postings for agent-tooling or developer-platform roles? | partial evidence | A current complete board is available; no retained historical board baseline establishes an increase. |
| What evidence supports or weakens claims about Letta's agent-memory product? | partial evidence | Repository counts and current jobs do not themselves validate memory-product claims; direct claim-specific supporting and conflicting passages require review. |
| Did Langfuse show growth in GitHub activity and LLM-observability hiring? | partial evidence | Parent-company jobs are not attributed wholesale to Langfuse; its historical role stock is unknown. |
| Did deepset add RAG or NLP engineering roles during the collection window? | partial evidence | The current board supports role inspection, but lacks a retained before/after baseline. |
| For companies with funding announcements, did GitHub activity rise afterward? | partial evidence | Three funding pages provide context; event dates remain unnormalized. Publication dates do not establish funding dates or causality. |
| Which investor led LangSmith's latest funding round? | abstention supported | Do not substitute a LangChain financing page for an independently established LangSmith funding round. |
| What was CrewAI's market share before the 2025-11-01 collection window? | abstention supported | No retained market-share evidence covers the requested period. |
| Which cohort company will acquire a retrieval startup next year? | abstention supported | The requested future outcome cannot be established from observed sources. |
| What private revenue growth did LangChain achieve in the latest quarter? | abstention supported | No such private revenue measurements are retained. |
| Why might a company claim remain emerging after one positive source? | policy only | Use origin control and claim-specific support; no new company-state judgment is made. |
| What evidence would change a technical company claim from corroborated to disputed? | policy only | A hypothetical policy transition is not evidence that a real company claim is disputed. |
| Why should an old hiring claim be marked stale instead of corroborated? | policy only | Age alone does not force stale; a claim-specific validity or refresh basis is needed. |
| Would syndicated copies of the same funding article count as independent origins? | policy only | Copies under common origin/control are not additional independent corroboration. |

Next data priorities are comparable historical role-level board snapshots,
source-grounded funding event dates and company/investor links, and consistent
public-voice sampling with claim-level independence review. Independent
entity/relation annotation and agreement remain a separate review stage; the
completed pilot does not replace them. Reproduce and check the coverage artifact:

```bash
.venv/bin/python -m evaluation.question_coverage --check
.venv/bin/python -m pytest tests/test_question_coverage.py -q
```

### Funding date and investor source review

The [funding source review](../evaluation/submission/funding-source-review.json)
adds exact source-text offsets and source hashes for three retained primary pages.
LangChain's Series C announcement is dated 13 November 2026 and names CapitalG
as lead. Browserbase's Series B announcement is dated 18 June 2025 and names
Notable Capital as lead; that date is outside this study's collection window.
LlamaIndex's Series A text names Norwest Venture Partners as lead, but the
retained page does not establish an announcement day. Its date remains null.
These are source-reported announcements, not verified legal closing dates.

For LangChain, the last retained complete commit window overlaps the announcement
week, and only one retained complete board snapshot is later than the announcement.
There is no complete post-announcement weekly commit trend or pair of later board
snapshots establishing an increase. The review therefore supplies grounded
investor and round components without claiming a funding-to-growth result.
The original frozen source records and benchmark labels are unchanged. Check:

```bash
.venv/bin/python -m evaluation.funding_review --check
```

### Official career archive and browser automation follow-up

The [new careers review](../evaluation/cohort-history-followup/review.json) adds
LlamaIndex's official career lists captured on 21 September and 1 October 2026,
verified against retained CDX entries and archive `Memento-Datetime`. Both show
8 specific roles plus one general talent-pool entry. The 21 November official
page shows 2 specific roles plus one talent-pool entry. Comparing either archive
to that page gives 1 newly observed role, 7 no-longer-observed roles and 1 retained
role, a net change of −6 specific postings. These are listing changes, not hires.
The career-list population is not mixed with a different ATS board's counts.

At that follow-up freeze, historical company coverage was **3/18**: LangChain, Modal and LlamaIndex.
Fifteen companies still lack a comparable historical population. Six retained
archive fetches failed; CrewAI's downloaded Workable pages do not establish a
complete historical list. Retrieval failures and JavaScript shells are unknown,
not zero jobs. The follow-up does not change earlier frozen corpora or scores.
The original 789-reference question inventory links to this separate careers
review rather than counting its new snapshots as old benchmark documents.

The optional [Selenium collector](../collectors/browser_snapshot.py) was run
successfully against the current LlamaIndex page using an explicit list selector.
Its 3 listing entries match the raw current HTML: 2 specific roles and the talent
pool. The isolated session retains its DOM, version and observation metadata in
[`browser-observations`](../evaluation/browser-observations/llamaindex-2026-11-21/manifest.json).
It supplies current-page discovery; it does not establish historical availability.
Historical HTML is parsed without executing scripts that might load current data.
Collection and replay commands are documented in the [collector guide](../collectors/README.md).

Agreement tooling now distinguishes planned positive-label counts from valid
reviewer decisions. Source-supported `NONE` decisions cannot invalidate an
otherwise valid agreement calculation merely because a positive quota is missed.
Personal independent attestations, matching source hashes and complete matching
candidate IDs remain required. The second entity/relation labels remain absent;
no independent agreement statistic has been inferred or generated.

### Expanded ATS history and independent-review collection

The [ATS follow-up](../evaluation/cohort-ats-history/review.json) expands comparable
historical posting coverage to **12/18 companies**, adding Arize, Browserbase,
Composio, deepset, E2B, Letta, Pinecone, Sourcegraph and Weaviate to the previous
LangChain, Modal and LlamaIndex coverage. Eleven current ATS boards are now
attributable. LlamaIndex's native career-list population remains separate from
ATS populations. The initial 789-reference inventory links to these follow-up
snapshots; the scored benchmarks remain unchanged.

Historical Ashby HTML contains `window.__appData.jobBoard.jobPostings`.
The collector decodes that embedded JSON offline and rejects individual posting
pages, wrong employers, duplicate identities, maintenance pages and incomplete
payloads. Greenhouse landing pages contain server-rendered job rows; posting
URLs, identities and visible total-count headers are checked. CDX discovery,
archive `Memento-Datetime`, source bytes and hashes are retained. No archived
page is rehydrated with a current API. Weaviate's board mapping was observed in
the iframe on its official careers page with Selenium. Arize's API was matched
to all 20 job identities in its official careers page before using its history.

| Company | Historical comparison to 21 November 2026 | Posting stock |
|---|---|---:|
| E2B | 17 November 2026 | 13 → 14 |
| Composio | 13 October / 6 November 2026 | 30 → 30 / 31 → 30 |
| Letta | 1 October / 2 November 2026 | 4 → 4 / 4 → 4 |
| Pinecone | 12 June / 13 October 2026 | 7 → 8 / 5 → 8 |
| Weaviate | 27 May 2026 | 4 → 2 |
| Browserbase | 12 November 2026 | 15 → 16 |
| Sourcegraph | 24 September / 4 October 2026 | 7 → 8 / 10 → 8 |
| deepset | 22 July 2026 | 3 → 4 |
| Arize | 8 May / 4 October 2026 | 41 → 20 / 24 → 20 |

These are irregular posting-stock comparisons, not weekly hiring trajectories,
completed hires, payroll headcount or skill-specific increases. E2B's interval
is only four days. Chroma, Continue, CrewAI, Langfuse, Replicate and Weights & Biases
still lack comparable source populations in the retained studies. Parent-company
boards, missing captures and dynamic shells are not substituted as company totals.

An English, loopback-only source-review console is available through
`evaluation.independent_review`. It serves the frozen source and candidate,
highlights entity spans, leaves labels unselected and hides prepared answers.
Each reviewer saves their own decisions into separate JSON files with frozen
source hashes and timestamps. Independence is reviewer self-reported, not an
external identity verification. The console preserves the existing assisted
workbooks and collects new personal decisions separately. Agreement requires
both complete actual decision sets; incomplete inputs produce a count of missing
decisions instead of an invented score. Review agreement is computed before
adjudication. The interface was checked in Chrome without submitting any study
decisions; record-submission tests write only isolated temporary fixtures.

```bash
.venv/bin/python -m evaluation.ats_history --check
.venv/bin/python -m evaluation.independent_review serve --port 8767
.venv/bin/python -m evaluation.independent_review agreement --round real
.venv/bin/python -m evaluation.independent_review agreement --round mixed
```

### Supplemental source-relation compatibility repair

A concurrent source-review expansion added 56 rows to Sueda's relation workbook
outside the original 126-item common candidate pool. Their supporting-passage
cells were empty. The [registered source supplement](../evaluation/real/sueda-review/relation-extension/manifest.json)
now binds each additional document-to-object mention to an exact frozen source
passage, offsets and source hashes. The original candidate pool, its round-input
hash, Mehmet's workbooks and the 30 participant responses are unchanged. The
source-only attestation records the 126 common candidates and 56 supplemental
items separately; it remains explicitly non-independent.

The workbook has 90 positive mention occurrences representing 88 distinct
(document, object) facts. Repeated mentions are not additional independent facts.
The separate frozen 90-distinct-fact source packet remains unchanged. Delivery
verification admits only the registered, source-checked supplement; unknown rows,
blank support and changed candidate fields are still rejected. Independent review
and agreement continue to use the shared frozen pool rather than treating these
supplemental prepared decisions as a second review.

The active direct-review console uses the frozen release annotation packet v2
(776 entity candidates and 100 relation candidates). The mixed-source pool remains
276 entities and 108 relations. These input universes are recorded in each review's
source hashes. The original 126-item release relation seed and its source-only
supplement remain separate from the v2 pairwise pool. Assisted JSON records are
preserved outside `evaluation/independent-review/<round>/direct/`; they neither
prefill the console nor qualify as personal independent decisions.

### Mixed relation source reconciliation

The [source reconciliation](../evaluation/mixed/relation-reconciliation.json)
reviews all 108 supplied source-assisted personal relation judgments. The original
Sueda and Mehmet decisions and confirmation fields are preserved. Before
reconciliation they match on 39/108 items (36.11% raw agreement), with descriptive
Cohen's kappa 0.0095694 and 69 disagreements. These figures describe the supplied
proposal-assisted judgments; they are not independent blind annotation results.

Source review resolves the 69 differing items as 2 `MENTIONS` and 67 `NONE`.
LangChain and LlamaParse are explicitly named typed entities. The rejected objects
are headings, ordinary words, pronouns, a truncated contraction or underspecified
person-name fragments. Each output retains its exact supporting passage, object
and passage offsets, source URL, text hash, original labels and rationale.

Three additional items have matching reviewer labels that conflict with the
existing source policy: `June`, `Paul`, and one `Counts` occurrence. They are
flagged separately, with `NONE` as the source-review resolution. Agreement between
reviewers is not treated as proof of source correctness. Across all 108 items,
the source-assisted final-label set contains 33 `MENTIONS` and 75 `NONE`.

These final labels are a source-assisted reconciliation artifact, not a claim of
personal human adjudicator signoff or an independent gold standard. Original
agreement is reported before reconciliation; it is not recomputed by substituting
one common final-label set for both raters. Frozen retrieval relevance judgments,
model scores and pilot participant responses are unchanged. Reproduce:

```bash
.venv/bin/python -m evaluation.mixed_relation_reconciliation --check
.venv/bin/python -m pytest tests/test_mixed_relation_reconciliation.py -q
```

### Entity seed source-quality check

The [entity source check](../evaluation/submission/sueda-entity-source-check.json)
verifies candidate identity, allowed label, exact entity offsets and supporting
passage membership for all 418 release-seed and 276 mixed-seed items. It preserves
both original source worksheets. Semantic source checks identify 41 release-seed
corrections: 39 positive labels are ordinary headings, imperatives, generic
fragments or lifecycle abbreviations and are recommended as `NONE`; `Responses`
and `Decisions` refer to API interfaces and are recommended as `Technology`
instead of `Document`. Named files `README` and `AGENTS.md` remain `Document`.

The original release seed stores 200 positives. The corrected source-review view
retains 161, including 132 Technology, 23 Product, 4 Startup and 2 Document
mentions; 257 candidates are `NONE`. Counts are not forced to reach an annotation
quota. The separate frozen expanded annotation packet and supplemental entity
inventory are unchanged. Mixed-seed formal checks pass with its existing 118
positive source labels. These are formal checks and documented contextual
corrections; labels carried forward are not a new independent semantic annotation.
No personal entity-agreement statistic is inferred. Reproduce:

```bash
.venv/bin/python -m evaluation.entity_source_check --check
.venv/bin/python -m pytest tests/test_entity_source_check.py -q
```

### Final six-company historical source review

The [remaining-company review](../evaluation/remaining-history-discovery/review.json)
retains all source payloads, archive discovery, capture clocks, source hashes and
listing identities for Chroma, Continue, CrewAI, Langfuse, Replicate and Weights &
Biases. Complete official-population comparisons now cover 13 companies, adding
Chroma to the previous 12. This means complete observed lists at selected dates,
not a complete weekly historical trajectory. Four additional companies have
paired observations for narrower populations. Seventeen companies therefore have
at least one paired public-channel population; that broader count is not presented
as 17 complete company hiring histories.

| Company | Retained source population | Dated observations |
|---|---|---|
| Chroma | Complete official native careers list | 6 roles on 3 October, 6 on 2 November, 6 on 21 November 2026; the same six listing paths |
| Continue | YC employer job channel only | 3 on 1 February, 0 on 13 May, 0 on 21 November 2026 |
| Langfuse | Explicit Langfuse titles in ClickHouse's complete Ashby account | 1 on 30 July, 11 on 17 October, 13 on 21 November 2026 |
| Weights & Biases | Explicit brand titles in CoreWeave's complete Greenhouse account | 1 on 29 September, 1 on 3 November, 5 on 21 November 2026 |
| Replicate | YC employer job channel only | 0 on 11 May and 0 on 21 November 2026 |
| CrewAI | Current complete Workable feed plus separate archived advertisements | 4 current postings; 2 archived role pages dated 15 July and 28 September 2026; historical whole-board stock unknown |

Chroma's two known archive URLs failed earlier HTTP retrieval. An isolated Chrome
fallback disabled page scripts and captured the archived network response body,
not a live-populated DOM. Exact CDX timestamps match archive `Memento-Datetime`;
category totals match six unique role links in each retained payload. The current
rendered official list is retained separately. No hidden weeks are interpolated.

The Continue and Replicate YC employer identities match the frozen official domains.
Their job-list payloads explicitly contain empty arrays at the reported zero-list
observations. Related jobs and individual job pages are excluded. These zeros do
not establish zero company vacancies, hires, employees or momentum. Source-reported
acquisition status does not remove a company from the original frozen cohort.

Parent ATS totals are retained as provenance, not brand totals. Only explicitly
branded job titles enter the Langfuse and Weights & Biases subsets. Newly selected
IDs are checked against the full earlier parent population so a renaming is not
confused with a newly observed parent posting. Subset changes remain posting
observations, not hires or whole-company hiring growth. The dedicated
`weights_and_biases` endpoint was unavailable; it was not treated as an empty board.
Cloudflare description mentions of Replicate do not establish a Replicate team
population, so its full parent account is not substituted for subsidiary hiring.

CrewAI's official website links its Workable account. The public widget and the
provider's machine-readable careers index both show four current openings. Specific
archived advertisement metadata identifies a Customer Success Manager, LATAM role
and a Software Engineer, Infrastructure & Reliability role. The first posting ID
is still in the retrieved current board; the second is not. Neither an advertisement
page nor its absence from the current list establishes a hire or a complete past
board population. CrewAI therefore remains without a paired complete stock baseline.

The collection stage is documented with these explicit population limits. Earlier
corpora, relevance judgments, personal reviewer decisions and pilot measurements
are unchanged. The original temporal benchmark is not retroactively rescored using
these follow-up sources. Reproduce the offline review:

```bash
.venv/bin/python -m evaluation.remaining_history_review --check
.venv/bin/python -m pytest tests/test_remaining_history_review.py -q
```
