from illumio_ops.paths import resolve_paths


def test_env_root_wins_over_package_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ILLUMIO_OPS_ROOT", str(tmp_path))
    p = resolve_paths()
    assert p.root == tmp_path
    assert p.settings_file == tmp_path / "config" / "settings.json"
    assert p.app_db == tmp_path / "data" / "app.sqlite"


def test_explicit_root_wins_over_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ILLUMIO_OPS_ROOT", "/nonexistent")
    assert resolve_paths(tmp_path).root == tmp_path


def test_package_root_is_default(monkeypatch):
    from pathlib import Path

    import illumio_ops

    monkeypatch.delenv("ILLUMIO_OPS_ROOT", raising=False)
    assert resolve_paths().root == Path(illumio_ops.__file__).resolve().parent.parent


def test_ensure_dirs_on_fresh_root(tmp_path):
    p = resolve_paths(tmp_path / "fresh")
    p.ensure_dirs()
    assert p.data_dir.is_dir() and p.tls_dir.is_dir() and p.limiter_dir.is_dir()
    assert p.logs_dir.is_dir() and p.reports_dir.is_dir()
    assert (p.data_dir.stat().st_mode & 0o777) == 0o700


def test_ensure_dirs_keeps_existing_mode(tmp_path):
    p = resolve_paths(tmp_path)
    p.logs_dir.mkdir(mode=0o755)
    p.logs_dir.chmod(0o755)
    p.ensure_dirs()
    assert (p.logs_dir.stat().st_mode & 0o777) == 0o755
