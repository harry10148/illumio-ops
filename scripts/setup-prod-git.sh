#!/usr/bin/env bash
# One-time git config for prod / deployment boxes.
#
# Why:
#   `git pull` on a deployment box often aborts because someone edited a
#   tracked file in place (deploy script, ingestor module, install script,
#   etc.). Enabling autoStash makes pull stash → fast-forward → pop, so
#   local edits survive without aborting the merge.
#
# Run once per deployment box. Idempotent.
set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "ERROR: not inside a git repo" >&2
    exit 1
}

echo "==> Enabling autoStash for merge and rebase (local repo only)"
git config --local merge.autoStash true
git config --local rebase.autoStash true

echo "==> Final settings:"
printf '  %-25s %s\n' "merge.autoStash"  "$(git config --local --get merge.autoStash)"
printf '  %-25s %s\n' "rebase.autoStash" "$(git config --local --get rebase.autoStash)"

echo
echo "Done. Future 'git pull' will auto-stash local edits and pop them"
echo "afterwards instead of aborting with 'would be overwritten by merge'."
