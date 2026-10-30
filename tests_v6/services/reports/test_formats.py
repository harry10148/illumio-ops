"""Report formats per type (P5c-4): a type declares the formats it makes; JSON and CSV carry a report's flat rows
(policy_resolver: no HTML, spec §6.5)."""
import csv
import io
import json
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.report import ReportDocument, RowsExport
from illumio_ops.domain.values import ReportFormat, ReportStatus, ReportType
from illumio_ops.services.reports import deliver, generate, registry
from illumio_ops.services.reports.registry import BuildInput, ReportParams, ReportSpec
from illumio_ops.store import reports as store
from tests_v6.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 30, 1, tzinfo=UTC)
ROWS_TYPE = ReportType.LATERAL_POSTURE  # any type: the test registers its own spec for it
J, C, H, X = ReportFormat.JSON, ReportFormat.CSV, ReportFormat.HTML, ReportFormat.XLSX


def _doc(inp: BuildInput) -> ReportDocument:
    return ReportDocument(report_type=inp.params.report_type, lang=inp.lang, title="T", period_start=inp.start,
                          period_end=inp.end, generated_at=inp.now, pce_label=inp.pce_label, kpis=(), findings=(),
                          data_quality=(), sections=(),
                          export=RowsExport(columns=("ruleset", "src_ip", "note"),
                                            rows=[("Web", "10.0.0.1", "中文"), ("Web", "10.0.0.2", "")],
                                            meta={"truncated": False, "row_cap": 500_000}))


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    reg = {t: ReportSpec(report_type=t, group="policy", needs_traffic=False, build=_doc,
                         formats=(J, C) if t is ROWS_TYPE else (H, X)) for t in ReportType}
    monkeypatch.setattr(registry, "REGISTRY", reg)
    return configured_ctx(tmp_path)


def _run(ctx, formats):
    rid = generate.enqueue(ctx, ReportParams(report_type=ROWS_TYPE, formats=formats), trigger="manual",
                           schedule_id=None, now=NOW)
    generate.run_queued(ctx, now=NOW)
    with ctx.db() as conn:
        return store.get(conn, rid)


def test_format_refused_for_type(ctx):
    settings = ctx.settings.current()
    assert generate.refusal(settings, ReportParams(report_type=ROWS_TYPE, formats=(H,))) == "rpt_err_format_unsupported"
    assert generate.refusal(settings, ReportParams(report_type=ReportType.AUDIT, formats=(C,))) == \
        "rpt_err_format_unsupported"
    assert generate.refusal(settings, ReportParams(report_type=ROWS_TYPE, formats=(J, C))) is None
    assert generate.REFUSAL_FIELDS["rpt_err_format_unsupported"] == "formats"


def test_json_and_csv_written(ctx):
    row = _run(ctx, (J, C))
    assert row.status is ReportStatus.DONE and sorted(f.rsplit(".", 1)[1] for f in row.files) == ["csv", "json"]
    out = ctx.paths.reports_dir / str(row.id)
    body = json.loads(next(out.glob("*.json")).read_text(encoding="utf-8"))
    assert body["truncated"] is False and body["rows"][0] == {"ruleset": "Web", "src_ip": "10.0.0.1", "note": "中文"}
    assert body["report_type"] == ROWS_TYPE.value and body["record_count"] == 2


def test_csv_utf8_bom(ctx):
    """Excel opens a UTF-8 CSV correctly only with the BOM."""
    row = _run(ctx, (C,))
    raw = next((ctx.paths.reports_dir / str(row.id)).glob("*.csv")).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows[0] == ["ruleset", "src_ip", "note"] and rows[1] == ["Web", "10.0.0.1", "中文"]


def test_mail_large_files_not_attached(ctx, monkeypatch, tmp_path):
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["alerts"]["channels"]["smtp"].update(
        enabled=True, host="smtp.example.com", sender="ops@example.com", recipients=["a@example.com"]))
    sent = {}
    monkeypatch.setattr(deliver, "send_mail", lambda smtp, **kw: sent.update(kw) or (True, None))
    monkeypatch.setattr(deliver, "MAX_ATTACHMENTS_BYTES", 10)
    big = tmp_path / "x.csv"
    big.write_bytes(b"0" * 100)
    doc = _doc(BuildInput(ctx=ctx, params=ReportParams(report_type=ROWS_TYPE, formats=(C,)), start=NOW, end=NOW,
                          lang=ctx.settings.current().display.language, tz=UTC, now=NOW, pce_label="p"))
    deliver.deliver(ctx, 1, doc, ReportParams(report_type=ROWS_TYPE, formats=(C,)), [big], tz=UTC)
    assert sent["attachments"] == [] and "Reports page" in sent["text"]


def test_catalog_lists_formats(ctx):
    from illumio_ops.services.reports.views import catalog
    entries = {e.report_type: e for e in catalog(ctx).entries}
    assert entries[ROWS_TYPE].formats == [J, C] and entries[ReportType.AUDIT].formats == [H, X]


def test_csv_cells_cannot_be_formulas(ctx, monkeypatch):
    """Security review: ruleset and service names come from the PCE; a cell starting = + - @ would run as a formula
    in Excel. The same guard as the XLSX (render_xlsx.safe); the JSON keeps the value as is."""
    def doc(inp):
        return _doc(inp).model_copy(update={"export": RowsExport(columns=("ruleset", "n"),
                                                                 rows=[("=HYPERLINK(\"x\")", 5), ("@cmd", -1)])})
    registry.REGISTRY[ROWS_TYPE] = ReportSpec(report_type=ROWS_TYPE, group="policy", needs_traffic=False, build=doc,
                                              formats=(J, C))
    row = _run(ctx, (J, C))
    out = ctx.paths.reports_dir / str(row.id)
    rows = list(csv.reader(io.StringIO(next(out.glob("*.csv")).read_bytes().decode("utf-8-sig"))))
    assert rows[1] == ["'=HYPERLINK(\"x\")", "5"] and rows[2] == ["'@cmd", "-1"]
    assert json.loads(next(out.glob("*.json")).read_text())["rows"][0]["ruleset"] == "=HYPERLINK(\"x\")"
