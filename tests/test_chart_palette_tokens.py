"""Phase 3C Task 2：圖表與資料模型的語意色與報表殼同源。

matplotlib 收的是 RGB 值，不是 CSS，所以圖表這一側**無法**用 `var(--tone-…)`。
能做到的是「同源」：色值一律從 `SHELL_CSS` 的 `:root` token 解析出來，程式碼裡
不再有自己的十六進位表。這條守門把「同源」寫成可執行的斷言。

為什麼需要它：Phase 2B 驗收報告的待辦 G 就是「圖表仍是 matplotlib 預設藍，與
報表的設計語彙不一致」。而且更糟的是**同一份報表內部**不一致——`_SEMANTIC_COLORS`
把 `low` 畫成綠色，`report_shell.SEVERITY_TONE`（HTML 徽章走的那份）卻是
`LOW → info`。表格徽章與圓餅圖對同一個嚴重度給不同顏色，讀者無從得知哪個才算數。
"""
from __future__ import annotations

import re

import pytest

from src.report.exporters import chart_renderer
from src.report.exporters.report_shell import SHELL_CSS, TONE_HEX
from src.report.analysis.audit import audit_risk

_HEX = re.compile(r"#[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{3})?\b(?![0-9A-Fa-f])")


def _shell_root_values() -> set[str]:
    """殼的 `:root` 區塊宣告的每一個色值（大小寫正規化）。"""
    start = SHELL_CSS.index(":root {")
    end = SHELL_CSS.index("}", start)
    return {v.upper() for v in _HEX.findall(SHELL_CSS[start:end])}


def _chart_palette() -> dict[str, str]:
    """圖表與資料模型端所有會畫到紙上的色值，逐個命名以便錯誤訊息指得出來。"""
    out: dict[str, str] = {}
    for name, table in (
        ("SIGNAL_COLORS", chart_renderer.SIGNAL_COLORS),
        ("VERDICT_COLORS", chart_renderer.VERDICT_COLORS),
        ("_SEMANTIC_COLORS", chart_renderer._SEMANTIC_COLORS),
        ("RISK_COLOR", audit_risk.RISK_COLOR),
        ("RISK_BG", audit_risk.RISK_BG),
    ):
        for key, value in table.items():
            out[f"{name}[{key!r}]"] = value
    out["CHART_INK"] = chart_renderer.CHART_INK
    return out


def test_every_chart_colour_is_a_value_the_shell_declares():
    shell = _shell_root_values()
    strays = {
        name: value for name, value in _chart_palette().items()
        if value.upper() not in shell
    }
    assert not strays, (
        "圖表色盤出現殼沒有宣告的色值。圖表這一側不能用 var()，所以規則是"
        "「值必須從 SHELL_CSS 的 :root 解析出來」——請走 TONE_HEX／SHELL_INK，"
        "不要自己寫死：\n  "
        + "\n  ".join(f"{k} = {v}" for k, v in sorted(strays.items()))
    )


def test_the_chart_agrees_with_the_html_badge_on_every_severity():
    """同一個嚴重度，圓餅圖的顏色與表格徽章的 tone 必須是同一個。

    這條才是重點。上面那條只保證「用的是殼的顏色」，不保證用對；`low` 曾經
    在圖上是綠的、在徽章上是 info 藍。
    """
    from src.report.exporters.report_shell import SEVERITY_TONE

    mismatches = []
    for sev, tone in SEVERITY_TONE.items():
        label = sev.lower()
        chart = chart_renderer._SEMANTIC_COLORS.get(label)
        if chart is None:
            continue  # 圖表沒有這個標籤的語意色，不是不一致
        expected = TONE_HEX[tone]
        if chart.upper() != expected.upper():
            mismatches.append(
                f"{sev}: 圖 {chart}，徽章 tone={tone} → {expected}")
    assert not mismatches, (
        "圖表與 HTML 徽章對同一個嚴重度給了不同顏色：\n  "
        + "\n  ".join(mismatches))


def test_tone_hex_is_parsed_from_the_shell_not_retyped():
    """TONE_HEX 的每個值都要真的出現在 SHELL_CSS 的 tone 宣告裡。

    手打一份對照表是這個任務要消滅的東西本身；如果 TONE_HEX 變成第二份手打
    的表，換色時它一樣會落後。
    """
    for tone, value in TONE_HEX.items():
        decl = f"--tone-{tone}-border: {value};"
        assert decl in SHELL_CSS, f"TONE_HEX[{tone!r}] 與殼不符，找不到 {decl!r}"


@pytest.mark.parametrize("label,tone", [
    ("allowed", "ok"),
    ("blocked", "crit"),
    ("potentially blocked", "warn"),
    ("unknown", "neutral"),
])
def test_the_verdict_vocabulary_keeps_its_meaning(label, tone):
    """判定語彙的語意固定：Allowed 是好的、Blocked 是壞的、PB 是要注意的。

    2026-07-23 的視覺實檢抓過一次「98% Potentially Blocked 被畫成安全綠」，
    那是用順序色盤造成的。換成 token 之後這條把語意本身釘住。
    """
    assert chart_renderer._SEMANTIC_COLORS[label].upper() == TONE_HEX[tone].upper()


def test_critical_and_high_stay_apart_on_a_pie():
    """兩級共用 crit tone，圖上必須有第二個裝置把它們分開。

    分開的方式**不能是把 HIGH 畫淡**：圓餅切片的顏色重量會被讀成量級，淡粉紅的
    HIGH 會比琥珀色的 MEDIUM 還輕，嚴重度排序在圖上被顛倒。所以兩級同紅、
    靠網底分開，而這條斷言同時釘住「同色」與「有網底」——少任何一半都紅。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import to_rgba

    from src.report.exporters.chart_renderer import _build_matplotlib_figure

    spec = {
        "type": "pie", "title": "Severity",
        "data": {"labels": ["CRITICAL", "HIGH", "MEDIUM"], "values": [1, 1, 1]},
        "i18n": {"lang": "en"},
    }
    fig = _build_matplotlib_figure(spec, lang="en")
    try:
        crit, high, medium = fig.axes[0].patches[:3]
        assert crit.get_facecolor() == to_rgba(TONE_HEX["crit"])
        assert high.get_facecolor() == to_rgba(TONE_HEX["crit"]), (
            "HIGH 不得被畫淡——那會讓它看起來比 MEDIUM 還輕")
        assert medium.get_facecolor() == to_rgba(TONE_HEX["warn"])
        assert high.get_hatch(), "HIGH 少了網底，會與 CRITICAL 塌成同一塊紅"
        assert not crit.get_hatch()
        assert not medium.get_hatch()
    finally:
        plt.close(fig)
