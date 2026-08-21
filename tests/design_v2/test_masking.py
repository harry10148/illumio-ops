import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "design" / "v2" / "tools"))
from masking import mask_payload, mask_values_only, is_sensitive_key


def test_masks_sensitive_keys_recursively():
    src = {"api_key": "AAA", "nested": [{"hec_token": "BBB", "name": "keep"}],
           "password_hash": "CCC", "credentials": {"x": 1}}
    out = mask_payload(src)
    assert out["api_key"] == "***MASKED***"
    assert out["nested"][0]["hec_token"] == "***MASKED***"
    assert out["nested"][0]["name"] == "keep"
    assert out["password_hash"] == "***MASKED***"
    assert out["credentials"] == "***MASKED***"   # 整棵子樹遮掉
    assert src["api_key"] == "AAA"                # 不改原物件


def test_masks_secretish_string_values_even_under_safe_keys():
    # 防呆：value 長得像 PCE api secret（40+ hex）也遮
    out = mask_payload({"note": "a" * 10, "blob": "0123456789abcdef" * 3})
    assert out["note"] == "a" * 10
    assert out["blob"] == "***MASKED***"


def test_masks_compound_key_words_adjacent_to_key_token():
    # 語意式：'key' token 前後緊鄰特定機密詞才算複合機密字
    # （api_key/ssh_key/.../apikey 這種無底線合體字也要認得出來）。
    out = mask_payload({
        "ssh_key": "s1", "signing_key": "s2", "encryption_key": "s3",
        "session_key": "s4", "access_key": "s5", "auth_token": "s6",
        "license_key": "s7", "apikey": "s8", "private_key": "s9",
        "keyboard_layout": "en-US",
        "monkey": "primate",
        "allowed_key": "not-secret-anymore",  # 語意調整：allowed 不在機密鄰接詞清單
        "name": "Alice",
    })
    for k in ("ssh_key", "signing_key", "encryption_key", "session_key",
              "access_key", "auth_token", "license_key", "apikey", "private_key"):
        assert out[k] == "***MASKED***", k
    assert out["keyboard_layout"] == "en-US"
    assert out["monkey"] == "primate"
    assert out["allowed_key"] == "not-secret-anymore"
    assert out["name"] == "Alice"


def test_does_not_mask_semantic_key_suffixed_identifiers():
    # 翻車點：底線 _key 是 identifier 尾綴（指到另一個字典/i18n 條目的鍵名），
    # 不是機密複合詞，語意式規則下不可遮。
    src = {
        "filter_key": "f1", "label_key": "l1", "i18n_key": "i1",
        "desc_key": "d1", "rec_key": "r1", "name_key": "n1",
    }
    assert mask_payload(src) == src


def test_does_not_mask_check_health_fields_previously_caught_by_hec_substring():
    # 舊版「子字串即遮」regex 會把 c-h-e-c-k 裡的 "hec" 誤判成機密；
    # token 化後只認完整 token，這批欄位必須維持原值。
    src = {
        "check_interval_seconds": 30,
        "health_check": "ok",
        "enable_health_check": True,
        "last_checked": "2026-08-03T00:00:00Z",
        "check_failed": False,
    }
    assert mask_payload(src) == src


def test_mask_values_only_skips_key_based_masking_but_still_catches_hex_values():
    # 靜態目錄型端點（ui_translations/event_catalog）：鍵名是識別碼，值才是
    # 要顯示的文字，key 命中規則完全不套用，但長 hex 值仍要遮。
    out = mask_values_only({
        "gui_password": "顯示用標籤文字：密碼",
        "api_key": "這是一個 UI 翻譯字串的 key 名稱，不是真的金鑰",
        "blob": "0123456789abcdef" * 3,
    })
    assert out["gui_password"] == "顯示用標籤文字：密碼"
    assert out["api_key"] == "這是一個 UI 翻譯字串的 key 名稱，不是真的金鑰"
    assert out["blob"] == "***MASKED***"


def test_does_not_mask_backend_redaction_metadata_suffixes():
    # _redact_secrets() 已經把真正的機密值換成星號，另外合成
    # <key>__set（bool）這個安全的衍生 metadata 供前端顯示「是否已設定」。
    # 這個尾綴本身不可能還原出機密，語意式規則不該把它也打光。
    src = {
        "line_channel_access_token": "********",
        "line_channel_access_token__set": True,
        "smtp_password__set": False,
    }
    out = mask_payload(src)
    assert out["line_channel_access_token"] == "***MASKED***"  # 本尊仍遮
    assert out["line_channel_access_token__set"] is True
    assert out["smtp_password__set"] is False


def test_masks_camelcase_compound_secret_names():
    # review I1：舊 tokenizer 只切非英數字元，camelCase 合體字（如 apiToken）
    # 被當成一個查無此字的 token 而漏遮（fail open）。這批是 review 點名的
    # LEAK 清單，camelCase 邊界切開後應全數命中完整字 token 而遮蔽。
    leaked_before_fix = {
        "apiToken": "s1", "authToken": "s2", "clientSecret": "s3",
        "passwordHash": "s4", "apiSecret": "s5", "secretKey": "s6",
        "sessionToken": "s7", "accessToken": "s8", "hecToken": "s9",
        "bearerToken": "s10", "refreshToken": "s11",
    }
    out = mask_payload(leaked_before_fix)
    for k in leaked_before_fix:
        assert out[k] == "***MASKED***", k
    for k in leaked_before_fix:
        assert is_sensitive_key(k), k


def test_camelcase_tokenizer_does_not_overmask_non_secret_camelcase_keys():
    # camelCase 切法不能反而把安全欄位打光：filter_key/health_check/keyboard
    # 這幾個既有的「不遮」案例，camelCase 或不同拼法下仍要維持不遮。
    src = {
        "filterKey": "f1", "healthCheck": "ok", "keyboard": "en-US",
        "filter_key": "f2", "health_check": "ok2",
    }
    assert mask_payload(src) == src
    for k in src:
        assert not is_sensitive_key(k), k


def test_is_sensitive_key_standalone_words():
    for k in ("password", "passwd", "secret", "token", "credential", "credentials", "hec",
              "some_password_field", "auth_token", "hec_token"):
        assert is_sensitive_key(k), k
    for k in ("filter_key", "check_interval_seconds", "keyboard_layout", "name",
              "label_key", "i18n_key"):
        assert not is_sensitive_key(k), k


def test_masks_last_target_as_pii_not_secret():
    # 2026-08-03 使用者裁決：alert_channels[].last_target 是收件人 email／
    # LINE 使用者 ID，屬個資（PII）而非機密（secret），但快照/截圖仍不可
    # 外流真實聯絡方式，走同一條 mask_payload pipeline、遮成同一個
    # ***MASKED*** token。刻意窄範圍（exact key match，非 "target" 這種
    # 泛用 token），避免誤傷同結構下的其餘欄位。
    src = {
        "alert_channels": [
            {
                "name": "mail",
                "enabled": True,
                "configured": True,
                "last_status": "success",
                "last_target": "test-user@example.com",
            },
            {
                "name": "line",
                "enabled": True,
                "configured": True,
                "last_status": "success",
                "last_target": "Uabc123def456abc123def456abc12345",
            },
        ]
    }
    out = mask_payload(src)
    ch0, ch1 = out["alert_channels"]
    assert ch0["last_target"] == "***MASKED***"
    assert ch1["last_target"] == "***MASKED***"
    # 相鄰欄位維持原值，不可被連坐遮蔽
    for ch in (ch0, ch1):
        assert ch["name"] in ("mail", "line")
        assert ch["enabled"] is True
        assert ch["configured"] is True
        assert ch["last_status"] == "success"
    assert is_sensitive_key("last_target")
    assert not is_sensitive_key("last_status")
    assert not is_sensitive_key("target")  # 泛用字不應被連坐


def test_last_target_empty_string_stays_masked_not_falsy_skipped():
    # 未設定的頻道 last_target 是空字串——遮罩函式對 key 命中一律換成
    # MASK token，不因值是 falsy 就跳過（否則測試會誤以為「反正是空的不用管」
    # 而漏掉未來這裡被填入真值時的遮蔽）。
    out = mask_payload({"last_target": ""})
    assert out["last_target"] == "***MASKED***"


def test_line_target_id_masked_as_exact_pii_key():
    # settings.json /alerts/line_target_id 是同一顆真實 LINE 使用者 ID，
    # 只是在 settings 端點下換了個鍵名（不是 last_target）。精確 key 全字
    # 比對，和 last_target 同一條 pipeline。
    src = {"line_target_id": "Uabc123def456abc123def456abc12345", "webhook_url": ""}
    out = mask_payload(src)
    assert out["line_target_id"] == "***MASKED***"
    assert out["webhook_url"] == ""
    assert is_sensitive_key("line_target_id")


def test_target_and_recipients_masked_only_when_value_looks_like_pii():
    # 發現超出原始盤點範圍的洩漏面：dashboard_overview.json
    # /alerts/recent[].target、status.json /dispatch_history[].target、
    # settings.json /email/recipients 都用同一顆真實 email／LINE ID，但鍵名
    # 是泛用的 "target"／"recipients"，不能無條件遮（"target" 在
    # /posture/remediation[].target 是數字目標值 100，不是個資，若無條件遮
    # 會把不相干的數字打成字串 MASK，造成資料型別錯誤的連坐傷害）。
    # 因此對這兩個鍵採「值形狀」二次確認：值本身長得像 email 或 LINE 使用者
    # ID（U + 32 hex）才遮，否則原樣保留。
    src = {
        "alerts": {
            "recent": [
                {"channel": "mail", "target": "test-user@example.com", "status": "success"},
                {"channel": "line", "target": "Uabc123def456abc123def456abc12345", "status": "success"},
            ]
        },
        "posture": {
            "remediation": [{"label": "全域", "target": 100, "actual": 87}],
        },
        "dispatch_history": [
            {"channel": "line", "target": "Uabc123def456abc123def456abc12345"},
        ],
        "email": {"recipients": ["test-user@example.com"], "sender": "admin@lab.local"},
    }
    out = mask_payload(src)
    assert out["alerts"]["recent"][0]["target"] == "***MASKED***"
    assert out["alerts"]["recent"][1]["target"] == "***MASKED***"
    assert out["alerts"]["recent"][0]["status"] == "success"  # 相鄰欄位不連坐
    # 數字目標值必須原封不動保留（型別跟數值都不可變）
    assert out["posture"]["remediation"][0]["target"] == 100
    assert out["posture"]["remediation"][0]["actual"] == 87
    assert out["dispatch_history"][0]["target"] == "***MASKED***"
    assert out["email"]["recipients"] == "***MASKED***"
    # sender 自 2026-08-05 起也在 value-gated 清單裡（見下面的 sender/user 測試）
    assert out["email"]["sender"] == "***MASKED***"


def test_non_pii_shaped_target_and_recipients_left_untouched():
    # 值形狀不像 email／LINE ID 的 target/recipients，即使鍵名相符也不遮。
    src = {"target": "some-non-pii-string", "recipients": ["ops-team"], "count_target": 5}
    out = mask_payload(src)
    assert out == src


def test_sender_and_user_masked_only_when_value_is_email_shaped():
    # 2026-08-05 使用者裁決：settings.json /email/sender 與 /smtp/user 是同一顆
    # 真實個人信箱，與 last_target 同一個 PII 類別。鍵名（sender／user）都是
    # 泛用字，走既有的「值形狀二次確認」規則：值長得像 email 才遮。
    src = {
        "email": {"sender": "admin@example.net", "recipients": ["ops@example.net"]},
        "smtp": {"host": "mail.example.net", "user": "admin@example.net", "port": 587},
        # 對照組：同名鍵在別的語境下不是個資，值形狀也不像 email，不可誤遮
        "flows": [{"source": {"user": ""}, "destination": {"user": "SYSTEM"}}],
        "audit": {"user": {"href": "/users/11", "username": "ops@example.net"}},
        "sender": "automation-daemon",
    }
    out = mask_payload(src)
    assert out["email"]["sender"] == "***MASKED***"
    assert out["smtp"]["user"] == "***MASKED***"
    assert out["smtp"]["port"] == 587
    assert out["flows"][0]["source"]["user"] == ""
    assert out["flows"][0]["destination"]["user"] == "SYSTEM"
    # 值是 dict 的 "user"（事件明細的巢狀物件）不該被整棵打光；它底下的
    # username 不在名單裡，維持原值——本次裁決的範圍只有 sender/user 的
    # email 值本身。
    assert out["audit"]["user"]["username"] == "ops@example.net"
    assert out["sender"] == "automation-daemon"


def test_smtp_host_masked_by_explicit_path_not_by_key_name():
    # settings.json /smtp/host 帶的是同一顆個人網域（mail.<個人網域>），與
    # sender/user 同源。但 "host" 是全專案最泛用的鍵名之一（siem_destinations
    # 的目的地 host、workload 主機名都叫 host），值形狀又只是個主機名——沒有
    # 任何值形狀規則能把「個人郵件網域」跟「機房主機」分開。因此這一顆走
    # 精確路徑比對（_PII_PATHS），只遮 settings 端點的 smtp.host。
    src = {
        "smtp": {"host": "mail.example.net", "port": 587},
        "destinations": [{"host": "172.16.15.105", "port": 514}],
        "workload": {"host": "web-01.internal"},
    }
    out = mask_payload(src)
    assert out["smtp"]["host"] == "***MASKED***"
    assert out["smtp"]["port"] == 587
    assert out["destinations"][0]["host"] == "172.16.15.105"
    assert out["workload"]["host"] == "web-01.internal"


def test_pii_paths_are_index_agnostic_inside_lists():
    # 路徑比對不帶陣列索引：list 沿用父層路徑，所以就算 smtp 被包成陣列，
    # 底下的 host 仍然命中。
    out = mask_payload({"smtp": [{"host": "mail.example.net"}]})
    assert out["smtp"][0]["host"] == "***MASKED***"


def test_mask_values_only_also_applies_sender_user_and_paths():
    # catalog 端點跳過的是「機密 key 判定」，個資防呆不跳過（同 last_target
    # 的既有約定）。
    out = mask_values_only({"email": {"sender": "admin@example.net"},
                            "smtp": {"host": "mail.example.net"},
                            "gui_password": "顯示用標籤文字：密碼"})
    assert out["email"]["sender"] == "***MASKED***"
    assert out["smtp"]["host"] == "***MASKED***"
    assert out["gui_password"] == "顯示用標籤文字：密碼"
