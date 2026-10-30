# Evidence Ledger

The evidence ledger records why a claim is accepted, qualified, disputed, superseded, or rejected. It is not a separate source of truth; it is an auditable layer over source passages and graph claims.

## Evidence states

| State | Working rule | Answer behavior |
|---|---|---|
| `emerging` | Supported by one independent document or one operational signal and not contradicted by stronger evidence | Qualify the answer |
| `corroborated` | Supported by at least two independent origins, or by one documentary source plus one operational signal | Answer with the evidence path |
| `disputed` | Credible evidence disagrees on a material entity or relationship; amounts differ by more than 10%; dates differ by more than 7 days | Show the conflict; do not silently resolve it |
| `stale` | A newer snapshot supersedes the claim, two refresh windows were missed, or `valid_to` expires | Mark the time limit. Historical events stay historical; they do not become stale only because time passed |
| `insufficient` | Available evidence does not justify a factual answer | Abstain and name the missing evidence |

Syndicated copies that share the same origin do not count as independent sources. Origin membership is stored on each source record as `origin_cluster_id`.

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
