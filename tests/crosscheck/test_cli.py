import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

import illumio_ops.crosscheck.__main__ as cli
from illumio_ops.crosscheck import io
from illumio_ops.crosscheck.model import Finding
from illumio_ops.paths import resolve_paths
from illumio_ops.pce.client import PceClient
from illumio_ops.settings.store import SettingsStore
from tests.web.conftest import cached_hash

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
API_KEY = "api_crosscheck_key_7f3a"
API_SECRET = "secret-that-must-never-be-printed-9d41c0"


def _root(tmp_path, *, configured=True):
    root = tmp_path / "root"
    paths = resolve_paths(root)
    paths.ensure_dirs()
    store = SettingsStore(paths.settings_file)
    store.create_initial(password_hash=cached_hash("illumio"), secret_key="ab" * 32)
    if configured:
        store.update(store.current().revision, lambda d: d["pce"].update(
            url="https://pce.example.test:8443", org_id="3", api_key=API_KEY, api_secret=API_SECRET))
    return root


# --- arguments and the period ---------------------------------------------------------------------------------

def test_defaults():
    a = cli.parse_args(["all", "--out", "/x"])
    assert (a.command, a.days, a.margin_minutes, a.root) == ("all", 7, 30, None)


@pytest.mark.parametrize("days", ["0", "91", "-1", "seven"])
def test_days_out_of_range_rejected(days, capsys):
    with pytest.raises(SystemExit) as e:
        cli.parse_args(["events", "--days", days, "--out", "/x"])
    assert e.value.code == 2  # argparse's usage error; the same number as "cannot run"
    assert "--days" in capsys.readouterr().err


@pytest.mark.parametrize("days", ["1", "90"])
def test_days_bounds_accepted(days):
    assert cli.parse_args(["events", "--days", days, "--out", "/x"]).days == int(days)


def test_out_is_required_and_command_must_be_known():
    with pytest.raises(SystemExit):
        cli.parse_args(["all"])
    with pytest.raises(SystemExit):
        cli.parse_args(["traffic", "--out", "/x"])
    with pytest.raises(SystemExit):
        cli.parse_args(["all", "--out", "/x", "--margin-minutes", "-5"])


def test_period_ends_margin_before_now_and_spans_days():
    start, end = cli.period(NOW, days=7, margin_minutes=30)
    assert end == NOW - timedelta(minutes=30)
    assert start == end - timedelta(days=7)


# --- read-only database access --------------------------------------------------------------------------------

def test_open_ro_reads_but_cannot_write(tmp_path):
    db = tmp_path / "app.sqlite"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE t (x INTEGER)")
        c.execute("INSERT INTO t VALUES (1)")
    c.close()
    conn = io.open_ro(db)
    try:
        assert conn.execute("SELECT x FROM t").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO t VALUES (2)")
    finally:
        conn.close()


def test_open_ro_never_creates_a_database(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        io.open_ro(tmp_path / "missing.sqlite")
    assert not (tmp_path / "missing.sqlite").exists()


def test_pce_client_has_its_own_limiter(tmp_path):
    s = SettingsStore(resolve_paths(_root(tmp_path)).settings_file).load()
    client = io.pce(s)
    try:
        assert isinstance(client, PceClient)
        assert client._rate_limiter is not None
    finally:
        client.close()


# --- output ---------------------------------------------------------------------------------------------------

def test_write_groups_by_area_and_lists_unchecked_before_consistent(tmp_path):
    findings = [
        Finding("events", "catalog", "consistent", "all types known"),
        Finding("events", "received", "inconsistent", "3 events missing", sample=[{"href": "/orgs/3/events/1"}]),
        Finding("events", "older rows", "unchecked", "outside retention"),
        Finding("alerts", "rule r1", "consistent", "ok"),
    ]
    out = tmp_path / "o"
    out.mkdir()
    io.write(out, findings, {"period_start": "2026-11-13T11:30:00Z", "period_end": "2026-11-20T11:30:00Z",
                             "pce_url": "https://pce", "org_id": "3", "version": "6.12.5",
                             "limitations": ["a stated limit"]})
    data = json.loads((out / "findings.json").read_text())
    assert data["meta"]["version"] == "6.12.5"
    assert [f["status"] for f in data["findings"]] == ["consistent", "inconsistent", "unchecked", "consistent"]
    md = (out / "report.md").read_text()
    for s in ("2026-11-13T11:30:00Z", "https://pce", "6.12.5", "a stated limit", "outside retention",
              "3 events missing", "/orgs/3/events/1"):
        assert s in md, s
    ev = md[md.index("## events"):md.index("## alerts")]
    assert ev.index("inconsistent") < ev.index("unchecked") < ev.index("consistent: 1")


def test_finding_rejects_unknown_status():
    with pytest.raises(ValueError):
        Finding("events", "x", "ok", "")  # type: ignore[arg-type]


# --- end to end and exit codes --------------------------------------------------------------------------------

def test_all_writes_both_files_and_exits_0_with_nothing_inconsistent(tmp_path, capsys):
    root = _root(tmp_path)
    out = tmp_path / "new" / "out"  # created when missing
    assert cli.main(["all", "--root", str(root), "--out", str(out)], now=NOW) == 0
    data = json.loads((out / "findings.json").read_text())
    assert {f["area"] for f in data["findings"]} == {"events", "alerts", "reports"}
    assert all(f["status"] == "unchecked" for f in data["findings"])  # nothing checked is never "consistent"
    assert data["meta"]["period_end"] == "2026-11-20T11:30:00Z"
    assert data["meta"]["period_start"] == "2026-11-13T11:30:00Z"
    md = (out / "report.md").read_text()
    printed = capsys.readouterr()
    for text in (md, (out / "findings.json").read_text(), printed.out, printed.err):
        assert API_SECRET not in text and API_KEY not in text
    assert "unchecked" in printed.out


def test_single_area_runs_only_that_area(tmp_path):
    root = _root(tmp_path)
    out = tmp_path / "out"
    assert cli.main(["events", "--root", str(root), "--out", str(out)], now=NOW) == 0
    assert {f["area"] for f in json.loads((out / "findings.json").read_text())["findings"]} == {"events"}


def test_inconsistent_exits_1(tmp_path, monkeypatch):
    root = _root(tmp_path)
    monkeypatch.setitem(cli.CHECKS, "alerts", lambda run: [Finding("alerts", "rule r1", "inconsistent", "missed")])
    out = tmp_path / "out"
    assert cli.main(["all", "--root", str(root), "--out", str(out)], now=NOW) == 1
    assert "missed" in (out / "report.md").read_text()


def test_missing_settings_exits_2(tmp_path, capsys):
    assert cli.main(["all", "--root", str(tmp_path / "none"), "--out", str(tmp_path / "out")], now=NOW) == 2
    assert "settings" in capsys.readouterr().err
    assert not (tmp_path / "out" / "report.md").exists()


def test_invalid_settings_exits_2_naming_the_field_not_the_value(tmp_path, capsys):
    root = _root(tmp_path)
    f = resolve_paths(root).settings_file
    d = json.loads(f.read_text())
    d["pce"]["org_id"] = "not-a-number"
    f.write_text(json.dumps(d))
    assert cli.main(["all", "--root", str(root), "--out", str(tmp_path / "out")], now=NOW) == 2
    err = capsys.readouterr().err
    assert "pce.org_id" in err and API_SECRET not in err


def test_unconfigured_pce_exits_2(tmp_path, capsys):
    root = _root(tmp_path, configured=False)
    assert cli.main(["all", "--root", str(root), "--out", str(tmp_path / "out")], now=NOW) == 2
    assert "PCE" in capsys.readouterr().err


def test_out_that_is_a_file_exits_2(tmp_path, capsys):
    root = _root(tmp_path)
    (tmp_path / "taken").write_text("x")
    assert cli.main(["all", "--root", str(root), "--out", str(tmp_path / "taken")], now=NOW) == 2
    assert "cannot write" in capsys.readouterr().err


def test_pce_unreachable_during_a_check_exits_2(tmp_path, monkeypatch, capsys):
    from illumio_ops.pce.client import PceTransportError

    def boom(run):
        raise PceTransportError("/events", "refused")
    root = _root(tmp_path)
    monkeypatch.setitem(cli.CHECKS, "events", boom)
    assert cli.main(["all", "--root", str(root), "--out", str(tmp_path / "out")], now=NOW) == 2
    err = capsys.readouterr().err
    assert "refused" in err and API_SECRET not in err
