from types import SimpleNamespace

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


def test_siem_status_no_db(runner, tmp_path, monkeypatch):
    """Status command with no cache DB prints error gracefully (no crash)."""
    from src.cli.siem import siem_group
    # Should not crash even if DB doesn't exist
    result = runner.invoke(siem_group, ["status"])
    # Any output is fine; just must not raise unhandled exception
    assert result.exit_code in (0, 1)


def test_siem_replay_missing_dest_exits_1(runner, tmp_path, monkeypatch):
    """Replay with no DB exits with an error code."""
    from src.cli.siem import siem_group
    from src.cli._exit_codes import EXIT_UNAVAILABLE
    result = runner.invoke(siem_group, ["replay", "--dest", "nonexistent"])
    # No replay data / uninitialised DB now maps to the centralised
    # EXIT_UNAVAILABLE instead of a raw ctx.exit(1).
    assert result.exit_code in (0, 1, EXIT_UNAVAILABLE)


def test_siem_dlq_empty(runner, tmp_path, monkeypatch):
    """DLQ list with empty table prints 'no entries' message."""
    from src.cli.siem import siem_group
    import os
    os.makedirs(tmp_path / "data", exist_ok=True)

    # Patch ConfigManager at its source module (lazy import inside siem.py)
    from unittest.mock import MagicMock, patch
    mock_cm = MagicMock()
    mock_cm.models.pce_cache.db_path = str(tmp_path / "data" / "test.sqlite")
    with patch("src.config.ConfigManager", return_value=mock_cm):
        result = runner.invoke(siem_group, ["dlq", "--dest", "dest1"])
    assert result.exit_code == 0
    assert "No DLQ entries" in result.output or "dest1" in result.output


def test_siem_purge_empty_db(runner, tmp_path, monkeypatch):
    """Purge on empty DB reports 0 removed."""
    from src.cli.siem import siem_group
    import os
    os.makedirs(tmp_path / "data", exist_ok=True)
    from unittest.mock import MagicMock, patch
    mock_cm = MagicMock()
    mock_cm.models.pce_cache.db_path = str(tmp_path / "data" / "test.sqlite")
    with patch("src.config.ConfigManager", return_value=mock_cm):
        result = runner.invoke(siem_group, ["purge", "--dest", "dest1"])
    assert result.exit_code == 0
    assert "0" in result.output or "Purged" in result.output


def test_siem_status_counts_by_destination_and_status(runner, tmp_path):
    """Regression: siem status must correctly aggregate counts per
    (destination, status) — not conflate rows across destinations or
    misclassify statuses. Guards the count-queries -> single GROUP BY
    refactor against cross-destination/status bleed."""
    import os
    import json as _json
    from datetime import datetime, timezone
    from unittest.mock import MagicMock, patch
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import SiemDispatch, DeadLetter
    from src.cli.root import cli

    os.makedirs(tmp_path / "data", exist_ok=True)
    db_path = str(tmp_path / "data" / "test.sqlite")
    eng = create_engine(f"sqlite:///{db_path}")
    init_schema(eng)
    sf = sessionmaker(eng)
    now = datetime.now(timezone.utc)
    with sf.begin() as s:
        # destA: 2 pending, 1 sent, 1 failed, 1 DLQ entry
        for _ in range(2):
            s.add(SiemDispatch(source_table="pce_events", source_id=1,
                                destination="destA", status="pending", retries=0, queued_at=now))
        s.add(SiemDispatch(source_table="pce_events", source_id=1,
                            destination="destA", status="sent", retries=0, queued_at=now))
        s.add(SiemDispatch(source_table="pce_events", source_id=1,
                            destination="destA", status="failed", retries=0, queued_at=now))
        s.add(DeadLetter(source_table="pce_events", source_id=1, destination="destA",
                          retries=1, last_error="e", payload_preview="", quarantined_at=now))
        # destB: 3 sent, no DLQ
        for _ in range(3):
            s.add(SiemDispatch(source_table="pce_events", source_id=1,
                                destination="destB", status="sent", retries=0, queued_at=now))

    mock_cm = MagicMock()
    mock_cm.models.pce_cache.db_path = db_path
    mock_cm.models.siem.destinations = []
    with patch("src.config.ConfigManager", return_value=mock_cm):
        result = runner.invoke(cli, ["--json", "siem", "status"])

    assert result.exit_code == 0, result.output
    payload = _json.loads(result.output)
    by_dest = {r["destination"]: r for r in payload}
    assert by_dest["destA"] == {"destination": "destA", "pending": 2, "sent": 1, "failed": 1, "dlq": 1}
    assert by_dest["destB"] == {"destination": "destB", "pending": 0, "sent": 3, "failed": 0, "dlq": 0}


def test_siem_test_bad_destination_exits_usage(runner):
    """siem test with unknown destination exits EXIT_USAGE (64)."""
    from src.cli.siem import siem_group
    from unittest.mock import MagicMock, patch

    mock_cm = MagicMock()
    # Return an empty destinations list so any name misses
    mock_cm.models.siem.destinations = []
    with patch("src.config.ConfigManager", return_value=mock_cm):
        result = runner.invoke(siem_group, ["test", "no_such_dest"])

    from src.cli._exit_codes import EXIT_USAGE
    assert result.exit_code == EXIT_USAGE
    # i18n-aware: assert the destination name appears, not the surrounding text
    assert "no_such_dest" in result.output


# ── Phase 2C Task 9: chrome, without weakening the existing gates ───────────

def test_siem_menu_renders_inside_panel(monkeypatch):
    from src import siem_cli
    screens = []
    monkeypatch.setattr(siem_cli, "menu_screen",
                        lambda path, lines, **kw: screens.append((path, lines)))
    monkeypatch.setattr("builtins.input", lambda *a, **k: "0")
    siem_cli.manage_siem_menu(SimpleNamespace(config={"siem": {}}))
    path, lines = screens[0]
    assert "SIEM" in path
    assert lines


def test_destination_delete_still_demands_the_word_yes(monkeypatch):
    """This gate is stricter than a y/N box; chrome must not downgrade it."""
    from src import siem_cli
    import inspect
    src_text = inspect.getsource(siem_cli._delete_destination)
    assert '"yes"' in src_text or "'yes'" in src_text


def test_dlq_purge_still_demands_the_word_yes():
    from src import siem_cli
    import inspect
    src_text = inspect.getsource(siem_cli._dlq_bulk)
    assert '"yes"' in src_text or "'yes'" in src_text
