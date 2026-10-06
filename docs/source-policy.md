# Source Policy — Draft

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

Every retained record must include its source URL, observation time, content hash, and an access note when relevant.

