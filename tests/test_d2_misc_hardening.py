"""D2 雜項強化：session cookie Secure flag、login.html 密碼 minlength、
以及 /api/security 與 /api/tls/config 的 write-lock 覆蓋。
"""
from __future__ import annotations

import inspect
import json


def _write_config(tmp_path, **web_gui_overrides):
    cfg = tmp_path / "config.json"
    web_gui = {
        "username": "illumio",
        "password": "illumio",
        "secret_key": "x" * 64,
        "allowed_ips": [],
    }
    web_gui.update(web_gui_overrides)
    cfg.write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "web_gui": web_gui,
    }), encoding="utf-8")
    return str(cfg)


# ── 子項 1：session cookie Secure flag 必須跟隨 use_https ──────────────────

def test_session_cookie_secure_when_https_enabled(tmp_path):
    from src.config import ConfigManager
    from src.gui import build_app

    cm = ConfigManager(config_file=_write_config(tmp_path))
    app = build_app(cm, use_https=True)
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_session_cookie_not_secure_when_https_disabled(tmp_path):
    """修正前 SESSION_COOKIE_SECURE 被寫死 True：TLS 關閉時，瀏覽器經純 HTTP
    連 GUI 永遠不會回傳 session cookie——登入看起來像靜默失敗。"""
    from src.config import ConfigManager
    from src.gui import build_app

    cm = ConfigManager(config_file=_write_config(tmp_path))
    app = build_app(cm, use_https=False)
    assert app.config["SESSION_COOKIE_SECURE"] is False


# ── 子項 2：login.html 密碼欄位必須符合後端的 12 字元下限 ──────────────────

def test_login_page_password_minlength_matches_backend(tmp_path):
    from src.config import ConfigManager
    from src.gui import build_app

    cm = ConfigManager(config_file=_write_config(tmp_path))
    app = build_app(cm, use_https=False)
    app.config["TESTING"] = True
    body = app.test_client().get("/login").get_data(as_text=True)
    assert 'id="new-password"' in body
    assert body.count('minlength="12"') >= 2, "兩個密碼欄位都必須要求 12 字元（對齊 config.py 的 12-512 規則）"
    assert 'minlength="8"' not in body


# ── 子項 5：/api/security 與 /api/tls/config 必須序列化存檔 ────────────────

def test_api_security_post_holds_write_lock_across_load_mutate_save():
    from src.gui.routes import config as config_routes
    src = inspect.getsource(config_routes.make_config_blueprint)
    # 粗略的結構檢查：api_security_post 本體（以下一個 @bp.route 為界）
    # 必須包含 write_lock context manager，比照既有的
    # api_save_settings / api_pce_profiles_action 慣例。
    start = src.index("def api_security_post")
    end = src.index("# ── API: Settings")
    body = src[start:end]
    assert "with cm.write_lock:" in body


def test_api_tls_config_holds_write_lock_across_load_mutate_save():
    from src.gui.routes import config as config_routes
    src = inspect.getsource(config_routes.make_config_blueprint)
    start = src.index("def api_tls_config")
    end = src.index("def api_tls_renew")
    body = src[start:end]
    assert "with cm.write_lock:" in body
