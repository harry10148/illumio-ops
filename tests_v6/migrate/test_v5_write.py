"""P8 write mode: the migrated settings, the 5.x TLS files and the handover, written into a new v6 root."""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from illumio_ops.domain.values import IngestSource
from illumio_ops.migrate.v5_write import AlreadyInstalled, upgrade
from illumio_ops.paths import InstallPaths
from illumio_ops.services.collect.cycle import COLD_START_KEY
from illumio_ops.settings.store import SettingsStore
from illumio_ops.store import alerts as alert_store
from illumio_ops.store import siem as siem_store
from illumio_ops.store.flowdb import ingest_state
from illumio_ops.store.flowdb.db import FlowDb
from tests_v6.migrate.test_v5_handover import EVENTS, T, _db

FIXTURES = Path(__file__).parent / "fixtures"
NOW = T + timedelta(hours=1)


@pytest.fixture
def v5(tmp_path):
    root = tmp_path / "v5"
    (root / "config" / "tls").mkdir(parents=True)
    raw = json.loads((FIXTURES / "v5_2_x_config_106_redacted.json").read_text())
    raw["pce_cache"]["db_path"] = "data/pce_cache.sqlite"  # .106's value (redacted in the fixture)
    (root / "config" / "config.json").write_text(json.dumps(raw))
    (root / "config" / "tls" / "self_signed.pem").write_text("CERT")
    (root / "config" / "tls" / "self_signed_key.pem").write_text("KEY")
    (root / "illumio-ops.py").write_text("")
    _db(root, EVENTS, [(1, "redacted-25", "sent"), (2, "redacted-25", "sent"), (3, "redacted-25", "pending")],
        cursor=(T + timedelta(minutes=5), 3))
    return root


def _ctx(root):
    from illumio_ops.services.context import AppContext
    paths = InstallPaths(root)
    store = SettingsStore(paths.settings_file)
    store.load()
    return AppContext(paths=paths, settings=store), store.current()


def test_upgrade_writes_settings_tls_and_the_handover(v5, tmp_path):
    root = tmp_path / "v6"
    summary = upgrade(v5, root, now=NOW)
    ctx, s = _ctx(root)
    [dest] = s.siem.destinations
    assert dest.name == "redacted-25"
    with ctx.db() as conn:
        cur = siem_store.get_cursor(conn, dest.id, "audit")
        assert cur.last_id == 0 and cur.floor_time == T + timedelta(minutes=2) - timedelta(milliseconds=1)
        assert alert_store.eval_watermark(conn, "events", pce_url=s.pce.url, org_id=s.pce.org_id) == \
            "t:" + (T + timedelta(minutes=2)).isoformat()
    with FlowDb(root / "data" / "flows.sqlite").connect() as conn:
        bound = ingest_state.get(conn, IngestSource.EVENTS).progress[COLD_START_KEY]
    assert datetime.fromisoformat(bound) == T + timedelta(minutes=2) - timedelta(milliseconds=1)
    assert (root / "config" / "tls" / "self_signed.pem").read_text() == "CERT"
    assert os.stat(root / "config" / "tls" / "self_signed_key.pem").st_mode & 0o777 == 0o600
    report = (root / "logs" / "migration-report.txt").read_text()
    assert "redacted-25" in report and summary
    raw = json.loads((v5 / "config" / "config.json").read_text())
    assert raw["api"]["secret"] not in report


def test_a_floor_older_than_seven_days_starts_collection_seven_days_back_and_says_so(v5, tmp_path):
    root = tmp_path / "v6"
    summary = upgrade(v5, root, now=T + timedelta(days=10))
    with FlowDb(root / "data" / "flows.sqlite").connect() as conn:
        bound = ingest_state.get(conn, IngestSource.EVENTS).progress[COLD_START_KEY]
    assert datetime.fromisoformat(bound) == T + timedelta(days=3)
    assert any("7" in line for line in summary)


def test_upgrade_never_overwrites_an_installation(v5, tmp_path):
    root = tmp_path / "v6"
    upgrade(v5, root, now=NOW)
    with pytest.raises(AlreadyInstalled):
        upgrade(v5, root, now=NOW)


def test_the_5x_installation_is_left_as_it_was(v5, tmp_path):
    before = {p: p.read_bytes() for p in v5.rglob("*") if p.is_file()}
    upgrade(v5, tmp_path / "v6", now=NOW)
    assert {p: p.read_bytes() for p in v5.rglob("*") if p.is_file()} == before


def test_the_command_writes_once_and_prints_the_handover(v5, tmp_path):
    import subprocess
    import sys
    repo = Path(__file__).resolve().parents[2]
    root = tmp_path / "v6"
    cmd = [sys.executable, "-m", "illumio_ops.migrate", "--from", str(v5), "--write", "--root", str(root),
           "--lang", "zh_TW"]
    env = os.environ | {"PYTHONPATH": str(repo)}
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False, env=env, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "redacted-25" in r.stdout and "migration-report.txt" in r.stdout
    again = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False, env=env, cwd=tmp_path)
    assert again.returncode == 73 and "nothing was changed" in again.stderr
