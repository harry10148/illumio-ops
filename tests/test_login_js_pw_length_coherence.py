"""batch 6 final review 的 Minor：login.js 前端密碼長度檢查（原本 < 8）與
server 端 /api/security 的實際門檻（12，見 src/gui/routes/config.py 的
``12 <= len(new_pw) <= 512``）及 login.html 的 minlength="12" 不一致。

修正後三處（JS、HTML、i18n 文案）都應以 12 為準，避免使用者在前端通過驗證，
送到後端卻被拒絕的落差體驗。
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


# Phase 2A Task 11 note: the three surfaces are the same three, one layer
# over. src/static/js/login.js and the server-rendered src/templates/
# login.html were replaced by the single v2 login module, which builds the
# fields AND validates them; the i18n key it reads is gui_login_err_pw_short
# (the login_* prefix cannot resolve through /api/ui_translations, see
# src/static/js/v2/areas/login.mjs's header note 6). Nothing was dropped:
# the JS floor, the input constraint and the message all still have to say
# 12, and tests/test_v2_login_e2e.py proves the rendered inputs really carry
# minlength=12 in a browser.
LOGIN_MJS = REPO_ROOT / "src" / "static" / "js" / "v2" / "areas" / "login.mjs"


def test_login_js_uses_12_char_minimum_matching_server():
    js = LOGIN_MJS.read_text(encoding="utf-8")
    assert "newPw.length < 12" in js
    assert "newPw.length < 8" not in js


def test_login_input_minlength_matches_server():
    js = LOGIN_MJS.read_text(encoding="utf-8")
    # Both password inputs (new + confirm), built by login.mjs's field().
    assert js.count(".input.minLength = 12;") == 2
    assert "minLength = 8" not in js


def test_login_err_pw_short_i18n_says_12_in_both_locales():
    import json
    en = json.loads((REPO_ROOT / "src" / "i18n_en.json").read_text(encoding="utf-8"))
    zh = json.loads((REPO_ROOT / "src" / "i18n_zh_TW.json").read_text(encoding="utf-8"))
    assert "12" in en["gui_login_err_pw_short"]
    assert "8" not in en["gui_login_err_pw_short"]
    assert "12" in zh["gui_login_err_pw_short"]
    assert "8" not in zh["gui_login_err_pw_short"]
