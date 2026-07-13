"""報表卡片 icon 對應（真機回饋 2026-07-13）。

每個報表家族的卡片與產生 modal 必須用對應內容的 icon，不得全部共用盾牌
（盾牌保留給資安與風險報表）。比照本 repo 靜態字串斷言慣例（無 JS runtime）。
"""
from __future__ import annotations

import re
from pathlib import Path

_HTML = Path("src/templates/index.html")
_JS = Path("src/static/js/dashboard.js")

# 報表家族 → icon 語意：流量=播放、資安=盾、盤點=放大鏡、稽核=剪貼板、
# VEN=晶片、Policy 使用=長條圖、命中次數=靶心、就緒度=勾選圓、
# Diff=＋/−差異、Resolver=層疊展開、App 摘要=格狀。
EXPECTED = {
    "traffic": "#icon-play",
    "security_risk": "#icon-shield",
    "network_inventory": "#icon-search",
    "audit": "#icon-clipboard",
    "ven": "#icon-cpu",
    "policy_usage": "#icon-bar-chart",
    "rule_hit_count": "#icon-target",
    "readiness": "#icon-check-circle",
    "policy_diff": "#icon-diff",
    "policy_resolver": "#icon-layers",
    "app_summary": "#icon-grid",
}


def _card_blocks(html: str):
    idxs = [(m.group(1), m.start()) for m in re.finditer(r'data-rtype="([a-z_]+)"', html)]
    for i, (rtype, start) in enumerate(idxs):
        end = idxs[i + 1][1] if i + 1 < len(idxs) else start + 1200
        yield rtype, html[start:end]


def test_report_cards_use_content_specific_icons():
    html = _HTML.read_text(encoding="utf-8")
    seen = set()
    for rtype, block in _card_blocks(html):
        assert rtype in EXPECTED, f"unexpected report card {rtype}"
        # 每卡兩個 use（rcard-icon + Generate 按鈕），只取本卡前兩個避免越界
        hrefs = set(re.findall(r'<use href="(#icon-[a-z-]+)"', block)[:2])
        assert hrefs == {EXPECTED[rtype]}, f"{rtype}: {hrefs} != {EXPECTED[rtype]}"
        seen.add(rtype)
    assert seen == set(EXPECTED)


def test_report_card_icons_defined_in_sprite():
    html = _HTML.read_text(encoding="utf-8")
    for icon in set(EXPECTED.values()):
        assert f'<symbol id="{icon[1:]}"' in html, f"sprite missing {icon}"


def test_gen_modal_meta_icons_match_cards():
    js = _JS.read_text(encoding="utf-8")
    meta = js.split("const meta = {", 1)[1].split("};", 1)[0]
    for rtype, icon in EXPECTED.items():
        m = re.search(rf"\b{rtype}:\s*{{[^}}]*icon: '([^']+)'", meta)
        assert m, f"modal meta missing {rtype}"
        assert m.group(1) == icon, f"{rtype}: modal {m.group(1)} != card {icon}"


def test_app_header_uses_segment_mark_not_shield():
    """header 的 Illumio PCE Ops 用自有微分段 mark（六邊形＋中心節點）；
    盾牌保留給資安語意（品牌規範不允許模仿官方 logo，app 內用原創 mark）。"""
    html = _HTML.read_text(encoding="utf-8")
    hdr = html.split('<h1 data-i18n="gui_title">', 1)[1].split("</h1>", 1)[0]
    assert '#icon-segment' in hdr and '#icon-shield' not in hdr
    assert '<symbol id="icon-segment"' in html
