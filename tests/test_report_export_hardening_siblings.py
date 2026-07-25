"""Regression tests for the sibling report exporters (review batch 3, residuals).

The traffic HTML/CSV exporters were hardened first; these gates cover the same
defect classes in every remaining exporter plus the four analysis-side residuals:

  - no 0-byte report left behind when document build raises
  - collision-safe, atomic output filenames (same-minute concurrent runs)
  - a failed draft-PD query must not render as "no risk detected"
  - a failed VEN xlsx export must be surfaced, not swallowed
  - the Policy Resolver total row cap must disclose what it dropped
  - query-failed / pending rules must not be counted as unused
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from src.report.exporters.app_summary_html_exporter import AppSummaryHtmlExporter
from src.report.exporters.audit_html_exporter import AuditHtmlExporter
from src.report.exporters.policy_diff_html_exporter import PolicyDiffHtmlExporter
from src.report.exporters.policy_resolver_exporter import PolicyResolverExporter
from src.report.exporters.policy_usage_html_exporter import PolicyUsageHtmlExporter
from src.report.exporters.readiness_html_exporter import ReadinessHtmlExporter
from src.report.exporters.rule_hit_count_html_exporter import RuleHitCountHtmlExporter
from src.report.exporters.ven_html_exporter import VenHtmlExporter

# (exporter factory, name of the document-build method)
_EXPORTERS = [
    pytest.param(lambda: AuditHtmlExporter({}), "_build", id="audit"),
    pytest.param(lambda: PolicyUsageHtmlExporter({}), "_build", id="policy_usage"),
    pytest.param(lambda: VenHtmlExporter({}), "_build", id="ven"),
    pytest.param(lambda: ReadinessHtmlExporter({}), "_render_html", id="readiness"),
    pytest.param(lambda: RuleHitCountHtmlExporter({}), "_render_html", id="rule_hit_count"),
    pytest.param(lambda: PolicyDiffHtmlExporter({}), "_render_html", id="policy_diff"),
    pytest.param(lambda: AppSummaryHtmlExporter({"app": "web"}), "_render_html", id="app_summary"),
]


@pytest.mark.parametrize("factory,build_attr", _EXPORTERS)
def test_export_leaves_no_file_when_build_fails(factory, build_attr, tmp_path):
    """建置期例外不可留下 0-byte 報表：GUI 的報表列表只看副檔名，殘檔照樣列出。"""
    exporter = factory()
    setattr(exporter, build_attr,
            lambda *a, **k: (_ for _ in ()).throw(KeyError("boom")))
    with pytest.raises(KeyError):
        exporter.export(str(tmp_path))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("factory,build_attr", _EXPORTERS)
def test_export_does_not_overwrite_a_same_minute_run(factory, build_attr, tmp_path):
    first_exp, second_exp = factory(), factory()
    setattr(first_exp, build_attr, lambda *a, **k: "<html>first</html>")
    setattr(second_exp, build_attr, lambda *a, **k: "<html>second</html>")
    first = first_exp.export(str(tmp_path))
    second = second_exp.export(str(tmp_path))
    assert first != second, "same-minute export reused the filename"
    assert Path(first).read_text(encoding="utf-8") == "<html>first</html>"
    assert Path(second).read_text(encoding="utf-8") == "<html>second</html>"
    # 檔名格式不得改變：只有真的撞名的那一份才帶 -2 後綴。
    assert Path(first).name.endswith(".html") and "-2." not in Path(first).name
    assert Path(second).stem.endswith("-2")


def test_policy_resolver_json_export_is_collision_safe(tmp_path):
    first = PolicyResolverExporter({"rulesets": {}}).export_json(str(tmp_path))
    second = PolicyResolverExporter({"rulesets": {}}).export_json(str(tmp_path))
    assert first != second
    assert os.path.exists(first) and os.path.exists(second)


def test_policy_resolver_json_leaves_no_file_when_serialization_fails(tmp_path):
    class _Unserializable:
        pass

    exporter = PolicyResolverExporter({"rulesets": _Unserializable()})
    with pytest.raises(TypeError):
        exporter.export_json(str(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_no_exporter_writes_report_output_with_plain_open():
    """通用不變量：報表輸出一律走 _output_paths 的 reserve + atomic write。

    直接 open(path, "w") 會同時帶回兩個缺陷——同分鐘撞名互相覆寫，以及
    建置中途拋錯留下半截檔案。新增 exporter 時這條測試會擋下回歸。
    """
    root = Path(__file__).resolve().parents[1] / "src" / "report" / "exporters"
    offenders = []
    for path in sorted(root.glob("*.py")):
        if path.name == "_output_paths.py":  # 唯一被授權的實作點
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "open"):
                continue
            mode = node.args[1] if len(node.args) > 1 else None
            mode_val = mode.value if isinstance(mode, ast.Constant) else ""
            if isinstance(mode_val, str) and mode_val[:1] in ("w", "a", "x"):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], f"plain write-mode open() in exporters: {offenders}"


# ── R1: failed draft-PD query must not read as a clean result ────────────────

def test_draft_pd_failure_renders_a_warning_not_an_all_clear():
    empty = PolicyUsageHtmlExporter({"mod05": {"skipped": True, "reason": "no flows returned"}})
    empty._s = lambda k: k
    empty_html = empty._mod05_html()
    assert "rpt_pu_draft_pd_empty" in empty_html

    failed = PolicyUsageHtmlExporter(
        {"mod05": {"skipped": True, "failed": True, "reason": "PCE 503"}})
    failed._s = lambda k: k
    failed_html = failed._mod05_html()
    assert "rpt_pu_draft_pd_empty" not in failed_html, \
        "failed draft-PD query rendered as 'no risk detected'"
    assert "note-warn" in failed_html
    assert "PCE 503" in failed_html


def test_draft_pd_failure_reason_is_html_escaped():
    exp = PolicyUsageHtmlExporter(
        {"mod05": {"skipped": True, "failed": True, "reason": "<script>x</script>"}})
    exp._s = lambda k: k
    out = exp._mod05_html()
    assert "<script>" not in out and "&lt;script&gt;" in out


# ── R4: VEN xlsx export failure must be surfaced ─────────────────────────────

def test_ven_xlsx_failure_is_recorded_and_partial_file_removed(tmp_path, monkeypatch):
    from src.report import ven_status_generator as vsg

    def _boom(analysis, out_path, *, lang="en"):
        with open(out_path, "wb") as fh:      # 模擬寫到一半才失敗的活頁簿
            fh.write(b"PK\x03\x04partial")
        raise RuntimeError("ENOSPC")

    monkeypatch.setattr(vsg, "generate_ven_xlsx", _boom)
    gen = vsg.VenStatusGenerator(config_manager=None)
    result = vsg.VenStatusResult(module_results={})
    paths = gen.export(result, fmt="xlsx", output_dir=str(tmp_path))

    assert paths == []
    assert gen.last_export_errors["xlsx"] == "ENOSPC"
    assert list(tmp_path.glob("*.xlsx")) == [], "truncated workbook was left behind"


# ── R5: Policy Resolver total row cap must disclose ──────────────────────────

def _resolver_report(monkeypatch, rulesets, rows_per_ruleset):
    from src.report import policy_resolver_report as prr

    def _fake_resolve(rs, **lookups):
        return [{"ruleset_name": rs["name"], "rule_href": "h", "action": "allow",
                 "src_ip": f"10.0.0.{i % 250}", "dst_ip": "10.1.1.1", "port": 443,
                 "protocol": "tcp", "src_kind": "label", "dst_kind": "label",
                 "service_name": "HTTPS"} for i in range(rows_per_ruleset)]

    monkeypatch.setattr(prr, "resolve_ruleset", _fake_resolve)
    monkeypatch.setattr(prr, "_MAX_TOTAL_ROWS", 10)

    class _Api:
        def get_active_rulesets(self, raise_on_error=False):
            return rulesets
        def fetch_managed_workloads(self):
            return []
        def get_ip_lists(self, raise_on_error=False):
            return []
        def get_label_groups(self, raise_on_error=False):
            return []
        def get_services(self, raise_on_error=False):
            return []

    return prr.PolicyResolverReport(cm=None, api_client=_Api()).resolve()


def test_policy_resolver_total_cap_is_disclosed(monkeypatch):
    out = _resolver_report(monkeypatch,
                           [{"name": "rs-a"}, {"name": "rs-b"}, {"name": "rs-c"}], 6)
    assert out["record_count"] == 10
    assert out["truncated"] is True
    assert out["rows_omitted"] == 8          # 18 resolved - 10 kept
    assert out["truncated_rulesets"] == ["rs-b", "rs-c"]
    # 每個被砍的 ruleset 都要在自己的列裡寫明，CSV 端才看得到（JSON 端另有欄位）。
    for name in ("rs-b", "rs-c"):
        notice = out["rulesets"][name][-1]
        assert notice["truncated"] == "total_row_cap"
        assert "rows omitted" in notice["src_ip"]
    assert out["rulesets"]["rs-a"][-1].get("truncated") is None


def test_policy_resolver_under_the_cap_declares_nothing(monkeypatch):
    out = _resolver_report(monkeypatch, [{"name": "rs-a"}], 3)
    assert out["record_count"] == 3
    assert "truncated" not in out and "rows_omitted" not in out


# ── R6: query-failed rules are not "unused" ──────────────────────────────────

def test_pu_overview_excludes_query_failed_rules_from_unused():
    from src.report.analysis.policy_usage.pu_mod01_overview import pu_overview

    rules = [{"href": f"/r/{i}"} for i in range(10)]
    hit = {"/r/0", "/r/1"}
    stats = {
        "failed_rule_details": [{"rule_href": "/r/2"}, {"rule_href": "/r/3"}],
        "pending_rule_details": [{"rule_href": "/r/4"}],
    }
    out = pu_overview(rules, hit, stats)
    assert out["hit_count"] == 2
    assert out["indeterminate_count"] == 3
    assert out["unused_count"] == 5, "query-failed/pending rules counted as unused"
    assert out["total_rules"] == 10
    # summary_df 必須跟純量一致，而且把「無法判定」明白寫出來。
    df = out["summary_df"]
    counts = dict(zip(df["Status"], df["Count"]))
    assert counts["Hit"] == 2 and counts["Unused"] == 5
    indet_label = [s for s in df["Status"] if s.startswith("Indeterminate")]
    assert indet_label and counts[indet_label[0]] == 3
    assert int(df["Count"].sum()) == 10


def test_pu_overview_without_execution_stats_has_no_indeterminate_row():
    from src.report.analysis.policy_usage.pu_mod01_overview import pu_overview

    out = pu_overview([{"href": f"/r/{i}"} for i in range(4)], {"/r/0"})
    assert out["unused_count"] == 3 and out["indeterminate_count"] == 0
    assert list(out["summary_df"]["Status"]) == ["Hit", "Unused"]


def test_overview_section_reconciles_with_mod03_indeterminate_count():
    """mod01 若沒拿到 execution_stats，報表改採 mod03 的分流數字，不得兩個口徑並存。"""
    from src.report.analysis.policy_usage.pu_mod01_overview import pu_overview

    mod01 = pu_overview([{"href": f"/r/{i}"} for i in range(10)], {"/r/0", "/r/1"})
    exp = PolicyUsageHtmlExporter({"mod01": mod01,
                                   "mod03": {"indeterminate_count": 3}})
    exp._s = lambda k: k
    # 執行摘要的 KPI 與 overview 區塊必須是同一個未使用口徑。
    mod00 = {"kpis": [{"label_key": "rpt_pu_unused_rules", "label": "Unused Rules",
                       "value": "8"}]}
    assert exp._reconciled_mod00(mod00)["kpis"][0]["value"] == "5"

    html = exp._mod01_html()
    assert "Indeterminate" in html, html
    assert ">5<" in html.replace(" ", ""), html   # confirmed unused, not 8
    assert ">8<" not in html.replace(" ", ""), html
    assert "note-warn" in html
