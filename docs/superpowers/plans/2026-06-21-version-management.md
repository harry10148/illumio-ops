# Version Management Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `src/__init__.py` `__version__` the single source of truth for the illumio-ops version, give offline bundles clean semver names, and provide one command to bump the version that keeps code, git tag, and CHANGELOG in sync.

**Architecture:** A small standalone script `scripts/resolve_version.sh` prints the resolved bundle version (env override → `__version__` → clean tag vs `+hash` dev suffix); `build_offline_bundle.sh` calls it instead of `git describe`. A second script `scripts/bump_version.sh` edits `__version__` + seeds a CHANGELOG section, then commits and tags. Both are tested via pytest subprocess against throwaway git repos so no network/download is needed.

**Tech Stack:** Bash (`set -euo pipefail`), Python 3.10+ (the `src` package), pytest with `subprocess`/`tmp_path`.

## Global Constraints

- Version format is **pure semver `X.Y.Z`** — no codename / topic-slug suffix.
- Single source of truth: `src/__init__.py` → `__version__`.
- Bundle version is clean (`X.Y.Z`); a `+<short-hash>` suffix appears **only** for non-release/dev builds. The old `git describe` `-<N>-g<hash>` form must never appear.
- Scripts never run `git push`.
- All new shell scripts start with `#!/usr/bin/env bash` and `set -euo pipefail`, derive `REPO_ROOT` from their own location, and are `chmod +x`.
- Tests follow the repo convention: pytest files under `tests/`, run with `pytest`.
- Existing codenamed git tags are left untouched (history).

---

### Task 1: `scripts/resolve_version.sh` — resolve bundle version

**Files:**
- Create: `scripts/resolve_version.sh`
- Modify: `scripts/build_offline_bundle.sh:13`
- Test: `tests/test_resolve_version.py`

**Interfaces:**
- Consumes: `src/__init__.py` (`__version__ = "X.Y.Z"`), optional `VERSION` env var, git.
- Produces: an executable that prints the resolved version string to stdout. Resolution order: (1) `$VERSION` env if non-empty → verbatim; (2) `base` = `__version__`; (3) if git present AND tag `v<base>` points at HEAD AND working tree clean → `<base>`; (4) else → `<base>+<short-hash>`; (5) if no git context → `<base>`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_resolve_version.py`:

```python
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT_SRC = REPO / "scripts" / "resolve_version.sh"


def _make_repo(tmp_path, version="1.2.3"):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "src").mkdir()
    shutil.copy(SCRIPT_SRC, repo / "scripts" / "resolve_version.sh")
    (repo / "src" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    return repo


def _git(repo, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", "-C", str(repo), *args],
                   check=True, capture_output=True, env=env)


def _resolve(repo, version_env=None):
    env = {**os.environ}
    if version_env is not None:
        env["VERSION"] = version_env
    else:
        env.pop("VERSION", None)
    out = subprocess.run(
        ["bash", str(repo / "scripts" / "resolve_version.sh")],
        check=True, capture_output=True, text=True, env=env,
    )
    return out.stdout.strip()


def test_env_override_wins(tmp_path):
    repo = _make_repo(tmp_path)
    assert _resolve(repo, version_env="verify") == "verify"


def test_no_git_returns_bare_base(tmp_path):
    repo = _make_repo(tmp_path, version="2.0.0")
    assert _resolve(repo) == "2.0.0"


def test_clean_tag_returns_bare_version(tmp_path):
    repo = _make_repo(tmp_path, version="1.2.3")
    _git(repo, "init")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    _git(repo, "tag", "-a", "v1.2.3", "-m", "v1.2.3")
    assert _resolve(repo) == "1.2.3"


def test_ahead_of_tag_appends_hash(tmp_path):
    repo = _make_repo(tmp_path, version="1.2.3")
    _git(repo, "init")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    _git(repo, "tag", "-a", "v1.2.3", "-m", "v1.2.3")
    (repo / "extra.txt").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "more")
    assert _resolve(repo).startswith("1.2.3+")
    assert _resolve(repo) != "1.2.3"


def test_dirty_tree_appends_hash(tmp_path):
    repo = _make_repo(tmp_path, version="1.2.3")
    _git(repo, "init")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    _git(repo, "tag", "-a", "v1.2.3", "-m", "v1.2.3")
    (repo / "src" / "__init__.py").write_text('__version__ = "1.2.3"\n# edit\n')
    assert _resolve(repo).startswith("1.2.3+")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_resolve_version.py -v`
Expected: FAIL — `scripts/resolve_version.sh` does not exist (copy raises `FileNotFoundError`).

- [ ] **Step 3: Write the script**

Create `scripts/resolve_version.sh`:

```bash
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
```

Then make it executable:

Run: `chmod +x scripts/resolve_version.sh`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_resolve_version.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Wire `build_offline_bundle.sh` to use it**

In `scripts/build_offline_bundle.sh`, replace line 13:

```bash
VERSION="${VERSION:-$(cd "$REPO_ROOT" && git describe --tags --always 2>/dev/null || echo "dev")}"
```

with:

```bash
VERSION="$("$SCRIPT_DIR/resolve_version.sh")"
```

(`resolve_version.sh` already honors the `VERSION` env var, so `VERSION=verify ./scripts/build_offline_bundle.sh` still works — the value is inherited from the environment by the child script.)

- [ ] **Step 6: Verify the wiring**

Run: `grep -n "resolve_version.sh" scripts/build_offline_bundle.sh`
Expected: line 13 shows `VERSION="$("$SCRIPT_DIR/resolve_version.sh")"`.

Run: `bash -n scripts/build_offline_bundle.sh`
Expected: no output (syntax OK).

- [ ] **Step 7: Commit**

```bash
git add scripts/resolve_version.sh scripts/build_offline_bundle.sh tests/test_resolve_version.py
git commit -m "feat(build): resolve bundle version from __version__ (clean names)"
```

---

### Task 2: Set `__version__` to `4.1.0`

**Files:**
- Modify: `src/__init__.py:1`
- Test: `tests/test_app_version.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `src.__version__ == "4.1.0"`, matching `^\d+\.\d+\.\d+$`. Relied on by `resolve_version.sh`, `src/cli/root.py`, `src/gui/routes/dashboard.py`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_app_version.py`:

```python
import re

import src


def test_version_is_pure_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", src.__version__), src.__version__


def test_version_value():
    assert src.__version__ == "4.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app_version.py -v`
Expected: FAIL — current value is `4.0.0-secure-modern-saas` (fails both the regex and the equality).

- [ ] **Step 3: Update the version**

Replace the single line in `src/__init__.py`:

```python
__version__ = "4.1.0"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_app_version.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/__init__.py tests/test_app_version.py
git commit -m "feat(version): drop codename, set __version__ to 4.1.0"
```

---

### Task 3: `scripts/bump_version.sh` — release bump tool

**Files:**
- Create: `scripts/bump_version.sh`
- Test: `tests/test_bump_version.py`

**Interfaces:**
- Consumes: `<X.Y.Z>` arg, optional `--no-tag` flag; edits `src/__init__.py` and `CHANGELOG.md`.
- Produces: in default mode — updated `__version__`, a new `## [X.Y.Z] — <today>` CHANGELOG section, a `chore(release): vX.Y.Z` commit, and an annotated tag `vX.Y.Z`. In `--no-tag` mode — only the two file edits (no commit, no tag). Exits non-zero on a bad version arg, an existing tag, or (default mode) a dirty working tree.

- [ ] **Step 1: Write the failing test**

Create `tests/test_bump_version.py`:

```python
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT_SRC = REPO / "scripts" / "bump_version.sh"

CHANGELOG_SEED = """# Changelog

All notable changes to illumio-ops are documented in this file.

## [1.0.0] — 2026-01-01

### Changed

- initial
"""


def _git(repo, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(["git", "-C", str(repo), *args],
                          check=True, capture_output=True, text=True, env=env)


def _make_repo(tmp_path, version="1.0.0"):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "src").mkdir()
    shutil.copy(SCRIPT_SRC, repo / "scripts" / "bump_version.sh")
    (repo / "src" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (repo / "CHANGELOG.md").write_text(CHANGELOG_SEED)
    _git(repo, "init")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return repo


def _bump(repo, *args, check=True):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["bash", str(repo / "scripts" / "bump_version.sh"), *args],
        check=check, capture_output=True, text=True, env=env,
    )


def test_bump_edits_commits_and_tags(tmp_path):
    repo = _make_repo(tmp_path)
    _bump(repo, "1.1.0")
    assert '__version__ = "1.1.0"' in (repo / "src" / "__init__.py").read_text()
    assert "## [1.1.0]" in (repo / "CHANGELOG.md").read_text()
    tags = _git(repo, "tag").stdout.split()
    assert "v1.1.0" in tags
    msg = _git(repo, "log", "-1", "--pretty=%s").stdout.strip()
    assert msg == "chore(release): v1.1.0"


def test_changelog_section_is_inserted_at_top(tmp_path):
    repo = _make_repo(tmp_path)
    _bump(repo, "1.1.0")
    body = (repo / "CHANGELOG.md").read_text()
    assert body.index("## [1.1.0]") < body.index("## [1.0.0]")


def test_no_tag_mode_edits_only(tmp_path):
    repo = _make_repo(tmp_path)
    _bump(repo, "1.1.0", "--no-tag")
    assert '__version__ = "1.1.0"' in (repo / "src" / "__init__.py").read_text()
    assert "v1.1.0" not in _git(repo, "tag").stdout.split()
    # no new commit: HEAD is still the init commit
    assert _git(repo, "log", "-1", "--pretty=%s").stdout.strip() == "init"


def test_rejects_non_semver(tmp_path):
    repo = _make_repo(tmp_path)
    r = _bump(repo, "1.1", check=False)
    assert r.returncode != 0
    r2 = _bump(repo, "v1.1.0-foo", check=False)
    assert r2.returncode != 0


def test_rejects_existing_tag(tmp_path):
    repo = _make_repo(tmp_path)
    _git(repo, "tag", "-a", "v1.1.0", "-m", "v1.1.0")
    r = _bump(repo, "1.1.0", check=False)
    assert r.returncode != 0


def test_rejects_dirty_tree_in_tag_mode(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "dirty.txt").write_text("x\n")
    _git(repo, "add", "dirty.txt")
    r = _bump(repo, "1.1.0", check=False)
    assert r.returncode != 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bump_version.py -v`
Expected: FAIL — `scripts/bump_version.sh` does not exist.

- [ ] **Step 3: Write the script**

Create `scripts/bump_version.sh`:

```bash
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
section="## [$NEW_VERSION] — $today\n\n### Changed\n\n- \n"
awk -v sec="$section" '
    !done && /^## \[/ { printf "%s\n", sec; done=1 }
    { print }
' "$CHANGELOG" > "$CHANGELOG.tmp" && mv "$CHANGELOG.tmp" "$CHANGELOG"

echo "==> Bumped to $NEW_VERSION"

if [[ "$NO_TAG" -eq 1 ]]; then
    echo "    --no-tag: edited src/__init__.py and CHANGELOG.md only."
    echo "    Fill in the CHANGELOG, then commit and tag manually:"
    echo "      git add src/__init__.py CHANGELOG.md && git commit -m 'chore(release): $TAG' && git tag -a $TAG -m '$TAG'"
    exit 0
fi

git -C "$REPO_ROOT" add "$INIT_FILE" "$CHANGELOG"
git -C "$REPO_ROOT" commit -m "chore(release): $TAG"
git -C "$REPO_ROOT" tag -a "$TAG" -m "$TAG"
echo "    Committed and tagged $TAG."
echo "    Push when ready:  git push --follow-tags"
```

Then make it executable:

Run: `chmod +x scripts/bump_version.sh`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bump_version.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/bump_version.sh tests/test_bump_version.py
git commit -m "feat(release): add bump_version.sh to sync version, tag, changelog"
```

---

### Task 4: Reconcile `CHANGELOG.md`

**Files:**
- Modify: `CHANGELOG.md` (preamble scheme sentence + new 4.1.0 and 4.0.0 sections)
- Test: `tests/test_changelog_reconciled.py`

**Interfaces:**
- Consumes: nothing.
- Produces: CHANGELOG preamble states a plain semver scheme; CHANGELOG contains `## [4.1.0]` and `## [4.0.0]` headings, both above `## [3.27.0-docs-refactor]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_changelog_reconciled.py`:

```python
from pathlib import Path

CHANGELOG = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text()


def test_scheme_sentence_is_semver():
    assert "<topic-slug>" not in CHANGELOG
    assert "`<major>.<minor>.<patch>`" in CHANGELOG


def test_has_4_1_0_and_4_0_0_entries():
    assert "## [4.1.0]" in CHANGELOG
    assert "## [4.0.0]" in CHANGELOG


def test_new_entries_are_above_3_27_0():
    assert CHANGELOG.index("## [4.1.0]") < CHANGELOG.index("## [4.0.0]")
    assert CHANGELOG.index("## [4.0.0]") < CHANGELOG.index("## [3.27.0-docs-refactor]")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_changelog_reconciled.py -v`
Expected: FAIL — `<topic-slug>` still present; no 4.1.0 / 4.0.0 entries.

- [ ] **Step 3: Update the preamble scheme sentence**

In `CHANGELOG.md`, replace this sentence (lines 5-7):

```
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to a `<major>.<minor>.<patch>-<topic-slug>` versioning
scheme aligned with the git tag conventions.
```

with:

```
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/) —
a plain `<major>.<minor>.<patch>` scheme. (Tags through v4.0.0 carried a
`-<topic-slug>` codename; the codename was retired in 4.1.0.)
```

- [ ] **Step 4: Insert the 4.1.0 and 4.0.0 sections**

In `CHANGELOG.md`, immediately before the line `## [3.27.0-docs-refactor] — 2026-05-15`, insert:

```
## [4.1.0] — 2026-06-21

### Changed

- Version management refactor: `src/__init__.py` `__version__` is now the
  single source of truth; offline bundle names are clean semver
  (`illumio-ops-<X.Y.Z>-offline-...`, or `<X.Y.Z>+<short-hash>` for dev builds)
  via `scripts/resolve_version.sh` instead of `git describe`.
- Added `scripts/bump_version.sh` to bump `__version__`, seed a CHANGELOG
  section, commit, and tag in one step.
- Retired the `-<topic-slug>` codename convention in favour of plain semver.

## [4.0.0] — 2026-05-23

### Changed

- UI/UX Modern SaaS overhaul, security-audit remediation, and timezone-aware
  datetime refactor. Tagged `v4.0.0-secure-modern-saas`; this entry backfills
  the 3.27.0 → 4.0.0 gap. See the git tag and history for the full commit set.

```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_changelog_reconciled.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add CHANGELOG.md tests/test_changelog_reconciled.py
git commit -m "docs(changelog): switch to semver scheme, backfill 4.0.0, add 4.1.0"
```

---

### Task 5: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the new tests together**

Run: `pytest tests/test_resolve_version.py tests/test_app_version.py tests/test_bump_version.py tests/test_changelog_reconciled.py -v`
Expected: all PASS.

- [ ] **Step 2: Confirm the app reports the clean version**

Run: `python -c "import src; print(src.__version__)"`
Expected: `4.1.0`

- [ ] **Step 3: Confirm resolution against the real repo**

Run: `bash scripts/resolve_version.sh`
Expected: `4.1.0+<short-hash>` (HEAD is not on a `v4.1.0` tag yet — dev build). Confirms no `-<N>-g` form.

- [ ] **Step 4: Syntax-check the build script**

Run: `bash -n scripts/build_offline_bundle.sh`
Expected: no output.

**Note (manual, post-merge):** the real `v4.1.0` tag is intentionally NOT
created on this branch. `__version__` is already `4.1.0` and the 4.1.0 CHANGELOG
entry already exists, so do NOT run `scripts/bump_version.sh 4.1.0` (it would
re-bump). After merging to `main`, just tag the release commit:
`git tag -a v4.1.0 -m v4.1.0 && git push --follow-tags`. From then on, future
releases (4.2.0, …) use `scripts/bump_version.sh <X.Y.Z>`.
