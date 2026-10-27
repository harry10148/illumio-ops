"""The network inventory report (P5b-1 Task 5): label hygiene from the inventory and the flows, app-to-app
dependencies with same- and cross-environment counts, the services each app provides, unmanaged sources into
apps, and the rule findings."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.report import TableBlock, TextBlock
from illumio_ops.domain.values import Language, ReportType
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.store.flowdb import labels, workloads
from tests_v6.services.collect.conftest import configured_ctx
from tests_v6.services.reports.test_findings import flow
from tests_v6.services.reports.test_traffic import _write

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)


def _build(ctx, lang=Language.EN):
    return specs()[ReportType.NETWORK_INVENTORY].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=ReportType.NETWORK_INVENTORY), start=START, end=END, lang=lang,
        tz=UTC, now=NOW, pce_label="pce"))


def _section(doc, sid):
    return next(s for s in doc.sections if s.id == sid)


def _tables(doc, sid):
    return [b for b in _section(doc, sid).blocks if isinstance(b, TableBlock)]


def _texts(doc, sid):
    return " ".join(p for b in _section(doc, sid).blocks if isinstance(b, TextBlock) for p in b.paragraphs)


def _inventory(ctx, hosts):
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href=f"/orgs/1/workloads/{name}", hostname=name, name=None, managed=managed, enforcement_mode="full",
            visibility_level=None, os_id=None, ven_version=None, ven_href=None,
            label_set=labels.label_set_id(conn, tuple(sorted(lab.items()))), online=1, risk_exposure=None,
            risk_percent=None, risk_updated_at=None, fetched_at="x") for name, lab, managed in hosts])
        conn.commit()


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path)


def test_label_hygiene_from_inventory(ctx):
    full = {"app": "Web", "env": "Prod", "loc": "TPE", "role": "web"}
    _inventory(ctx, [("ok", full, 1), ("noapp", {k: v for k, v in full.items() if k != "app"}, 1),
                     ("bare", {}, 1), ("unmanaged", {}, 0)])
    _write(ctx, [flow(port=443), flow(port=443, src_app="", dst_app="")])
    doc = _build(ctx)
    missing = {r[0]: r[1] for r in _tables(doc, "hygiene")[0].rows}
    assert missing == {"noapp": "app", "bare": "app, env, loc, role"}
    assert {k.key: k.value for k in doc.kpis}["hosts_missing_labels"] == 2
    assert "1 flows" in _texts(doc, "hygiene")


def test_app_pairs_same_and_cross_env(ctx):
    _write(ctx, [flow(port=5432, src_app="Web", dst_app="DB", conns=3),
                 flow(port=5432, src_app="Web", dst_app="DB", src_env="Dev", dst_env="Prod", conns=2)])
    doc = _build(ctx)
    assert _tables(doc, "dependencies")[0].rows[0] == ("Web", "DB", 5)
    text = _texts(doc, "dependencies")
    assert "3 connections stayed within" in text and "2 crossed" in text
    assert {k.key: k.value for k in doc.kpis}["cross_env_connections"] == 2


def test_services_per_app(ctx):
    _write(ctx, [flow(port=5432, src_app="Web", dst_app="DB", conns=5), flow(port=22, src_app="Ops", dst_app="DB", conns=3),
                 flow(port=443, src_app="Web", dst_app="DB", conns=2), flow(port=80, src_app="Web", dst_app="DB", conns=1)])
    row = _tables(_build(ctx), "services")[0].rows[0]
    assert row[0] == "DB" and row[1] == 11 and row[2] == "5432/TCP, 22/TCP, 443/TCP" and row[3] == 2


def test_unmanaged_into_apps(ctx):
    _write(ctx, [flow(port=445, unmanaged_src=True, dst_app="DB", conns=4),
                 flow(port=445, unmanaged_src=True, dst_app="DB", conns=1), flow(port=443, dst_app="Web")])
    rows = _tables(_build(ctx), "unmanaged")[0].rows
    assert rows == (("DB", 5, 2),)


def test_findings_section(ctx):
    _write(ctx, [flow(port=5900)])
    doc = _build(ctx)
    assert any(r[0] == "B002" for r in _tables(doc, "findings")[0].rows) and doc.findings


def test_zh_tw_builds(ctx):
    _write(ctx, [flow(port=443)])
    assert _build(ctx, Language.ZH_TW).title
