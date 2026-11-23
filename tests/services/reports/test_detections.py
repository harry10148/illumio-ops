"""The local detections and alert history report (6.15.0 Task 2)."""
from datetime import UTC, datetime, timedelta
from io import BytesIO

from openpyxl import load_workbook

from illumio_ops.domain.alerting import Confidence, Trigger
from illumio_ops.domain.report import BarBlock, TableBlock, TextBlock
from illumio_ops.domain.values import (
    AlertRuleType,
    DeliveryStatus,
    Language,
    ReportType,
    Severity,
)
from illumio_ops.services.reports import detections
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.services.reports.render_html import render_html
from illumio_ops.services.reports.render_xlsx import render_xlsx
from illumio_ops.store import alerts as alert_store
from illumio_ops.store import detection_annotations
from illumio_ops.store.flowdb import analysis, workloads
from illumio_ops.store.flowdb.analysis import DetectionWrite
from tests.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
A, B = "/orgs/1/workloads/a", "/orgs/1/workloads/b"


def _input(ctx, lang=Language.EN):
    return BuildInput(ctx=ctx, params=ReportParams(report_type=ReportType.DETECTIONS), start=START, end=END,
                      lang=lang, tz=UTC, now=NOW, pce_label="pce")


def _host_inventory(ctx):
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href=href, hostname=name, name=None, managed=1, enforcement_mode="selective", visibility_level=None,
            os_id=None, ven_version=None, ven_href=None, label_set=None, online=1, risk_exposure=None,
            risk_percent=None, risk_updated_at=None, fetched_at="x") for href, name in ((A, "app-01"), (B, "db-01"))])


def _detection(ctx, detector, fingerprint, subject, first, *, severity="medium", critical=False):
    with ctx.flows().connect() as conn:
        analysis.upsert_detections(conn, [DetectionWrite(
            detector=detector, fingerprint=fingerprint, subject_key=subject, severity=severity,
            first_seen=first, last_seen=first + timedelta(minutes=5), critical_asset=critical,
            summary_json="{}", segment_json="{}", confidence_json="{}")],
            dedup={detector: timedelta(minutes=1)}, late=False, at=first)


def _alert(ctx, at, detector, *, status, error=None, known=False):
    settings = ctx.settings.current()
    rule = next(r for r in settings.alerts.rules if r.type == "lateral" and detector in r.detectors)
    t = Trigger(rule_id=rule.id, rule_type=AlertRuleType.LATERAL, subject_key=f"{detector}|{A}",
                severity=Severity.HIGH, first_seen=at, last_seen=at, late=False,
                message_key="alert_lateral_fanout", params={"detector": detector, "account": A}, facts={},
                evidence=None, confidence=Confidence(), grouped_annotation=7 if known else None)
    with ctx.db() as conn:
        alert_id = alert_store.insert_alert(conn, pce_url=settings.pce.url, org_id=settings.pce.org_id,
                                            rule_name="Fanout rule", pack_key=None, trigger=t, at=at,
                                            channels=["line"], hold=DeliveryStatus.GROUPED if known else None)
        if error is not None:
            delivery = alert_store.deliveries(conn, [alert_id])[0]
            conn.execute("UPDATE alert_deliveries SET status = 'failed', attempts = 2, last_error = ? WHERE id = ?",
                         (error, delivery["id"]))
        conn.commit()
    return alert_id


def _table(doc, title_key):
    return next(b for section in doc.sections for b in section.blocks
                if isinstance(b, TableBlock) and b.title == title_key)


def _text(doc):
    return "\n".join([doc.title, *doc.data_quality,
                      *(p for section in doc.sections for block in section.blocks if isinstance(block, TextBlock)
                        for p in block.paragraphs),
                      *(str(cell) for _, table in doc.tables() for row in table.rows for cell in row),
                      *(block.title for section in doc.sections for block in section.blocks if isinstance(block, BarBlock))])


def test_builder_reads_detections_alerts_known_and_delivery_errors(tmp_path):
    ctx = configured_ctx(tmp_path)
    _host_inventory(ctx)
    first = START + timedelta(days=1)
    _detection(ctx, "fanout", f"fanout|{A}", A, first, severity="high", critical=True)
    _detection(ctx, "auth_to_non_dc", f"authdst|{A}|{B}", A, first + timedelta(days=1))
    settings = ctx.settings.current()
    with ctx.db() as conn:
        detection_annotations.add(conn, pce_url=settings.pce.url, org_id=settings.pce.org_id, detector="fanout",
                                 subject_key=A, fingerprint=f"fanout|{A}", reason="reviewed", created_by="operator",
                                 at=first)
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["alerts"]["channels"]["line"].update(
        enabled=True, access_token="secret-line-token", target_id="target"))
    _alert(ctx, first + timedelta(days=1), "fanout", status=DeliveryStatus.FAILED,
           error="request failed with secret-line-token")
    _alert(ctx, first + timedelta(days=2), "fanout", status=DeliveryStatus.GROUPED, known=True)

    doc = specs()[ReportType.DETECTIONS].build(_input(ctx))
    kpis = {k.key: k.value for k in doc.kpis}
    assert kpis == {"new_detections": 2, "high_critical_detections": 1, "detection_alerts": 2,
                    "failed_deliveries": 1, "known_alerts": 1}
    by_kind = _table(doc, "New detections by kind")
    fanout = next(row for row in by_kind.rows if row[0] == "Fan-out")
    assert fanout == ("Fan-out", 1, 1, 1, 1)
    detail = _table(doc, "New detections by severity")
    assert detail.rows[0][0] == "High" and detail.rows[0][2] == "app-01"
    assert detail.rows[0][-1] == "Yes" and detail.rows[1][-1] == "No"
    history = _table(doc, "Detection rules in the period")
    row = next(row for row in history.rows if row[0].startswith("Fanout rule"))
    assert row[1] == 2 and row[-5:] == (1, 0, 1, 1, 0)  # known, sent, failed, not notified, pending
    failed = _table(doc, "Failed deliveries for detection-category alerts")
    assert len(failed.rows) == 1 and "secret-line-token" not in str(failed.rows[0])
    assert "..." in failed.rows[0][-1]
    assert any("complete only from" in text for text in _text(doc).splitlines())

    html = render_html(doc, tz=UTC)
    assert "Detections and alerts" in html and "secret-line-token" not in html
    book = load_workbook(BytesIO(render_xlsx(doc, tz=UTC)), read_only=True)
    assert "New detections by kind" in book.sheetnames
    assert "Fan-out" in {cell.value for row in book["New detections by kind"].iter_rows() for cell in row}


def test_builder_with_no_data_lists_all_kinds(tmp_path):
    ctx = configured_ctx(tmp_path)
    _host_inventory(ctx)
    doc = specs()[ReportType.DETECTIONS].build(_input(ctx))
    assert _table(doc, "New detections by kind").total_rows == 21
    assert _table(doc, "New detections by severity").rows == ()
    assert _table(doc, "Failed deliveries for detection-category alerts").rows == ()
    assert "No detections for these kinds:" in _text(doc)


def test_lightweight_mode_marks_detection_numbers_unavailable(tmp_path):
    ctx = configured_ctx(tmp_path, mode="lightweight")
    _host_inventory(ctx)
    doc = specs()[ReportType.DETECTIONS].build(_input(ctx))
    kpis = {k.key: k for k in doc.kpis}
    assert kpis["new_detections"].value is None and kpis["high_critical_detections"].value is None
    assert kpis["new_detections"].note == "Detections need the traffic of every collection cycle: switch to alert or full mode."
    assert "Detections need the traffic of every collection cycle" in _text(doc)


def test_top_detection_limit_states_shown_and_total(tmp_path, monkeypatch):
    ctx = configured_ctx(tmp_path)
    _host_inventory(ctx)
    _detection(ctx, "fanout", f"fanout|{A}", A, START + timedelta(hours=1), severity="critical")
    _detection(ctx, "fanout", f"fanout|{B}", B, START + timedelta(hours=2), severity="high")
    monkeypatch.setattr(detections, "DETECTION_ROWS", 1)
    detail = _table(specs()[ReportType.DETECTIONS].build(_input(ctx)),
                    "New detections by severity")
    assert len(detail.rows) == 1 and detail.total_rows == 2
    assert detail.limit_note == "Showing the top 1 of 2."


def test_scrubbed_delivery_error_in_zh_report(tmp_path):
    ctx = configured_ctx(tmp_path)
    _host_inventory(ctx)
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["alerts"]["channels"]["line"].update(
        enabled=True, access_token="秘密-token", target_id="target"))
    _alert(ctx, START + timedelta(days=1), "fanout", status=DeliveryStatus.FAILED,
           error="transport failed using 秘密-token")
    text = _text(specs()[ReportType.DETECTIONS].build(_input(ctx, Language.ZH_TW)))
    assert "秘密-token" not in text and "..." in text



def test_rules_are_named_without_their_id_and_hosts_as_the_flows_named_them():
    """6.15.0 on .106: rule rows read "name (32-hex id)", and an unmanaged Workload — absent from the inventory, named
    in the flows — read "Removed host …id"."""
    import tempfile
    from pathlib import Path

    from illumio_ops.domain.values import DataOrigin
    from illumio_ops.store.flowdb.flows import upsert_flows
    from tests.services.reports.test_findings import flow
    ctx = configured_ctx(Path(tempfile.mkdtemp()), mode="full")
    _host_inventory(ctx)
    row = flow(src="fortigate-gw", dst="db-01", port=22)
    object.__setattr__(row, "src_managed", False)
    with ctx.flows().connect() as conn:
        upsert_flows(conn, [row], origin=DataOrigin.INGEST, now=NOW)
        conn.commit()
    _detection(ctx, "pivot_chain", "fp-u", "/orgs/1/workloads/fortigate-gw", START + timedelta(hours=2))
    _alert(ctx, START + timedelta(hours=3), "fanout", status="sent")
    doc = detections.build_detections(_input(ctx))
    import re
    names = [r[0] for r in _table(doc, "Detection rules in the period").rows]
    assert "Fanout rule" in names and not any(re.search(r"[0-9a-f]{6}", n) for n in names)
    hosts = [r[2] for r in _table(doc, "New detections by severity").rows]
    assert hosts == ["fortigate-gw"]
