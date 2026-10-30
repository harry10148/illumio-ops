"""policy_resolver report (P5c-4): JSON and CSV of the active policy's IP-level rows; no HTML (spec §6.5)."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.values import Language, ReportFormat, ReportType
from illumio_ops.pce.collections import PceCollectionIncomplete
from illumio_ops.services.analysis.policy_resolver import COLUMNS, Resolved
from illumio_ops.services.reports import policy_resolver as report
from illumio_ops.services.reports.registry import (
    BuildInput,
    ReportFailed,
    ReportParams,
    specs,
)
from tests_v6.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 30, 1, tzinfo=UTC)
ROW = {"ruleset_name": "Web", "rule_href": "/r/1", "action": "allow", "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2",
       "port": 1433, "protocol": "TCP", "src_kind": "label", "dst_kind": "label", "service_name": ""}


def _resolved(**kw):
    base = {"rows": [ROW], "per_ruleset": {"Web": 1}, "rule_count": 1, "rules_capped": 0, "truncated_rulesets": [],
            "rows_omitted": 0, "not_expanded": [], "computed_at": NOW}
    return Resolved(**{**base, **kw})


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "resolve", lambda ctx, **kw: _resolved())
    return configured_ctx(tmp_path)


def _build(ctx, lang=Language.EN):
    return specs()[ReportType.POLICY_RESOLVER].build(BuildInput(
        ctx=ctx, params=ReportParams(report_type=ReportType.POLICY_RESOLVER, lookback_days=1,
                                     formats=(ReportFormat.JSON, ReportFormat.CSV)),
        start=NOW, end=NOW, lang=lang, tz=UTC, now=NOW, pce_label="pce"))


def test_formats_json_csv_only():
    assert specs()[ReportType.POLICY_RESOLVER].formats == (ReportFormat.JSON, ReportFormat.CSV)


def test_rows_exported(ctx):
    doc = _build(ctx)
    assert doc.export.columns == COLUMNS and doc.export.rows[0][3] == "10.0.0.1"
    assert doc.export.rows[0][COLUMNS.index("port_to")] is None
    k = {x.key: x.value for x in doc.kpis}
    assert (k["rulesets"], k["rules"], k["rows"], k["omitted"]) == (1, 1, 1, 0)


def test_total_cap_disclosed_in_both(ctx, monkeypatch):
    """Review Focus 1: JSON says so (meta) and CSV carries the notice row (from the service)."""
    monkeypatch.setattr(report, "resolve", lambda ctx, **kw: _resolved(rows_omitted=5, truncated_rulesets=["Web"]))
    doc = _build(ctx)
    assert doc.export.meta["truncated"] is True and doc.export.meta["rows_omitted"] == 5
    assert any("5" in q for q in doc.data_quality) and doc.findings


def test_fetch_failure_fails_report(ctx, monkeypatch):
    def boom(ctx, **kw):
        raise PceCollectionIncomplete("/workloads", 0, "HTTP 500")
    monkeypatch.setattr(report, "resolve", boom)
    with pytest.raises(ReportFailed) as e:
        _build(ctx)
    assert e.value.key == "rpt_prs_err_read"


def test_zh_tw_builds(ctx):
    assert _build(ctx, lang=Language.ZH_TW).title


def test_top_level_flag_counts_summarized_and_not_expanded(ctx, monkeypatch):
    """Final review #7: a rule summarized or not expanded leaves the file incomplete too."""
    monkeypatch.setattr(report, "resolve", lambda ctx, **kw: _resolved(rules_capped=1))
    assert _build(ctx).export.meta["truncated"] is True
    monkeypatch.setattr(report, "resolve", lambda ctx, **kw: _resolved(not_expanded=[("Web", "/r/2", "unknown_reference")]))
    doc = _build(ctx)
    assert doc.export.meta["truncated"] is True and doc.export.meta["rules_not_expanded"] == 1
    assert {k.key: k.value for k in doc.kpis}["not_expanded"] == 1 and doc.findings
