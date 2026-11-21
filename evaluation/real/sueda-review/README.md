# First source review for Sueda's release-study deliverables

The existing `../workbooks/sueda-entities.csv` and `sueda-relations.csv` now
contain source-based decisions for all 418 and 126 frozen candidates.
`../workbooks/corpus-review.csv` contains the 45 `sueda_include` decisions.
`../workbooks/qrels.csv` contains 1,260 `sueda_grade` values and rationale notes.
Second-review and final-adjudication values are preserved.

Candidate headings such as “Release”, “Notes”, “What”, “Changed”, and “Features”
are rejected as `NONE`. Source-supported named software, models, APIs,
algorithms, products, and startups receive the corresponding allowed type.
The reviewed vocabulary and method are in `evaluation/review_workbooks.py`.

`additional-entities.csv` supplies 358 exact source spans missed by the
capitalized-first-12 candidate seed. Together with 142 accepted seed mentions,
the first review has 500 distinct labelled entity mentions.
`relation-inventory.csv` retains 220 distinct document/named-object facts.
`relations-90.csv` is a deterministic 90-fact sample, taking one fact per document per pass
in frozen document/source-span order, with the `MENTIONS` relation and a supporting
passage. These are documentary mentions, not inferred causal relations.

The original shared candidate set is preserved. The explicit
[`candidate-review-v2`](candidate-review-v2/README.md) packet consolidates the
seed and supplemental spans into one first-review dataset with matching empty
common candidates. It contains 776 entity candidates (500 accepted) and 100
relation candidates (90 accepted and 10 rejected). Its manifest binds this
revision to the existing source snapshot and original candidate seed.
Original worksheets and pilot setup are preserved under `before-*` filenames.
The attestation identifies a project source review prepared on behalf of the
assigned owner. It makes no statement that Sueda or Mehmet personally completed
an independent annotation round. No second-review labels are copied or invented.

Pilot task keys, five reported consent records, and frozen task assignments
are prepared in `../trust-pilot.json` and `../pilot-session/`.
`pilot-evidence-policy.md` is the checksummed policy reference. No actual
participant task responses or measurements have been submitted yet.

```bash
.venv/bin/python -m evaluation.verify_sueda_delivery
```
