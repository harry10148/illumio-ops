"""Phase 3C Task 1：報表色票只能來自 shell token，不得寫死在 exporter 裡。

報表殼一次換色（v2 藍 → v3 橘）之後，散落在 exporter 裡的 `style="color:#..."`
不會跟著動——它們是這種改動的沉默失效點：畫面上大部分變了，少數幾塊還留在舊
主題，而所有既有測試都是綠的（它們檢查結構與文字，不看顏色）。

兩層守門，因為任一層單獨都有看不見的東西：

  1. **渲染層**：六個 exporter 各產一份 HTML，斷言 `<style>` 以外的部位沒有
     任何十六進位色值。這是「使用者實際拿到的東西」，但它只走得到最小 fixture
     打得開的分支——高衝擊區塊、執行模式分佈那些要有資料才渲染的段落，這一層
     看不到。所以它不能單獨存在。
  2. **原始碼層（逐檔 ratchet）**：直接數每個檔案裡的十六進位字面量，除了下面
     列出的豁免外一律為 0。這一層看得到渲染層走不到的分支。它**看不到**的是
     用拼接或 format 組出來的色值（`"#" + code`）——目前 repo 裡沒有這種寫法，
     真的出現時要靠渲染層或人眼。

豁免一律逐檔寫明理由，不寫成「跳過這幾個檔」。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_SRC = REPO_ROOT / "src" / "report"

#: 3 碼與 6 碼十六進位色值。後面的 negative lookahead 擋掉 8 碼（帶 alpha）被
#: 當成 6 碼＋雜訊，也擋掉 git SHA 之類的長字串被切一段出來當顏色。
_HEX = re.compile(r"#[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{3})?\b(?![0-9A-Fa-f])")

#: relpath -> (允許的字面量數量, 理由)。0 不列在這裡——沒列到的檔一律必須是 0。
#:
#: 每一條都是「這裡的色值不能是 CSS 變數」的具體理由，不是「這個檔還沒清」。
_ALLOWED: dict[str, tuple[int, str]] = {
    "exporters/report_shell.py": (
        39,
        "SHELL_CSS 的 :root token 區塊本身——色票就是在這裡定義的，"
        "值必須是字面量。這個檔另有 drift guard 綁住 design/v3/reports/shell.css。",
    ),
    "report_generator.py": (
        32,
        "電子郵件 HTML。收件端（Outlook、Gmail）不解析 CSS 自訂屬性，"
        "var() 在信裡會整條宣告掉掉、留下沒有顏色的文字，所以信件範本只能寫死。"
        "這份範本已經是 v3 品牌色。另含 severity→色 的對照表，Task 2 收斂。",
    ),
    "exporters/chart_renderer.py": (
        17,
        "matplotlib 收的是 RGB 值，不是 CSS——var() 在這裡無從解析。"
        "Task 2 把它收成一份鏡射 shell tone token 的常數並加子集守門；"
        "屆時這個數字會降到那份常數自己的長度。",
    ),
    "analysis/audit/audit_risk.py": (
        10,
        "risk→色的資料模型層，被 exporter 與 chart 兩邊消費，同樣不經過 CSS。"
        "Task 2 與 chart_renderer 一起收斂。",
    ),
    "exporters/policy_diff_html_exporter.py": (
        3,
        "只有 :hover 那三條。它們是 report_css.py:473-475 的逐字移植，"
        "不依賴任何舊色票變數，且 tone 家族在 v3 沒有變動，所以它們與底下的"
        "var(--tone-*-bg) 配對關係沒有跟著主色一起漂移。紙上不會 hover，"
        "這三個值只活在螢幕上。",
    ),
}


def _relpaths() -> list[str]:
    return sorted(
        str(p.relative_to(REPORT_SRC)) for p in REPORT_SRC.rglob("*.py")
    )


def test_no_report_module_writes_a_colour_the_shell_should_own():
    """原始碼層：逐檔 ratchet。"""
    offenders: list[str] = []
    for rel in _relpaths():
        text = (REPORT_SRC / rel).read_text(encoding="utf-8")
        found = _HEX.findall(text)
        allowed = _ALLOWED.get(rel, (0, ""))[0]
        if len(found) > allowed:
            offenders.append(
                f"{rel}: {len(found)} hex literal(s), baseline {allowed} "
                f"— {sorted(set(found))[:8]}"
            )
    assert not offenders, (
        "報表模組出現新的寫死色值。改用 shell 的 token（var(--tone-*-…)、"
        "var(--text-*)、var(--line)…）；真的無法用 CSS 的，把理由加進 "
        "_ALLOWED 並說明為什麼那裡不能是變數：\n  " + "\n  ".join(offenders)
    )


def test_the_baselines_are_not_stale():
    """ratchet 只會往下走：清乾淨了就把 baseline 收緊，否則它會變成永久白名單。"""
    stale: list[str] = []
    for rel, (allowed, _why) in _ALLOWED.items():
        path = REPORT_SRC / rel
        assert path.exists(), f"_ALLOWED 指到不存在的檔：{rel}"
        found = len(_HEX.findall(path.read_text(encoding="utf-8")))
        if found < allowed:
            stale.append(f"{rel}: 實際 {found}，baseline 仍寫 {allowed}")
    assert not stale, "baseline 比實際寬鬆，請收緊：\n  " + "\n  ".join(stale)


# ── 渲染層 ───────────────────────────────────────────────────────────────────

def _strip_generated(html: str) -> str:
    """拿掉 <style>、<script> 與 <svg>。

    前兩者是 token 定義與排序 JS，本來就會帶字面色值。<svg> 是 matplotlib 自己
    序列化出來的圖：它把每個座標軸、每根線的 stroke 都寫成 `#000000`，那是繪圖
    後端的輸出格式，不是 exporter 寫的樣式。圖表要用哪些顏色是 Task 2 的題目
    （`chart_renderer.py` 那份色盤要鏡射 shell 的 tone token，並由子集守門鎖住）。
    """
    out = re.sub(r"<style\b.*?</style>", "", html, flags=re.S | re.I)
    out = re.sub(r"<script\b.*?</script>", "", out, flags=re.S | re.I)
    return re.sub(r"<svg\b.*?</svg>", "", out, flags=re.S | re.I)


def _traffic_results(*, investigation: bool) -> dict:
    """把有上色的分支全部餵開。

    最小 fixture 會讓這一層變成空砲：mod03 的三段覆蓋率條、mod04 的兩種提示框、
    mod13 的執行模式分佈，全部要有資料才渲染，而那正好就是這次改動的所在。
    """
    import pandas as pd

    part_e = pd.DataFrame([{"Risk Level": "High", "host": "h1"}]) if investigation else None
    return {
        "mod01": {}, "mod02": {},
        "mod03": {
            "enforced_coverage_pct": 55,
            "staged_coverage_pct": 25,   # >0 → 琥珀段
            "true_gap_pct": 20,          # >0 → 危險段
        },
        "mod04": {"risk_flows_total": 3, "part_e_investigation": part_e,
                  "part_e_total_hosts": 1},
        "mod05": {}, "mod06": {}, "mod07": {}, "mod08": {}, "mod09": {},
        "mod11": {}, "mod12": {},
        "mod13": {
            "total_score": 62, "grade": "C",
            "enforcement_mode_distribution": {
                "full": 4, "selective": 3, "visibility_only": 2, "idle": 1,
            },
        },
        "mod14": {}, "mod15": {},
    }


def _audit_results() -> dict:
    return {
        "mod03": {
            "total_policy_events": 12,
            "provision_count": 3,
            "rule_change_count": 2,
            "total_workloads_affected": 120,   # > threshold → crit 墨色
            "high_impact_threshold": 50,
            "high_impact_provisions": [{
                "workloads_affected": 120,
                "timestamp": "2026-06-05T12:00:00Z",
                "event_type": "workloads.update",
                "actor": "bob",
                "src_ip": "10.0.0.1",
                "resource_name": "RS-A",
                "status": "success",
            }],
        },
    }


def _policy_usage_results() -> dict:
    import pandas as pd
    return {
        "mod02": {
            "hit_df": pd.DataFrame([{"rule": "r1", "hits": 5}]),
            "record_count": 1,       # count 為真且未截斷 → 走 var(--text-3) 的 note
        },
    }


def _render(name: str) -> str:
    import pandas as pd

    if name == "traffic":
        from src.report.exporters.html_exporter import TrafficFlowsHtmlExporter
        return TrafficFlowsHtmlExporter(
            _traffic_results(investigation=True), lang="en").build()
    # 上色的三段（mod03 覆蓋率條、mod04 提示框、mod13 執行模式）只出現在
    # security_risk 的章節序列裡（`_ordered_section_keys`），traffic 型別不收
    # 這三章。要驗它們就得用會渲染它們的型別。
    if name == "security_risk":
        from src.report.exporters.html_exporter import SecurityRiskHtmlExporter
        return SecurityRiskHtmlExporter(
            _traffic_results(investigation=True), lang="en").build()
    if name == "security_risk_no_investigation":
        from src.report.exporters.html_exporter import SecurityRiskHtmlExporter
        return SecurityRiskHtmlExporter(
            _traffic_results(investigation=False), lang="en").build()
    if name == "audit":
        from src.report.exporters.audit_html_exporter import AuditHtmlExporter
        return AuditHtmlExporter(_audit_results(), lang="en", data_source="cache")._build()
    if name == "ven":
        from src.report.exporters.ven_html_exporter import VenHtmlExporter
        df = pd.DataFrame([{"hostname": "h1", "os": "linux"}])
        return VenHtmlExporter({"online": df}, lang="en")._build()
    if name == "policy_usage":
        from src.report.exporters.policy_usage_html_exporter import PolicyUsageHtmlExporter
        return PolicyUsageHtmlExporter(_policy_usage_results(), lang="en")._build()
    if name == "policy_diff":
        from src.report.exporters.policy_diff_html_exporter import PolicyDiffHtmlExporter
        rs = pd.DataFrame([{
            "change_type": "modified", "ruleset_name": "RS-A", "ruleset_id": "1",
            "field": "enabled", "draft_value": "False", "active_value": "True",
            "last_actor": "bob", "last_changed": "2026-06-05T12:00:00Z",
            "last_event": "rule_set.update",
        }])
        rule = pd.DataFrame(columns=["change_type", "ruleset_name", "rule_id", "field",
                                     "draft_value", "active_value",
                                     "last_actor", "last_changed", "last_event"])
        return PolicyDiffHtmlExporter({
            "ruleset_changes": rs, "rule_changes": rule,
            "summary": {"rulesets_added": 0, "rulesets_removed": 0,
                        "rulesets_modified": 1, "rules_added": 0,
                        "rules_removed": 0, "rules_modified": 0,
                        "total_changes": 1},
        }, lang="en")._render_html()
    raise AssertionError(name)


_CASES = ["traffic", "security_risk", "security_risk_no_investigation", "audit",
          "ven", "policy_usage", "policy_diff"]


@pytest.mark.parametrize("name", _CASES)
def test_rendered_report_body_carries_no_hex_colour(name):
    """渲染層：使用者真的拿到的 HTML，<style>／<script>／<svg> 以外不得有色值。"""
    body = _strip_generated(_render(name))
    found = sorted(set(_HEX.findall(body)))
    assert not found, (
        f"{name} 報表的內文帶著寫死色值 {found}——這些不會跟著 shell 換色。"
    )


#: 上一條只斷言「沒有色值」，分支沒渲染時它一樣是綠的——空砲。這一條反過來
#: 斷言那些分支**真的渲染了，而且用的是 token**，所以任一個改回寫死色值，
#: 或者 fixture 退化到打不開那個分支，兩邊都會紅。
_MUST_RENDER: dict[str, tuple[str, ...]] = {
    # needle 要能認出**是哪一段**。單看 `background:var(--tone-ok-border)`
    # 不行——mod03 的已執行段與 mod13 的 full 都會命中，mod03 整段不渲染時
    # 這條照樣是綠的（實測過：只把 mod03 那一條改回寫死色值，這個測試沒紅）。
    # 所以 mod03 三段各自綁自己的 title。
    "security_risk": (
        'background:var(--tone-ok-border)" title="Enforced"',    # mod03 已執行段
        'background:var(--tone-warn-border)" title="Staged"',    # mod03 暫存段
        'background:var(--tone-crit-border)" title="True Gap"',  # mod03 缺口段
        "color:var(--paper)",                   # 覆蓋率條上的白字
        "background:var(--tone-warn-bg);",      # mod04 需調查提示框
        "var(--tone-info-border)",              # mod13 selective
        "var(--tone-neutral-border)",           # mod13 idle
    ),
    "security_risk_no_investigation": (
        "background:var(--tone-ok-bg);",        # mod04 無須調查提示框
    ),
    "audit": (
        "background:var(--tone-crit-bg);",      # 高衝擊區塊底色
        "border:1px solid var(--tone-crit-border);",
        "color:var(--tone-crit-fg);",
        "color:var(--text-3);",                 # 事件列的次要中繼資料
        'style="color:var(--tone-crit-fg)"',    # 超過門檻的統計數字
        "solid var(--tone-ok-border);",         # data_source="cache" 的來源膠囊
    ),
    "policy_usage": (
        '<p style="color:var(--text-3);font-size:12px;">',
    ),
}


@pytest.mark.parametrize("name", sorted(_MUST_RENDER))
def test_the_coloured_branches_actually_render_and_use_tokens(name):
    html = _render(name)
    missing = [needle for needle in _MUST_RENDER[name] if needle not in html]
    assert not missing, (
        f"{name}：這些帶顏色的段落沒有渲染出來，或顏色不再是 token。"
        f"前者代表上面那條『沒有色值』的斷言在這個分支上是空砲，"
        f"fixture 要修；後者代表色值被改回寫死。缺少：{missing}"
    )
