# Proposal gap collection

Collected by Sueda Sen and Mehmet Aksit on 23 November 2026. This branch does not replace the frozen 18-company graph. A record exists only when a public URL returned a page.

The earlier gap list was a count of that frozen graph, not a scrape. The graph kept 3 funding pages and at most 25 job listings per company. `evaluation/cohort-job-history/records.jsonl` already held 393 job observations before this run.

## What this run fetched

| Proposal item | Result |
|---|---|
| Job observations, 150–300 | 238 live listings from the audited board APIs. Greenhouse: Browserbase 16, Sourcegraph 8. Ashby: the other boards that answered. Nine companies have no board in the audit, so nothing was requested for them. |
| Greenhouse and Lever for all 18 | Greenhouse stays those two slugs. The audit contains no Lever slug, so no Lever URL was called. |
| Funding events, 20–40 | 18 public pages contained a funding sentence and were kept. Two extra candidate URLs failed: Browserbase `/blog/series-a` had no funding sentence, and a guessed Pinecone Series A URL returned 404. Amounts stay inside the page text. An announcement date is not a close date. |
| News and public-voice documents, 120–180 | 2 TechCrunch items matched a cohort name. 6 public-voice items matched. 112 posts came from company feeds that responded, capped at 40 per feed: CrewAI, E2B, Continue, Pinecone, and Arize. The other 13 company domains had no feed at the paths that were tried. Together that is 120 documents. Most of them are E2B and Pinecone posts, not an even news sample. |
| Wikidata | Search ran for all 18 names. 15 returned at least one label hit. 3 returned none. A label hit is not an identity check. |
| SEC EDGAR | The project user agent received HTTP 403. EDGAR asks for a contact email in the user agent. No filing count is recorded. |
| LDA | Fitted with `lda_collapsed_gibbs_v1` on 138 news, funding, company, and voice documents. `underpowered` is false. Topics are a baseline, not a ranking. |
| Transformer NER | `dslim/bert-base-NER` ran on 20 texts and returned 123 spans. Those spans are not human labels. |

Rerun from the repository root:

```bash
PYTHONPATH=. python evaluation/sueda-mehmet-proposal-gaps/collect.py
```
