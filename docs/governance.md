# Repository Governance and Review Policy

## Administrative control

- Repository administrators: `@SuedaSen` and `@mcaksit`.
- Other contributors receive only the access needed for their assigned work.
- Organization owners may retain implicit administrative access under GitHub's organization rules; organization ownership should therefore be limited separately if exclusive control is required.

## Protected branch

The default branch is `main` (not `master`). No contributor, including an administrator, should work directly on or push directly to `main`.

Every change follows this path:

1. Create a focused branch from the current `main`.
2. Commit and push changes to that branch.
3. Open a pull request using the repository template.
4. Resolve review conversations.
5. Obtain approval from at least one code owner on the latest revision.
6. Merge through GitHub after all protection requirements pass.

## Enforced controls

- Pull request required before merging.
- At least one code-owner approval required.
- The author of the latest push cannot satisfy the approval requirement alone.
- New commits dismiss stale approvals.
- Unresolved review conversations block merging.
- Administrators are subject to the same branch protection.
- Force pushes and deletion of `main` are blocked.
- Linear history is required.
- No bypass users, teams, or apps are configured.

## Local branch example

```bash
git switch main
git pull --ff-only
git switch -c sueda/source-pilot
```

Direct commits to a local `main` branch are technically possible, but the GitHub protection rule prevents them from being pushed or merged without the required pull-request review.
