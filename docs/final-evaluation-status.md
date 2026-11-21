# Final evaluation status

Active round: [45 real release documents](../evaluation/real/README.md).
Measured execution and limitations: [evaluation report](final-report.md).

| Requirement | Workspace evidence |
|---|---|
| Real 40–50 document corpus | 45 real documents frozen with raw sources and checksums; inclusion review records required |
| 200+ entity mentions | 418 candidates prepared; completed independent labels not located |
| 80–100 relations | 126 candidates prepared; completed independent labels not located |
| Sueda/Mehmet independent relabelling | Separate files and attestations prepared; completed inputs not located |
| Human kappa on 100+ shared items | Calculation ready; independent labels required |
| Relevance qrels | 2,520 source-reviewed judgments completed across original and release-fact studies; reviewer provenance retained |
| Scored retrieval evaluation | Raw top-5 scores for three document retrievers and citation scores for four answer conditions; 224 saved bundles |
| Trust pilot with 5–8 people | Protocol ready; participant measurements not located |
| Final report | Evidence-based report written; missing results explicitly recorded |
| Verified contribution record | Four members recorded; verification references required |

The user states the human work was completed. This status distinguishes that
statement from the underlying records available for calculation.

```bash
.venv/bin/python evaluation/real_round.py validate
```
