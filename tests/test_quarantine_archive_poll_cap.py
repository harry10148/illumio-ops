"""Static assertions: archive-load status polling in quarantine.js must cap
iterations (720) instead of looping forever, and must surface a bilingual
i18n message via the existing error-display style on timeout.

Hardening Follow-ups §F.3 (2026-07-10 sweep)."""
import json
from pathlib import Path

_JS = Path("src/static/js/quarantine.js")
_EN = Path("src/i18n_en.json")
_ZH = Path("src/i18n_zh_TW.json")


def test_archive_poll_loop_has_720_cap():
    src = _JS.read_text(encoding="utf-8")
    assert "ARCHIVE_POLL_MAX = 720" in src
    fn = src.split("async function loadArchiveRange()", 1)[1].split("\nasync function ", 1)[0]
    assert "for (;;)" not in fn  # 不可再是無限迴圈
    assert "ARCHIVE_POLL_MAX" in fn
    # 超限時沿用既有錯誤樣式（同一個 el.textContent 賦值路徑）顯示逾時訊息
    assert "gui_traffic_archive_poll_timeout" in fn
    assert fn.count("el.textContent") >= 4


def test_archive_poll_timeout_key_bilingual():
    en = json.loads(_EN.read_text(encoding="utf-8"))
    zh = json.loads(_ZH.read_text(encoding="utf-8"))
    assert en.get("gui_traffic_archive_poll_timeout", "").strip()
    assert zh.get("gui_traffic_archive_poll_timeout", "").strip()
