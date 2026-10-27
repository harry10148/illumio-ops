"""The unmanaged endpoints report (P5a Task 5): addresses without a VEN that talk to managed hosts."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.report import TableBlock
from illumio_ops.domain.values import Language, ReportType
from illumio_ops.services.reports import unmanaged
from illumio_ops.services.reports.registry import BuildInput, ReportParams
from illumio_ops.services.reports.unmanaged import build_unmanaged
from tests_v6.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
W = "/orgs/1/workloads/{}"


def _inp(ctx):
    return BuildInput(ctx=ctx, params=ReportParams(report_type=ReportType.UNMANAGED_ENDPOINTS), start=START,
                      end=END, lang=Language.EN, tz=UTC, now=NOW, pce_label="pce")


def _rollup(ctx, rows):
    with ctx.flows().connect() as conn:
        conn.executemany(
            "INSERT INTO flow_rollup_daily (day, src_key, dst_key, port, proto, policy_decision, initiator_user, "
            "initiator_process, connections, flow_records, bytes_in, bytes_out, bytes_known_records) "
            "VALUES (?, ?, ?, ?, 6, ?, '', '', ?, 1, 0, 0, 0)", rows)
        conn.commit()


@pytest.fixture
def ctx(tmp_path):
    c = configured_ctx(tmp_path)
    _rollup(c, [
        ("2026-10-21", "ip:10.5.5.5", W.format("a"), 445, "allowed", 10),       # private, inbound, admin port
        ("2026-10-22", "ip:10.5.5.5", W.format("b"), 3389, "potentially_blocked", 4),
        ("2026-10-22", "ip:10.5.5.5", W.format("c"), 80, "allowed", 2),
        ("2026-10-23", W.format("a"), "ip:10.5.5.5", 53, "allowed", 7),         # also outbound: both
        ("2026-10-23", W.format("a"), "ip:8.8.8.8", 53, "allowed", 30),         # public, outbound
        ("2026-10-24", "ip:10.6.6.6", W.format("a"), 443, "allowed", 1),        # private, one peer
        ("2026-10-24", "ip:10.7.7.7", "ip:10.8.8.8", 443, "unknown", 5),        # neither end managed: ignored
        ("2026-10-15", "ip:10.9.9.9", W.format("a"), 22, "allowed", 3),         # previous period
    ])
    return c


def _table(doc, sid):
    return next(b for s in doc.sections if s.id == sid for b in s.blocks if isinstance(b, TableBlock))


def test_unmanaged_rollup_grouping(ctx):
    rows = {r[0]: r for r in _table(build_unmanaged(_inp(ctx)), "all").rows}
    assert set(rows) == {"10.5.5.5", "8.8.8.8", "10.6.6.6"}
    r = rows["10.5.5.5"]
    assert r[1] == "Private" and r[2] == "Both directions" and r[3] == 3 and r[4] == 23
    assert r[5].startswith("445/TCP") and "Allowed" in r[6]


def test_private_vs_public(ctx):
    rows = {r[0]: r for r in _table(build_unmanaged(_inp(ctx)), "all").rows}
    assert rows["8.8.8.8"][1] == "Public" and rows["8.8.8.8"][2] == "Managed hosts connect to it"


def test_ven_candidates_need_three_peers(ctx):
    rows = _table(build_unmanaged(_inp(ctx)), "candidates").rows
    assert [r[0] for r in rows] == ["10.5.5.5"]


def test_admin_port_sources(ctx):
    rows = _table(build_unmanaged(_inp(ctx)), "admin").rows
    assert [r[0] for r in rows] == ["10.5.5.5"] and "445/TCP" in rows[0][2] and "3389/TCP" in rows[0][2]


def test_kpis_and_previous_window(ctx):
    k = {x.key: x for x in build_unmanaged(_inp(ctx)).kpis}
    assert (k["total"].value, k["total"].previous) == (3, 1)
    assert (k["private"].value, k["private"].previous) == (2, 1)
    assert (k["admin_sources"].value, k["admin_sources"].previous) == (1, 1)
    assert (k["public"].value, k["public"].previous) == (1, 0)


def test_limit_disclosed(ctx, monkeypatch):
    monkeypatch.setattr(unmanaged, "ROW_LIMIT", 2)
    t = _table(build_unmanaged(_inp(ctx)), "all")
    assert len(t.rows) == 2 and t.total_rows == 3 and t.limit_note


def test_empty_period_says_why(ctx):
    inp = BuildInput(**{**_inp(ctx).__dict__, "start": datetime(2026, 9, 1, tzinfo=UTC),
                        "end": datetime(2026, 9, 8, tzinfo=UTC)})
    t = _table(build_unmanaged(inp), "all")
    assert t.rows == () and t.empty_text
