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
