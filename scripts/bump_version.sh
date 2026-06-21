#!/usr/bin/env bash
# Bump the illumio-ops version: update src/__init__.py + CHANGELOG.md, then
# commit and tag. Usage: scripts/bump_version.sh <X.Y.Z> [--no-tag]
#   --no-tag : edit the two files only (no commit, no tag) so you can fill in
#              the CHANGELOG before committing and tagging by hand.
# Never runs git push.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

NEW_VERSION="${1:-}"
NO_TAG=0
[[ "${2:-}" == "--no-tag" ]] && NO_TAG=1

if [[ ! "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "ERROR: version must be X.Y.Z (semver, no codename). Got: '$NEW_VERSION'" >&2
    echo "Usage: scripts/bump_version.sh <X.Y.Z> [--no-tag]" >&2
    exit 1
fi

INIT_FILE="$REPO_ROOT/src/__init__.py"
CHANGELOG="$REPO_ROOT/CHANGELOG.md"
TAG="v$NEW_VERSION"

if git -C "$REPO_ROOT" rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    echo "ERROR: tag $TAG already exists" >&2
    exit 1
fi

if [[ "$NO_TAG" -eq 0 ]] && ! git -C "$REPO_ROOT" diff --quiet HEAD; then
    echo "ERROR: working tree has uncommitted changes; commit/stash them or use --no-tag" >&2
    exit 1
fi

# 1. update __version__
sed -i.bak "s/^__version__ *=.*/__version__ = \"$NEW_VERSION\"/" "$INIT_FILE"
rm -f "$INIT_FILE.bak"

# 2. insert a new CHANGELOG section before the first existing "## [" heading
today="$(date +%Y-%m-%d)"
section="$(printf '## [%s] — %s\n\n### Changed\n\n- ' "$NEW_VERSION" "$today")"
awk -v sec="$section" '
    !done && /^## \[/ { print sec; print ""; done=1 }
    { print }
' "$CHANGELOG" > "$CHANGELOG.tmp" && mv "$CHANGELOG.tmp" "$CHANGELOG"

# 3. update Version badge in README.md and README_zh.md (skip if absent)
README_FILES=()
for readme in "$REPO_ROOT/README.md" "$REPO_ROOT/README_zh.md"; do
    if [ -f "$readme" ]; then
        sed -i.bak -E "s#(badge/Version-v)[^?]*(-blue)#\1${NEW_VERSION}\2#" "$readme"
        rm -f "$readme.bak"
        README_FILES+=("$readme")
    fi
done

echo "==> Bumped to $NEW_VERSION"

if [[ "$NO_TAG" -eq 1 ]]; then
    echo "    --no-tag: edited src/__init__.py and CHANGELOG.md only."
    echo "    Fill in the CHANGELOG, then commit and tag manually:"
    echo "      git add src/__init__.py CHANGELOG.md && git commit -m 'chore(release): $TAG' && git tag -a $TAG -m '$TAG'"
    exit 0
fi

git -C "$REPO_ROOT" add "$INIT_FILE" "$CHANGELOG"
for readme in "${README_FILES[@]+"${README_FILES[@]}"}"; do
    git -C "$REPO_ROOT" add "$readme"
done
git -C "$REPO_ROOT" commit -m "chore(release): $TAG"
git -C "$REPO_ROOT" tag -a "$TAG" -m "$TAG"
echo "    Committed and tagged $TAG."
echo "    Push when ready:  git push --follow-tags"
