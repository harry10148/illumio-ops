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
