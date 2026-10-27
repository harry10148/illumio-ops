"""Every built report type in both languages (P5a Task 10): no raw message key in the HTML, the XLSX or the email,
and a zh_TW report carries no English sentence of the report's own copy."""
import json
import re
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import load_workbook

from illumio_ops.domain.values import Language, ReportType
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.services.reports.render_email import render_email
from illumio_ops.services.reports.render_html import render_html
from illumio_ops.services.reports.render_xlsx import render_xlsx
from tests_v6.services.reports.test_lateral_posture import _detection, _exposure, _hosts, _snapshot
from tests_v6.services.reports.test_new_connections import _baseline
from tests_v6.services.reports.test_unmanaged import _rollup
from tests_v6.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
RAW_KEY = re.compile(r"\b(?:rpt|gui_reports|detector_name|decision|severity)_[a-z_]+\b")
EN = json.loads((Path(__file__).resolve().parents[3] / "illumio_ops/i18n/en.json")
                .read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    c = configured_ctx(tmp_path_factory.mktemp("i18n"))
    c.settings.update(c.settings.current().revision,
                      lambda d: d["lateral"].update(critical_assets=[{"key": "app", "value": "Finance"}]))
    _hosts(c)
    _exposure(c)
    _snapshot(c, "2026-10-26")
    _detection(c, "fanout", datetime(2026, 10, 21, tzinfo=UTC), severity="high")
    _detection(c, "auth_to_non_dc", datetime(2026, 10, 22, tzinfo=UTC), summary={"target": "dc", "port": 88})
    d = datetime(2026, 10, 22, tzinfo=UTC)
    _baseline(c, [("/orgs/1/workloads/a", "/orgs/1/workloads/db", 3389, d, "allowed"),
                  ("ip:10.9.9.9", "/orgs/1/workloads/a", 445, d, "unknown")])
    _rollup(c, [("2026-10-21", "ip:10.5.5.5", "/orgs/1/workloads/a", 445, "allowed", 10),
                ("2026-10-23", "/orgs/1/workloads/a", "ip:8.8.8.8", 53, "allowed", 3)])
    return c


def _outputs(ctx, report_type, lang):
    inp = BuildInput(ctx=ctx, params=ReportParams(report_type=report_type), start=START, end=END, lang=lang,
                     tz=UTC, now=NOW, pce_label="pce")
    doc = specs()[report_type].build(inp).model_copy(update={"gui_link": "https://ops.example/reports?id=1"})
    wb = load_workbook(BytesIO(render_xlsx(doc, tz=UTC)))
    cells = "\n".join(str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row
                      if c.value is not None)
    mail = render_email(doc, tz=UTC)
    return {"html": render_html(doc, tz=UTC), "xlsx": cells + "\n" + "\n".join(wb.sheetnames),
            "email": mail.subject + "\n" + mail.text + "\n" + (mail.html or "")}


@pytest.mark.parametrize("lang", [Language.EN, Language.ZH_TW])
@pytest.mark.parametrize("report_type", list(ReportType))
def test_no_raw_keys_in_output(ctx, report_type, lang):
    for kind, text in _outputs(ctx, report_type, lang).items():
        body = text.split("<style>", 1)[0] + text.split("</style>", 1)[-1].split("<script>", 1)[0]
        found = sorted(set(RAW_KEY.findall(body)))
        assert found == [], f"{report_type} {lang} {kind}: {found}"


@pytest.mark.parametrize("report_type", list(ReportType))
def test_zh_tw_has_no_english_report_copy(ctx, report_type):
    english = [v for k, v in EN.items() if k.startswith(("rpt_", "detector_name_")) and len(v) > 12
               and not re.search(r"\{\w+\}", v) and v.isascii()]
    for kind, text in _outputs(ctx, report_type, Language.ZH_TW).items():
        leaked = [s for s in english if s in text]
        assert leaked == [], f"{report_type} {kind}: {leaked[:3]}"


def test_period_kept_in_both_languages(ctx):
    for lang in Language:
        assert "2026-10-20 – 2026-10-26" in _outputs(ctx, ReportType.LATERAL_POSTURE, lang)["email"]
    assert START + timedelta(days=7) == END
