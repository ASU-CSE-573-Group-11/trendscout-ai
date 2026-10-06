# Evidence Ledger

The evidence ledger records why a claim is accepted, qualified, disputed, superseded, or rejected. It is not a separate source of truth; it is an auditable layer over source passages and graph claims.

## Evidence states

| State | Working rule |
|---|---|
| `emerging` | Supported by one source or one operational signal and not contradicted by stronger evidence |
| `corroborated` | Supported by at least two independent sources, or by one documentary source plus one operational signal |
| `disputed` | Credible evidence disagrees on a material entity, amount, date, or relationship |
| `stale` | The validity window has expired or a newer observation supersedes the claim |
| `insufficient` | Available evidence does not justify a factual answer |

Syndicated copies that share the same origin do not count as independent sources.

## Minimum ledger entry

Each entry should preserve:

- claim identifier and normalized claim text;
- subject, predicate, and object or event fields;
- event/valid time and observation time;
- exact supporting or contradicting passage identifier;
- source URL, publisher, content hash, and origin cluster;
- extraction method and model/rule version;
- confidence and current evidence state;
- state-change timestamp and a short machine-readable reason.

## Decision behavior

- Never convert a trend score into a claim of objective future performance.
- Prefer qualification over silent conflict resolution.
- When evidence is insufficient, return the missing evidence needed to answer.
- Preserve prior states so the team can explain how and when a conclusion changed.
- Tune thresholds only on development data and report them with evaluation results.
