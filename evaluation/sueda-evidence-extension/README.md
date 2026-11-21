# Dated evidence extension

This separate source freeze supplements the earlier documentary and experiment
snapshots. It does not change their questions, labels, answers, or scores.

Five dated public-voice articles from Simon Willison and Latent Space produce
eight company-association passages. Associations from the same article are one
documentary origin, not independent corroboration. The source window is
1 November 2025 through 21 November 2026. `articles.json` preserves normalized
article text; `sources/` retains the fetched bodies. Date-only publication
values explicitly use day precision; UTC midnight is normalization, not an
observed publication instant. Commentary is not confirmation of a financing.

The archived LangChain Ashby board contains 104 listed postings at
2026-10-21T16:36:07Z; the current board contains 102 at
2026-11-21T07:50:03Z. Comparing stable posting IDs yields 26 newly observed,
28 no longer observed, and 76 retained postings: a net change of **−2**.
This is a posting-count decrease, not evidence of hiring growth, hires, filled
positions, or funding causality. One company and two observations do not provide
a cohort-wide weekly trajectory. Missing intervening weeks remain unknown.

Archive provenance binds the CDX-selected timestamp to the response's
`Memento-Datetime` and saved payload hash. Source records retain retrieval time;
`metadata.source_snapshot_at` records the board capture time used for weekly
feature placement. Posting identities remain stable across captures while
observation IDs distinguish captures. `manifest.json` fingerprints the source
bodies, frozen cohort, and derived files.

The existing trend pipeline produces 34 weekly series in `signals/`. Weeks
2026-W44 through W46 have unknown values between the observed W43 and W47.
All 170 scored series/week outputs are `insufficient_history`. No rising
hiring trend is inferred from these two observations.

Replay without network access:

```bash
.venv/bin/python -m collectors.evidence_archives replay
.venv/bin/python -m evaluation.verify_sueda_delivery
```

Independent annotation, second review, agreement, participant answers and task
durations remain separate inputs. This collection creates none of those results.
