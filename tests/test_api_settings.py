"""Tests for Phase 4 security hardening: secrets redaction, settings allowlist, URL validation."""
import json
import os
import tempfile

import pytest

from src.config import ConfigManager, hash_password
from src.gui import build_app as _create_app


from tests._helpers import _csrf


@pytest.fixture
def temp_config_file():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        json.dump(
            {
                "api": {
                    "url": "https://pce.example.com:8443",
                    "key": "myapikey",
                    "secret": "mysecret",
                    "org_id": "1",
                },
                "smtp": {
                    "host": "smtp.example.com",
                    "port": 587,
                    "password": "smtppassword",
                },
                "alerts": {
                    "line_channel_access_token": "mytoken123",
                    "webhook_url": "https://hooks.example.com/abc",
                },
                "rules": [],
            },
            f,
        )
    yield path
    os.unlink(path)


@pytest.fixture
def app(temp_config_file):
    cm = ConfigManager(config_file=temp_config_file)
    cm.load()
    cm.config["web_gui"] = {
        "username": "admin",
        "password": hash_password("testpass"),
        "allowed_ips": [],
        "secret_key": "test-secret",
    }
    cm.save()
    application = _create_app(cm, persistent_mode=True)
    application.config.update({"TESTING": True})
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def authed_client(client):
    login = client.post("/api/login", json={"username": "admin", "password": "testpass"})
    assert login.status_code == 200
    csrf = _csrf(login)
    return client, csrf


# ── Test 1: secrets are redacted in GET /api/settings ─────────────────────────

def test_redaction_response(authed_client):
    client, csrf = authed_client
    res = client.get("/api/settings")
    assert res.status_code == 200
    body = res.get_json()

    # api.key and api.secret must be redacted
    api = body.get("api", {})
    assert api.get("key") != "myapikey", "api.key should be redacted"
    assert api.get("secret") != "mysecret", "api.secret should be redacted"

    # smtp.password must be redacted
    smtp = body.get("smtp", {})
    assert smtp.get("password") != "smtppassword", "smtp.password should be redacted"

    # alerts token and webhook should be redacted
    alerts = body.get("alerts", {})
    assert alerts.get("line_channel_access_token") != "mytoken123", (
        "line_channel_access_token should be redacted"
    )
    assert alerts.get("webhook_url") != "https://hooks.example.com/abc", (
        "webhook_url should be redacted"
    )

    # Non-secret fields must still be present
    assert api.get("url") == "https://pce.example.com:8443"
    assert smtp.get("host") == "smtp.example.com"


def test_redaction_never_reports_secret_length(authed_client):
    """The redactor may say a secret IS set; it must not say how long it is.

    `<key>__length` used to ride along with `<key>__set` and was rendered
    verbatim in the settings form ("Configured (32 characters)"), handing the
    exact size of a stored credential to anyone who could read the response.
    `__set` stays — it is how the UI tells configured from not.
    """
    client, _csrf = authed_client
    body = client.get("/api/settings").get_json()
    flat = json.dumps(body)
    assert "__length" not in flat, (
        "GET /api/settings still exposes a secret's length: "
        + ", ".join(sorted(k for section in body.values()
                           if isinstance(section, dict)
                           for k in section if k.endswith("__length")))
    )


# ── Test 1b: the contract the Integrations → Overview channel cards depend on ──
# Regression guard for the "LINE configured but displayed as Not configured" bug.
# The overview detects a configured channel via the redacted-secret companion flag
# `<key>__set`, reading FLAT keys (alerts.line_channel_access_token) — NOT the masked
# value (which contains asterisks) and NOT a nested alerts.line object. If this
# contract drifts, the channel cards silently misreport configured channels.

def test_alert_channel_configured_flag_contract(authed_client):
    client, _ = authed_client
    alerts = client.get("/api/settings").get_json().get("alerts", {})

    # configured secret → __set True; value is masked, so the UI must trust __set
    assert alerts.get("line_channel_access_token__set") is True
    assert "*" in str(alerts.get("line_channel_access_token")), "secret value must be masked"
    assert alerts.get("webhook_url__set") is True

    # keys stay FLAT under `alerts`, not nested (alerts.line / alerts.webhook)
    assert not isinstance(alerts.get("line"), dict), "config must stay flat, not nested alerts.line"
    assert not isinstance(alerts.get("webhook"), dict)

    # an unconfigured secret must not read as configured
    assert not alerts.get("telegram_bot_token__set")


# ── Test 2: mass-assignment via __proto__ or unknown keys is rejected ──────────

def test_mass_assignment_rejected(authed_client, app):
    client, csrf = authed_client
    res = client.post(
        "/api/settings",
        json={"smtp": {"__proto__": "x", "host": "test.host"}},
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 200

    cm = app.config["CM"]
    cm.load()
    smtp_cfg = cm.config.get("smtp", {})
    assert "__proto__" not in smtp_cfg, "__proto__ should be filtered out by allowlist"
    assert smtp_cfg.get("host") == "test.host", "Allowed key 'host' should be saved"


# ── Test 2b: telegram/teams keys survive the alerts allowlist ─────────────────
# Backend supports these channels (AlertsSettings + dispatch plugins); the GUI
# settings-save must not silently drop them when an operator configures them.

def test_alerts_save_preserves_telegram_and_teams_keys(authed_client, app):
    client, csrf = authed_client
    res = client.post(
        "/api/settings",
        json={"alerts": {
            "telegram_bot_token": "tg-bot-123",
            "telegram_chat_id": "chat-456",
            "teams_webhook_url": "https://outlook.office.com/webhook/abc",
        }},
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 200

    cm = app.config["CM"]
    cm.load()
    alerts_cfg = cm.config.get("alerts", {})
    assert alerts_cfg.get("telegram_bot_token") == "tg-bot-123"
    assert alerts_cfg.get("telegram_chat_id") == "chat-456"
    assert alerts_cfg.get("teams_webhook_url") == "https://outlook.office.com/webhook/abc"


# ── Test 3: api.url with ftp:// scheme is rejected with 400 ───────────────────

def test_pce_url_scheme_validator(authed_client):
    client, csrf = authed_client
    res = client.post(
        "/api/settings",
        json={"api": {"url": "ftp://malicious.host"}},
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 400
    body = res.get_json()
    assert body.get("ok") is False


# ── Test 4：批次 5 C3 配套——api 區塊在弄壞下一次 cm.load() 之前先驗證
# （verify_ssl=False 而 profile 仍是 'production' 會在 load 時觸發
# ApiSettings 的 fail-hard TLS guard）──────────────────────────────────────

def test_settings_post_rejects_api_block_that_would_brick_next_load(authed_client, app):
    client, csrf = authed_client
    res = client.post(
        "/api/settings",
        json={"api": {"verify_ssl": False}},
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 400
    body = res.get_json()
    assert body.get("ok") is False

    # 不可已寫入磁碟：重新 load() 不得拋出 ConfigError。
    cm = app.config["CM"]
    cm.load()
    assert cm.config["api"]["verify_ssl"] is True


def test_settings_post_accepts_verify_ssl_false_with_explicit_dev_profile(authed_client, app):
    """Sanity：這個 guard 就是其他地方共用的同一條 ApiSettings 規則
    （dev profile 明確選擇停用 TLS 驗證），不是一律禁止。"""
    client, csrf = authed_client
    cm = app.config["CM"]
    cm.load()
    cm.config["api"]["profile"] = "dev"
    cm.save()

    res = client.post(
        "/api/settings",
        json={"api": {"verify_ssl": False}},
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 200
    cm.load()
    assert cm.config["api"]["verify_ssl"] is False


def test_settings_response_has_no_profile_fields(authed_client):
    """Profile 概念已移除：設定回應不得再帶 profile 清單或 active id。"""
    client, _csrf = authed_client
    body = client.get("/api/settings").get_json()
    assert "pce_profiles" not in body
    assert "active_pce_id" not in body


def test_settings_round_trips_runtime_connection_metadata_without_target_change(
    authed_client, app,
):
    """Deployment/Console metadata changes runtime connection behaviour, but
    does not identify a different PCE or require a cache decision."""
    client, csrf = authed_client

    before = client.get("/api/settings").get_json()["api"]
    assert before["deployment_type"] == "on_prem"
    assert before["console_url"] == ""

    res = _save(client, csrf, {
        "deployment_type": "saas",
        "console_url": "https://tenant.illumio.example/",
    })

    assert res.status_code == 200
    assert res.get_json() == {"ok": True, "restart_required": True}
    cm = app.config["CM"]
    cm.load()
    assert cm.config["api"]["deployment_type"] == "saas"
    assert cm.config["api"]["console_url"] == "https://tenant.illumio.example"
    reread = client.get("/api/settings").get_json()["api"]
    assert reread["deployment_type"] == "saas"
    assert reread["console_url"] == "https://tenant.illumio.example"


@pytest.mark.parametrize("api_block", [
    {"deployment_type": "cloud", "console_url": "https://tenant.example.com"},
    {"deployment_type": "saas", "console_url": "ftp://tenant.example.com"},
])
def test_settings_rejects_invalid_runtime_connection_metadata_atomically(
    authed_client, app, api_block,
):
    """A bad value in either new field rejects the complete API block; the
    other valid value must not be partially persisted."""
    client, csrf = authed_client
    cm = app.config["CM"]
    cm.load()
    before = dict(cm.config["api"])

    res = _save(client, csrf, api_block)

    assert res.status_code == 400
    assert res.get_json()["ok"] is False
    cm.load()
    assert cm.config["api"] == before


@pytest.mark.parametrize(("api_block", "choice"), [
    ({
        "deployment_type": "saas",
        "console_url": "https://fake-user:fake-pass@tenant.illumio.example",
    }, None),
    ({
        "url": "https://fake-user:fake-pass@pce.example.com:8443",
        "org_id": "sentinel-org",
    }, "same-pce"),
])
def test_settings_rejects_userinfo_urls_without_partial_mutation(
    authed_client, app, api_block, choice,
):
    client, csrf = authed_client
    cm = app.config["CM"]
    cm.load()
    before = dict(cm.config["api"])

    res = _save(client, csrf, api_block, choice=choice)

    assert res.status_code == 400
    assert res.get_json()["ok"] is False
    cm.load()
    assert cm.config["api"] == before
    stored = json.dumps(cm.config["api"])
    assert "fake-user" not in stored
    assert "sentinel-org" not in stored


def test_settings_rejects_userinfo_url_before_target_change_response(
    authed_client, app,
):
    client, csrf = authed_client
    cm = app.config["CM"]
    cm.load()
    before = dict(cm.config["api"])

    res = _save(client, csrf, {
        "url": "https://fake-user:fake-pass@other-pce.example.com:8443",
        "org_id": "sentinel-org",
    })

    assert res.status_code == 400
    body = res.get_json()
    assert body["ok"] is False
    assert "pce_target_changed" not in body
    serialized_body = json.dumps(body)
    assert "fake-user" not in serialized_body
    assert "fake-pass" not in serialized_body
    assert "sentinel-org" not in serialized_body
    cm.load()
    assert cm.config["api"] == before


def test_runtime_connection_metadata_neither_flushes_nor_changes_target(
    tmp_path, monkeypatch,
):
    client, csrf, cache_db = _flush_test_app(tmp_path, monkeypatch)
    _seed_one_event(cache_db)

    res = _save(client, csrf, {
        "deployment_type": "saas",
        "console_url": "https://console.illum.io",
    })

    assert res.status_code == 200
    assert res.get_json()["restart_required"] is True
    assert "pce_target_changed" not in res.get_json()
    assert _count_events(cache_db) == 1


def test_pce_profiles_endpoint_is_gone(authed_client):
    client, _csrf = authed_client
    assert client.get("/api/pce-profiles").status_code == 404


# ── PCE 連線目標變更必須是明示的決定 ──────────────────────────────────────────
# 這台設備的快取、擷取位置、封存與排程都沒有 PCE 維度（見
# docs/superpowers/specs/2026-08-21-pce-profile-isolation-assessment.md）。把
# api.url 或 api.org_id 指向另一台 PCE 而不處理既有資料，兩台的資料會靜默混合，
# 而且沒有任何徵兆。所以這裡不猜、也不自動清——直接擋下來要求操作者選。

def _save(client, csrf, api_block, choice=None):
    body = {"api": api_block}
    if choice is not None:
        body["pce_target_change"] = choice
    return client.post("/api/settings", json=body,
                       headers={"X-CSRFToken": csrf},
                       environ_overrides={"REMOTE_ADDR": "127.0.0.1"})


def test_changing_url_without_a_choice_is_refused(authed_client):
    client, csrf = authed_client
    res = _save(client, csrf, {"url": "https://other-pce.example.com:8443"})
    assert res.status_code == 409
    body = res.get_json()
    assert body["ok"] is False
    assert body["pce_target_changed"] is True
    assert body["old"]["url"] == "https://pce.example.com:8443"
    assert body["new"]["url"] == "https://other-pce.example.com:8443"


def test_changing_org_id_without_a_choice_is_refused(authed_client):
    client, csrf = authed_client
    res = _save(client, csrf, {"org_id": "7"})
    assert res.status_code == 409
    assert res.get_json()["pce_target_changed"] is True


def test_rotating_credentials_is_not_a_target_change(authed_client):
    """換 key/secret 只是輪替憑證，不該擋。"""
    client, csrf = authed_client
    res = _save(client, csrf, {"key": "newkey", "secret": "newsecret"})
    assert res.status_code == 200
    assert res.get_json()["ok"] is True


def test_same_pce_choice_saves_without_touching_data(tmp_path, monkeypatch):
    """"same-pce" is the answer that must leave the data alone, so 200 on its
    own proves nothing — the seeded row is the assertion that matters."""
    client, csrf, cache_db = _flush_test_app(tmp_path, monkeypatch)
    _seed_one_event(cache_db)
    assert _count_events(cache_db) == 1

    res = _save(client, csrf, {"url": "https://renamed.example.com:8443"},
                choice="same-pce")
    assert res.status_code == 200
    assert res.get_json()["ok"] is True
    assert _count_events(cache_db) == 1, "same-pce must not touch the cache"


def test_unknown_choice_is_rejected(authed_client):
    client, csrf = authed_client
    res = _save(client, csrf, {"url": "https://other.example.com:8443"},
                choice="whatever")
    assert res.status_code == 400


# ── choice="flush" 端到端：真的清掉快取；而且只在整個 save 都通過驗證之後 ──
# 才動手（見 src/gui/routes/config.py 的 _do_pce_flush）——handler 在 api
# 區塊驗證之後還有 email/smtp/alerts/settings/report/外掛區塊各自能 400，
# flush 提早跑，遇到後面才炸的 400 就會把還連著的 PCE 的快取清光。

def _isolate_flush_side_files(tmp_path, monkeypatch):
    """flush_pce_derived_state() reaches three files this app never names:
    logs/state.json (via config.py's _resolve_state_file), logs/analysis.lock
    (the cross-process analysis lock it takes) and logs/dashboard_summary.json
    (ven_summary). All three resolve relative to the REPO, not to tmp_path —
    so without this, running the suite on a checkout where the appliance
    actually runs deleted its event_watermark / alert_history / event_seen
    (history re-fetched from zero, suppressed alerts re-fired) and blocked on
    a live monitor cycle.

    _resolve_state_file is patched where it is looked up (imported into
    src.gui.routes.config's namespace), not where it is defined."""
    import src.gui.routes.config as _config_routes
    import src.main as _main
    from src import dashboard_store

    state_file = tmp_path / "state.json"
    state_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(_config_routes, "_resolve_state_file", lambda: str(state_file))
    monkeypatch.setattr(_main, "analysis_lock_path",
                        lambda: str(tmp_path / "analysis.lock"))
    monkeypatch.setattr(dashboard_store, "_dashboard_file",
                        lambda: str(tmp_path / "dashboard_summary.json"))
    return state_file


def _flush_test_app(tmp_path, monkeypatch):
    """獨立 app（不共用模組層的 temp_config_file/app fixture）：需要一個
    真實、可讀寫的 pce_cache.db_path 才能驗證 flush 對快取檔案的實際效果。"""
    _isolate_flush_side_files(tmp_path, monkeypatch)
    cache_db = tmp_path / "cache.sqlite"
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "api": {
            "url": "https://pce.example.com:8443",
            "key": "myapikey",
            "secret": "mysecret",
            "org_id": "1",
        },
        "pce_cache": {"db_path": str(cache_db)},
        "web_gui": {
            "username": "admin",
            "password": hash_password("testpass"),
            "allowed_ips": [],
            "secret_key": "test-secret",
        },
    }), encoding="utf-8")

    cm = ConfigManager(config_file=str(config_path))
    cm.load()
    application = _create_app(cm, persistent_mode=True)
    application.config.update({"TESTING": True})
    client = application.test_client()
    login = client.post("/api/login", json={"username": "admin", "password": "testpass"})
    assert login.status_code == 200
    csrf = _csrf(login)
    return client, csrf, cache_db


def _seed_one_event(db_path):
    from datetime import datetime, timezone

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.pce_cache.models import Base, PceEvent

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    sf = sessionmaker(bind=engine)
    with sf() as s:
        s.add(PceEvent(pce_href="/orgs/1/events/a", pce_event_id="a",
                       timestamp=now, event_type="x", severity="info",
                       status="success", pce_fqdn="pce.example.com",
                       raw_json="{}", ingested_at=now))
        s.commit()
    engine.dispose()


def _count_events(db_path):
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import sessionmaker

    from src.pce_cache.models import Base, PceEvent

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    sf = sessionmaker(bind=engine)
    with sf() as s:
        n = s.execute(select(func.count()).select_from(PceEvent)).scalar_one()
    engine.dispose()
    return n


def test_flush_choice_empties_the_seeded_cache(tmp_path, monkeypatch):
    client, csrf, cache_db = _flush_test_app(tmp_path, monkeypatch)
    _seed_one_event(cache_db)
    assert _count_events(cache_db) == 1

    res = _save(client, csrf, {"url": "https://other-pce.example.com:8443"}, choice="flush")
    assert res.status_code == 200
    assert res.get_json()["ok"] is True
    assert _count_events(cache_db) == 0


def test_a_save_rejected_by_later_validation_leaves_a_flush_cache_intact(tmp_path, monkeypatch):
    """PCE choice 通過後若較晚的 report 驗證失敗，不得先清除舊 PCE 快取。"""
    client, csrf, cache_db = _flush_test_app(tmp_path, monkeypatch)
    _seed_one_event(cache_db)
    assert _count_events(cache_db) == 1

    cm = client.application.config["CM"]
    cm.load()
    before_api = dict(cm.config["api"])
    before_report = dict(cm.config["report"])

    res = client.post(
        "/api/settings",
        json={
            "api": {"url": "https://other-pce.example.com:8443"},
            "pce_target_change": "flush",
            "report": {"output_dir": "/etc/evil"},
        },
        headers={"X-CSRFToken": csrf},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert res.status_code == 400
    body = res.get_json()
    assert body["ok"] is False
    assert "Report output directory" in body["error"]
    assert _count_events(cache_db) == 1, "被拒絕的 save 不得清除快取"
    assert cm.config["api"] == before_api
    assert cm.config["report"] == before_report

    cm.load()
    assert cm.config["api"] == before_api
    assert cm.config["report"] == before_report
