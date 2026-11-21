# Submission review status

Reviewed on 21 November 2026 (America/Phoenix).

| Area | Verified output | Remaining requirement |
|---|---|---|
| Contribution evidence | Four members' local commit objects, recorded authors and changed paths checked; prepared-deliverable hashes checked. | All four project-account mappings are confirmed by GitHub commit data and team confirmation. Independent annotation/pilot measurements are not inferred from commits. |
| Source-review artifacts | Sueda's 45-document first review, 500 accepted entity mentions, 90 documentary relations, and 1,260 first-pass relevance grades verified. | Independent second review and final adjudication. |
| Retrieval measurements | 224 release-study saved answers and scores verified; the mixed-source study retains 196 additional answers. | Primary temporal multi-hop success and semantic dense comparison are not established. |
| Pilot enrollment | Five consent reports recorded: four-member group approval reported by P05 and P05's self-consent. | Actual responses, measured task times, confidence, and task-key adjudication. There are no pilot results yet. |
| License inventory | Direct requirement declarations and installed distribution license metadata inventoried; public-source fetch/access notes retained. | Team-wide code license and publisher redistribution clearance have not been established. |
| Repository access | Private visibility, main branch and collaborator roles read from the live authenticated GitHub API. | Branch-protection API returned HTTP 403 for the current plan/visibility; enforcement is not verified. |
| Archive | Local review archive includes code, docs, snapshots, measurements, open-input status and file hashes. | It is not a declaration of a complete research submission or permission to publish third-party data. |

## Evidence files

The machine-readable evidence is under `evaluation/submission/`:
`contribution-audit.json`, `license-access-inventory.json`, `access-review.json`,
and `submission-status.json`. The pilot's real response collection files and
assignment instructions are under `evaluation/real/pilot-session/`.

```bash
.venv/bin/python -m evaluation.verify_sueda_delivery
.venv/bin/python -m evaluation.submission_audit audit
.venv/bin/python -m evaluation.submission_audit build --out artifacts/submission-review.zip
```

The archive excludes Git metadata, credentials/configuration directories,
virtual environments, caches, and generated artifact directories. It retains
public-source material for local coursework review. The archive manifest lists
checksums for every packaged file and explicitly records incomplete research
requirements. No synthetic participant or task result is counted as empirical
evidence.
