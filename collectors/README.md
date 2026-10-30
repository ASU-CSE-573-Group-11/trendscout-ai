# Collectors

Independent collection modules. Every collector must output records compatible with `schemas/record.schema.json`.

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
