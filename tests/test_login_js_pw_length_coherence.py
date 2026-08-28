"""batch 6 final review 的 Minor：login.js 前端密碼長度檢查（原本 < 8）與
server 端 /api/security 的實際門檻（12，見 src/gui/routes/config.py 的
``12 <= len(new_pw) <= 512``）及 login.html 的 minlength="12" 不一致。

修正後三處（JS、HTML、i18n 文案）都應以 12 為準，避免使用者在前端通過驗證，
送到後端卻被拒絕的落差體驗。
"""
from __future__ import annotations

import re
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


# #10: login_err_pw_short shipped in system.mjs's password-change form
# without the gui_ prefix, so it never reached /api/ui_translations
# (src/gui/_helpers.py's _ui_translation_dict whitelists by prefix) and t()
# rendered the bare key name to the user. login.mjs already had this right
# (see the note above); the coherence test above only scanned login.mjs,
# which is why nothing caught the system.mjs twin. This test scans every
# v2 area module and calls the real _ui_translation_dict filter — not a
# copy of its prefix list, which would silently drift from the real one —
# so any literal t() key that the endpoint would actually drop is caught
# regardless of which area file it lives in.
AREAS_DIR = REPO_ROOT / "src" / "static" / "js" / "v2" / "areas"

# Matches only a bare `t("key")` call: \b keeps this from matching the tail
# of unrelated identifiers/calls that happen to end in "t(" followed by a
# quote (e.g. `.split("_")`, `new Event("change")`, `.get("hl")`,
# `.request("POST", ...)`) — those are real strings in this codebase and,
# without the \b, are indistinguishable from a call to t() by this regex.
T_CALL_RE = re.compile(r'\bt\(\s*"([a-zA-Z0-9_]+)"')


def test_all_area_modules_only_call_t_with_whitelisted_keys():
    from src.gui._helpers import _ui_translation_dict

    # en/zh_TW carry the same key set (see the locale-parity test elsewhere
    # in this suite); either locale exercises the same prefix/extra-key
    # filter, which is what this test is actually checking.
    allowed = _ui_translation_dict("en")

    offenders: dict[str, set[str]] = {}
    for mjs in sorted(AREAS_DIR.glob("*.mjs")):
        text = mjs.read_text(encoding="utf-8")
        for key in T_CALL_RE.findall(text):
            if key not in allowed:
                offenders.setdefault(mjs.name, set()).add(key)

    assert not offenders, (
        "t() called with key(s) that _ui_translation_dict() filters out, "
        "so they can never resolve through /api/ui_translations and will "
        f"render as the literal key name: {offenders}"
    )
