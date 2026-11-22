# Greenhouse, Lever, and GitHub collectors

Owner: Vidya Sagar Dudekula.

## Run

From the repository root, using Python 3.10+:

```bash
python -m pip install -r requirements-collectors.txt
python -m collectors --source greenhouse --target BOARD_SLUG --company-id COMPANY_ID --company-name 'Company Name'
python -m collectors --source lever --target BOARD_SLUG --company-id COMPANY_ID --company-name 'Company Name'
python -m collectors --source github --target OWNER/REPO --company-id COMPANY_ID --company-name 'Company Name'
```

Use the company's ID from `data/registry/cohort.json`. Lever supports `--region eu`.
GitHub reads an optional `GITHUB_TOKEN` environment variable; `.env` is not loaded.
Private repositories are rejected, even with an authenticated token.

For an offline demo:

```bash
python -m collectors --replay tests/fixtures/collectors/greenhouse.json
python -m collectors --replay tests/fixtures/collectors/lever.json
python -m collectors --replay tests/fixtures/collectors/github.json
```

Fixtures are synthetic. Replay also accepts a previously collected `snapshot.json`
and preserves its observation time. It never makes old data appear freshly collected.

## Output

Each attempt creates a directory under `artifacts/collectors/` (gitignored).
Change the destination with `--output-dir`.

- `snapshot.json`: source payload, company identity, observation time, and coverage.
- `records.jsonl`: normalized records validated against `schemas/record.schema.json`.
- `manifest.json`: success/failure, count, coverage, timestamps, and collector version.

Only consume runs whose manifest says `success`. Failures exit with code 1 and
never masquerade as empty boards. GitHub snapshots retain repository fields and
commit SHA/date/account type; names, emails, profiles, and messages are discarded.

## Record contract

`company_id`, `origin_cluster_id`, `title`, and `collector_version` are top-level
fields, matching the current graph and retrieval contracts.

- `record_id` combines the source identity and a hash of normalized evidence.
  Observation time is excluded: unchanged jobs keep their IDs across runs.
- `metadata.source_record_id` stays stable when content changes. Consumers should
  upsert by `record_id` and keep observation history from snapshots/manifests.
- `origin_cluster_id` defaults to the shared canonical URL hash. Separate jobs
  remain separate documents. `metadata.source_control_group` tracks company control;
  different documents do not automatically mean independent corroboration.
- Version-1 snapshots replay into the current schema with new IDs/hashes. Their
  old company-level default origin is migrated; explicit custom origins are kept.
  New snapshots use version 2. Do not mix old-schema JSONL with replay output.

Job titles receive case/whitespace normalization. Skills use a small explicit-mention
vocabulary, without inferring requirements or negation. Greenhouse `updated_at`
stays in metadata; unsupported publication/event dates remain null.

GitHub emits one record per repository with counters, quality flags, and a trailing
seven-day default-branch commit window. Use `--window-days` to change the window.
Pagination is pinned to one branch tip; the interval is `(start, end]`. This is
not a calendar-week aggregate. Stars/forks are current counters, not weekly growth.
`open_issues_count` includes pull requests. `bot_heavy` means at least half the
commits have GitHub account type `Bot`; unknown authors are counted separately.
The source description stays in `text`; derived metrics stay in metadata.

Requests use a 30-second timeout and at most three attempts. Rate-limit headers
are respected; required waits over 60 seconds fail for a later retry. Redirects,
repeated pages, malformed responses, and pagination caps fail explicitly.
Lever/GitHub default to 100 pages (`--max-pages`). Missing jobs are not interpreted
as filled positions. EWMA and dense retrieval remain downstream work.

## Tests and integration

```bash
python -m unittest discover -s tests -p test_collectors.py -v
python -m pip install -r requirements.txt
python -m pytest -q
```

The collector suite has 49 tests; the full suite passes 72 tests and 21 subtests.
Coverage includes normalization, schema, identity, retries, pagination, replay,
privacy, graph import, and BM25 evidence handoff. One pytest/RDF namespace warning
is present in the full suite.

Live checks on November 10, 2026 (Phoenix time):

| Source | Target | Result |
|---|---|---|
| Greenhouse | Anthropic | 679 postings |
| Lever | ShyftLabs | 28 postings |
| GitHub | langchain-ai/langchain | 1 snapshot; 35 commits, 11 bot-attributed |

All 708 records passed graph conversion, RDF export, and SHACL validation together.
BM25 returned five results with source URLs for `Python engineer`. Each live API
run used one page; multi-page paths are tested offline.

Anthropic and ShyftLabs are connectivity checks outside the frozen cohort.

## Frozen cohort job boards

The November 21 Phoenix collection observed 16 Browserbase listings and 8
Sourcegraph listings. Both Greenhouse slugs are in the registry. No company-owned
Lever site was verified. Arize has a separate 20-listing Greenhouse snapshot.
The two-board registry scope follows the demo assignment. Arize's later
ID-level verification is recorded separately below.

| Company | Verified board or public hiring channel | Evidence |
|---|---|---|
| LangChain | Ashby `langchain` | [Board audit][audit] |
| LlamaIndex | Official careers page with a native role list | [Careers review][native] |
| CrewAI | Workable `crewai` | [Workable widget review][review] |
| E2B | Ashby `e2b` | [Board audit][audit] |
| Browserbase | Greenhouse `browserbaseinc` | [Board audit][audit] |
| Composio | Ashby `composio` | [Board audit][audit] |
| Letta | Ashby `letta` | [Board audit][audit] |
| Langfuse | Archived Ashby `langfuse`. The live board returned 404. | [Archive findings][archives] |
| deepset | Ashby `deepsetai` | [Board audit][audit] |
| Continue | Archived Ashby `continue`. The live board returned 404. | [Archive findings][archives] |
| Sourcegraph | Greenhouse `sourcegraph91` | [Board audit][audit] |
| Modal | Ashby `modal` | [Board audit][audit] |
| Replicate | Archived Ashby `replicate`. The careers link now points to Cloudflare. | [Archive findings][archives] |
| Weights & Biases | Greenhouse `coreweave` is the parent board. The dedicated `weights_and_biases` endpoint returned 404. | [Channel review][review] |
| Pinecone | Ashby `pinecone` | [Board audit][audit] |
| Weaviate | Ashby `weaviate` | [Verified board](../evaluation/cohort-ats-history/weaviate-discovery.json) |
| Chroma | Official careers page with a native role list | [Careers review][review] |
| Arize | Greenhouse `arizeai`. All 20 posting IDs matched Arize's careers page in the later audit. | [Arize ID check](../evaluation/cohort-ats-history/arize-candidate-check.json) |

[audit]: ../evaluation/cohort-source-audit/board-audit.json
[native]: ../evaluation/cohort-history-followup/review.json
[review]: ../evaluation/remaining-history-discovery/review.json
[archives]: ../evaluation/remaining-history-discovery/followup-2026-11-21-findings.json

The [snapshot manifest](../evaluation/vidya-cohort-jobs/manifest.json) lists
observation times, source URLs, counts, checksums, and normalized records.
Replay a board from the repository root with
`python -m collectors --replay evaluation/vidya-cohort-jobs/browserbase/snapshot.json`.
Use `sourcegraph` or `arize` in the same path for the other boards.

The snapshots retain the complete listing-metadata response. Greenhouse omits
descriptions on this endpoint, so skill extraction here sees only titles.
Collector v1 normalizes title case and whitespace and recognizes 11 explicit
skill terms. Downstream role families are defined in
[`signals/job_features.py`](../signals/job_features.py).

Each board was observed once, after the October 30 study cutoff. Weekly hiring
comparisons use the separate [historical board review][review]. Süeda's
[GitHub history](../evaluation/cohort-history-v2/manifest.json) covers eight
weeks for each of the 18 companies.

## Sources and dependencies

Team-authored code and synthetic fixtures. Requests uses Apache-2.0; jsonschema
uses MIT. Provider content remains subject to its own terms. Keep live snapshots
local and review redistribution terms before sharing them.

- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html)
- [Lever Postings API](https://github.com/lever/postings-api)
- [GitHub repositories](https://docs.github.com/en/rest/repos/repos), [branches](https://docs.github.com/en/rest/branches/branches), and [commits](https://docs.github.com/en/rest/commits/commits)
- [GitHub rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
