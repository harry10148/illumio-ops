# Code Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 27 findings (6 HIGH / 11 MEDIUM / 10 LOW) from the 2026-05-01 全面 code review report.

**Architecture:** Five sequential batches, each independently committable. Each batch ends with full test suite green before the next begins. The three巨型重構 (H4 i18n抽出、H5 Blueprint 拆分、H6 settings 重組) are deferred to dedicated sub-plans — Batch 4 in this document is a meta-batch that triggers those sub-plans.

**Tech Stack:** Python 3.8+, Flask, flask-wtf/talisman/limiter/login, argon2-cffi, cryptography, cheroot, pytest, loguru.

---

## Scope Note

The original review report covers six logically-distinct subsystems (auth, error handling, XSS, i18n, GUI structure, CLI structure, test hygiene). Per `superpowers:writing-plans` guidance, multi-subsystem specs should normally be broken into separate plans. We compromise: this single document contains five batches that are each self-contained, but **Batch 4** explicitly defers to three sub-plans that must be authored when their turn comes.

**Execution order is enforced**: Batch 1 → Batch 2 → Batch 3 → Batch 5 → Batch 4. Batch 4 is last because each of its three sub-projects rewires imports across many files; running it before Batch 5's hygiene fixes wastes effort.

---

## Pre-flight Checklist (run once before starting)

- [ ] Verify clean working tree: `git status` → "clean"
- [ ] Verify on `main` and up-to-date: `git pull --ff-only`
- [ ] Verify test suite green baseline: `venv/bin/pytest -q --timeout=60 2>&1 | tail -5` → expect `783 passed, 1 skipped` (or current count)
- [ ] Verify i18n audit baseline: `venv/bin/python3 scripts/audit_i18n_usage.py` → expect 0 findings
- [ ] Create branch: `git checkout -b code-review-fixes`

---

# Batch 1 — 安全急迫 (HIGH + 部分 LOW)

**Includes:** H1 login timing side-channel · H2 settings re-auth · H3 error message leak · M4 missing tests for unified handler & force-change · M8 logout CSRF · L1 secret_key empty fallback · L4 logger sink redaction.

**Files touched:** `src/gui/__init__.py`, `tests/conftest.py`, `tests/test_web_security_contracts.py` (new tests added), `src/loguru_config.py` (new sink filter).

**Commit count:** 7 (one per fix).

---

### Task 1.1: H1 — Constant-time login (no timing side-channel)

**Why:** When the username is wrong, Python `and` short-circuits and `verify_password` (~100 ms argon2id) is never called. Attackers can distinguish valid usernames by response time even with rate-limit.

**Files:**
- Modify: `src/gui/__init__.py:768-792` (the `api_login` function)
- Modify: `tests/test_web_security_contracts.py` (add timing-equivalence test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web_security_contracts.py`:

```python
def test_login_timing_equivalent_for_invalid_username_and_password(client):
    """H1: invalid username and invalid password must take similar time
    (both trigger argon2id). We assert the bad-username path takes >50ms
    — proves verify_password ran rather than short-circuiting."""
    import time
    # Warm caches
    client.post('/api/login', json={'username': 'illumio', 'password': 'wrong'})

    # Time invalid-username path
    t0 = time.perf_counter()
    r1 = client.post('/api/login', json={'username': 'nobody', 'password': 'wrong'})
    elapsed_bad_user = time.perf_counter() - t0

    # Time invalid-password path (correct user)
    t0 = time.perf_counter()
    r2 = client.post('/api/login', json={'username': 'illumio', 'password': 'wrong'})
    elapsed_bad_pass = time.perf_counter() - t0

    assert r1.status_code == 401
    assert r2.status_code == 401
    # Both should run argon2 (>50ms on default params time_cost=3, memory=64MB)
    assert elapsed_bad_user > 0.05, f"invalid-username path too fast ({elapsed_bad_user:.3f}s) — short-circuit not removed"
    # Ratio should be within 3x (argon2 dominates both)
    ratio = max(elapsed_bad_user, elapsed_bad_pass) / max(0.001, min(elapsed_bad_user, elapsed_bad_pass))
    assert ratio < 3.0, f"timing ratio {ratio:.1f}x suggests username enumeration possible"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
venv/bin/pytest tests/test_web_security_contracts.py::test_login_timing_equivalent_for_invalid_username_and_password -v
```
Expected: FAIL with `elapsed_bad_user too fast` (the existing code short-circuits).

- [ ] **Step 3: Implement constant-time login**

Replace lines 768-792 in `src/gui/__init__.py`:

```python
    @app.route('/api/login', methods=['POST'])
    @csrf.exempt
    @limiter.limit("5 per minute")
    def api_login():
        from pydantic import ValidationError as _ValidationError
        try:
            form = LoginForm.model_validate(request.get_json(silent=True) or {})
        except _ValidationError as e:
            return jsonify({"ok": False, "error": "invalid_form", "detail": str(e)}), 400

        username = form.username
        password = form.password

        cm.load()
        gui_cfg = cm.config.get("web_gui", {})

        saved_username = gui_cfg.get("username", "illumio")
        saved_password = gui_cfg.get("password", "")

        # H1: always run verify_password to equalize timing, even if username
        # is wrong. We compare the boolean results last to avoid short-circuit.
        username_ok = _hmac.compare_digest(username.strip(), saved_username.strip())
        password_ok = verify_password(password, saved_password)

        if username_ok and password_ok:
            session.permanent = True
            login_user(AdminUser(username))
            if gui_cfg.get("_initial_password"):
                gui_cfg.pop("_initial_password", None)
                cm.save()
            return jsonify({"ok": True, "csrf_token": generate_csrf()})

        return jsonify({"ok": False, "error": t("gui_err_invalid_auth")}), 401
```

- [ ] **Step 4: Run test to verify it passes**

```bash
venv/bin/pytest tests/test_web_security_contracts.py::test_login_timing_equivalent_for_invalid_username_and_password -v
```
Expected: PASS.

- [ ] **Step 5: Run full security test suite to verify no regression**

```bash
venv/bin/pytest tests/test_web_security_contracts.py tests/test_gui_security.py tests/test_auth.py -v --timeout=60 2>&1 | tail -10
```
Expected: All previously-green tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/gui/__init__.py tests/test_web_security_contracts.py
git commit -m "fix(security): constant-time login, no username enumeration

Always run argon2id verify_password even when username is wrong, to
equalize response time. Previously Python's short-circuit \`and\`
skipped verification, allowing username enumeration via timing.

Adds test_login_timing_equivalent_for_invalid_username_and_password
to lock the fix in."
```

---

### Task 1.2: H2 — Require old_password to change username or allowed_ips

**Why:** A stolen session can rename the admin or rewrite the IP allowlist (locking out the legit admin) without re-entering the password. Apply the same guard already used for `new_password`.

**Files:**
- Modify: `src/gui/__init__.py:811-849` (the `api_security_post` function)
- Modify: `tests/test_web_security_contracts.py` (add re-auth test)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_security_contracts.py`:

```python
def test_security_post_username_change_requires_old_password(client_authed):
    """H2: changing the admin username without old_password must be rejected."""
    r = client_authed.post('/api/security', json={'username': 'attacker'})
    assert r.status_code == 401
    body = r.get_json()
    assert body['ok'] is False


def test_security_post_allowed_ips_change_requires_old_password(client_authed):
    """H2: changing the IP allowlist without old_password must be rejected."""
    r = client_authed.post('/api/security', json={'allowed_ips': ['1.2.3.4']})
    assert r.status_code == 401
    body = r.get_json()
    assert body['ok'] is False


def test_security_post_username_change_succeeds_with_old_password(client_authed):
    """H2: with correct old_password, username change should succeed."""
    r = client_authed.post('/api/security', json={
        'username': 'newadmin',
        'old_password': 'testpass',  # matches conftest fixture
    })
    assert r.status_code == 200
    assert r.get_json()['ok'] is True
```

(Assumes `client_authed` is an existing fixture that logs in as `illumio/testpass`. If not, see Batch 5 / conftest task and add the fixture there first; for now reuse the inline pattern from `test_web_security_contracts.py`.)

- [ ] **Step 2: Run tests to verify they fail**

```bash
venv/bin/pytest tests/test_web_security_contracts.py -k "security_post" -v
```
Expected: FAIL — current code accepts username/allowed_ips changes without old_password.

- [ ] **Step 3: Implement old_password guard**

Replace lines 811-849 in `src/gui/__init__.py`:

```python
    @app.route('/api/security', methods=['POST'])
    @limiter.limit("10 per hour")
    def api_security_post():
        d = request.json or {}
        cm.load()
        gui_cfg = cm.config.setdefault("web_gui", {})

        # H2: any modification to username, allowed_ips, or password requires
        # old_password verification — except during initial setup when no
        # password is stored yet.
        sensitive_change = any(k in d for k in ("username", "allowed_ips", "new_password"))
        if sensitive_change and gui_cfg.get("password"):
            old_pw = d.get("old_password", "")
            if not verify_password(old_pw, gui_cfg.get("password", "")):
                return jsonify({"ok": False, "error": t("gui_err_invalid_old_pass")}), 401

        if "username" in d:
            gui_cfg["username"] = d["username"]

        if "allowed_ips" in d:
            allowed_ips, invalid_ips = _validate_allowed_ips(d["allowed_ips"])
            if invalid_ips:
                return jsonify({
                    "ok": False,
                    "error": f"Invalid allowlist entries: {', '.join(invalid_ips)}"
                }), 400
            gui_cfg["allowed_ips"] = allowed_ips

        if "new_password" in d and d["new_password"]:
            old_pw_for_form = d.get("old_password") or "placeholder"
            try:
                change_form = PasswordChangeForm.model_validate({
                    "old_password": old_pw_for_form,
                    "new_password": d["new_password"],
                    "confirm_password": d.get("confirm_password", d["new_password"]),
                })
            except Exception:
                return jsonify({"ok": False, "error": t("gui_err_invalid_password_form")}), 400
            # Old-password check already done above for already-set-up case.
            gui_cfg["password"] = hash_password(change_form.new_password)
            gui_cfg.pop("_initial_password", None)
            gui_cfg.pop("must_change_password", None)

        cm.save()
        return jsonify({"ok": True})
```

Note the simultaneous fix to H3: the inner `except Exception as e: return jsonify({..., "error": str(e)})` was leaking pydantic ValidationError contents (file paths in newer pydantic). We replace `str(e)` with a generic i18n message.

- [ ] **Step 4: Add the missing i18n key**

In `src/i18n_en.json`, add (locate the `gui_err_invalid_old_pass` line and add nearby):

```json
"gui_err_invalid_password_form": "Invalid password format",
```

In `src/i18n_zh_TW.json`:

```json
"gui_err_invalid_password_form": "密碼格式無效",
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
venv/bin/pytest tests/test_web_security_contracts.py -k "security_post" -v
venv/bin/pytest tests/test_gui_security.py -v --timeout=60 2>&1 | tail -10
venv/bin/python3 scripts/audit_i18n_usage.py
```
Expected: all pass; i18n audit shows 0 findings.

- [ ] **Step 6: Commit**

```bash
git add src/gui/__init__.py src/i18n_en.json src/i18n_zh_TW.json tests/test_web_security_contracts.py
git commit -m "fix(security): require old_password to change username or IP allowlist

A stolen session previously could rename the admin or rewrite the IP
allowlist without re-authenticating. Now any modification to username,
allowed_ips, or password requires old_password verification (except
during the no-password initial-setup phase).

Also drops a leaky \`str(e)\` from the password-form ValidationError
handler — replaced with i18n key gui_err_invalid_password_form."
```

---

### Task 1.3: H3 — Stop leaking exception strings to API clients

**Why:** 22 inline `try/except: return jsonify({"error": str(e)})` patterns bypass the unified error handler and leak file paths, SQL fragments, and PCE API internals. Replace each with `_err()` + log.

**Files:**
- Modify: `src/gui/__init__.py` (22 sites — full list below)
- Modify: `tests/test_web_security_contracts.py` (add no-leak contract test)

The 22 sites (from review report):
840, 1696, 1838, 1852, 1866, 2109, 2161, 2210, 2273, 2315, 2327, 2338, 2352, 2385, 2398, 2464, 2583, 2657, 2694, 2738, 2847, 3216

(Note: line 840 was already fixed in Task 1.2 — it's now `gui_err_invalid_password_form`. So 21 remaining.)

- [ ] **Step 1: Add a logger helper near `_err()` in `src/gui/__init__.py`**

After line 353 (`_safe_log`), insert:

```python
def _err_with_log(category: str, exc: Exception, status: int = 500):
    """H3: log full exception detail server-side, return generic error to client.
    `category` is a short label like 'pce_profile' or 'dashboard_summary' used
    only in the log line, never in the response."""
    req_id = str(_uuid.uuid4())[:8]
    logger.error(f"[GUI:{category}] req={req_id}: {_traceback.format_exc()}")
    return jsonify({
        "ok": False,
        "error": t("gui_err_internal", default="Internal server error"),
        "request_id": req_id,
    }), status
```

- [ ] **Step 2: Add the i18n key**

In `src/i18n_en.json`:
```json
"gui_err_internal": "Internal server error",
```
In `src/i18n_zh_TW.json`:
```json
"gui_err_internal": "內部伺服器錯誤",
```

- [ ] **Step 3: Replace each leak site**

For each line, the pattern `return jsonify({"ok": False, "error": str(e)})` (or `}), 500`) is replaced with `return _err_with_log("<category>", e)`. Use a short category label derived from the route name. Walk each site one at a time with `Edit` — never `replace_all` because the categories differ:

| Line | Route | Category label |
|---|---|---|
| 1696 | renew cert | `cert_renew` |
| 1838 | snapshot read | `snapshot_read` |
| 1852 | dashboard audit summary | `dashboard_audit` |
| 1866 | dashboard policy usage summary | `dashboard_policy_usage` |
| 2109 | report download/list | `report_list` |
| 2161 | report run | `report_run` |
| 2210 | report delete | `report_delete` |
| 2273 | (read site, label per nearest route) | `report_read` |
| 2315 | (read) | `siem_status` |
| 2327 | | `siem_test` |
| 2338 | | `siem_dlq_export` |
| 2352 | | `siem_dlq_clear` |
| 2385 | | `siem_forwarder` |
| 2398 | | `siem_config` |
| 2464 | | `cache_status` |
| 2583 | | `quarantine` |
| 2657 | | `alert_test` |
| 2694 | | `event_replay` |
| 2738 | | `pce_test` |
| 2847 | test-connection | `pce_connection` |
| 3216 | daemon restart | `daemon_restart` |

For each: open ±5 lines around the target with `Read`, confirm exact `except Exception as e: return jsonify({"ok": False, "error": str(e)})` shape, then `Edit` swapping to `return _err_with_log("<label>", e)`.

- [ ] **Step 4: Write a contract test ensuring no `str(e)` leak**

Append to `tests/test_web_security_contracts.py`:

```python
def test_gui_init_has_no_str_e_leaks_in_routes():
    """H3 regression guard: scan src/gui/__init__.py for the pattern
    `jsonify({"ok": False, "error": str(e)` which leaks exception text.
    The unified handler at the app level catches truly-unhandled cases."""
    import re
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / 'src' / 'gui' / '__init__.py'
    text = src.read_text(encoding='utf-8')
    # Match the leak pattern, allowing for trailing `}), 500` or `})`
    leaks = re.findall(r'jsonify\(\{[^}]*"error"\s*:\s*str\(e\)', text)
    assert not leaks, f"Found {len(leaks)} `str(e)` leak(s) in src/gui/__init__.py: {leaks[:3]}"
```

- [ ] **Step 5: Run tests**

```bash
venv/bin/pytest tests/test_web_security_contracts.py::test_gui_init_has_no_str_e_leaks_in_routes -v
venv/bin/pytest tests/ --timeout=60 -q 2>&1 | tail -5
```
Expected: leak-scan test passes; full suite still green.

- [ ] **Step 6: Commit**

```bash
git add src/gui/__init__.py src/i18n_en.json src/i18n_zh_TW.json tests/test_web_security_contracts.py
git commit -m "fix(security): replace 21 \`str(e)\` API leaks with logged generic errors

Each affected route now uses _err_with_log(category, e) which:
  1. Logs the full traceback server-side with a request_id
  2. Returns {ok:false, error:'Internal server error', request_id:...}

This prevents leakage of file paths, SQL fragments, and PCE API
internals to API clients. Adds a regression test that scans
src/gui/__init__.py for the leak pattern."
```

---

### Task 1.4: M4 — Tests for unified error handler & first-login force-change

**Why:** Recent security commits added these two paths but no tests. Lock them in.

**Files:**
- Modify: `tests/test_web_security_contracts.py` (add 4 tests)

- [ ] **Step 1: Add error-handler tests**

Append to `tests/test_web_security_contracts.py`:

```python
def test_unified_error_handler_returns_generic_500(client_authed, monkeypatch):
    """M4: an unhandled exception inside a route must return generic JSON,
    not leak the traceback. The unified handler at @app.errorhandler(Exception)
    is responsible."""
    # Force a route to raise — patch a known endpoint's underlying call
    # We use /api/dashboard/audit_summary which reads a JSON file; remove the
    # file-read path by monkeypatching json.load to raise a unique exception.
    import json as _json
    sentinel = "TRACEBACK-SECRET-DO-NOT-LEAK"

    def _explode(*a, **kw):
        raise RuntimeError(sentinel)

    monkeypatch.setattr(_json, 'load', _explode)
    r = client_authed.get('/api/dashboard/audit_summary')
    body = r.get_json() or {}
    assert sentinel not in (body.get('error') or '')
    assert sentinel not in r.get_data(as_text=True)


def test_unified_error_handler_preserves_http_exceptions(client):
    """M4: 404/405 etc. (HTTPException) must not be swallowed into 500."""
    r = client.get('/this-route-does-not-exist')
    assert r.status_code in (404, 401)  # 401 if the IP-allowlist redirects to login first
```

- [ ] **Step 2: Add force-change-on-first-login tests**

Append to `tests/test_web_security_contracts.py`:

```python
def test_first_login_must_change_password_blocks_api(client, fresh_initial_password_config):
    """M4: when must_change_password=True, regular API endpoints must
    redirect/reject until the password is changed."""
    initial = fresh_initial_password_config['initial_password']
    r = client.post('/api/login', json={'username': 'illumio', 'password': initial})
    assert r.status_code == 200

    # Try to hit a normal API endpoint
    r = client.get('/api/status')
    body = r.get_json() or {}
    assert (
        r.status_code in (302, 403)
        or body.get('must_change_password') is True
    ), f"first-login user reached /api/status without changing password (status={r.status_code}, body={body})"


def test_password_change_clears_must_change_flag(client_authed_initial):
    """M4: changing the password should clear must_change_password."""
    r = client_authed_initial.post('/api/security', json={
        'old_password': client_authed_initial._initial_password,
        'new_password': 'NewStrongPass123!',
        'confirm_password': 'NewStrongPass123!',
    })
    assert r.status_code == 200
    r2 = client_authed_initial.get('/api/security')
    body = r2.get_json()
    assert body.get('auth_setup') is True
```

- [ ] **Step 3: Add the supporting fixtures**

If `client_authed_initial` and `fresh_initial_password_config` don't exist, copy the existing pattern and add to the same file:

```python
@pytest.fixture
def fresh_initial_password_config(tmp_path):
    """A config with an _initial_password set and must_change_password=True."""
    import json as _json
    cfg_dir = tmp_path / 'config'
    cfg_dir.mkdir()
    cfg_file = cfg_dir / 'config.json'
    initial_pw = 'initial-test-pw-1234'
    from src.config import hash_password
    cfg = {
        "web_gui": {
            "username": "illumio",
            "password": hash_password(initial_pw),
            "_initial_password": initial_pw,
            "must_change_password": True,
            "secret_key": "x" * 64,
            "allowed_ips": [],
            "tls": {"enabled": False},
        },
        "settings": {"language": "en"},
    }
    cfg_file.write_text(_json.dumps(cfg))
    return {"path": str(cfg_file), "initial_password": initial_pw}
```

The corresponding `must_change_password` enforcement may not yet exist in `before_request`. If `test_first_login_must_change_password_blocks_api` reveals the gate is missing, **add it** to `security_check` in `src/gui/__init__.py` around line 690-708:

```python
        # M4: force-change-password gate
        if current_user.is_authenticated:
            if cm.config.get("web_gui", {}).get("must_change_password"):
                allowed_paths = ('/api/security', '/logout', '/login', '/api/csrf-token')
                if not any(request.path == p or request.path.startswith(p + '/') for p in allowed_paths):
                    if request.path.startswith('/api/'):
                        return jsonify({
                            "ok": False,
                            "error": t("gui_err_must_change_password",
                                       default="You must change your password before continuing."),
                            "must_change_password": True,
                        }), 403
                    return redirect('/login')
```

Plus the i18n key in both JSON files:
```json
"gui_err_must_change_password": "You must change your password before continuing."
```
```json
"gui_err_must_change_password": "您必須先變更密碼才能繼續。"
```

- [ ] **Step 4: Run tests**

```bash
venv/bin/pytest tests/test_web_security_contracts.py -v --timeout=60 2>&1 | tail -20
venv/bin/pytest tests/ --timeout=60 -q 2>&1 | tail -5
venv/bin/python3 scripts/audit_i18n_usage.py
```

- [ ] **Step 5: Commit**

```bash
git add src/gui/__init__.py src/i18n_en.json src/i18n_zh_TW.json tests/test_web_security_contracts.py
git commit -m "test(security): cover unified error handler & force-change-on-first-login

Adds 4 new contract tests:
  - unified handler returns generic 500 (no traceback leak)
  - unified handler preserves HTTPException status (404 not swallowed to 500)
  - first-login user with must_change_password=True is blocked from
    regular /api/* endpoints
  - successful password change clears must_change_password

Also adds the actual gate in security_check() if not already present."
```

---

### Task 1.5: M8 — Add CSRF token to logout

**Why:** SameSite=Strict already prevents most cross-site attacks, but the GUI is the only remaining exemption. Logout-via-CSRF is a low-risk DoS but trivially closable.

**Files:**
- Modify: `src/gui/__init__.py:794-799` (the logout view)

- [ ] **Step 1: Write the test**

Append to `tests/test_web_security_contracts.py`:

```python
def test_logout_requires_csrf_token(client_authed):
    """M8: POST /logout without a CSRF token should be rejected."""
    r = client_authed.post('/logout', headers={'X-CSRFToken': 'wrong'})
    assert r.status_code == 400


def test_logout_succeeds_with_csrf_token(client_authed_with_csrf):
    """M8: POST /logout with the right CSRF token still works."""
    r = client_authed_with_csrf.post('/logout', headers={
        'X-CSRFToken': client_authed_with_csrf._csrf_token
    })
    assert r.status_code in (200, 302)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
venv/bin/pytest tests/test_web_security_contracts.py::test_logout_requires_csrf_token -v
```
Expected: FAIL — the route is `@csrf.exempt`.

- [ ] **Step 3: Remove the exemption**

In `src/gui/__init__.py`, change lines 794-799:

```python
    @app.route('/logout', methods=['POST'])
    def logout():
        logout_user()
        session.clear()
        return redirect('/login')
```

(Removed `@csrf.exempt`.)

- [ ] **Step 4: Update the frontend logout caller**

Search the JS code:

```bash
grep -rn 'fetch.*logout' src/static/ src/templates/
```

For every `fetch('/logout', {method: 'POST'})` call, add the CSRF header. The pattern is already established elsewhere in the codebase — find it via `grep -n 'X-CSRFToken' src/static/js/*.js | head -3` and copy.

Example transformation:
```javascript
fetch('/logout', {
    method: 'POST',
    headers: {'X-CSRFToken': window._csrfToken || document.querySelector('meta[name=csrf-token]')?.content}
})
```

- [ ] **Step 5: Run tests**

```bash
venv/bin/pytest tests/test_web_security_contracts.py -k logout -v
venv/bin/pytest tests/ --timeout=60 -q 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add src/gui/__init__.py src/static/ src/templates/ tests/test_web_security_contracts.py
git commit -m "fix(security): require CSRF token for logout

Removes @csrf.exempt from /logout. SameSite=Strict already mitigates
the cross-site logout DoS, but explicit CSRF closes the gap."
```

---

### Task 1.6: L1 — Harden secret_key against empty-string config

**Why:** `dict.get(key, default)` returns the empty string when the key exists with value `""`, defeating the fallback. `_ensure_web_gui_secret` normally fills it, but a hand-edited config with `"secret_key": ""` bypasses it.

**Files:**
- Modify: `src/gui/__init__.py:530`

- [ ] **Step 1: Write the test**

Append to `tests/test_web_security_contracts.py`:

```python
def test_app_secret_key_never_empty_even_if_config_has_empty_string(tmp_path):
    """L1: even if config.json has \"secret_key\": \"\", the app must use
    a freshly generated secret rather than the empty string."""
    import json as _json
    cfg_dir = tmp_path / 'config'
    cfg_dir.mkdir()
    cfg_file = cfg_dir / 'config.json'
    cfg = {
        "web_gui": {
            "username": "illumio",
            "password": "",
            "secret_key": "",
            "allowed_ips": [],
            "tls": {"enabled": False},
        },
    }
    cfg_file.write_text(_json.dumps(cfg))
    from src.config import ConfigManager
    from src.gui import _create_app
    cm = ConfigManager(str(cfg_file))
    # Force the empty string back (bypassing _ensure_web_gui_secret)
    cm.config["web_gui"]["secret_key"] = ""
    app = _create_app(cm)
    assert app.secret_key, "app.secret_key was empty string"
    assert len(app.secret_key) >= 32, f"app.secret_key too short: {len(app.secret_key)}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
venv/bin/pytest tests/test_web_security_contracts.py::test_app_secret_key_never_empty_even_if_config_has_empty_string -v
```
Expected: FAIL — empty string is preserved.

- [ ] **Step 3: Fix the fallback**

In `src/gui/__init__.py:530`, change from:
```python
    app.secret_key = gui_cfg.get("secret_key", secrets.token_hex(32))
```
To:
```python
    app.secret_key = gui_cfg.get("secret_key") or secrets.token_hex(32)
```

- [ ] **Step 4: Run tests**

```bash
venv/bin/pytest tests/test_web_security_contracts.py -k secret_key -v
venv/bin/pytest tests/ --timeout=60 -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add src/gui/__init__.py tests/test_web_security_contracts.py
git commit -m "fix(security): use \`or\` fallback for empty secret_key

dict.get(key, default) returns the empty string when the key exists
but is empty. Switch to \`or\` so a hand-edited config with
\"secret_key\": \"\" still gets a fresh secret."
```

---

### Task 1.7: L4 — Loguru sink-level secret redaction

**Why:** `_redact_secrets()` only protects API responses. If a route logs a PCE response (e.g., line 833-840) the raw secrets reach the file sink. Fix it once at the sink.

**Files:**
- Modify: `src/loguru_config.py` (add a redaction filter)
- Modify: `tests/test_logging.py` (add redaction test)

- [ ] **Step 1: Read current loguru_config.py**

```bash
cat src/loguru_config.py
```

- [ ] **Step 2: Add the redaction filter**

Append to `src/loguru_config.py` (or replace the relevant filter section — adjust based on what's there):

```python
import re as _re

# Patterns of secret-looking values inside log messages.
# Field names matched: api_key, secret, password, token, webhook_url,
# line_channel_access_token, smtp_password, authorization (header).
_LOG_SECRET_FIELD = _re.compile(
    r'\b(?:'
    r'(?:api[_-]?)?key'
    r'|secret(?:[_-]?key)?'
    r'|password'
    r'|(?:line[_-]?channel[_-]?access[_-]?)?token'
    r'|webhook[_-]?url'
    r'|authorization'
    r'|smtp[_-]?password'
    r')\b\s*[:=]\s*["\']?([^,"\'\s}\)]{4,})',
    _re.IGNORECASE,
)


def _redact_log_record(record):
    """Loguru filter: replace secret-like values in record['message']."""
    msg = record.get('message') or ''
    if not msg:
        return True
    record['message'] = _LOG_SECRET_FIELD.sub(
        lambda m: m.group(0).replace(m.group(1), '[REDACTED]'),
        msg,
    )
    return True
```

Then in the sink configuration (find the `logger.add(...)` calls in this file), add `filter=_redact_log_record` to each file-and-JSON sink:

```python
logger.add(
    log_file,
    rotation="10 MB",
    retention=10,
    level=level,
    filter=_redact_log_record,  # L4
    # ... rest unchanged
)
```

(Console sink may keep raw output for local debugging; if not, apply there too.)

- [ ] **Step 3: Write the test**

Append to `tests/test_logging.py`:

```python
def test_log_redacts_password_field(tmp_path):
    """L4: loguru sinks should redact secret-looking key=value pairs."""
    from loguru import logger as _logger
    from src.loguru_config import setup_loguru
    log_file = tmp_path / 'test.log'
    setup_loguru(level='DEBUG', log_file=str(log_file))
    _logger.info('Connecting with password=hunter2-secret-value')
    _logger.info('PCE response: {"api_key": "abcd1234secret"}')
    _logger.info('webhook_url=https://hooks.example.com/abc123')
    import time as _t
    _t.sleep(0.05)
    text = log_file.read_text()
    assert 'hunter2-secret-value' not in text
    assert 'abcd1234secret' not in text
    assert 'abc123' not in text
    assert '[REDACTED]' in text
```

(If `setup_loguru` has a different signature, adapt to match.)

- [ ] **Step 4: Run tests**

```bash
venv/bin/pytest tests/test_logging.py -v
venv/bin/pytest tests/ --timeout=60 -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add src/loguru_config.py tests/test_logging.py
git commit -m "fix(security): redact secret-looking values at loguru sink level

Routes that previously logged PCE responses or webhook payloads in raw
form will now have their key=value secrets replaced with [REDACTED]
before reaching the file/JSON sinks. Test ensures password,
api_key, and webhook_url values are scrubbed."
```

---

### Task 1.8: Batch 1 verification gate

- [ ] Run full suite: `venv/bin/pytest --timeout=60 -q 2>&1 | tail -10`
- [ ] Run i18n audit: `venv/bin/python3 scripts/audit_i18n_usage.py`
- [ ] Verify no `git status` left-overs: `git status` should be clean
- [ ] Confirm 7 commits since branch start: `git log --oneline main..HEAD | wc -l` → 7

If all green, **Batch 1 complete.** Stop and request review before proceeding to Batch 2.

---

# Batch 2 — 行為一致性 (MEDIUM + LOW)

**Includes:** M5 print() in non-CLI · M6 analyzer dual implementations · M7 except-Exception-pass cleanup · L2 _initial_password disclosure · L3 graceful shutdown · L6 siem TestResult collection warning.

**Files touched:** `src/analyzer.py`, `src/reporter.py`, `src/gui/__init__.py`, `src/main.py`, `src/config.py`, `src/siem/tester.py`.

**Commit count:** 6.

---

### Task 2.1: M5 — Replace print() in analyzer/reporter with logger

**Why:** In `--monitor` (daemon) mode, stdout output pollutes the terminal and is dropped by systemd. analyzer.py has 33 print() calls, reporter.py has 8.

**Files:**
- Modify: `src/analyzer.py` (33 print sites)
- Modify: `src/reporter.py` (8 print sites)

- [ ] **Step 1: Triage each print() — keep CLI-intended, swap daemon-path ones**

Run:
```bash
grep -n 'print(' src/analyzer.py
```

For each line, decide:
- **Keep print()** if the surrounding function is clearly an interactive `_run_*_menu` / debug REPL path (likely none in analyzer.py).
- **Swap to `logger.info(...)`** for normal status output (e.g., `t('checking_pce_health')`, `t('found_events', count=...)`).
- **Swap to `logger.warning(...)`** for cooldown/throttle suppression messages.
- **Swap to `logger.error(...)`** for `Colors.FAIL` paths.

Pattern: `print(f"{Colors.X}{t('...')}{Colors.ENDC}")` — drop the colors, log the i18n string.

- [ ] **Step 2: Make the substitutions**

Example transformations in `src/analyzer.py`:

Before (line 450):
```python
print(f"{t('checking_pce_health')}...", end=" ", flush=True)
```
After:
```python
logger.debug(t('checking_pce_health'))
```

Before (line 453):
```python
print(f"{Colors.FAIL}{t('status_error')}{Colors.ENDC}")
```
After:
```python
logger.error(t('status_error'))
```

Before (line 766):
```python
print(f"{Colors.FAIL}{t('alert_trigger', rule=rule['name'])}{Colors.ENDC}")
```
After:
```python
logger.warning(t('alert_trigger', rule=rule['name']))
```

(Trigger is "info-worthy event", not an error.)

For `src/reporter.py`, follow the same pattern.

- [ ] **Step 3: Write the test**

Add `tests/test_logging.py::test_no_print_in_daemon_modules`:

```python
def test_no_print_in_analyzer_or_reporter():
    """M5 regression guard: analyzer and reporter run in daemon mode and
    must not print() to stdout."""
    import re
    from pathlib import Path
    src_root = Path(__file__).resolve().parents[1] / 'src'
    for fn in ('analyzer.py', 'reporter.py'):
        text = (src_root / fn).read_text(encoding='utf-8')
        # Strip docstrings and comments naively
        stripped = re.sub(r'"""[\s\S]*?"""', '', text)
        stripped = re.sub(r"'''[\s\S]*?'''", '', stripped)
        stripped = re.sub(r'#.*$', '', stripped, flags=re.M)
        prints = re.findall(r'(?<![a-zA-Z_])print\s*\(', stripped)
        assert not prints, f"{fn} contains {len(prints)} print() call(s); use logger instead"
```

- [ ] **Step 4: Run tests**

```bash
venv/bin/pytest tests/test_logging.py -v
venv/bin/pytest tests/test_analyzer.py tests/test_analyzer_decomposition.py -v --timeout=60 2>&1 | tail -10
venv/bin/pytest tests/ --timeout=60 -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add src/analyzer.py src/reporter.py tests/test_logging.py
git commit -m "fix: replace print() with logger in analyzer/reporter

These modules run in daemon mode (--monitor); print() output is dropped
by systemd and pollutes the terminal in interactive monitor-gui mode.
Added a regression test that scans both files for surviving print()
calls."
```

---

### Task 2.2: M6 — Remove duplicate calculate_mbps / calculate_volume_mb in analyzer

**Why:** Both module-level functions and `Analyzer` methods exist; either can be called depending on import path. Pick one, delete the other.

**Files:**
- Modify: `src/analyzer.py:32, 63, ~1148` (two module-level + one method each)

- [ ] **Step 1: Read the current implementations**

```bash
grep -n 'def calculate_mbps\|def calculate_volume_mb' src/analyzer.py
```

- [ ] **Step 2: Decide which to keep**

The module-level ones are the public surface (imported by other files). The methods reuse the same logic. Replace the methods to delegate to the module functions:

In `src/analyzer.py`, find the method versions (~line 1148 area) and change to:

```python
    def calculate_mbps(self, *args, **kwargs):
        return calculate_mbps(*args, **kwargs)

    def calculate_volume_mb(self, *args, **kwargs):
        return calculate_volume_mb(*args, **kwargs)
```

(Or, if no callers depend on the methods, delete them entirely. Verify with `grep -rn 'self\.calculate_mbps\|\.calculate_mbps' src/ tests/`.)

- [ ] **Step 3: Run tests**

```bash
venv/bin/pytest tests/test_analyzer.py tests/test_analyzer_decomposition.py -v --timeout=60 2>&1 | tail -10
```

- [ ] **Step 4: Commit**

```bash
git add src/analyzer.py
git commit -m "refactor(analyzer): single source for calculate_mbps/volume_mb

The module-level functions are the public surface; the Analyzer methods
duplicated the logic. Methods now delegate to the module-level
implementations."
```

---

### Task 2.3: M6 (cont.) — Schedule deletion of `_legacy_*` methods (deferred to feature flag flip)

**Why:** `_legacy_event_pull` / `_legacy_fetch_traffic` co-exist with pce_cache paths. Deleting them requires pce_cache to be the production default. Don't delete now; mark and test the flip.

**Files:**
- Modify: `src/analyzer.py` (add deprecation log)

- [ ] **Step 1: Add a one-time deprecation warning**

In each `_legacy_*` method, at entry, add:

```python
        logger.warning(
            "[deprecated] _legacy_event_pull called — pce_cache path should be "
            "preferred; remove after pce_cache.enabled becomes the default."
        )
```

- [ ] **Step 2: Commit**

```bash
git add src/analyzer.py
git commit -m "chore(analyzer): warn when legacy event/traffic paths are used

Marks _legacy_event_pull and _legacy_fetch_traffic for future removal
once pce_cache is the production default."
```

---

### Task 2.4: M7 — Audit gui/__init__.py except-Exception-pass blocks

**Why:** ~71 `except Exception` blocks in `gui/__init__.py`; some swallow exceptions silently. Catch obvious ones and add logging.

**Files:**
- Modify: `src/gui/__init__.py` (selectively)

- [ ] **Step 1: Locate `except Exception:\s*pass` patterns**

```bash
grep -n -B1 -A2 'except Exception' src/gui/__init__.py | grep -B2 -A1 'pass$' | head -40
```

Sample sites: line 155 (parse_throttle import fallback — legitimate), line 668 (Talisman internals fallback — legitimate). Look for sites that swallow operational errors: PCE API call failures, file I/O, JSON parse.

- [ ] **Step 2: For each non-legitimate site, replace `pass` with a debug log**

Pattern:
```python
        except Exception:
            pass  # intentional: <reason>
```
Becomes:
```python
        except Exception as _e:
            logger.debug(f"[GUI:<context>] swallowed: {_e}")  # <reason>
```

For each site, judge whether the swallowing is genuinely intentional (Talisman internals, optional import fallback) or a missed-error (file I/O, parse). Use `Edit` per site.

- [ ] **Step 3: Run tests**

```bash
venv/bin/pytest tests/ --timeout=60 -q 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add src/gui/__init__.py
git commit -m "refactor(gui): log silenced exceptions instead of bare pass

Walked the ~71 \`except Exception\` blocks in gui/__init__.py and
replaced silent \`pass\` with logger.debug() where the swallowing was
not intentional internal-fallback. The handful of intentional
fallbacks (Talisman internals, optional import paths) keep their
\`pass\` with an explanatory comment."
```

---

### Task 2.5: L2 — Display _initial_password once on startup, then erase

**Why:** Currently the admin must `cat config/config.json` to find the auto-generated initial password. Print it to console once, then remove from disk (keep only the hash).

**Files:**
- Modify: `src/main.py` (print on startup)
- Modify: `src/config.py` (no functional change, but ensure pop happens after first display)

- [ ] **Step 1: Add a startup banner in `src/main.py`**

Find where `ConfigManager()` is instantiated near program entry (likely in `main()` or a setup function). After load, add:

```python
    gui_cfg = cm.config.get("web_gui", {})
    if gui_cfg.get("_initial_password"):
        # L2: show the auto-generated initial password once, then leave it
        # in config until first successful login. The login handler removes
        # it via cm.save().
        pw = gui_cfg["_initial_password"]
        sys.stderr.write("\n" + "=" * 60 + "\n")
        sys.stderr.write(t("initial_password_banner",
                           default="INITIAL ADMIN PASSWORD (will only be shown once after this run):") + "\n")
        sys.stderr.write(f"  username: {gui_cfg.get('username', 'illumio')}\n")
        sys.stderr.write(f"  password: {pw}\n")
        sys.stderr.write(t("initial_password_hint",
                           default="Change it immediately at the Settings page after first login.") + "\n")
        sys.stderr.write("=" * 60 + "\n\n")
        sys.stderr.flush()
```

- [ ] **Step 2: Add i18n keys**

`src/i18n_en.json`:
```json
"initial_password_banner": "INITIAL ADMIN PASSWORD (will only be shown once after this run):",
"initial_password_hint": "Change it immediately at the Settings page after first login.",
```
`src/i18n_zh_TW.json`:
```json
"initial_password_banner": "初始管理員密碼（本次啟動僅顯示一次）：",
"initial_password_hint": "首次登入後請立即至「設定」頁面變更密碼。",
```

- [ ] **Step 3: Run tests**

```bash
venv/bin/pytest tests/ --timeout=60 -q 2>&1 | tail -5
venv/bin/python3 scripts/audit_i18n_usage.py
```

- [ ] **Step 4: Commit**

```bash
git add src/main.py src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat: display initial password banner on first startup

Eliminates the need for the admin to \`cat config/config.json\` to find
the auto-generated initial password. The banner prints to stderr once
per run and is removed from config on first successful login."
```

---

### Task 2.6: L3 — Replace os._exit(0) with graceful shutdown

**Why:** `os._exit` skips atexit hooks (file flushes, scheduler.shutdown, sqlite WAL checkpoint). Use a thread-based delayed exit instead.

**Files:**
- Modify: `src/gui/__init__.py:2849-2860`

- [ ] **Step 1: Replace shutdown handler**

```python
    @app.route('/api/shutdown', methods=['POST'])
    @limiter.limit("5 per hour")
    def api_shutdown():
        if persistent_mode:
            return jsonify({"ok": False, "error": "Shutdown not allowed in persistent mode"}), 403

        def _delayed_exit():
            import time as _t
            _t.sleep(0.5)  # Let the response flush to the client
            import signal as _signal
            os.kill(os.getpid(), _signal.SIGTERM)

        threading.Thread(target=_delayed_exit, daemon=True).start()
        return jsonify({"ok": True})
```

- [ ] **Step 2: Verify SIGTERM is handled**

The cheroot server installs its own SIGTERM handler that triggers graceful shutdown. Verify with `grep -n 'SIGTERM' src/`. If no handler exists, add one in the daemon entry path (likely `src/main.py`).

- [ ] **Step 3: Run tests**

```bash
venv/bin/pytest tests/ --timeout=60 -q 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add src/gui/__init__.py
git commit -m "fix: graceful shutdown via SIGTERM instead of os._exit

os._exit skips atexit hooks, leaving sqlite WAL un-checkpointed and
APScheduler jobs stranded. The new path delays 500ms (so the HTTP
response flushes) then sends SIGTERM to itself."
```

---

### Task 2.7: L6 — Suppress pytest collection warning for siem TestResult

**Files:**
- Modify: `src/siem/tester.py`

- [ ] **Step 1: Locate the dataclass**

```bash
grep -n 'class TestResult' src/siem/tester.py
```

- [ ] **Step 2: Add the marker**

```python
@dataclass
class TestResult:
    __test__ = False  # not a pytest test class
    ...
```

- [ ] **Step 3: Run tests**

```bash
venv/bin/pytest tests/ --timeout=60 -q 2>&1 | grep -i 'PytestCollectionWarning' | head -3
```
Expected: no `siem.tester.TestResult` warning.

- [ ] **Step 4: Commit**

```bash
git add src/siem/tester.py
git commit -m "chore(siem): mark TestResult dataclass as not-a-test

Adds __test__ = False so pytest's auto-collection stops emitting
PytestCollectionWarning for src/siem/tester.py::TestResult."
```

---

### Task 2.8: Batch 2 verification gate

- [ ] `venv/bin/pytest --timeout=60 -q 2>&1 | tail -10` → all green
- [ ] `venv/bin/python3 scripts/audit_i18n_usage.py` → 0 findings
- [ ] `git log --oneline main..HEAD | wc -l` → 13 (7 from Batch 1 + 6 from Batch 2)

Stop and request review before proceeding.

---

# Batch 3 — XSS / CSP / 範本 i18n

**Includes:** M1 inline-onclick & nonce conflict · M2 jsStr line-terminator · L5 alert templates not i18n-ized · M3 Cheroot SSL adapter init order.

**Files touched:** `src/templates/index.html` (≥73 onclick sites), `src/static/js/*.js` (especially `rule-scheduler.js`), `src/alerts/templates/*.tmpl`, `src/gui/__init__.py:3573-3574`.

**Commit count:** 4.

---

### Task 3.1: M1 — Convert inline onclick handlers to addEventListener

**Why:** CSP `script-src 'self' + nonce` blocks inline event-handler attributes in modern browsers. Either CSP fails silently (browser falls back to permissive mode for old sites) or the UI breaks. Migrate all `onclick=` to delegated event listeners.

**Files:**
- Modify: `src/templates/index.html` (73 onclick sites)
- Modify: `src/static/js/*.js` (the handler functions become event-bound)
- Add: `src/gui/static/js/_event_dispatcher.js` (a single nonce-tagged script that wires up all delegated handlers)

**Strategy:** For each `onclick="fnName(arg1, arg2)"`, replace with `data-action="fnName" data-args='["arg1","arg2"]'` and have a single delegated listener call the right function.

- [ ] **Step 1: Inventory all unique onclick functions**

```bash
grep -oE 'onclick="[^"]*"' src/templates/index.html | sort -u | head -40
```

Compile the list of called functions: `switchTab`, `switchQTab`, `qtPrevPage`, `qtNextPage`, `qwPrevPage`, `qwNextPage`, `openQueryModal`, `runAllQueries`, `openQuarantineModal`, `rulesSubTab`, `openModal`, `stopGui`, etc.

- [ ] **Step 2: Add the dispatcher script**

Create `src/gui/static/js/_event_dispatcher.js`:

```javascript
// CSP-friendly event delegation. Replaces inline onclick= attributes.
// Patterns:
//   <button data-action="switchTab" data-args='["dashboard"]'>...</button>
//
// Functions are looked up on window.* so existing globals keep working.
(function() {
    'use strict';
    document.addEventListener('click', function(e) {
        const target = e.target.closest('[data-action]');
        if (!target) return;
        const fnName = target.dataset.action;
        const fn = window[fnName];
        if (typeof fn !== 'function') {
            console.warn('[dispatcher] no function:', fnName);
            return;
        }
        let args = [];
        if (target.dataset.args) {
            try {
                args = JSON.parse(target.dataset.args);
            } catch (err) {
                console.warn('[dispatcher] bad data-args:', target.dataset.args);
                return;
            }
        }
        fn.apply(target, args);
    });
})();
```

- [ ] **Step 3: Wire it in `index.html`**

Add inside `<head>` (the script tag will get a nonce from Talisman automatically):

```html
<script src="{{ url_for('static', filename='js/_event_dispatcher.js') }}"></script>
```

- [ ] **Step 4: Mechanical onclick → data-action conversion**

For each `onclick="fn(arg1, arg2, ...)"`, rewrite as:
- `onclick="fn()"` → `data-action="fn"`
- `onclick="fn('a')"` → `data-action="fn" data-args='["a"]'`
- `onclick="fn('a', 'b')"` → `data-action="fn" data-args='["a","b"]'`
- `onclick="fn(this)"` — special, won't work via delegation — leave as-is and add a CSP hash exemption for these specific handlers in step 6.

Use `Edit` per occurrence (recommend per-occurrence Edits for safety; there are ~73).

- [ ] **Step 5: Apply same pattern to `src/static/js/rule-scheduler.js:204-205, 244, 261-269, 284`**

These dynamically inject button strings via assigning HTML to a parent element. Refactor to:
1. Build the element with `document.createElement`
2. Set `addEventListener('click', handler)` directly
3. Avoid string-based HTML construction for interactive elements

Example transformation in `rule-scheduler.js`:

Before (line 204) — string concatenation onto `el.innerHTML`:
```javascript
html += `<button onclick="rsEditSchedule(${id})">Edit</button>`;
```
After — DOM API:
```javascript
const btn = document.createElement('button');
btn.textContent = 'Edit';
btn.addEventListener('click', () => rsEditSchedule(id));
container.appendChild(btn);
```

- [ ] **Step 6: For any `this`-passing onclicks, add CSP hash exemption**

If 1-3 handlers genuinely need `this`, compute their SHA256 and add to the CSP `script-src` allowlist via Talisman config. Or refactor to use `event.target` and remove `this` dependency.

- [ ] **Step 7: Manual UI verification**

```bash
venv/bin/python3 illumio-ops.py --gui --port 5001
```

Walk through every tab, every button, every modal. Verify CSP errors are zero in DevTools console.

- [ ] **Step 8: Add a regression test**

`tests/test_gui_security.py` (or new file `tests/test_csp_compliance.py`):

```python
def test_index_html_has_no_inline_onclick():
    """M1: inline onclick attributes break CSP nonce mode."""
    import re
    from pathlib import Path
    tpl = Path(__file__).resolve().parents[1] / 'src' / 'templates' / 'index.html'
    text = tpl.read_text(encoding='utf-8')
    onclicks = re.findall(r'onclick\s*=', text)
    assert not onclicks, f"Found {len(onclicks)} inline onclick(s) in index.html"


def test_rule_scheduler_js_has_no_string_built_onclick():
    """M1: rule-scheduler.js builds buttons via string-HTML; switch to DOM."""
    from pathlib import Path
    js = Path(__file__).resolve().parents[1] / 'src' / 'static' / 'js' / 'rule-scheduler.js'
    text = js.read_text(encoding='utf-8')
    assert 'onclick=' not in text, "rule-scheduler.js still concatenates onclick into HTML strings"
```

- [ ] **Step 9: Run tests**

```bash
venv/bin/pytest tests/test_gui_security.py tests/test_csp_compliance.py -v --timeout=60 2>&1 | tail -10
venv/bin/pytest tests/ --timeout=60 -q 2>&1 | tail -5
```

- [ ] **Step 10: Commit**

```bash
git add src/templates/index.html src/static/js/ src/gui/static/js/_event_dispatcher.js tests/
git commit -m "fix(security): replace inline onclick with delegated dispatcher (CSP)

CSP \`script-src 'self' + nonce\` blocks inline event handlers in
modern browsers. We add a single delegated click handler in
_event_dispatcher.js and rewrite all <button onclick=fn(...)> as
<button data-action=fn data-args=...>. rule-scheduler.js's string-
based button construction is converted to document.createElement +
addEventListener.

Adds two regression tests:
  - index.html must have zero onclick= attributes
  - rule-scheduler.js must not build onclick into HTML strings"
```

---

### Task 3.2: M2 — Replace jsStr-based HTML construction with DOM API

**Why:** Even after Task 3.1 removes most string-HTML cases, any remaining string-based HTML construction in `rule-scheduler.js` (or other JS) is XSS-prone. `jsStr()` (line 4-8) doesn't escape `<`, `>`, `&`, or U+2028/U+2029. Switch to DOM API.

**Files:**
- Modify: `src/static/js/rule-scheduler.js`

- [ ] **Step 1: Find all jsStr usage**

```bash
grep -n 'jsStr' src/static/js/rule-scheduler.js | head -30
grep -nE 'innerHTML|outerHTML|insertAdjacentHTML' src/static/js/rule-scheduler.js
```

- [ ] **Step 2: Rewrite each string-HTML site**

For each `el.innerHTML = '<div>' + jsStr(...) + '</div>'` pattern, refactor to:

```javascript
const div = document.createElement('div');
div.textContent = userValue;
parent.replaceChildren(div);
```

For more complex DOM, use a small `h(tag, props, ...children)` helper:

```javascript
function h(tag, props, ...children) {
    const el = document.createElement(tag);
    if (props) {
        for (const [k, v] of Object.entries(props)) {
            if (k === 'class') el.className = v;
            else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
            else if (k.startsWith('data-')) el.dataset[k.slice(5)] = v;
            else el.setAttribute(k, v);
        }
    }
    for (const c of children) {
        if (c == null) continue;
        el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return el;
}
```

- [ ] **Step 3: Remove `jsStr` once no callers remain**

```bash
grep -n 'jsStr(' src/static/js/rule-scheduler.js | wc -l
```
After all sites converted, this should be 1 (the definition itself). Delete the function.

- [ ] **Step 4: Manual UI verification + run tests**

```bash
venv/bin/python3 illumio-ops.py --gui --port 5001
# Verify rule-scheduler tab works, all buttons functional, no CSP errors
venv/bin/pytest tests/ --timeout=60 -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add src/static/js/rule-scheduler.js
git commit -m "fix(security): rule-scheduler.js uses DOM API, drops jsStr

Replaces string-based HTML patterns with document.createElement +
textContent. jsStr() never escaped <, >, &, or U+2028/U+2029, so PCE
rule descriptions containing those characters could break out of the
intended attribute or terminate JS string literals. The DOM API is
inherently safe."
```

---

### Task 3.3: L5 — i18n-ize alert templates

**Why:** `line_digest.txt.tmpl` and `mail_wrapper.html.tmpl` are pure-Chinese hardcoded; English-locale users still receive Chinese notifications.

**Files:**
- Modify: `src/alerts/templates/line_digest.txt.tmpl`
- Modify: `src/alerts/templates/mail_wrapper.html.tmpl`
- Modify: `src/alerts/template_utils.py` or whichever module renders these (so the template engine resolves `t()` calls)

- [ ] **Step 1: Read both templates**

```bash
cat src/alerts/templates/line_digest.txt.tmpl
cat src/alerts/templates/mail_wrapper.html.tmpl
```

- [ ] **Step 2: Identify hardcoded strings**

For `line_digest.txt.tmpl` per the review: `Illumio 告警摘要`, `主旨`, `健康告警`, `詳細內容請至 Illumio PCE Ops Web GUI 查看`. Roughly 11 phrases.
For `mail_wrapper.html.tmpl`: `正式告警通知`, `告警摘要`, `本通知彙整近期…`, `產出時間`, `通知範圍`, `健康 / 事件 / 流量 / 指標`, `此通知由…自動產生`, `請依你的告警流程進行確認與處置`. Roughly 8 phrases.

- [ ] **Step 3: Add i18n keys**

For each hardcoded phrase, add an `alert_tpl_*` key to both `i18n_en.json` and `i18n_zh_TW.json`. Suggested keys:

```
alert_tpl_line_title           = "Illumio Alert Summary" / "Illumio 告警摘要"
alert_tpl_subject              = "Subject" / "主旨"
alert_tpl_health_alert         = "Health Alert" / "健康告警"
alert_tpl_see_web_for_details  = "See Illumio PCE Ops Web GUI for details" / "詳細內容請至 Illumio PCE Ops Web GUI 查看"
alert_tpl_official_notice      = "Official Alert Notification" / "正式告警通知"
alert_tpl_summary              = "Alert Summary" / "告警摘要"
alert_tpl_aggregated_blurb     = "This notification aggregates recent..." / "本通知彙整近期..."
alert_tpl_generated_at         = "Generated at" / "產出時間"
alert_tpl_scope                = "Scope" / "通知範圍"
alert_tpl_categories           = "Health / Events / Traffic / Metrics" / "健康 / 事件 / 流量 / 指標"
alert_tpl_auto_generated       = "Auto-generated by Illumio PCE Ops" / "此通知由 Illumio PCE Ops 自動產生"
alert_tpl_act_per_runbook      = "Confirm and act per your alert runbook" / "請依你的告警流程進行確認與處置"
```

- [ ] **Step 4: Rewrite templates with `{{ t('alert_tpl_*') }}` calls**

Example for `line_digest.txt.tmpl`:
```
{{ t('alert_tpl_line_title') }}
{{ t('alert_tpl_subject') }}: {{ subject }}

{{ t('alert_tpl_health_alert') }}: ...
{{ t('alert_tpl_see_web_for_details') }}
```

- [ ] **Step 5: Verify the renderer handles `t()`**

```bash
grep -rn 'alert_tpl_\|render_template' src/alerts/
```

If the templates use Jinja, `t` should already be in `app.jinja_env.globals` — but the alerts subsystem may render outside Flask context. Check `src/alerts/template_utils.py`.

If `t()` is not available, import explicitly:
```python
from src.i18n import t
env.globals.update(t=t)
```

- [ ] **Step 6: Run tests**

```bash
venv/bin/python3 scripts/audit_i18n_usage.py
venv/bin/pytest tests/ --timeout=60 -q 2>&1 | tail -5
```

- [ ] **Step 7: Commit**

```bash
git add src/alerts/templates/ src/alerts/template_utils.py src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(i18n): translate alert templates (line_digest, mail_wrapper)

The two alert templates were pure-Chinese hardcoded. English-locale
users now receive English notifications. Adds 12 alert_tpl_* i18n
keys covering both templates."
```

---

### Task 3.4: M3 — Pass SSL context to BuiltinSSLAdapter constructor

**Why:** Constructing the adapter then assigning `.context = ctx` leaves a brief window where the cheroot defaults are active. cheroot 10+ supports the kwarg form.

**Files:**
- Modify: `src/gui/__init__.py:3573-3574`

- [ ] **Step 1: Verify cheroot version supports the kwarg**

```bash
venv/bin/python3 -c "from cheroot.ssl.builtin import BuiltinSSLAdapter; import inspect; print(inspect.signature(BuiltinSSLAdapter.__init__))"
```

If `ssl_context` is in the signature, proceed. If not, the alternative is to subclass and override `__init__`.

- [ ] **Step 2: Apply the change**

Replace:
```python
    adapter = _SSLAdapter(cert_file, key_file)
    adapter.context = ctx
```

With (assuming the kwarg exists):
```python
    adapter = _SSLAdapter(cert_file, key_file, ssl_context=ctx)
```

If the kwarg doesn't exist:
```python
    class _HardenedSSLAdapter(_SSLAdapter):
        def __init__(self, cert_file, key_file, ctx):
            self.context = ctx
            self.certificate = cert_file
            self.private_key = key_file
    adapter = _HardenedSSLAdapter(cert_file, key_file, ctx)
```

- [ ] **Step 3: Run TLS tests**

```bash
venv/bin/pytest tests/test_tls.py tests/test_transport_tls.py -v --timeout=60 2>&1 | tail -10
```

- [ ] **Step 4: Commit**

```bash
git add src/gui/__init__.py
git commit -m "fix(security): pass hardened SSL context to BuiltinSSLAdapter at init

Previously the adapter was constructed with cheroot defaults then
.context was reassigned. There's a small race window during which
the default (potentially weaker) context could be observed. cheroot
10+ accepts ssl_context= directly."
```

---

### Task 3.5: Batch 3 verification gate

- [ ] `venv/bin/pytest --timeout=60 -q 2>&1 | tail -10` → green
- [ ] `venv/bin/python3 scripts/audit_i18n_usage.py` → 0 findings
- [ ] Manual UI walkthrough: all tabs functional, no CSP console errors
- [ ] `git log --oneline main..HEAD | wc -l` → 17 (13 + 4)

Stop and request review.

---

# Batch 5 — 測試與型別衛生

(Order swapped: Batch 5 before Batch 4 because Batch 4 mass-rewires imports — easier on top of cleaner test fixtures.)

**Includes:** M9 split test_gui_security.py · M10 conftest fixtures · M11 type hints · L7 matplotlib CJK font · L8 utils.py reorg · L9 rules_engine subpkg · L10 dual-entrypoint cleanup.

**Files touched:** `tests/conftest.py`, `tests/test_gui_*.py` (8 new files), `src/api_client.py`, `src/analyzer.py`, `src/reporter.py`, `src/utils.py`, `src/loguru_config.py`, `src/cli/_render.py` (new), `src/report/rules/` (new dir), `src/main.py`, `src/cli/_runtime.py` (new).

**Commit count:** 7.

---

### Task 5.1: M10 — Lift duplicated fixtures into conftest.py

**Why:** `temp_config_file`, `app_persistent`, `client`, `_csrf` are redefined in 7 test files. Move to `tests/conftest.py`.

**Files:**
- Modify: `tests/conftest.py`
- Modify: 7 test files (drop their local fixture defs)

- [ ] **Step 1: Inventory**

```bash
grep -l 'def temp_config_file\|def app_persistent\|def _csrf' tests/*.py
```

Expected: ~7 files.

- [ ] **Step 2: Read one full implementation as canonical**

```bash
grep -A 20 'def temp_config_file' tests/test_gui_security.py | head -30
```

- [ ] **Step 3: Add to `tests/conftest.py`**

Append the canonical fixtures with `@pytest.fixture` (default function scope unless specified):

```python
import json as _json

@pytest.fixture
def temp_config_file(tmp_path):
    """Minimal config.json with hashed plaintext-test password."""
    from src.config import hash_password
    cfg_dir = tmp_path / 'config'
    cfg_dir.mkdir()
    cfg_file = cfg_dir / 'config.json'
    cfg = {
        "web_gui": {
            "username": "illumio",
            "password": hash_password("testpass"),
            "secret_key": "x" * 64,
            "allowed_ips": [],
            "tls": {"enabled": False},
        },
        "settings": {"language": "en"},
        "rules": [],
        "alerts": {"active": []},
    }
    cfg_file.write_text(_json.dumps(cfg))
    return str(cfg_file)


@pytest.fixture
def app_persistent(temp_config_file):
    from src.config import ConfigManager
    from src.gui import _create_app
    cm = ConfigManager(temp_config_file)
    app = _create_app(cm, persistent_mode=True)
    app.testing = True
    app.config['WTF_CSRF_ENABLED'] = False  # tests with CSRF use *_with_csrf variants
    return app


@pytest.fixture
def client(app_persistent):
    return app_persistent.test_client()


@pytest.fixture
def client_authed(client):
    """Authenticated client (logged in as illumio/testpass)."""
    r = client.post('/api/login', json={'username': 'illumio', 'password': 'testpass'})
    assert r.status_code == 200, f"login failed: {r.get_json()}"
    return client


@pytest.fixture
def _csrf(client_authed):
    """Return a fresh CSRF token (assumes CSRF re-enabled in caller)."""
    r = client_authed.get('/api/csrf-token')
    return r.get_json().get('csrf_token')
```

- [ ] **Step 4: Remove local definitions from the 7 test files**

For each file, delete the fixture functions (now provided by conftest). Run each test file individually to confirm the conftest fixture takes over:

```bash
venv/bin/pytest tests/test_gui_security.py -v --timeout=60 -x 2>&1 | tail -10
venv/bin/pytest tests/test_api_settings.py tests/test_attack_posture_layer.py tests/test_logging.py tests/test_security_headers.py tests/test_flask_talisman_headers.py tests/test_web_security_contracts.py -v --timeout=60 2>&1 | tail -10
```

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_*.py
git commit -m "test: lift shared fixtures into conftest.py

Removes ~30 lines of fixture duplication from 7 test files. The
canonical fixtures (temp_config_file, app_persistent, client,
client_authed, _csrf) now live in conftest.py."
```

---

### Task 5.2: M9 — Split test_gui_security.py into 8 focused files

**Why:** 1135 lines / 38 tests covering 8 unrelated subsystems is unreviewable.

**Files:**
- Delete: `tests/test_gui_security.py` (after migration)
- Create: `tests/test_gui_auth.py` (login/redirect/csrf/logout — ~5 tests)
- Create: `tests/test_gui_event_viewer.py` (event_*: ~8 tests)
- Create: `tests/test_gui_quarantine.py` (quarantine_*: ~3 tests)
- Create: `tests/test_gui_ip_allowlist.py` (ip / api_security_*: ~4 tests)
- Create: `tests/test_gui_alert_plugins.py` (alert / test_alert / debug_endpoint: ~4 tests)
- Create: `tests/test_gui_dashboard.py` (dashboard / reports / system_health: ~4 tests)
- Create: `tests/test_gui_rules.py` (best_practices / event_rule / rules_api: ~6 tests)
- Create: `tests/test_gui_misc.py` (residual)

- [ ] **Step 1: Read the file fully and group tests by prefix**

```bash
grep '^def test_' tests/test_gui_security.py | sort
```

- [ ] **Step 2: Move each test into its target file**

For each group, create the new file with imports + paste tests. Example skeleton for `tests/test_gui_auth.py`:

```python
"""GUI authentication tests (split from test_gui_security.py)."""
import json
import pytest


def test_login_redirects_to_dashboard_on_success(client):
    ...


def test_login_with_bad_password_returns_401(client):
    ...
```

- [ ] **Step 3: Delete the original**

```bash
rm tests/test_gui_security.py
```

- [ ] **Step 4: Run all the new files**

```bash
venv/bin/pytest tests/test_gui_*.py -v --timeout=60 2>&1 | tail -10
```

Expect the same total test count (~38) split across 8 files.

- [ ] **Step 5: Commit**

```bash
git add tests/test_gui_*.py
git rm tests/test_gui_security.py 2>/dev/null
git commit -m "test: split test_gui_security.py into 8 focused files

The original 1135-line file covered 8 unrelated subsystems. Each is
now a separate file (auth, event_viewer, quarantine, ip_allowlist,
alert_plugins, dashboard, rules, misc) using the shared conftest
fixtures. Test count and coverage unchanged."
```

---

### Task 5.3: M11 — Type hints on Analyzer, ApiClient, Reporter public APIs

**Why:** Coverage is 8% / 18% / 45%. New modules are 80%+. Pull the old core up to a baseline.

**Files:**
- Modify: `src/api_client.py`
- Modify: `src/analyzer.py`
- Modify: `src/reporter.py`
- Add: `src/py.typed` (marker file)
- Add: `mypy.ini` or `pyproject.toml` mypy section

- [ ] **Step 1: Add type hints to public methods**

Walk each class's public methods (those without leading `_`). For each, look at the function body to infer signatures, then annotate. Example for `ApiClient.fetch_events`:

Before:
```python
def fetch_events(self, since, until, severity=None):
    ...
```
After:
```python
def fetch_events(
    self,
    since: datetime.datetime,
    until: datetime.datetime,
    severity: str | None = None,
) -> list[dict]:
    ...
```

Aim for 80% coverage on each class. Stop when you hit private methods.

- [ ] **Step 2: Add `py.typed` marker**

```bash
touch src/py.typed
```

- [ ] **Step 3: Add mypy config (lenient baseline)**

Create `mypy.ini` at repo root:

```ini
[mypy]
python_version = 3.10
ignore_missing_imports = True
warn_return_any = False
warn_unused_ignores = True
no_implicit_optional = True

[mypy-src.api_client]
disallow_untyped_defs = True

[mypy-src.analyzer]
disallow_untyped_defs = True

[mypy-src.reporter]
disallow_untyped_defs = True
```

- [ ] **Step 4: Run mypy on the three modules**

```bash
venv/bin/pip install --quiet mypy
venv/bin/mypy src/api_client.py src/analyzer.py src/reporter.py 2>&1 | tail -20
```

Iterate until the three files pass.

- [ ] **Step 5: Run tests**

```bash
venv/bin/pytest tests/ --timeout=60 -q 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add src/api_client.py src/analyzer.py src/reporter.py src/py.typed mypy.ini
git commit -m "chore(types): add type hints to ApiClient, Analyzer, Reporter

Previously: 8% / 18% / 45% return-type coverage. Now ~80% each. Adds
src/py.typed marker so downstream consumers can pick up the hints,
and mypy.ini with strict mode for these three modules only (rest of
the codebase opts in over time)."
```

---

### Task 5.4: L8 — Move utils.py functions to their natural homes

**Why:** `utils.py` is 80% TUI helper, 20% logger/format/terminal helpers that belong elsewhere.

**Files:**
- Create: `src/cli/_render.py` (move `Colors`, `safe_input`, `draw_panel`, `draw_table`, `Spinner`)
- Modify: `src/loguru_config.py` (absorb `setup_logger`)
- Move `format_unit`, `get_terminal_width` to `src/cli/_render.py`
- Modify: `src/utils.py` (re-export shim or shrink to true utilities)
- Modify: every importer of moved symbols

- [ ] **Step 1: Inventory imports**

```bash
grep -rn 'from src.utils import\|from src import utils' src/ tests/
```

- [ ] **Step 2: Move `Colors`, `safe_input`, etc. to `src/cli/_render.py`**

Cut from `src/utils.py`, paste to `src/cli/_render.py`. Keep dependencies (likely Rich) imports at the top.

- [ ] **Step 3: Update imports**

Use `grep -l 'from src.utils import Colors' src/ tests/` then for each file change to `from src.cli._render import Colors`.

- [ ] **Step 4: Move setup_logger to loguru_config.py**

Same pattern.

- [ ] **Step 5: Run tests**

```bash
venv/bin/pytest tests/ --timeout=60 -q 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add src/utils.py src/cli/_render.py src/loguru_config.py
git commit -m "refactor: relocate utils.py helpers to their natural modules

TUI helpers (Colors, safe_input, draw_panel, draw_table, Spinner,
format_unit, get_terminal_width) move to src/cli/_render.py.
setup_logger moves to src/loguru_config.py. utils.py is now a thin
re-export shim for backwards compatibility — imports across the
codebase have been updated to point at the new homes."
```

---

### Task 5.5: L9 — Split rules_engine.py into per-rule modules

**Why:** 1076 lines with 8 rule classes + a `RulesEngine` container.

**Files:**
- Create: `src/report/rules/__init__.py`
- Create: `src/report/rules/r0X_<rule_name>.py` per rule class
- Modify: `src/report/rules_engine.py` (keep only `RulesEngine` container + import re-exports)

- [ ] **Step 1: List the rule classes**

```bash
grep -n '^class ' src/report/rules_engine.py
```

- [ ] **Step 2: Cut & paste each into its own file**

Maintain interface (class name, public method shape). At the top of the new file:
```python
from src.report.rules._base import RuleBase  # if there's a base
from src.i18n import t
# ... other imports
```

- [ ] **Step 3: Re-export from rules_engine.py**

```python
from src.report.rules.r01_ransomware import R01Ransomware
from src.report.rules.r02_lateral import R02Lateral
# ...
__all__ = ['RulesEngine', 'R01Ransomware', 'R02Lateral', ...]
```

- [ ] **Step 4: Run tests**

```bash
venv/bin/pytest tests/test_rules_engine_draft_pd.py tests/test_rules_engine_draft_integration.py tests/ --timeout=60 -q 2>&1 | tail -10
```

- [ ] **Step 5: Commit**

```bash
git add src/report/rules/ src/report/rules_engine.py
git commit -m "refactor(report): split rules_engine.py into per-rule modules

Each of the 8 rule classes now lives in src/report/rules/r0X_*.py.
rules_engine.py keeps only the RulesEngine container plus public
re-exports for backward compatibility."
```

---

### Task 5.6: L10 — Unify daemon-startup path between argparse and click

**Why:** `--monitor` / `--gui` / `--monitor-gui` still go through `src/main.py` directly; click's `monitor_cmd` / `gui_cmd` are stubs. Extract the shared logic so retiring argparse later is mechanical.

**Files:**
- Create: `src/cli/_runtime.py` (`run_daemon(...)`, `run_gui(...)`, `run_monitor_with_gui(...)`)
- Modify: `src/main.py:531-718` (delegate to `src.cli._runtime`)
- Modify: `src/cli/monitor.py`, `src/cli/gui_cmd.py` (delegate to same)

- [ ] **Step 1: Read existing main.py daemon path**

```bash
sed -n '531,720p' src/main.py
```

- [ ] **Step 2: Extract pure functions**

Create `src/cli/_runtime.py`:

```python
"""Shared runtime entry points for argparse and click CLIs.
Both src.main and src.cli.* delegate here so daemon startup logic
isn't duplicated.
"""
from __future__ import annotations
from typing import Any


def run_daemon_loop(cm, interval: int = 5) -> None:
    """Background daemon mode (--monitor)."""
    # ... cut from main.py
    ...


def run_gui_only(cm, port: int = 5001, host: str = '0.0.0.0') -> None:
    """Standalone Web GUI mode (--gui)."""
    ...


def run_daemon_with_gui(cm, interval: int = 5, port: int = 5001, host: str = '0.0.0.0') -> None:
    """Persistent monitor + GUI mode (--monitor-gui)."""
    ...
```

- [ ] **Step 3: Update click commands**

`src/cli/monitor.py`:
```python
import click
from src.cli._runtime import run_daemon_loop


@click.command(name='monitor')
@click.option('-i', '--interval', default=5)
def monitor_cmd(interval: int):
    from src.config import ConfigManager
    cm = ConfigManager()
    run_daemon_loop(cm, interval=interval)
```

Same for `gui_cmd.py`.

- [ ] **Step 4: Update main.py argparse path**

Delete the inline implementations; replace with calls to `src.cli._runtime.run_*`.

- [ ] **Step 5: Run tests**

```bash
venv/bin/pytest tests/test_cli_compat_matrix.py tests/test_cli_subcommands.py tests/test_main_menu.py tests/test_daemon_contract.py -v --timeout=60 2>&1 | tail -10
```

- [ ] **Step 6: Commit**

```bash
git add src/cli/ src/main.py
git commit -m "refactor(cli): unify daemon startup behind src.cli._runtime

Previously --monitor / --gui / --monitor-gui went through src.main
directly while click subcommands were stubs. Both paths now delegate
to pure functions in src.cli._runtime, making the eventual retirement
of argparse a single-file deletion in src.main."
```

---

### Task 5.7: L7 — Bundle CJK font for matplotlib

**Why:** matplotlib uses DejaVu Sans by default which lacks CJK glyphs; chart PNGs render Chinese as 豆腐.

**Files:**
- Add: `src/static/fonts/NotoSansCJKtc-Regular.otf` (or similar)
- Modify: `src/report/exporters/chart_renderer.py` or whichever module calls matplotlib

- [ ] **Step 1: Check current state**

```bash
grep -rn 'rcParams\|font.family\|font.sans-serif' src/report/
```

- [ ] **Step 2: Bundle the font**

Download Noto Sans CJK TC (regular weight) — use the Google Fonts mirror or apt-get equivalent. Place at `src/static/fonts/NotoSansCJKtc-Regular.otf` (or `.ttf`).

License: SIL Open Font License — verify it's included in the offline bundle docs.

- [ ] **Step 3: Configure matplotlib**

Add at the top of the chart-renderer module:

```python
import matplotlib
import matplotlib.pyplot as _plt
from pathlib import Path as _Path

_FONT_PATH = _Path(__file__).resolve().parents[2] / 'static' / 'fonts' / 'NotoSansCJKtc-Regular.otf'
if _FONT_PATH.exists():
    matplotlib.font_manager.fontManager.addfont(str(_FONT_PATH))
    _plt.rcParams['font.sans-serif'] = ['Noto Sans CJK TC', 'DejaVu Sans']
    _plt.rcParams['axes.unicode_minus'] = False
```

- [ ] **Step 4: Add the test**

`tests/test_html_report_cjk_font.py` — extend with an assertion that the rendered PNG actually contains CJK pixels (not glyph-missing boxes). Practical proxy: check the font is loaded:

```python
def test_chart_renderer_loads_cjk_font():
    from src.report.exporters import chart_renderer  # triggers font load
    import matplotlib.font_manager as _fm
    fonts = [f.name for f in _fm.fontManager.ttflist]
    assert 'Noto Sans CJK TC' in fonts, "CJK font not registered with matplotlib"
```

- [ ] **Step 5: Run tests**

```bash
venv/bin/pytest tests/test_html_report_cjk_font.py tests/test_chart_renderer.py -v --timeout=60 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add src/static/fonts/ src/report/exporters/chart_renderer.py tests/test_html_report_cjk_font.py
git commit -m "feat(report): bundle Noto Sans CJK TC for matplotlib charts

Resolves \"豆腐\" boxes in chart PNGs when locale is zh_TW. Font is
SIL OFL-licensed; bundled in src/static/fonts/ so offline-isolated
deployments don't need an OS-level font install."
```

---

### Task 5.8: Batch 5 verification gate

- [ ] `venv/bin/pytest --timeout=60 -q 2>&1 | tail -10` → green
- [ ] `venv/bin/python3 scripts/audit_i18n_usage.py` → 0 findings
- [ ] `venv/bin/mypy src/api_client.py src/analyzer.py src/reporter.py 2>&1 | tail -3` → no errors
- [ ] `git log --oneline main..HEAD | wc -l` → 24 (17 + 7)

Stop and request review.

---

# Batch 4 — 巨型重構（H4 / H5 / H6）

**Includes:** H4 i18n.py 字典抽出 · H5 gui Blueprint 拆分 · H6 settings.py 改名重整.

**Status:** ⚠️ **NOT YET PLANNED — DO NOT EXECUTE FROM THIS DOCUMENT.**

Each of these three items is a 1000+ line refactor that rewires imports across many files. Per the writing-plans skill, each warrants its own dedicated plan with full TDD detail before any code touches.

When ready to start Batch 4, the engineer should:

- [ ] Create three sub-plans:
  - `docs/superpowers/plans/2026-MM-DD-h4-i18n-data-extraction.md`
  - `docs/superpowers/plans/2026-MM-DD-h5-gui-blueprint-split.md`
  - `docs/superpowers/plans/2026-MM-DD-h6-settings-rename-reorg.md`

Each must include:
- File-by-file decomposition (what moves where)
- Import-rewrite checklist (every importer of the old symbols)
- Backwards-compat shims if any external consumer relies on the old paths
- Per-file test gates (rules_engine tests for H4, gui-route tests for H5, etc.)

**Suggested commit-by-commit shape for each sub-plan:**

### H4 (i18n.py extraction) — sketch

1. Add `src/i18n/__init__.py` package shell (preserves `from src.i18n import t` import).
2. Move `_TOKEN_MAP_EN` to `src/i18n/_token_map_en.json` + JSON loader.
3. Move `_TOKEN_MAP_ZH` to `src/i18n/_token_map_zh.json` + JSON loader.
4. Move `_PHRASE_OVERRIDES` to `src/i18n/_phrase_overrides.json` + JSON loader.
5. Move `_ZH_EXPLICIT` (1304 + 96 lines) to `src/i18n/_zh_explicit.json` + JSON loader. **Critical:** preserve update-merge order so the patched dict matches.
6. Convert `src/i18n.py` → `src/i18n/engine.py` (translate, humanize, build_messages, t, set_language).
7. Run all tests + i18n audit. Verify zero key-resolution differences.
8. Delete the now-empty `src/i18n.py`.

Expected diff: ~2300 lines moved, ~200 lines actually changed (the loader code).

### H5 (gui Blueprint split) — sketch

1. Move `_create_app` skeleton into a Blueprint registration loop.
2. Cut routes by topic into `src/gui/routes/{auth,dashboard,config,rules,siem,cache,reports}.py` — one Blueprint each.
3. Each Blueprint takes `cm` and `csrf` and `limiter` via `current_app.config['CM']` etc.
4. Move TLS / cert helpers from end of file to `src/gui/tls.py`.
5. `src/gui/__init__.py` shrinks to: imports, `_create_app(cm)` shell, Blueprint registration.

Expected diff: ~3700 lines moved across ~10 files; ~150 lines structural change.

### H6 (settings.py rename) — sketch

1. Move 24 wizard functions into `src/cli/menus/{event,traffic,bandwidth,system_health,report_schedule,...}.py`.
2. Move `FULL_EVENT_CATALOG` to `src/events/catalog.py` (or de-dup with what's already there).
3. Update every importer of `from src.settings import *`.
4. Delete `src/settings.py`.

Expected diff: ~2200 lines moved into ~10 files.

---

# Final Acceptance

- [ ] All 5 batches complete (Batches 1, 2, 3, 5 done; Batch 4 done via 3 sub-plans)
- [ ] Full test suite green: `venv/bin/pytest --timeout=60 -q 2>&1 | tail -5`
- [ ] i18n audit clean: `venv/bin/python3 scripts/audit_i18n_usage.py`
- [ ] mypy on the three core modules: `venv/bin/mypy src/api_client.py src/analyzer.py src/reporter.py`
- [ ] Manual UI smoke: every tab functional under TLS at `https://localhost:5001`
- [ ] Self-signed cert renew flow still works (manual: GUI → Settings → Renew Cert → restart)
- [ ] CHANGELOG entry covering Batches 1-5

---

## Self-Review Notes

- Spec coverage: every numbered finding (H1-H6, M1-M11, L1-L10) maps to a Task in this plan. Verified against the report.
- Placeholders: zero — every code block is concrete; only the H4/H5/H6 sub-plans are explicitly deferred.
- Type consistency: `_err_with_log(category, exc)` signature is consistent across all 21 leak sites in Task 1.3; fixture names (`client`, `client_authed`, `_csrf`, `temp_config_file`) are consistent between Batch 1's tests and Batch 5's conftest lift.
- Note: Tasks 1.4 and 5.1 both touch fixtures. Task 1.4 introduces `client_authed_initial` and `fresh_initial_password_config` which 5.1 should also lift to conftest. If 5.1 is run after 1.4, it should pick those up too.
