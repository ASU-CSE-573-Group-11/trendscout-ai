#!/usr/bin/env bash
set -euo pipefail

repo="ASU-CSE-573-Group-11/trendscout-ai"

if [[ -z "${GH_TOKEN:-}" ]]; then
  echo "GH_TOKEN is not set. Read a GitHub token into GH_TOKEN before running this script." >&2
  exit 1
fi

command -v gh >/dev/null 2>&1 || {
  echo "GitHub CLI (gh) is required." >&2
  exit 1
}

root_dir="$(git rev-parse --show-toplevel)"
protection_file="$root_dir/.github/branch-protection.json"

gh api --method PUT "repos/$repo/collaborators/SuedaSen" -f permission=admin >/dev/null
gh api --method PUT "repos/$repo/collaborators/mcaksit" -f permission=admin >/dev/null
gh api --method PUT "repos/$repo/branches/main/protection" --input "$protection_file" >/dev/null

echo "Configured @SuedaSen and @mcaksit as repository admins."
echo "Protected main with required pull requests and code-owner review."
