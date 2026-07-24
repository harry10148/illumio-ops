"""Task F5：GUI validate-then-mutate + report.output_dir 防護。

子項 1：api_save_settings / api_security_post 早退 400 前不得讓 cm.config
       殘留任何被拒欄位（scratch dict → 驗證 → 通過才寫回）。
子項 2：report.output_dir 新設定必須拒絕系統敏感路徑與檔案系統根。
"""
import pytest

from tests._helpers import _csrf


@pytest.fixture
def authed_client(app_persistent):
    client = app_persistent.test_client()
    login = client.post(
        "/api/login",
        json={"username": "admin", "password": "testpass"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert login.status_code == 200
    csrf = _csrf(login)
    return client, csrf


def _post(client, csrf, path, payload):
    return client.post(
        path,
        json=payload,
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        headers={"X-CSRF-Token": csrf},
    )


# ── 子項 1：validate-then-mutate ────────────────────────────────────────────

def test_rejected_security_post_does_not_leave_partial_mutation_in_memory(authed_client, app_persistent):
    """RED（修復前）：allowed_ips 驗證失敗前，username 已直接寫入 cm.config。

    不呼叫 cm.load()，直接檢查記憶體中的 cm.config——證明「被拒絕的中間
    狀態留在記憶體」，即使沒有下一次 reload 也可能被併發 GET 觀察到。
    """
    client, csrf = authed_client
    cm = app_persistent.config["CM"]
    cm.load()
    original_username = cm.config["web_gui"]["username"]

    res = _post(client, csrf, "/api/security", {
        "username": "attacker",
        "allowed_ips": ["not-an-ip"],
    })
    assert res.status_code == 400

    assert cm.config["web_gui"]["username"] == original_username


def test_rejected_settings_post_does_not_leave_partial_api_mutation_in_memory(authed_client, app_persistent):
    """RED（修復前）：api 允許清單欄位在 for 迴圈中先寫入 cm.config['api']，
    迴圈結束後才呼叫 ApiSettings.model_validate() 做整體驗證並拒絕。
    """
    client, csrf = authed_client
    cm = app_persistent.config["CM"]
    cm.load()
    original_org_id = cm.config["api"]["org_id"]

    res = _post(client, csrf, "/api/settings", {
        "api": {"org_id": "999-poisoned", "verify_ssl": False},
    })
    assert res.status_code == 400

    assert cm.config["api"]["org_id"] == original_org_id
    assert cm.config["api"]["verify_ssl"] is True


def test_rejected_security_post_still_returns_same_error_message(authed_client):
    """行為不變：拒絕路徑的錯誤訊息維持原樣。"""
    client, csrf = authed_client
    res = _post(client, csrf, "/api/security", {"allowed_ips": ["not-an-ip"]})
    assert res.status_code == 400
    assert "not-an-ip" in res.get_json()["error"]


def test_security_post_happy_path_unchanged(authed_client, app_persistent):
    """行為不變：成功路徑輸出與最終落地狀態維持原樣。"""
    client, csrf = authed_client
    # Include the requester (test client is 127.0.0.1) so the change is not a
    # self-lockout — the new guard rejects an allowlist that would lock the
    # current admin out.
    res = _post(client, csrf, "/api/security", {
        "username": "admin2",
        "allowed_ips": ["10.0.0.0/8", "127.0.0.1"],
    })
    assert res.status_code == 200
    assert res.get_json() == {"ok": True}

    cm = app_persistent.config["CM"]
    cm.load()
    assert cm.config["web_gui"]["username"] == "admin2"
    assert cm.config["web_gui"]["allowed_ips"] == ["10.0.0.0/8", "127.0.0.1"]


# ── 子項 2：report.output_dir 防護 ──────────────────────────────────────────

@pytest.mark.parametrize("bad_dir", [
    "/etc/evil", "/etc", "/usr/local", "/bin", "/sbin/x", "/boot",
    "/root/.ssh", "/proc/1", "/sys/class", "/dev/null", "/lib/x86_64",
])
def test_output_dir_rejects_system_prefixes(authed_client, app_persistent, bad_dir):
    client, csrf = authed_client
    cm = app_persistent.config["CM"]
    cm.load()
    original = cm.config["report"]["output_dir"]

    res = _post(client, csrf, "/api/settings", {"report": {"output_dir": bad_dir}})
    assert res.status_code == 400
    assert res.get_json()["ok"] is False

    cm.load()
    assert cm.config["report"]["output_dir"] == original


def test_output_dir_rejects_filesystem_root(authed_client, app_persistent):
    client, csrf = authed_client
    cm = app_persistent.config["CM"]
    cm.load()
    original = cm.config["report"]["output_dir"]

    res = _post(client, csrf, "/api/settings", {"report": {"output_dir": "/"}})
    assert res.status_code == 400

    cm.load()
    assert cm.config["report"]["output_dir"] == original


def test_output_dir_error_message_localized(authed_client):
    client, csrf = authed_client
    res = _post(client, csrf, "/api/settings", {
        "report": {"output_dir": "/etc/evil"},
        "lang": "zh_TW",
    })
    assert res.status_code == 400
    body = res.get_json()
    assert body["ok"] is False
    assert body["error"]
    # 不應該還是英文預設訊息（確認 zh_TW 詞條存在且被選用）
    en_res = _post(client, csrf, "/api/settings", {
        "report": {"output_dir": "/etc/evil"},
        "lang": "en",
    })
    assert en_res.get_json()["error"] != body["error"]


def test_output_dir_accepts_legit_custom_path(authed_client, app_persistent, tmp_path):
    """不落系統敏感前綴的自訂路徑（如資料碟／NAS 掛載模擬）仍允許。"""
    client, csrf = authed_client
    custom_dir = str(tmp_path / "nas_reports")

    res = _post(client, csrf, "/api/settings", {"report": {"output_dir": custom_dir}})
    assert res.status_code == 200
    assert res.get_json() == {"ok": True}

    cm = app_persistent.config["CM"]
    cm.load()
    assert cm.config["report"]["output_dir"] == custom_dir


def test_existing_output_dir_not_revalidated_on_load(app_persistent):
    """相容性：既有 config 已存的 output_dir 不因新增的 POST-time 檢查而在
    load() 時被拒絕，避免升級後自鎖（brief 明確要求：只擋新設定）。
    """
    cm = app_persistent.config["CM"]
    cm.load()
    cm.config["report"]["output_dir"] = "/etc/legacy_reports"
    cm.save()

    cm.load()  # 不應拋出，也不應被還原成預設值
    assert cm.config["report"]["output_dir"] == "/etc/legacy_reports"
