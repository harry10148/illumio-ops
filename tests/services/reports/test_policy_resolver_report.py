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
from tests.services.collect.conftest import configured_ctx

NOW = datetime(2026, 10, 30, 1, tzinfo=UTC)
ROW = {"ruleset_name": "Web", "rule_href": "/r/1", "action": "allow", "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2",
       "port": 1433, "protocol": "TCP", "src_kind": "label", "dst_kind": "label", "service_name": ""}


def _resolved(**kw):
    base = {"rows": [ROW], "per_ruleset": {"Web": 1}, "rule_count": 1, "rules_capped": 0, "truncated_rulesets": [],
            "rows_omitted": 0, "not_expanded": [], "rules_no_address": 0, "computed_at": NOW}
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


@pytest.mark.parametrize(("lang", "words"), [(Language.ZH_TW, "沒有位址可展開 2 條"), (Language.EN, "no address to expand: 2")])
def test_rules_without_addresses_are_in_the_sentence_and_the_files(ctx, monkeypatch, lang, words):
    """lab .106 2026-11-03: "2 rules in force expanded into 0 rows; 0 could not be expanded" — the reader needs the
    number that makes it add up."""
    monkeypatch.setattr(report, "resolve", lambda ctx, **kw: _resolved(rows=[], per_ruleset={}, rule_count=2,
                                                                       rules_no_address=2))
    doc = _build(ctx, lang)
    assert {k.key: k.value for k in doc.kpis}["no_address"] == 2 and doc.export.meta["rules_no_address"] == 2
    from illumio_ops.domain.conclusion import conclusion
    from illumio_ops.i18n import translate
    assert words in conclusion(doc, lambda key, params: translate(lang, key, params))


def test_rules_without_addresses_are_named_with_the_empty_side(ctx, monkeypatch):
    """lab .106 run 146: 0 rows and "2 resolving to no address", with nothing saying which rules or why. Both were
    Quarantine deny rules whose label no host carried. Each is named with the side that has no address; past
    NO_ADDRESS_NAMED the rest are counted. The files carry all of them."""
    rules = [("Quarantine", f"/orgs/1/sec_policy/active/rule_sets/100/deny_rules/{i}", side)
             for i, side in enumerate(["providers", "consumers", "both", "scope", "providers", "providers", "providers"])]
    monkeypatch.setattr(report, "resolve", lambda ctx, **kw: _resolved(rows=[], per_ruleset={"Quarantine": 0},
                                                                       rule_count=7, rules_no_address=7, no_address=rules))
    doc = _build(ctx)
    f = next(x for x in doc.findings if "no address" in x.title)
    assert f.title == "7 rules produced no row: no address to expand"
    assert f.why.startswith("Quarantine: deny_rules/0 (destination has no address), deny_rules/1 (source has no address), "
                            "deny_rules/2 (neither side has an address), "
                            "deny_rules/3 (source and destination are never in the same scope), ")
    assert f.why.endswith("and 2 more.")
    assert doc.export.meta["no_address_rules"].count("deny_rules/") == 7
    assert "deny_rules/6 (providers)" in doc.export.meta["no_address_rules"]
    zh = _build(ctx, Language.ZH_TW)
    assert any("目的端沒有位址" in x.why and "其餘 2 條" in x.why for x in zh.findings)


def test_no_rule_without_addresses_no_finding(ctx):
    doc = _build(ctx)
    assert not any("no address" in x.title for x in doc.findings) and doc.export.meta["no_address_rules"] == ""
