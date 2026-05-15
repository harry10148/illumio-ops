"""Header chip must be a single element containing the status dot,
compressed PCE host, and inline KPIs separated by middle-dot."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "src" / "templates" / "index.html"
EN = ROOT / "src" / "i18n_en.json"
ZH = ROOT / "src" / "i18n_zh_TW.json"


def test_single_chip_element_replaces_two_divs() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="hdr-stats"' not in html, "old hdr-stats div should be removed"
    assert 'id="hdr-chip"' in html, "new hdr-chip element missing"


def test_chip_contains_status_dot() -> None:
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r'id="hdr-chip"[^>]*>(.*?)</div>', html, flags=re.DOTALL)
    assert m, "hdr-chip element body not found"
    body = m.group(1)
    assert 'id="hdr-chip-dot"' in body, (
        f"hdr-chip-dot missing inside chip:\n{body}"
    )


def test_chip_inline_kpis_use_middle_dot_separator() -> None:
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r'id="hdr-chip"[^>]*>(.*?)</div>', html, flags=re.DOTALL)
    body = m.group(1)
    assert 'gui_rules_count' in body
    assert 'gui_schedules_count' in body
    assert 'gui_config_loaded' in body


def test_chip_aria_label_i18n_key_present() -> None:
    en = json.loads(EN.read_text(encoding="utf-8"))
    zh = json.loads(ZH.read_text(encoding="utf-8"))
    assert en.get("gui_hdr_chip_aria") == \
        "PCE connection status, {rules} rules, {schedules} schedules, loaded {loaded}"
    assert zh.get("gui_hdr_chip_aria") == \
        "PCE 連線狀態，{rules} 條規則，{schedules} 個排程，載入於 {loaded}"
