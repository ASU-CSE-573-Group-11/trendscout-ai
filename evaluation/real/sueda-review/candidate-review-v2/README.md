# Source-review candidate revision 2

This packet consolidates Sueda's first project source review over the frozen
45-document release corpus. It preserves the earlier corpus and candidate seed.

- `reviewed-entities.csv`: 776 decisions, including 500 accepted entity mentions.
- `reviewed-relations.csv`: 100 decisions, including 90 accepted documentary
  MENTIONS facts and 10 rejected heading/fragment candidates.
- `candidates.json`: the same IDs, offsets, objects, and passages, with empty
  label/note fields for a subsequent independent pass.
- `manifest.json`: source-snapshot and base-candidate fingerprints, file hashes,
  method, counts, and relation-sampling rule.

The relation sample takes one distinct document/object fact per document per
pass until 90 have been selected, then adds the first 10 rejected original
candidates. This is a defined candidate-classification set, not an unbiased
sample of semantic funding/hiring relations. No extraction F1 is claimed.

For the second review, distribute only `candidates.json`, the frozen source
records, and the guidelines. Keep the first-review files separate until both
passes are locked. Software checks common IDs and empty candidate labels;
actual independence requires the reviewers' genuine process records.

```bash
.venv/bin/python -m evaluation.verify_sueda_delivery
```
