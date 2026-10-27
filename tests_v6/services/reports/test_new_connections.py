"""The new connections report (P5a Task 4): connections first seen in the period, against the baseline."""
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.domain.report import TableBlock
from illumio_ops.domain.values import Language, ReportType
from illumio_ops.services.reports import new_connections
from illumio_ops.services.reports.new_connections import build_new_connections
from illumio_ops.services.reports.registry import BuildInput, ReportParams
from illumio_ops.store.flowdb import workloads
from tests_v6.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
A, DB = "/orgs/1/workloads/a", "/orgs/1/workloads/db"


def _inp(ctx):
    return BuildInput(ctx=ctx, params=ReportParams(report_type=ReportType.NEW_CONNECTIONS), start=START, end=END,
                      lang=Language.EN, tz=UTC, now=NOW, pce_label="pce")


def _baseline(ctx, rows):
    with ctx.flows().connect() as conn:
        conn.executemany("INSERT INTO connection_baseline (src_key, dst_key, port, proto, first_seen, last_seen, "
                         "last_decision) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         [(s, d, p, 6, f.isoformat(), (f + timedelta(hours=1)).isoformat(), dec)
                          for s, d, p, f, dec in rows])
        conn.commit()


@pytest.fixture
def ctx(tmp_path):
    c = configured_ctx(tmp_path)
    c.settings.update(c.settings.current().revision,
                      lambda d: d["lateral"].update(critical_assets=[{"key": "app", "value": "Finance"}]))
    from illumio_ops.store.flowdb.labels import label_set_id
    with c.flows().connect() as conn:
        fin = label_set_id(conn, (("app", "Finance"),))
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href=h, hostname=n, name=None, managed=1, enforcement_mode="selective", visibility_level=None,
            os_id=None, ven_version=None, ven_href=None, label_set=ls, online=1, risk_exposure=None,
            risk_percent=None, risk_updated_at=None, fetched_at="x") for h, n, ls in ((A, "app-01", None),
                                                                                    (DB, "fin-db-01", fin))])
    d = datetime(2026, 10, 22, tzinfo=UTC)
    _baseline(c, [
        (A, DB, 3389, d, "allowed"),                       # admin, to a critical asset
        (A, DB, 8080, d, "potentially_blocked"),           # to a critical asset
        ("ip:10.9.9.9", A, 445, d, "unknown"),             # admin, from an unmanaged source
        (A, "ip:10.1.1.1", 443, d, "allowed"),
        (A, "ip:10.1.1.2", 443, datetime(2026, 10, 15, tzinfo=UTC), "allowed"),   # previous period
        (A, "ip:10.1.1.3", 22, datetime(2026, 10, 1, tzinfo=UTC), "allowed"),     # older: not new
    ])
    return c


def _tables(doc, sid):
    return [b for s in doc.sections if s.id == sid for b in s.blocks if isinstance(b, TableBlock)]


def test_counts_and_previous_window(ctx):
    k = {x.key: x for x in build_new_connections(_inp(ctx)).kpis}
    assert (k["new"].value, k["new"].previous) == (4, 1)
    assert (k["admin"].value, k["admin"].previous) == (2, 0)
    assert (k["critical"].value, k["critical"].previous) == (2, 0)
    assert (k["unmanaged_source"].value, k["unmanaged_source"].previous) == (1, 0)


def test_admin_class_and_last_decision_in_rows(ctx):
    [table] = _tables(build_new_connections(_inp(ctx)), "all")
    rows = {(r[0], r[1], r[2]): r for r in table.rows}
    rdp = rows[("app-01", "fin-db-01", "3389/TCP")]
    assert rdp[3] == "Remote execution" and rdp[6] == "Allowed"
    assert rows[("10.9.9.9", "app-01", "445/TCP")][3] == "Remote execution"
    assert rows[("app-01", "10.1.1.1", "443/TCP")][3] == ""


def test_service_and_destination_rankings(ctx):
    doc = build_new_connections(_inp(ctx))
    [by_service] = _tables(doc, "by_service")
    [by_dst] = _tables(doc, "by_destination")
    assert ("fin-db-01", 2) in [(r[0], r[1]) for r in by_dst.rows]
    assert {r[0] for r in by_service.rows} == {"3389/TCP", "8080/TCP", "445/TCP", "443/TCP"}


def test_admin_section_lists_only_admin(ctx):
    [admin] = _tables(build_new_connections(_inp(ctx)), "admin")
    assert {r[2] for r in admin.rows} == {"3389/TCP", "445/TCP"}


def test_accumulating_baseline_note(ctx):
    doc = build_new_connections(_inp(ctx))
    assert all(k.note and "Baseline" in k.note for k in doc.kpis)  # no traffic coverage: baseline 0 days


def test_limit_disclosed(ctx, monkeypatch):
    monkeypatch.setattr(new_connections, "ROW_LIMIT", 3)
    [table] = _tables(build_new_connections(_inp(ctx)), "all")
    assert len(table.rows) == 3 and table.total_rows == 4 and "4" in table.limit_note


def test_empty_period_says_why(ctx):
    inp = _inp(ctx)
    inp = BuildInput(**{**inp.__dict__, "start": datetime(2026, 9, 1, tzinfo=UTC),
                        "end": datetime(2026, 9, 8, tzinfo=UTC)})
    [table] = _tables(build_new_connections(inp), "all")
    assert table.rows == () and table.empty_text


def test_index_exists_after_migration(ctx):
    with ctx.flows().connect() as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'ix_baseline_first'").fetchone()


def test_findings_critical_first_then_unmanaged(ctx):
    f = build_new_connections(_inp(ctx)).findings
    assert [x.severity.value for x in f] == ["high", "medium"]
    assert "3389/TCP" in f[0].title and "fin-db-01" in f[0].title and "10.9.9.9" in f[1].title
