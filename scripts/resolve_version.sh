#!/usr/bin/env bash
# Resolve the illumio-ops bundle/release version and print it to stdout.
# Resolution order:
#   1. $VERSION env var, if non-empty -> verbatim (escape hatch, e.g. VERSION=verify)
#   2. base = __version__ from src/__init__.py
#   3. clean release (tag v<base> points at HEAD, working tree clean) -> <base>
#   4. dev build (ahead of / dirty vs that tag)                        -> <base>+<short-hash>
#   5. no git context (e.g. unpacked inside a bundle)                  -> <base>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -n "${VERSION:-}" ]]; then
    printf '%s\n' "$VERSION"
    exit 0
fi

base="$(sed -n 's/^__version__ *= *["'"'"']\([^"'"'"']*\)["'"'"'].*/\1/p' "$REPO_ROOT/src/__init__.py")"
if [[ -z "$base" ]]; then
    echo "ERROR: could not read __version__ from src/__init__.py" >&2
    exit 1
fi

if ! command -v git >/dev/null 2>&1 || ! git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    printf '%s\n' "$base"
    exit 0
fi

if git -C "$REPO_ROOT" rev-parse -q --verify "refs/tags/v$base" >/dev/null \
   && [[ "$(git -C "$REPO_ROOT" rev-parse HEAD)" == "$(git -C "$REPO_ROOT" rev-parse "v$base^{commit}")" ]] \
   && git -C "$REPO_ROOT" diff --quiet HEAD; then
    printf '%s\n' "$base"
else
    short="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    printf '%s\n' "$base+$short"
fi
