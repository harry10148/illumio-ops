"""batch 6 final review 的 Minor：login.js 前端密碼長度檢查（原本 < 8）與
server 端 /api/security 的實際門檻（12，見 src/gui/routes/config.py 的
``12 <= len(new_pw) <= 512``）及 login.html 的 minlength="12" 不一致。

修正後三處（JS、HTML、i18n 文案）都應以 12 為準，避免使用者在前端通過驗證，
送到後端卻被拒絕的落差體驗。
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_login_js_uses_12_char_minimum_matching_server():
    js = (REPO_ROOT / "src" / "static" / "js" / "login.js").read_text(encoding="utf-8")
    assert "newPw.length < 12" in js
    assert "newPw.length < 8" not in js


def test_login_html_minlength_matches_server():
    html = (REPO_ROOT / "src" / "templates" / "login.html").read_text(encoding="utf-8")
    assert 'id="new-password"' in html and 'minlength="12"' in html


def test_login_err_pw_short_i18n_says_12_in_both_locales():
    import json
    en = json.loads((REPO_ROOT / "src" / "i18n_en.json").read_text(encoding="utf-8"))
    zh = json.loads((REPO_ROOT / "src" / "i18n_zh_TW.json").read_text(encoding="utf-8"))
    assert "12" in en["login_err_pw_short"]
    assert "8" not in en["login_err_pw_short"]
    assert "12" in zh["login_err_pw_short"]
    assert "8" not in zh["login_err_pw_short"]
