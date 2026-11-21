# Collectors

Independent collection modules. Every collector must output records compatible with `schemas/record.schema.json`.

## Vidya Sagar Dudekula — Greenhouse, Lever, and GitHub APIs

See [API_COLLECTORS.md](API_COLLECTORS.md) for setup, live collection, offline
replay, schema/graph integration, and coverage limitations. Run the API CLI with
`python -m collectors`. Its retry helper is `api_http.py`; Süeda's existing
`http.py` and `python -m collectors.run` interface remain available.

## Sueda Sen — news, voices, company RSS, YC identity

This module collects the named documentary sources from the 28 October data plan. It does not collect Greenhouse, Lever, or GitHub activity; those remain Vidya's module.

| Input | Output |
|---|---|
| `data/registry/cohort.json` | Schema-valid JSON records |
| `data/registry/named_sources.json` | Coverage notes and quarantine failures |
| Optional `YOUTUBE_API_KEY` | Public video metadata only |

### Commands

```bash
python -m pip install -r requirements.txt
python -m pytest
python -m collectors.run
python -m collectors.run --live --out data/processed/sueda
python -m collectors.run --live --youtube --query "LangSmith hiring"
```

`--live` fetches permitted public RSS feeds with the project User-Agent and a short delay. Offline mode is the default and is what tests use.

### Record contract extras

Beyond the original required fields, Sueda records store `company_id`, `title`, the exact supporting passage in `text`, `origin_cluster_id`, and `collector_version`. Syndicated copies keep separate `record_id` values but share `origin_cluster_id`.

### Limits

- News and public-voice RSS captures the current feed window, not a guaranteed 6–12 month archive.
- Company RSS URLs missing from the frozen registry are skipped and recorded in coverage.
- YouTube collection is skipped unless `YOUTUBE_API_KEY` is present.
- A YC directory row is an identity record, not a trend score.

## Frozen documentary snapshot and replay

The [Sueda delivery corpus](../evaluation/sueda-delivery-corpus/README.md)
preserves decoded RSS/Atom source bodies, request failures, configuration,
checksums, dated records, and BM25 smoke queries. Reproduce it offline:

```bash
python -m collectors.snapshot replay --directory evaluation/sueda-delivery-corpus
```

Create a new freeze with a new directory and `collectors.snapshot collect`.
Use `--overrides data/registry/collection-endpoints.json` for documented current
endpoint corrections. The original cohort membership and IDs remain fixed.
YC records produced without fetching the page are registry assertions, not
verified directory content; publication and event dates stay unknown.

## Optional browser rendering and historical careers replay

Use saved official API responses and raw HTML first. For a current page whose
content loads through JavaScript, the optional Selenium collector uses an isolated
headless Chrome session and a site-specific explicit readiness selector. It saves
the rendered DOM, source URL, observation clock, browser/driver versions and SHA-256.
Selector presence does not establish a complete board. Iframes require separate
source inspection; the parent DOM does not contain their full listings.

```bash
.venv/bin/python -m pip install -r requirements-browser.txt
SE_CACHE_PATH=/tmp/trendscout-selenium-cache .venv/bin/python -m collectors.browser_snapshot \
  --company llamaindex --url https://www.llamaindex.ai/careers \
  --selector 'ul.RoleList a' --out /tmp/trendscout-new-careers-observation
.venv/bin/python -m evaluation.career_history --check
```

Choose a new output directory for each observation; overwriting is rejected.
Selenium Manager may download a matching driver. An existing driver can be supplied
with `--driver-path`; a Chrome binary can be supplied with `--browser-binary`.
See Selenium's official [waiting guidance](https://www.selenium.dev/documentation/webdriver/waits/)
and [driver management documentation](https://www.selenium.dev/documentation/selenium_manager/).
The verified live example is `evaluation/browser-observations/llamaindex-2026-11-21`.

Historical stock uses retained archive responses, CDX discovery and matching
`Memento-Datetime`, parsed offline without JavaScript. Rendering an archived page
can call a current API; it must not create historical observations. The saved
acquisition scripts in `evaluation/cohort-history-followup/acquisition` retain
this round's query settings and reject overwriting the existing acquisition.
LlamaIndex comparisons use the same official `RoleList` parser at all dates,
separating general talent pools from specific roles. Other dynamic shells and
failed archive requests remain unknown, with failures retained.

Independent review is a separate measurement step: automation can prepare source
items and compute agreement after actual decisions. `evaluation.real_round
agreement` verifies reviewer attestations and file hashes. Planned positive-label
counts are reported separately; reviewers must not assign unsupported positives
merely to meet a quota.

## Exact archived network-response fallback

When HTTP retrieval fails for a known official-domain capture, use the optional
`collectors.archive_browser` command. It disables page scripts and retains the
main-document response body through Chrome's
[Network.getResponseBody](https://chromedevtools.github.io/devtools-protocol/tot/Network/#method-getResponseBody),
with matching CDX/Memento clock checks. The output is the network response, not a
DOM populated by current APIs. Choose a new output directory for each attempt.

```bash
SE_CACHE_PATH=/tmp/trendscout-selenium-cache .venv/bin/python -m collectors.archive_browser \
  --company chroma --original-url https://www.trychroma.com/careers \
  --timestamp 20261102064608 --out /tmp/chroma-known-archive-retrieval
.venv/bin/python -m evaluation.remaining_history_review --check
```

The retained review separates full official-list populations, YC employer job
channels, explicit brand-title subsets in parent ATS accounts, and individual
historical advertisement pages. Category totals, employer identity, unique IDs,
source hashes and clocks are checked before comparisons. Original source files
and earlier benchmark datasets remain frozen.
