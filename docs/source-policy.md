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

## Frozen coursework snapshots

`collectors.snapshot` stores decoded public feed bodies as UTF-8 with SHA-256
checksums, frozen configuration, collection time, and request failure notes.
It reproduces normalized records offline. Endpoint revisions are explicit;
they do not backdate observations or change cohort membership. Successful
fetches, valid feeds, and retained cohort matches are reported separately.

Cached publisher text retains its original rights. Public RSS access is not a
blanket redistribution license. The delivery snapshot is a local coursework
cache; review publisher terms before distributing full raw bodies. Reference
registry assertions are distinguished from fetched source evidence. Core
Python dependencies use their upstream licenses: Requests (Apache-2.0),
feedparser (BSD-2-Clause), jsonschema (MIT), RDFLib (BSD-3-Clause), pySHACL
(Apache-2.0), and pytest (MIT). No repository-wide license is inferred for team
code; the team must select its distribution license before publication.

## YC identity source checks

The current source review is frozen separately in
`evaluation/cohort-identity-review/`. Its `usable-profiles.json` is the list of
YC profiles supported by a fetched name/domain match. New YC identity claims
must use that list, not treat the original cohort's URL strings as verification.
All 18 cohort rows are accounted for; 11 configured URLs were fetched. Langfuse,
Continue and Replicate match their frozen official domains. Seven configured
URLs returned 404. Seven other companies have no configured YC assertion.

The recorded `/companies/modal` profile describes an auto-commerce company
formerly Drive Motors at modalup.com. It does not support the frozen serverless
compute company at modal.com and is excluded from the usable-profile list.
This source decision retains exact passages and the fetched page fingerprint.
An unavailable profile is not evidence that a company never attended YC.
Current checks do not supply historical membership, YC batch dates, funding
events or hiring observations. The original cohort, study snapshots and earlier
unverified registry-assertion records remain intact.

## Restricted hiring populations and archive-browser fallback

Employer job-list payloads on YC are a separate source from a YC identity profile.
They may support a restricted job-channel comparison after name/domain matching.
Only the employer's explicit `jobPostings` array is counted; related jobs and
individual advertisement pages do not establish a complete employer population.
A zero array means zero postings on that channel, with company-wide hiring unknown.
A directory membership or team-size field is not used as a momentum/headcount signal.

For acquired brands, retain parent publisher/control attribution. A declared title
filter can compare explicitly branded roles across complete parent ATS snapshots;
parent totals, generic descriptions and unbranded roles are not assigned to the
cohort brand. Changes in branding can alter subset membership. Newly selected IDs
are checked against all baseline parent IDs before describing any listing change.
These limited subsets are reported separately from complete official career lists.

An archive-browser fallback retrieves the archived main-document network response
with page scripts disabled. Require HTTP 200, the exact requested archive URL,
a timezone-qualified `Memento-Datetime` matching the retained CDX timestamp, and
retained response bytes/hash. Parse those bytes offline. A rendered archived DOM
that loaded a current API is not accepted as a historical listing snapshot.
