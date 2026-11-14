"""The unmanaged endpoints report (P5a Task 5): addresses without a VEN that talk to managed hosts."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.report import TableBlock
from illumio_ops.domain.values import Language, ReportType
from illumio_ops.services.reports import unmanaged
from illumio_ops.services.reports.registry import BuildInput, ReportParams
from illumio_ops.services.reports.unmanaged import build_unmanaged
from tests.services.collect.conftest import configured_ctx

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
    assert r[5].startswith("445/TCP") and r[6] == "Allowed (a rule allows it), Potentially Blocked"


def test_private_vs_public(ctx):
    rows = {r[0]: r for r in _table(build_unmanaged(_inp(ctx)), "all").rows}
    assert rows["8.8.8.8"][1] == "Public" and rows["8.8.8.8"][2] == "Managed hosts connect to it"


def test_ven_candidates_need_three_peers(ctx):
    table = _table(build_unmanaged(_inp(ctx)), "candidates")
    assert [r[0] for r in table.rows] == ["10.5.5.5"]
    assert table.host_keys == {"address": ("ip:10.5.5.5",)} and table.host_section == "connections"


def test_admin_port_sources(ctx):
    rows = _table(build_unmanaged(_inp(ctx)), "admin").rows
    assert [r[0] for r in rows] == ["10.5.5.5"] and "445/TCP" in rows[0][2] and "3389/TCP" in rows[0][2]


def test_kpis_and_previous_window(ctx):
    from illumio_ops.domain.values import IngestSource
    from illumio_ops.store.flowdb import ingest_state
    with ctx.flows().connect() as conn:
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, START - (END - START), END)
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


def test_outbound_management_port_is_not_an_inbound_use(tmp_path):
    """Review: a managed host connecting to U on 445 made U look like it used 445 into managed hosts."""
    c = configured_ctx(tmp_path)
    _rollup(c, [("2026-10-21", "ip:10.4.4.4", W.format("a"), 443, "allowed", 3),
                ("2026-10-21", W.format("b"), "ip:10.4.4.4", 445, "allowed", 3)])
    doc = build_unmanaged(_inp(c))
    assert _table(doc, "admin").rows == () and doc.findings == ()


def test_admin_peers_count_only_admin_targets(tmp_path):
    c = configured_ctx(tmp_path)
    _rollup(c, [("2026-10-21", "ip:10.4.4.4", W.format("a"), 22, "allowed", 3),
                ("2026-10-21", "ip:10.4.4.4", W.format("b"), 443, "allowed", 3)])
    [row] = _table(build_unmanaged(_inp(c)), "admin").rows
    assert row[3] == 1  # only a was reached on a management port


def test_previous_none_when_previous_period_not_collected(ctx):
    from illumio_ops.domain.values import IngestSource
    from illumio_ops.store.flowdb import ingest_state
    with ctx.flows().connect() as conn:
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, START, END)
    assert all(k.previous is None for k in build_unmanaged(_inp(ctx)).kpis)


def test_findings_run_from_the_highest_severity_down(tmp_path):
    # 2026-11-10 report review: the findings read medium, medium, high - ordered by hosts reached, not by severity.
    c = configured_ctx(tmp_path)
    _rollup(c, [("2026-10-21", "ip:10.4.4.4", W.format(h), 22, "allowed", 3) for h in "abc"]
            + [("2026-10-21", "ip:10.4.4.5", W.format(h), 22, "allowed", 3) for h in "ab"]
            + [("2026-10-21", "ip:8.8.4.4", W.format("a"), 22, "allowed", 3)])
    doc = build_unmanaged(_inp(c))
    assert [f.severity.value for f in doc.findings] == ["high", "medium", "medium"]
    assert "8.8.4.4" in doc.findings[0].title and "10.4.4.4" in doc.findings[1].title
    # one thing to do for the three endpoints (the findings rules' "unmanaged"), naming the first two
    from illumio_ops.domain.actions import group_actions
    assert all(f.action_code == "unmanaged" and f.action_short for f in doc.findings)
    (action,) = group_actions(doc.findings)
    assert action.focus == ("8.8.4.4 reaches 1 managed hosts.", "10.4.4.4 reaches 3 managed hosts.")


def test_shared_address_space_is_not_called_private(tmp_path):
    # 100.64.0.0/10 (RFC 6598) is carrier shared space: not public, and not a private address either.
    c = configured_ctx(tmp_path)
    _rollup(c, [("2026-10-21", "ip:100.64.1.9", W.format("a"), 443, "allowed", 3),
                ("2026-10-21", "ip:169.254.3.3", W.format("a"), 443, "allowed", 3),
                ("2026-10-21", "ip:192.168.1.9", W.format("a"), 443, "allowed", 3)])
    doc = build_unmanaged(_inp(c))
    rows = {r[0]: r[1] for r in _table(doc, "all").rows}
    assert rows == {"100.64.1.9": "Shared (100.64.0.0/10)", "169.254.3.3": "Other non-public",
                    "192.168.1.9": "Private"}
    kpi = next(k for k in doc.kpis if k.key == "private")
    assert kpi.value == 3 and kpi.label == "Non-public addresses"


def test_the_long_lists_are_counted_in_the_html_and_whole_in_the_xlsx(ctx):
    """6.6.0 Task 5 (.106: an 18,000-pixel page): the list of every address and of every public one are sorted by
    the sections above them; the HTML gives the count and the first public ones, the tables keep every row."""
    from illumio_ops.services.reports.render_html import render_html
    _rollup(ctx, [("2026-10-21", f"ip:8.8.{i}.1", "/orgs/1/workloads/a", 443, "allowed", 1) for i in range(30)])
    doc = build_unmanaged(_inp(ctx))
    every, public = _table(doc, "all"), _table(doc, "public")
    assert len(every.rows) >= 30 and every.html_rows == 0 and len(public.rows) >= 30 and public.html_rows == 20
    html = render_html(doc, tz=UTC)
    assert f"{len(every.rows)} unmanaged addresses are not listed row by row" in html
    assert sum(f"8.8.{i}.1<" in html for i in range(30)) <= 20  # at most the listed public ones
