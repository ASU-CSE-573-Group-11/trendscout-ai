# Cohort ATS closure

Completed by Sueda Sen and Mehmet Aksit on 23 November 2026.

This is not a Vidya Sagar Dudekula deliverable. The assigned Greenhouse and Lever registry fields were still empty, so this branch records only boards already audited in `evaluation/cohort-source-audit/board-audit.json`.

- Browserbase: `greenhouse_board` = `browserbaseinc` (16 listings collected)
- Sourcegraph: `greenhouse_board` = `sourcegraph91` (8 listings collected)
- No Lever board was present in the audit, so every `lever_site` stays null.
- The other 16 companies stay null in those two fields. Their audited ATS, usually Ashby or Workable, is listed in `mapping.json`.

Replay a snapshot without the network:

```bash
python -m collectors --replay evaluation/sueda-mehmet-ats-closure/collector-runs/<run>/snapshot.json --output-dir /tmp/ats-replay
```
