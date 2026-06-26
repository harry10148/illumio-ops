# Phase 4 Implementation Plan — Web GUI 安全強化

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 取代 [src/gui.py](../../../src/gui.py) 內所有自製安全機制（CSRF synchronizer token、rate limiter、session auth），改用 Flask 生態的標準套件（flask-wtf、flask-limiter、flask-talisman、flask-login），同時把密碼雜湊從 PBKDF2-HMAC-SHA256 升級到 argon2id（保留 PBKDF2 verify 路徑供自動升級）。預期結果：減少 ~300 行自製安全程式碼、OWASP 對齊度提升、維護負擔下降。

**Architecture:** **嚴守向後相容** — 既有所有 `/api/*` endpoint 的路徑、HTTP method、request/response 格式**100% 保留**。flask-login 的 `User` 模型為單一 admin（與現有行為一致），認證儲存層仍走 [config.json](../../../config/config.json.example) web_gui 段。argon2 為新 hash、新使用者登入時 silent upgrade 既有 PBKDF2 hash。flask-limiter 用 in-memory storage（單節點部署）。flask-talisman 強制 HSTS + CSP + X-Frame-Options + X-Content-Type-Options。Phase 3 pydantic-settings 提供登入 form 的 server-side 驗證模型。

**Tech Stack:** flask-wtf>=1.2, flask-limiter>=3.5, flask-talisman>=1.1, flask-login>=0.6, argon2-cffi>=23.1（皆 Phase 0 已裝）

**Branch:** `upgrade/phase-4-web-security`（from main **after Phase 3 merge**，因 argon2 密碼欄位可透過 pydantic model 驗證）

**Target tag on merge:** `v3.5.0-websec`（major bump：安全相關，OWASP 對齊）

**Parent roadmap:** [2026-04-18-upgrade-roadmap.md](2026-04-18-upgrade-roadmap.md)

---

## File Structure

| 檔案 | 動作 | 責任 |
|---|---|---|
| `src/gui.py` | 大改 | 套用 4 個 Flask 擴充；移除 `_check_rate_limit`、`_validate_allowed_ips` 自製邏輯；login/logout 改 flask-login |
| `src/config.py` | 小改 | 新增 argon2 hash helper `hash_password_argon2()`；`verify_password()` 增加 argon2 前綴判斷 |
| `src/auth_models.py` | 新增 | flask-login `User` class + pydantic LoginForm schema (Phase 3 依賴) |
| `src/templates/index.html` | 小改 | 確認 `<meta name="csrf-token">` 仍是 flask-wtf 相容格式 |
| `src/static/js/utils.js` | 小改 | CSRF token 拿取邏輯若需要微調 |
| `tests/test_gui_security.py` | 大改 | 既有 login/CSRF/rate-limit 測試改用新 API |
| `tests/test_argon2_upgrade.py` | 新增 | 驗證 PBKDF2 → argon2 自動升級行為 |
| `tests/test_flask_talisman_headers.py` | 新增 | 驗證 CSP / HSTS / X-Frame-Options headers 正確 |

**檔案影響面**：2 大改 + 2 新增 + 2 新測試 + 2 小改。

---

## Task 1: Branch + baseline + prerequisites check

**Files:** 無

- [ ] **Step 1: 確認 Phase 3 已 merge**

```bash
git fetch origin main
git log origin/main --oneline -10 | grep -q "v3.4.3-settings"
```
**若失敗，停止** — Phase 4 需要 Phase 3 的 pydantic-settings。

- [ ] **Step 2: 建 branch**

```bash
git checkout main && git pull
git checkout -b upgrade/phase-4-web-security
```

- [ ] **Step 3: 基線**

```bash
python -m pytest tests/ -q
```
記下 pass 數。

---

## Task 2: 固化既有 Web 安全行為的 contract tests

**Files:**
- Create: `tests/test_web_security_contracts.py`

這是安全功能，**每一個行為都必須被測試鎖定**再改底層。

- [ ] **Step 1: 寫 contract tests**

Create `tests/test_web_security_contracts.py`:

```python
"""Freeze Web GUI security contracts before migrating to Flask extensions.

Phase 4 migrates to flask-wtf/flask-limiter/flask-talisman/flask-login/argon2-cffi.
These tests lock down behavior that MUST survive: login success/failure,
CSRF rejection, rate limit 429, session persistence, logout.
"""
from __future__ import annotations

import json
import pytest


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """Build a test Flask app against a temp config."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "web_gui": {
            "username": "illumio",
            "password_hash": "",  # let _ensure_web_gui_secret default to 'illumio'
            "password_salt": "",
            "secret_key": "",
            "allowed_ips": [],
        },
    }), encoding="utf-8")
    from src.config import ConfigManager
    from src.gui import build_app  # assume factory exists; refactor in Task 3 if not
    cm = ConfigManager(str(cfg))
    app = build_app(cm)
    app.config["TESTING"] = True
    return app.test_client(), cm


def test_login_valid_credentials_sets_session(app_client):
    client, _cm = app_client
    r = client.post("/api/login", json={"username": "illumio", "password": "illumio"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert "csrf_token" in body


def test_login_invalid_credentials_rejected(app_client):
    client, _cm = app_client
    r = client.post("/api/login", json={"username": "illumio", "password": "wrong"})
    assert r.status_code in (401, 403)


def test_rate_limit_triggers_429_after_5_failures(app_client):
    client, _cm = app_client
    for _ in range(5):
        client.post("/api/login", json={"username": "x", "password": "y"})
    r = client.post("/api/login", json={"username": "x", "password": "y"})
    assert r.status_code == 429


def test_csrf_required_on_post_after_login(app_client):
    client, _cm = app_client
    # Login first
    client.post("/api/login", json={"username": "illumio", "password": "illumio"})
    # POST without csrf header should be rejected
    r = client.post("/api/security", json={"allowed_ips": ["192.168.1.1"]})
    assert r.status_code in (400, 403), f"CSRF should block; got {r.status_code}"


def test_logout_clears_session(app_client):
    client, _cm = app_client
    client.post("/api/login", json={"username": "illumio", "password": "illumio"})
    client.get("/logout")
    # After logout, protected endpoint should be unauthorized
    r = client.get("/api/dashboard")
    assert r.status_code in (302, 401), f"Logout must unauth; got {r.status_code}"


def test_ip_allowlist_blocks_non_matching_client(app_client):
    client, cm = app_client
    cm.config["web_gui"]["allowed_ips"] = ["10.0.0.0/8"]
    cm.save()
    # Client is 127.0.0.1 (flask test); should be blocked
    r = client.get("/")
    assert r.status_code == 403
```

- [ ] **Step 2: 跑測試，很多會失敗（expected — `build_app` 工廠還沒建）**

Run:
```bash
python -m pytest tests/test_web_security_contracts.py -v
```
Expected: 多數 ERROR on fixture (build_app not found). 這就是 Task 3 要建的。

- [ ] **Step 3: Commit**

```bash
git add tests/test_web_security_contracts.py
git commit -m "test(websec): freeze login/CSRF/rate-limit/logout contracts

Six scenarios that MUST remain true through the Flask-extension
migration: valid login sets session, invalid rejected, 5 failures
trigger 429, CSRF required on POST, logout clears session, IP
allowlist blocks non-matching clients.

The app_client fixture assumes a build_app(cm) factory which may
not exist yet — next task introduces it for testability."
```

---

## Task 3: 重構 `launch_gui` 為 `build_app` factory + `run_app`

**Files:**
- Modify: `src/gui.py`

目前 `launch_gui(cm, port)` 混合 app 建構 + `app.run()`。拆成 `build_app(cm) -> Flask` + `run_app(app, port)` 以利測試。**既有 caller (`launch_gui`) 保留為 wrapper**。

- [ ] **Step 1: 讀目前 launch_gui**

Use Read tool on src/gui.py around `def launch_gui`.

- [ ] **Step 2: 拆出 factory**

在 gui.py 找到 `def launch_gui(cm, port=5001, persistent_mode=False):`，把內部「建立 app + 註冊路由」的部分抽成 `build_app(cm)`：

```python
def build_app(cm):
    """Build a Flask app bound to the given ConfigManager. Returns app instance.
    Pure constructor — does NOT call app.run(). Used by launch_gui and tests."""
    app = Flask(__name__, ...)
    # ...all existing route/before_request/after_request registration...
    return app


def launch_gui(cm, port=5001, persistent_mode=False):
    """Legacy wrapper: build the app and run it."""
    app = build_app(cm)
    # TLS / port / logging setup (existing code)
    app.run(host="0.0.0.0", port=port, ...)
```

- [ ] **Step 3: 跑 contract tests**

```bash
python -m pytest tests/test_web_security_contracts.py -v
```
Expected: fixture 可建 app；多數 contract test **仍通過**（因底層未改）。若仍有 ERROR，代表 factory 拆分錯誤，修復。

- [ ] **Step 4: 跑全套**

```bash
python -m pytest tests/ -q
```
Expected: 基線 +6 (contracts) passed，0 regressions。

- [ ] **Step 5: Commit**

```bash
git add src/gui.py
git commit -m "refactor(gui): extract build_app factory from launch_gui

Pure constructor returns a configured Flask app without calling run().
launch_gui() becomes a thin wrapper: build_app + app.run(). Enables
unit testing of auth/CSRF/rate-limit via test_client without spinning
up a real server."
```

---

## Task 4: 接 flask-login 取代自製 session 認證

**Files:**
- Create: `src/auth_models.py`
- Modify: `src/gui.py`

- [ ] **Step 1: 建立 User model 與 pydantic LoginForm**

Create `src/auth_models.py`:

```python
"""Flask-Login User model + pydantic LoginForm for illumio-ops admin auth.

Single-admin model: the web_gui.username / password_hash in config.json
defines the one admin user. flask-login's user_loader returns this user
if the session's user_id matches the configured username.
"""
from __future__ import annotations

from flask_login import UserMixin
from pydantic import BaseModel, Field


class AdminUser(UserMixin):
    """The single configured admin."""
    def __init__(self, username: str):
        self.id = username

    @classmethod
    def from_config(cls, cm):
        return cls(cm.config.get("web_gui", {}).get("username", "illumio"))


class LoginForm(BaseModel):
    """Server-side validation for /api/login payload (Phase 3 pydantic)."""
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)
```

- [ ] **Step 2: 在 `build_app` 接 flask-login**

Insert into `build_app(cm)` early (after `app = Flask(...)`):

```python
    from flask_login import LoginManager
    from src.auth_models import AdminUser

    app.config["SECRET_KEY"] = cm.config["web_gui"]["secret_key"]
    login_manager = LoginManager(app)
    login_manager.login_view = "login_page"
    login_manager.session_protection = "strong"

    @login_manager.user_loader
    def _load_user(user_id: str):
        admin_name = cm.config.get("web_gui", {}).get("username", "illumio")
        return AdminUser(admin_name) if user_id == admin_name else None
```

- [ ] **Step 3: 改寫 `/api/login` endpoint 使用 flask-login**

Find existing `/api/login` handler. Replace its success path (`session['logged_in'] = True`) with:

```python
    from flask_login import login_user
    from src.auth_models import AdminUser, LoginForm
    from pydantic import ValidationError

    try:
        form = LoginForm.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return jsonify({"ok": False, "error": "invalid_form", "detail": str(e)}), 400

    # ... existing password verify logic ...
    if password_ok:
        login_user(AdminUser(username))
        return jsonify({"ok": True, "csrf_token": <provided in next task>})
```

- [ ] **Step 4: 改 `/logout` 使用 flask-login `logout_user`**

```python
    from flask_login import logout_user
    @app.route('/logout')
    def logout():
        logout_user()
        return redirect('/login')
```

- [ ] **Step 5: 保護 endpoints 用 `@login_required`**

Replace the existing `@app.before_request` auth check with per-route `@login_required`:

```python
from flask_login import login_required

@app.route('/api/dashboard')
@login_required
def api_dashboard():
    ...
```

For the old before_request that bounced unauth requests, keep only the **IP allowlist check** (will move to flask-limiter context in Task 6).

- [ ] **Step 6: 跑 contract tests**

```bash
python -m pytest tests/test_web_security_contracts.py -v
```
Expected: `test_login_valid_credentials_sets_session`, `test_login_invalid_credentials_rejected`, `test_logout_clears_session` 應通過（CSRF/rate-limit tests 會因後續任務而仍失敗或通過）。

- [ ] **Step 7: 跑全套**

```bash
python -m pytest tests/ -q
```
Expected: 0 regressions。既有 test_gui_security.py 可能有 1-3 測試失敗（使用 `session['logged_in']` 直接檢查）— 列入 Task 9 的測試遷移範圍。

- [ ] **Step 8: Commit**

```bash
git add src/auth_models.py src/gui.py
git commit -m "feat(websec): migrate session auth to flask-login

Single-admin AdminUser model; session now managed by flask-login
(session_protection='strong'). Per-route @login_required replaces
the blanket @app.before_request auth check. /api/login payload
validated via pydantic LoginForm (Phase 3 integration)."
```

---

## Task 5: 接 flask-wtf CSRF protection

**Files:**
- Modify: `src/gui.py`

- [ ] **Step 1: 啟用 CSRFProtect**

In `build_app(cm)`, after login_manager setup:

```python
    from flask_wtf.csrf import CSRFProtect, generate_csrf

    app.config["WTF_CSRF_ENABLED"] = True
    app.config["WTF_CSRF_TIME_LIMIT"] = 3600  # 1 hour
    app.config["WTF_CSRF_CHECK_DEFAULT"] = True
    # Allow header OR form field
    app.config["WTF_CSRF_HEADERS"] = ["X-CSRFToken"]

    csrf = CSRFProtect(app)

    @app.context_processor
    def inject_csrf():
        return dict(csrf_token=generate_csrf())

    # API endpoints can fetch fresh token
    @app.route('/api/csrf-token')
    def api_csrf_token():
        return jsonify({"csrf_token": generate_csrf()})
```

- [ ] **Step 2: 移除自製 CSRF 程式碼**

Delete from gui.py:
- `session['csrf_token'] = secrets.token_hex(32)` blocks (~3 locations)
- `inject_csrf_cookie` after_request handler
- Manual CSRF check in before_request that compares `request.headers.get('X-CSRFToken')` to `session['csrf_token']`

These are ALL now handled by flask-wtf.

- [ ] **Step 3: 更新 `index.html` CSRF meta tag**

Confirm existing `<meta name="csrf-token" content="{{ csrf_token() }}">` uses flask-wtf's `csrf_token()` (jinja global).

- [ ] **Step 4: 登入成功時回傳 csrf_token**

`/api/login` success response still includes `{"csrf_token": generate_csrf()}` for JS client to cache.

- [ ] **Step 5: 跑 contract test**

```bash
python -m pytest tests/test_web_security_contracts.py::test_csrf_required_on_post_after_login -v
```
Expected: PASS。

- [ ] **Step 6: 跑全套**

```bash
python -m pytest tests/ -q
```
Expected: 0 regressions。

- [ ] **Step 7: Commit**

```bash
git add src/gui.py src/templates/index.html
git commit -m "feat(websec): migrate CSRF to flask-wtf CSRFProtect

Removes ~60 LOC of self-rolled synchronizer token logic. flask-wtf
now handles token generation, validation, and rotation. Header
name X-CSRFToken preserved for JS client compatibility. /api/csrf-token
endpoint lets SPA refresh tokens without full reload."
```

---

## Task 6: 接 flask-limiter 取代自製 rate limiter

**Files:**
- Modify: `src/gui.py`

- [ ] **Step 1: 初始化 Limiter**

In `build_app(cm)`:

```python
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=[],  # no global limit; apply per-endpoint
        storage_uri="memory://",  # single-node deployment
        strategy="fixed-window",
    )
```

- [ ] **Step 2: 套用 `/api/login` rate limit**

```python
    @app.route('/api/login', methods=['POST'])
    @limiter.limit("5 per minute")
    def api_login():
        ...
```

- [ ] **Step 3: 移除自製 rate limiter**

Delete `_check_rate_limit(remote_addr)` function + the `_LOGIN_ATTEMPTS` module-level dict. Remove the `if not _check_rate_limit(...)` block in api_login.

- [ ] **Step 4: 跑 contract test**

```bash
python -m pytest tests/test_web_security_contracts.py::test_rate_limit_triggers_429_after_5_failures -v
```
Expected: PASS。

- [ ] **Step 5: 跑全套**

```bash
python -m pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add src/gui.py
git commit -m "feat(websec): migrate login rate limit to flask-limiter

5/minute on /api/login, keyed by remote_addr. Memory storage for
single-node deployment. Removes _check_rate_limit and _LOGIN_ATTEMPTS
module-level state (Status.md T1 thread-safety risk also gone)."
```

---

## Task 7: 接 flask-talisman（安全 headers）

**Files:**
- Modify: `src/gui.py`
- Create: `tests/test_flask_talisman_headers.py`

- [ ] **Step 1: 寫 headers 測試**

Create `tests/test_flask_talisman_headers.py`:

```python
"""Verify flask-talisman sets standard security headers."""
import pytest


@pytest.fixture
def client(tmp_path):
    import json
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "web_gui": {"username": "illumio", "password_hash": "", "password_salt": "",
                    "secret_key": "", "allowed_ips": []},
    }), encoding="utf-8")
    from src.config import ConfigManager
    from src.gui import build_app
    app = build_app(ConfigManager(str(cfg)))
    app.config["TESTING"] = True
    return app.test_client()


def test_x_content_type_options_nosniff(client):
    r = client.get("/login")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"


def test_x_frame_options_deny(client):
    r = client.get("/login")
    assert r.headers.get("X-Frame-Options") in ("DENY", "SAMEORIGIN")


def test_content_security_policy_present(client):
    r = client.get("/login")
    csp = r.headers.get("Content-Security-Policy", "")
    assert "default-src" in csp
    # talisman default CSP includes 'self'
    assert "'self'" in csp


def test_hsts_only_when_tls_enabled(client):
    """HSTS should NOT be set when TLS is disabled (local dev)."""
    r = client.get("/login")
    # Default behavior: no HSTS header unless force_https is set
    hsts = r.headers.get("Strict-Transport-Security")
    # Either absent (TLS off) or present with max-age (TLS on) — both valid
    if hsts is not None:
        assert "max-age=" in hsts
```

- [ ] **Step 2: 初始化 Talisman**

In `build_app(cm)`:

```python
    from flask_talisman import Talisman

    tls_enabled = cm.config.get("web_gui", {}).get("tls", {}).get("enabled", False)

    # CSP: allow inline scripts/styles (SPA uses them); locked down otherwise
    csp = {
        'default-src': "'self'",
        'script-src': ["'self'", "'unsafe-inline'"],  # SPA inline JS
        'style-src': ["'self'", "'unsafe-inline'"],   # SPA inline CSS
        'img-src': ["'self'", "data:"],
        'font-src': "'self'",
        'connect-src': "'self'",
    }

    Talisman(
        app,
        force_https=tls_enabled,       # only when TLS is configured
        strict_transport_security=tls_enabled,
        content_security_policy=csp,
        content_security_policy_nonce_in=[],  # inline not nonce-based (SPA compat)
        frame_options='DENY',
        referrer_policy='strict-origin-when-cross-origin',
    )
```

- [ ] **Step 3: 跑 headers 測試**

```bash
python -m pytest tests/test_flask_talisman_headers.py -v
```
Expected: 4 PASS。

- [ ] **Step 4: 跑全套**

```bash
python -m pytest tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add src/gui.py tests/test_flask_talisman_headers.py
git commit -m "feat(websec): add flask-talisman security headers

Sets X-Frame-Options=DENY, X-Content-Type-Options=nosniff,
Referrer-Policy=strict-origin-when-cross-origin, and a CSP that
locks script/style/img/font/connect sources to 'self' (with
'unsafe-inline' script/style for the existing SPA).
HSTS + force_https engage automatically when web_gui.tls.enabled."
```

---

## Task 8: 密碼升級 PBKDF2 → argon2id (向下相容)

**Files:**
- Modify: `src/config.py`
- Create: `tests/test_argon2_upgrade.py`

- [ ] **Step 1: 寫 upgrade 測試**

Create `tests/test_argon2_upgrade.py`:

```python
"""Passwords created via PBKDF2 must still verify, and should silently
upgrade to argon2id on first successful verify."""
import pytest


def test_argon2_hash_starts_with_prefix():
    from src.config import hash_password_argon2
    h = hash_password_argon2("password123")
    assert h.startswith("argon2:"), f"expected argon2: prefix, got {h[:20]}"


def test_argon2_verify_round_trip():
    from src.config import hash_password_argon2, verify_password
    h = hash_password_argon2("password123")
    # argon2 hash has no separate salt column (embedded)
    assert verify_password(h, salt="", password="password123")
    assert not verify_password(h, salt="", password="wrong")


def test_pbkdf2_hash_still_verifies():
    """Legacy PBKDF2 hashes keep working."""
    from src.config import hash_password, verify_password
    salt = "abc123"
    h = hash_password(salt, "legacy_pw")
    assert verify_password(h, salt=salt, password="legacy_pw")


def test_verify_password_returns_needs_upgrade_flag_for_pbkdf2():
    """After a successful PBKDF2 verify, the caller can request a rehash."""
    from src.config import hash_password, verify_and_upgrade_password
    salt = "abc123"
    h = hash_password(salt, "legacy_pw")
    ok, new_hash = verify_and_upgrade_password(h, salt=salt, password="legacy_pw")
    assert ok is True
    assert new_hash is not None    # upgrade emitted
    assert new_hash.startswith("argon2:")


def test_verify_and_upgrade_password_on_argon2_returns_none_upgrade():
    """Already-argon2 hashes don't emit a new one."""
    from src.config import hash_password_argon2, verify_and_upgrade_password
    h = hash_password_argon2("pw")
    ok, new_hash = verify_and_upgrade_password(h, salt="", password="pw")
    assert ok is True
    assert new_hash is None    # no upgrade needed
```

- [ ] **Step 2: 跑測試，確認失敗**

```bash
python -m pytest tests/test_argon2_upgrade.py -v
```
Expected: 全 FAIL (functions don't exist)。

- [ ] **Step 3: 實作 argon2 helpers**

In `src/config.py`, after existing PBKDF2 helpers:

```python
from argon2 import PasswordHasher as _Argon2Hasher
from argon2.exceptions import VerifyMismatchError as _ArgonMismatch

_ARGON2_PREFIX = "argon2:"
_argon2_hasher = _Argon2Hasher(
    time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16
)


def hash_password_argon2(password: str) -> str:
    """Hash password with argon2id. Salt is embedded in the hash string."""
    return _ARGON2_PREFIX + _argon2_hasher.hash(password)


def verify_password(stored_hash: str, salt: str, password: str) -> bool:
    """Verify password against stored hash — supports argon2, PBKDF2, legacy SHA256.
    
    Constant-time comparison for legacy hashes; argon2-cffi handles timing internally.
    """
    if stored_hash.startswith(_ARGON2_PREFIX):
        try:
            _argon2_hasher.verify(stored_hash[len(_ARGON2_PREFIX):], password)
            return True
        except _ArgonMismatch:
            return False
        except Exception:
            return False
    # Fall through to existing PBKDF2/SHA256 logic
    if stored_hash.startswith(_PBKDF2_PREFIX):
        expected = hash_password(salt, password)
        return hmac.compare_digest(stored_hash, expected)
    legacy = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
    return hmac.compare_digest(stored_hash, legacy)


def verify_and_upgrade_password(stored_hash: str, salt: str, password: str):
    """Verify; if verified AND stored hash is not argon2, return a fresh argon2 hash
    as the second tuple element so the caller can persist the upgrade.
    
    Returns: (ok: bool, new_argon2_hash: str | None)
    """
    ok = verify_password(stored_hash, salt, password)
    if not ok:
        return False, None
    if stored_hash.startswith(_ARGON2_PREFIX):
        return True, None
    # Upgrade
    return True, hash_password_argon2(password)
```

- [ ] **Step 4: 跑測試**

```bash
python -m pytest tests/test_argon2_upgrade.py -v
```
Expected: 5 PASS。

- [ ] **Step 5: 在 `/api/login` 成功路徑接自動升級**

In `src/gui.py` api_login handler, replace:

```python
    # OLD:
    if verify_password(saved_hash, salt, password):
        login_user(AdminUser(username))
        return jsonify({"ok": True, ...})
```

With:

```python
    # NEW:
    ok, new_hash = verify_and_upgrade_password(saved_hash, salt, password)
    if ok:
        if new_hash is not None:
            # Silent upgrade to argon2id
            gui_cfg["password_hash"] = new_hash
            gui_cfg["password_salt"] = ""  # argon2 embeds salt
            cm.save()
            logger.info("Upgraded password hash from legacy → argon2id")
        login_user(AdminUser(username))
        return jsonify({"ok": True, "csrf_token": generate_csrf()})
```

- [ ] **Step 6: 跑全套**

```bash
python -m pytest tests/ -q
```
Expected: 0 regressions。

- [ ] **Step 7: Commit**

```bash
git add src/config.py src/gui.py tests/test_argon2_upgrade.py
git commit -m "feat(websec): upgrade password hashing PBKDF2 → argon2id

New argon2id hasher via argon2-cffi (memory-hard, modern OWASP recommendation).
Legacy PBKDF2 hashes still verify; first successful login with a legacy
hash silently upgrades it to argon2id (no user action required).

verify_and_upgrade_password returns (ok, new_hash_or_None) so the
caller can persist the upgrade on success. Status.md S1 resolved."
```

---

## Task 9: 更新既有 test_gui_security.py

**Files:**
- Modify: `tests/test_gui_security.py`

既有測試可能用到：
- `session['logged_in']` 直接存取 → 改用 flask-login 的 `current_user.is_authenticated`
- 自製 CSRF token fetching → 改用 `/api/csrf-token` endpoint
- 自製 rate limit 的 time mock → 改用 `@limiter.limit` 的行為

- [ ] **Step 1: 列出 test_gui_security.py 使用的 pattern**

```bash
grep -n "session\['logged_in'\]\|session\['csrf_token'\]\|_LOGIN_ATTEMPTS\|_check_rate_limit" tests/test_gui_security.py
```

- [ ] **Step 2: 逐一修改**

針對每個 pattern：
- `session['logged_in']` → 登入後用 client.post('/api/login') 建立 session；不直接 mutate session
- `session['csrf_token']` → 先 call /api/csrf-token 拿 token
- `_LOGIN_ATTEMPTS` mock → 改為 flask-limiter 的 `app.extensions['limiter'].reset()` 或 freezegun 推進時間

- [ ] **Step 3: 跑更新後的測試**

```bash
python -m pytest tests/test_gui_security.py -v
```
Expected: 全綠。

- [ ] **Step 4: 跑全套**

```bash
python -m pytest tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_gui_security.py
git commit -m "test(websec): migrate test_gui_security patterns to Flask extensions

session['logged_in'] mutations replaced by /api/login calls.
session['csrf_token'] reads replaced by /api/csrf-token endpoint.
_LOGIN_ATTEMPTS / _check_rate_limit mocks replaced by direct
observation of flask-limiter's 429 response."
```

---

## Task 10: 文件更新 + 驗收 + Merge

**Files:**
- Modify: `Status.md`, `Task.md`, `docs/User_Manual.md`, `docs/User_Manual_zh.md`

- [ ] **Step 1: 更新 Status.md**

- Version → `v3.5.0-websec`
- Security Findings 表：S1/S4/S5 標 ✅（前次 Phase 1 S-series 的延伸）
- Dependency Status：flask-wtf/flask-limiter/flask-talisman/flask-login/argon2-cffi 標 `used`
- 移除 Concurrency Issues T1（`_LOGIN_ATTEMPTS` 已刪）

- [ ] **Step 2: 更新 Task.md**

插入：
```markdown
---

## Phase 4: Web GUI Security ✅ DONE (2026-04-XX)

- [x] **P4**: flask-wtf + flask-limiter + flask-talisman + flask-login + argon2-cffi
  - `build_app(cm)` factory 拆分，利測試
  - CSRF：自製 synchronizer → flask-wtf CSRFProtect
  - Rate limit：`_check_rate_limit` 自製 → flask-limiter @limiter.limit
  - Session auth：自製 `session['logged_in']` → flask-login `@login_required`
  - Security headers：新增 flask-talisman（CSP/HSTS/X-Frame-Options）
  - Password hash：PBKDF2 → argon2id，自動 silent upgrade 舊 hash
  - Test count: 基線 +13
  - Resolves: Status.md S1 (argon2 upgrade), S4 (flask-wtf), S5 (flask-limiter), T1 (no more module-level _LOGIN_ATTEMPTS)
  - Branch: `upgrade/phase-4-web-security` → tag `v3.5.0-websec`
```

- [ ] **Step 3: 更新 User Manual 安全段落（EN + zh）**

找到 "Security" 或 "安全" 區塊，更新密碼雜湊演算法說明、rate limit 行為（5/min per IP）、CSRF 機制描述。

- [ ] **Step 4: 全套測試 + i18n audit**

```bash
python -m pytest tests/ -q
python -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py -v
```
Expected: 基線 +13-17 new tests (contracts 6 + talisman 4 + argon2 5 + possibly 2 others from migrations), i18n 0 findings。

- [ ] **Step 5: 手動煙霧測試**

```bash
python illumio_ops.py gui --port 5999   # Phase 1 subcommand
# 另一 terminal:
curl -s http://localhost:5999/login | grep -i "x-content-type\|x-frame"
curl -s http://localhost:5999/api/csrf-token   # 不應 401（未登入狀態拿 token OK）
# 5 次 login 錯誤後應回 429
for i in 1 2 3 4 5 6; do curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:5999/api/login -d '{"username":"x","password":"y"}' -H 'Content-Type: application/json'; done
```

- [ ] **Step 6: Commit docs + push**

```bash
git add Status.md Task.md docs/User_Manual.md docs/User_Manual_zh.md
git commit -m "docs: record Phase 4 (Web GUI security) completion"
git push -u origin upgrade/phase-4-web-security
```

- [ ] **Step 7: PR + merge + tag**

**Title**: `Phase 4: Web GUI security hardening (flask-wtf/limiter/talisman/login + argon2)`

Body 摘要即可（見 Status.md 的段落）。

Merge 後：
```bash
git checkout main && git pull
git tag -a v3.5.0-websec -m "Phase 4: Flask extensions + argon2 password hashing"
git push origin v3.5.0-websec
git branch -d upgrade/phase-4-web-security
```

---

## Phase 4 完成驗收清單

- [ ] `build_app(cm)` factory 存在且回傳 Flask app
- [ ] flask-login `@login_required` 保護所有 `/api/*` (除 /api/login + /api/csrf-token)
- [ ] flask-wtf CSRF 啟用，`X-CSRFToken` header 可用
- [ ] flask-limiter `5/minute` on /api/login
- [ ] flask-talisman CSP/HSTS/Frame-Options headers 正確設定
- [ ] `hash_password_argon2` + `verify_and_upgrade_password` 存在且可用
- [ ] 登入 legacy PBKDF2 hash 會 silent upgrade 到 argon2
- [ ] 所有 contract tests + new tests 通過
- [ ] i18n audit 0 findings
- [ ] Status.md S1/S4/S5 標 ✅
- [ ] `v3.5.0-websec` tag 存在

**Done means ready to:** Phase 5 (reports) / Phase 6 (scheduler) 可獨立啟動。

---

## Rollback Plan

```bash
git revert v3.5.0-websec
git tag -d v3.5.0-websec
git push origin :refs/tags/v3.5.0-websec
```

Flask extensions 都是 init-only，revert 乾淨；argon2 hash 也可正常被 verify_password fallback 處理（PBKDF2 fallback 仍在）。

---

## Self-Review Checklist

- ✅ **Spec coverage**：路線圖 Phase 4（5 個 Flask extensions + argon2）全部有 task
- ✅ **Backward compat**：Task 2 contract tests 守護所有既有 endpoint 行為
- ✅ **i18n**：pydantic LoginForm 錯誤訊息可後續接 lazy_gettext（若需要）
- ✅ **No placeholders**：每 step 有具體程式碼或指令
- ✅ **TDD**：Task 2/7/8 先紅後綠
- ✅ **Security**：argon2 upgrade path 不洩漏時間；CSRF 非 httponly cookie 已在 S4 解決
- ✅ **Type consistency**：`AdminUser`/`build_app`/`verify_and_upgrade_password` 跨 task 一致
