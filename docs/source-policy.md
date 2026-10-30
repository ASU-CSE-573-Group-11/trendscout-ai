# Source Policy - Version 1.0

| Source | Core status | Collection method | Main restriction |
|---|---|---|---|
| GitHub | Core | Public REST API | Respect rate limits; flag mirrors and bot-heavy activity |
| Greenhouse | Core | Public Job Board API | Do not collect applicant data |
| Lever | Core | Public Postings API | Retain only public job information |
| Company newsrooms | Core | RSS or permitted public pages | Preserve URL and dates |
| Technology news | Core | RSS or permitted public pages | Deduplicate syndicated copies |
| Public voices | Core, curated | RSS, blogs, newsletters, and public video metadata | Record source and access method |
| LinkedIn | Optional | Only when access is reproducible and permitted | The core system must not depend on it |
| Private profiles or restricted content | Excluded | None | Do not collect |

Named websites and RSS endpoints used by Sueda's collectors live in `data/registry/named_sources.json`. The frozen company list lives in `data/registry/cohort.json`.

Every retained record must include its source URL, observation time, content hash, origin cluster, and an access note when relevant.

## Independence and corroboration

- Syndicated copies and reposts sharing one origin count as one evidence source.
- Company announcements may establish what the company stated, but an independent source is required before the statement is labeled independently corroborated.
- GitHub, hiring, and funding signals must be interpreted in context; none is treated as a standalone measure of company quality.

## Storage and privacy

- Store organization-level public information only.
- Do not store applicant information, private profiles, session cookies, passwords, or access tokens.
- Cache only what is necessary for reproducible coursework and record applicable source terms.
- Raw data stays local by default. Share only permitted and documented snapshots.

## Failure behavior

If a source becomes unavailable, restricted, or non-reproducible, the system must continue from the last permitted frozen snapshot and identify the affected coverage. The core demo must not depend on LinkedIn or a paid database.
