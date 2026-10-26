"""`python -m illumio_ops serve`: refuses to start rather than guess."""
import fcntl
import json
import os
import signal
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from illumio_ops.paths import resolve_paths
from illumio_ops.runtime import prepare
from illumio_ops.settings.store import SettingsStore
from tests_v6.web.conftest import cached_hash

REPO = Path(__file__).resolve().parents[1]


def _run(root: Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"PYTHONPATH": str(REPO), "ILLUMIO_OPS_RATELIMIT_URI": "memory://"}
    return subprocess.run([sys.executable, "-m", "illumio_ops", "serve", "--root", str(root)],
                          capture_output=True, text=True, timeout=timeout, env=env, cwd="/", check=False)


def _initial(root: Path, port: int = 5001) -> Path:
    paths = resolve_paths(root)
    paths.ensure_dirs()
    SettingsStore(paths.settings_file).create_initial(password_hash=cached_hash("illumio"),
                                                      secret_key="ab" * 32, port=port)
    return paths.settings_file


def test_serve_refuses_invalid_settings(tmp_path):
    f = _initial(tmp_path)
    d = json.loads(f.read_text())
    d["web"]["port"] = 0
    f.write_text(json.dumps(d))
    before = f.read_bytes()
    r = _run(tmp_path)
    assert r.returncode == 78
    assert "web.port" in r.stderr
    assert f.read_bytes() == before


def test_second_instance_refused(tmp_path):
    _initial(tmp_path)
    paths = resolve_paths(tmp_path)
    fd = os.open(paths.service_lock, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        r = _run(tmp_path)
    finally:
        os.close(fd)
    assert r.returncode == 75 and "already running" in r.stderr


def test_fresh_root_creates_initial_settings_0600(tmp_path):
    root = tmp_path / "fresh"  # no config/ or data/ yet
    rt = prepare(root)
    try:
        assert (rt.paths.settings_file.stat().st_mode & 0o777) == 0o600
        s = rt.ctx.settings.current()
        assert s.web.username == "illumio" and s.web.port == 5001
        assert rt.paths.app_db.is_file() and rt.ssl_ctx is not None
        assert rt.ctx.served_cert_fingerprint
    finally:
        rt.release()


def test_provided_cert_missing_is_refused(tmp_path):
    f = _initial(tmp_path)
    d = json.loads(f.read_text())
    d["web"]["tls"].update(mode="provided", cert_file="/nonexistent/cert.pem", key_file="/nonexistent/key.pem")
    f.write_text(json.dumps(d))
    r = _run(tmp_path)
    assert r.returncode == 78 and "certificate" in r.stderr.lower()


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_serve_starts_https_and_stops_on_sigterm(tmp_path):
    port = _free_port()
    _initial(tmp_path, port=port)
    env = os.environ | {"PYTHONPATH": str(REPO), "ILLUMIO_OPS_RATELIMIT_URI": "memory://"}
    proc = subprocess.Popen([sys.executable, "-m", "illumio_ops", "serve", "--root", str(tmp_path)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd="/")
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        body = None
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"https://127.0.0.1:{port}/api/auth/csrf", context=ctx, timeout=2) as r:
                    body = json.loads(r.read())
                break
            except OSError:
                time.sleep(0.1)
        assert body is not None and body["ok"] is True
    finally:
        proc.send_signal(signal.SIGTERM)
        _out, err = proc.communicate(timeout=30)
    assert proc.returncode == 0, err[-2000:]


def _tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def test_invalid_settings_write_nothing_at_all(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    f = cfg / "settings.json"
    paths = resolve_paths(tmp_path)
    SettingsStore(paths.settings_file).create_initial(password_hash=cached_hash("illumio"), secret_key="ab" * 32)
    d = json.loads(f.read_text())
    d["web"]["port"] = 0
    f.write_text(json.dumps(d))
    before = _tree(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 78
    assert _tree(tmp_path) == before  # no logs/, no data/service.lock, nothing


def test_undecodable_settings_exit_78(tmp_path):
    f = _initial(tmp_path)
    f.write_bytes(b'{"schema_version": 1, "x": "\xff"}')
    r = _run(tmp_path)
    assert r.returncode == 78 and "Traceback" not in r.stderr


def test_bad_ciphers_exit_78(tmp_path):
    f = _initial(tmp_path)
    d = json.loads(f.read_text())
    d["web"]["tls"]["ciphers"] = "THIS_IS_NOT_A_CIPHER"
    f.write_text(json.dumps(d))
    r = _run(tmp_path)
    assert r.returncode == 78 and "Traceback" not in r.stderr


def test_unwritable_certificate_directory_exit_78(tmp_path):
    _initial(tmp_path)
    tls_dir = resolve_paths(tmp_path).tls_dir
    tls_dir.chmod(0o500)
    try:
        r = _run(tmp_path)
    finally:
        tls_dir.chmod(0o700)
    assert r.returncode == 78 and "Traceback" not in r.stderr


def test_missing_settings_on_an_existing_installation_is_refused(tmp_path):
    rt = prepare(tmp_path)  # first start: creates settings, database, certificate
    rt.release()
    rt.paths.settings_file.unlink()
    r = _run(tmp_path)
    assert r.returncode == 78 and "rescue" in r.stderr
    assert not rt.paths.settings_file.exists()


def test_flow_database_is_migrated_before_serving(tmp_path):
    # D1 (.106 upgrade): migrated on the first job's connection instead, the one-off 0002 (20 min at 1,000 workloads)
    # held up every job and GUI request opening the store; at startup the listener simply starts after it.
    import sqlite3

    from illumio_ops.store.db import _migrations
    from illumio_ops.store.flowdb.db import MIGRATIONS_PACKAGE

    rt = prepare(tmp_path / "root")
    try:
        with sqlite3.connect(rt.paths.flows_db) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == len(_migrations(MIGRATIONS_PACKAGE))
    finally:
        rt.release()


def test_newer_flow_database_is_refused_at_startup(tmp_path):
    import sqlite3

    from illumio_ops.runtime import StartupError

    paths = resolve_paths(tmp_path / "root")
    paths.ensure_dirs()
    with sqlite3.connect(paths.flows_db) as conn:
        conn.execute("PRAGMA user_version = 999")
    try:
        prepare(tmp_path / "root")
    except StartupError as exc:
        assert "999" in exc.message
    else:
        raise AssertionError("a flow database newer than the program was accepted")
