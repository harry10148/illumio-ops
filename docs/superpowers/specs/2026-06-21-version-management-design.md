# Version Management Refactor — Design

- **Date:** 2026-06-21
- **Status:** Approved (design); pending implementation plan
- **Author:** harry (with Claude)

## Problem

illumio-ops version numbers live in three independent, manually-maintained
places that have drifted apart:

| Source | Current value | How it is maintained |
|--------|---------------|----------------------|
| git tag | `v4.0.0-secure-modern-saas` (2026-05-23) | manual `git tag` |
| `src/__init__.py` `__version__` | `4.0.0-secure-modern-saas` | hand-edited in release commits |
| `CHANGELOG.md` latest entry | `3.27.0-docs-refactor` (2026-05-15) | hand-written |

CHANGELOG stopped at 3.27.0 while code and tag jumped to 4.0.0 — the 4.0.0
entry was never written. There are 383 commits on `main` after the 4.0.0 tag.

The offline bundle build script (`scripts/build_offline_bundle.sh:13`) derives
its version from `git describe --tags --always`, which appends `-<N>-g<hash>`
when HEAD is not exactly on a tag. With 383 commits past the tag, bundles are
currently named:

```
illumio-ops-v4.0.0-secure-modern-saas-383-g2ebe2d4-offline-linux-x86_64.tar.gz
```

The project is **not** a pip package (no `pyproject.toml` / `setup.py`); it is
run from source or shipped as an offline bundle. Bundles contain **no `.git`**,
so the running app cannot rely on `git describe` at runtime.

## Goals

1. One canonical source of truth for the version; everything else derives from it.
2. Clean bundle names — semantic version only, at most a short git hash suffix
   for non-release (mid-development) builds. Never the `-<N>-g<hash>` form.
3. Drop the codename suffix — pure `<major>.<minor>.<patch>` (semver).
4. A single command to bump the version that keeps code, git tag, and CHANGELOG
   in sync.

## Non-goals

- Renaming existing historical tags (they keep their codenames).
- Retroactively back-filling a per-commit CHANGELOG for the 383 commits since
  the 4.0.0 tag.
- Turning the project into a pip-installable package.
- Automatic `git push` (left to the operator).

## Decisions

### A. Single source of truth & format

- **Canonical source:** `src/__init__.py` → `__version__ = "X.Y.Z"`, pure
  three-part semver, **no codename**.
- Everything else derives from it. `src/cli/root.py` (`--version`) and
  `src/gui/routes/dashboard.py` already `import __version__` — unchanged; the
  value they show just becomes clean.
- Rule of thumb: **the `__version__` in code is authoritative.** A git tag is a
  bookmark applied after the fact; CHANGELOG is the human-readable record.

### B. Bundle version resolution (clean, at most a hash)

`scripts/build_offline_bundle.sh` replaces the `git describe` line with this
resolution order:

```
1. If the VERSION env var is set        -> use it verbatim (escape hatch, e.g. VERSION=verify)
2. Else base = __version__ from src/__init__.py        (e.g. 4.1.0)
3. If git is available AND tag v<base> exists AND points at HEAD
   AND the working tree is clean        -> version = <base>             (e.g. 4.1.0)
4. Otherwise                            -> version = <base>+<short-hash> (e.g. 4.1.0+2ebe2d4)
```

Resulting names:

- Release build: `illumio-ops-4.1.0-offline-linux-x86_64.tar.gz`
- Dev build:     `illumio-ops-4.1.0+2ebe2d4-offline-linux-x86_64.tar.gz`

`+` is the PEP 440 local-version separator and is a legal filename character on
both Linux and Windows. The same resolved value is written to the bundle's
`VERSION` file (`stage_app`, line 74), which `preflight.sh` / `preflight.ps1`
read — behavior unchanged, value just becomes clean.

Extraction of `__version__` in bash (handles single or double quotes):

```bash
base="$(sed -n 's/^__version__ *= *["'"'"']\([^"'"'"']*\)["'"'"'].*/\1/p' "$REPO_ROOT/src/__init__.py")"
```

Clean-release check:

```bash
if command -v git >/dev/null \
   && git -C "$REPO_ROOT" rev-parse -q --verify "refs/tags/v$base" >/dev/null \
   && [ "$(git -C "$REPO_ROOT" rev-parse HEAD)" = "$(git -C "$REPO_ROOT" rev-parse "v$base^{commit}")" ] \
   && git -C "$REPO_ROOT" diff --quiet; then
    VERSION="$base"
else
    short="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo nogit)"
    VERSION="$base+$short"
fi
```

(Wrapped in the `VERSION="${VERSION:-...}"` env escape hatch.)

### C. `scripts/bump_version.sh` (release flow)

Usage: `scripts/bump_version.sh <X.Y.Z>` — e.g. `scripts/bump_version.sh 4.1.0`.

Steps:

1. Validate the argument matches `^[0-9]+\.[0-9]+\.[0-9]+$` (reject codenames /
   typos). Abort if the working tree is dirty, unless `--no-tag` (see below).
2. Rewrite `__version__` in `src/__init__.py` to the new value.
3. Insert a new section at the top of `CHANGELOG.md` (below the header preamble):
   `## [X.Y.Z] — <today>` with an empty `### Changed` skeleton for the operator
   to fill.
4. `git commit -m "chore(release): vX.Y.Z"` staging `src/__init__.py` and
   `CHANGELOG.md`.
5. Create an annotated tag: `git tag -a vX.Y.Z -m "vX.Y.Z"`.
6. Print next steps (e.g. `git push --follow-tags`).

Flags:

- `--no-tag` — perform steps 2–3 only (edit files, no commit, no tag). Lets the
  operator fill in CHANGELOG content first, then commit and tag manually.

`git push` is **never** run by the script.

### D. CHANGELOG reconciliation

- Change the versioning-scheme sentence in the preamble from
  `<major>.<minor>.<patch>-<topic-slug>` to `<major>.<minor>.<patch>` (semver).
- Add a concise `## [4.0.0] — 2026-05-23` entry noting the codename scheme
  retirement and pointing at the git tag — closing the 3.27.0 → 4.0.0 gap
  without back-filling every commit.
- Going forward, `bump_version.sh` seeds each new section; the operator fills it.

### E. Version for this release

Set `__version__` to **`4.1.0`** — the 383 commits after the 4.0.0 tag (mostly
fixes) constitute a new minor, and this becomes the first clean release under
the new flow. (Rejected: reusing `4.0.0`, which would map one version string to
two different code states.)

## Affected files

- **Modify:** `scripts/build_offline_bundle.sh` (version resolution, line 13).
- **Modify:** `src/__init__.py` (`__version__` → `4.1.0`, codename dropped).
- **Modify:** `CHANGELOG.md` (scheme sentence + 4.0.0 entry + 4.1.0 entry).
- **Add:** `scripts/bump_version.sh`.
- **Unchanged:** `src/cli/root.py`, `src/gui/routes/dashboard.py`,
  `src/cli/menus/_root.py` (already read `__version__`); the bundle `VERSION`
  file mechanism and `preflight.{sh,ps1}` (read the bundled `VERSION` file).
- Existing codenamed tags are left as-is (history).

## Verification

1. `python -c "import src; print(src.__version__)"` prints `4.1.0`.
2. Build-script resolution, both branches:
   - On a clean `v4.1.0` tag → bundle name contains `4.1.0` (no hash).
   - Ahead of / dirty vs the tag → bundle name contains `4.1.0+<hash>`.
   - `VERSION=test` env override → bundle name contains `test`.
3. `bump_version.sh` dry-run (`--no-tag` on a scratch branch): confirm
   `src/__init__.py` and `CHANGELOG.md` are edited correctly; then a full run on
   a scratch branch creates the `chore(release)` commit and the `vX.Y.Z` tag.
4. `preflight.sh` against a freshly built bundle reports the clean
   `Bundle VERSION:` line.
