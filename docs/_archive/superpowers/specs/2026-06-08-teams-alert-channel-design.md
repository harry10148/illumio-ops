# 設計：Microsoft Teams 告警連接器（Adaptive Card via Power Automate Workflows）

- **日期**：2026-06-08
- **範圍代號**：P4（借鏡優化規劃，第四項：Teams 告警連接器）
- **狀態**：設計待實作（spec → writing-plans）

## 1. 背景與方向

illumio-ops 已有成熟的 alert-plugin 架構：`AlertOutputPlugin` ABC（`src/alerts/base.py`）以 `__init_subclass__` 自動註冊，`Reporter.send_alerts`（`src/reporter.py:701`）依 `alerts.active` 清單透過 registry 分派。現有四個 channel：`mail`、`line`、`webhook`、`telegram`。

本 spec 新增**第五個 channel：`teams`**，把告警以 **Adaptive Card** 透過 **Microsoft Teams Power Automate（Workflows）incoming webhook** 送出。範圍**只含 Teams**，不含 Slack / ServiceNow / Jira。

**鎖定決策（不再討論）：**

- 訊息格式為 **Adaptive Card JSON**，以 HTTP POST 送至 **Power Automate Workflow webhook URL**。
- **不使用**舊版 O365 MessageCard / Office 365 Connector（Microsoft 已宣布淘汰）。
- **完全鏡射既有 plugin 架構**：新 plugin 鏡射 `WebhookAlertPlugin` / `TelegramAlertPlugin`（HTTP POST 形狀、error dict 回傳、config 讀法），payload builder 鏡射 `_build_webhook_payload`，template 鏡射 `webhook_payload.json.tmpl` 放在 `src/alerts/templates/`。

明確排除（YAGNI）：Adaptive Card 的 `Action.OpenUrl` 互動按鈕僅放單一「Open in PCE」連結（不加 mention、不加圖片、不加 throttling/cooldown ——`line` 的 cooldown 是 LINE 專屬，Teams 不沿用）；不新增 GUI 前端渲染（沿用既有 `/api/alert-plugins` metadata 驅動的表單）。

## 2. 現況（不得破壞）

- `AlertOutputPlugin`（`src/alerts/base.py`）：`send(self, reporter, subject, *, lang="en") -> dict`；子類設 `name` ClassVar 即自動進 `_OUTPUT_REGISTRY`。
- `TelegramAlertPlugin`（`src/alerts/plugins.py:192`）與 `WebhookAlertPlugin`（`:156`）的 `send` 形狀：
  - 從 `self.cm.config.get("alerts", {})` 讀設定；缺設定回 `{"channel": ..., "status": "skipped", "target": "", "error": "missing configuration"}`。
  - 以 `urllib.request.Request(url, data=..., headers=..., method="POST")` + `urlopen(req, timeout=10)` 送出。
  - 成功回 `{"channel", "status": "success", "target"}`；失敗（HTTPError / URLError / TimeoutError / Exception）回 `status="failed"` 並帶 `error`。
- payload builder 在 `Reporter`：`_build_webhook_payload(subj)`（`src/reporter.py:342`）以 `render_alert_template("webhook_payload.json.tmpl", ...)` 組 JSON dict；`_build_telegram_message`（`:927`）以 `render_alert_template("telegram_digest.html.tmpl", ...)` 並對每個動態值 `html.escape`。
- registry 分派：`send_alerts` 取 `alerts_config.get("active", ["mail"])`，去重成 `ordered_channels`，對每個 channel `get_output_registry()` 查表，未註冊則 log `"Configured alert channel has no registered plugin"` 並補 `status="failed"`（`src/reporter.py:764` 附近）。
- metadata：`PLUGIN_METADATA: dict[str, PluginMeta]`（`src/alerts/metadata.py:67`），`PluginMeta(name, display_name, description, fields={...}, display_name_key, description_key)`，`FieldMeta(label, required, secret, placeholder, label_key, ...)`。`/api/alert-plugins` 直接序列化此結構（`tests/test_gui_alert_plugins.py`）。
- config schema：`AlertsSettings`（`src/config_models.py:63`）以 pydantic 定義 `active` / `line_*` / `webhook_url` / `telegram_*`；`webhook_url` 有 `_require_https` validator（`field_validator("webhook_url", mode="after")`）。`_DEFAULT_CONFIG["alerts"]`（`src/config.py:51`）為記憶體預設。
- CLI：`alert_settings_menu`（`src/cli/menus/alert.py`）為數字選單，toggle `mail`/`line`/`webhook` 與編輯欄位。
- i18n：`alert_plugin_*`（plugin 顯示名/描述/欄位 label）、`<channel>_alert_sent` / `<channel>_alert_failed` / `<channel>_config_missing` 三組 runtime 訊息；EN（`src/i18n_en.json`）與 ZH_TW（`src/i18n_zh_TW.json`）雙檔；glossary preserve-list（`src/i18n/data/glossary.json`）。
- **安全（README L-12）**：Telegram token 因放在 URL path 而曾經由 forward proxy access log 外洩；loguru 設有 token regex scrubber，但無法保護中間網路設備。**教訓**：channel 的 secret（此處為 Teams workflow webhook URL）**不得寫入任何 log / debug 輸出**，必須遮罩。

## 3. 新增：`TeamsAlertPlugin`

### 3.1 介面（鏡射 `WebhookAlertPlugin`）

新增於 `src/alerts/plugins.py`（接在 `TelegramAlertPlugin` 之後）：

```python
class TeamsAlertPlugin(AlertOutputPlugin):
    name = "teams"

    def send(self, reporter, subject, *, lang="en") -> dict:
        ...
```

- 設定讀取：`webhook_url = self.cm.config.get("alerts", {}).get("teams_webhook_url", "")`。
- 缺設定：印 `t("teams_config_missing", lang=lang)`，回 `{"channel": "teams", "status": "skipped", "target": "", "error": "missing configuration"}`。
- payload：`card = reporter._build_teams_card(subject)`（dict）→ `data = json.dumps(card).encode("utf-8")`，`headers = {"Content-Type": "application/json"}`。
- 送出：`urllib.request.Request(webhook_url, data=data, headers=headers, method="POST")` + `urlopen(req, timeout=10)`。
- 成功狀態碼：Power Automate Workflow webhook 對成功回 `200`、`201`、`202`（與既有 webhook plugin 接受 `[200, 201, 202, 204]` 一致；沿用該集合）。
- 回傳形狀與 `WebhookAlertPlugin` 完全一致（`success` / `failed` + `error`）。

### 3.2 Secret redaction（README L-12 落地）

Teams workflow webhook URL 內含可直接投遞訊息的祕密 token（`.../triggers/.../paths/invoke?...&sig=<SECRET>`）。因此：

- **`target` 欄位不得放完整 URL。** 與 webhook/telegram 不同（它們把完整 URL/chat_id 當 target），Teams plugin 的 `target` 一律回 **遮罩後字串**：`_redact_teams_url(webhook_url)`。
- **任何 error / log 輸出不得含完整 URL。** `HTTPError` 的 `error_body` 可保留（不含我方 secret），但凡需呈現 endpoint 之處一律用遮罩值。
- 提供模組級純函式 `redact_webhook_url(url: str) -> str`（放 `src/alerts/plugins.py` 或 `src/utils.py`；本 spec 選 `plugins.py` 就近）：保留 scheme + host，路徑與 query 以 `…` 取代，例如 `https://prod-12.westus.logic.azure.com/…`。空字串回空字串。

> 此遮罩是 L-12 教訓的延伸：Telegram 把 secret 放 URL path、Teams 把 secret 放 query string（`sig=`），兩者都不可入 log。dispatch 結果（`persist_dispatch_results`）會落地 `target`，故 `target` 必須是遮罩值。

### 3.3 邊界

- 不做 cooldown / 連續失敗計數（那是 `line` 專屬）。
- 不重試（與 webhook/telegram 一致，單次 `timeout=10`）。
- card 大小不主動截斷（Teams Adaptive Card 限制寬鬆；沿用 webhook builder 的「全量」語意，與 telegram 的 3500 字截斷不同）。

## 4. 新增：`Reporter._build_teams_card`

### 4.1 介面

新增於 `src/reporter.py`（接在 `_build_webhook_payload` 之後，鏡射其結構）：

```python
def _build_teams_card(self, subj: str) -> dict:
    """Build an Adaptive Card (v1.4) payload for Teams Power Automate Workflows.

    Returns the full POST body dict: an `attachments` array carrying one
    Adaptive Card. Pure data assembly (no I/O); HTML is NOT used — Adaptive
    Card uses TextBlock elements, so every dynamic value is inserted as plain
    text (no escaping pitfalls, but values are still str()-coerced).
    """
```

### 4.2 Card 結構（Power Automate Workflows 期望的外層）

Power Automate「當收到 Teams webhook 請求時 → 張貼卡片」範本期望的 body 為 `attachments` 陣列，每個 attachment 的 `contentType` 為 `application/vnd.microsoft.card.adaptive`，`content` 為 Adaptive Card：

```json
{
  "type": "message",
  "attachments": [
    {
      "contentType": "application/vnd.microsoft.card.adaptive",
      "content": { "...adaptive card..." }
    }
  ]
}
```

Adaptive Card `content`（`$schema` v1.4、`version` "1.4"）以 template 渲染，欄位鏡射 `webhook_payload.json.tmpl`：title（subject）、generated_at、四類計數（health/event/traffic/metric）、各類前幾筆摘要（FactSet）、一個 `Action.OpenUrl`「Open in PCE」（取 `self.cm.config.get("gui_base_url", "")`，空則略過 actions）。

### 4.3 Template

新增 `src/alerts/templates/teams_card.json.tmpl`，以 `string.Template` `$placeholder` 風格（與既有 `webhook_payload.json.tmpl` 一致），由 `render_alert_template` 渲染後 `json.loads` 成 dict。動態值以 `*_json`（已 `json.dumps` 的 token，鏡射 webhook builder 對 `$subject_json` 的做法）注入，確保產出為合法 JSON。`alert_tpl_*` 標題類字串由 `render_alert_template` 自動注入 i18n（template_utils 的 `_ALERT_TPL_KEY_RE` 機制）。

> 設計取捨：teams card 的 title 沿用 `alert_tpl_telegram_title`（"Illumio Monitor Alerts" / "Illumio 監控警示"）以重用既有 i18n，避免新增重複字串；若日後需區分再拆 key（YAGNI）。

## 5. Config 與 schema

### 5.1 欄位

新增單一設定鍵 `alerts.teams_webhook_url`（字串，空=停用）。啟用以 `alerts.active` 含 `"teams"` 表示（與其他 channel 一致，**不**新增獨立 `enabled` 旗標——既有架構用 `active` 清單當啟用開關）。

### 5.2 pydantic（`AlertsSettings`，`src/config_models.py`）

新增 `teams_webhook_url: str = ""`，並加 `field_validator("teams_webhook_url", mode="after")` 強制 `https://`（鏡射既有 `_require_https`；Teams workflow URL 必為 https，且 https 是 L-12 之外的最低傳輸保護）。空字串放行（停用）。

### 5.3 預設（`_DEFAULT_CONFIG["alerts"]`，`src/config.py`）

`"teams_webhook_url": ""` 加入預設 alerts 區塊。

## 6. metadata（`PLUGIN_METADATA`，`src/alerts/metadata.py`）

新增 `"teams"` 條目，鏡射 `"webhook"`：

```python
"teams": PluginMeta(
    name="teams",
    display_name="Microsoft Teams",
    display_name_key="alert_plugin_teams_display_name",
    description="Post an Adaptive Card to a Teams channel via a Power Automate Workflow webhook.",
    description_key="alert_plugin_teams_description",
    fields={
        "alerts.teams_webhook_url": FieldMeta(
            label="Workflow Webhook URL",
            label_key="alert_plugin_field_teams_webhook_url",
            required=True, secret=True,
            placeholder="https://prod-XX.logic.azure.com:443/workflows/.../triggers/manual/paths/invoke?...",
        ),
    },
),
```

`secret=True` 確保 `/api/alert-plugins` 將欄位標為祕密、GUI 遮罩輸入（與 telegram token 一致）。

## 7. CLI（`src/cli/menus/alert.py`）

鏡射 webhook 的兩處：在 `active` toggle 與「編輯 URL」加入 Teams。沿用既有遮罩慣例（`current[:5] + "..."`）顯示既有值的 hint——**永不印完整 URL**。新增對應 i18n key（`toggle_teams_alert`、`edit_teams_webhook_url`、`teams_webhook_url_input`）。選單編號順移。

## 8. i18n

EN（`src/i18n_en.json`）與 ZH_TW（`src/i18n_zh_TW.json`）雙檔同步新增：

- plugin metadata：`alert_plugin_teams_display_name`、`alert_plugin_teams_description`、`alert_plugin_field_teams_webhook_url`。
- runtime：`teams_alert_sent`、`teams_alert_failed`（帶 `{status}`/`{error}`）、`teams_config_missing`。
- CLI：`toggle_teams_alert`（帶 `{status}`）、`edit_teams_webhook_url`、`teams_webhook_url_input`。

遵守 glossary preserve-list（"Microsoft Teams"、"Adaptive Card"、"Workflow" 在 ZH_TW 保留英文；"PCE" 已在 preserve list）。新增後跑 `python scripts/audit_i18n_usage.py` 驗 parity。

## 9. 測試

- **plugin 行為**（鏡射 `tests/test_alerts_telegram.py` 的 mock `urllib.request.urlopen`）：
  - 已註冊（`"teams" in get_output_registry()`）。
  - 缺設定回 `skipped` + `missing configuration`。
  - 成功（mock 200/202）回 `success`，**`target` 為遮罩值且不含完整 URL / sig**。
  - 4xx（HTTPError）/ URLError 回 `failed` 並帶 error。
  - 送出 request：`req.full_url` 等於設定的 webhook URL、body 為含 `attachments[0].contentType == "application/vnd.microsoft.card.adaptive"` 的合法 JSON。
- **secret redaction**（L-12 落地，獨立測試）：`redact_webhook_url("https://x.logic.azure.com/workflows/AAA/triggers/manual/paths/invoke?sig=SECRET")` 不含 `"SECRET"`、不含 `"sig="`、不含完整路徑；保留 host。成功與失敗回傳的 `target`/`error` 皆不含 `"SECRET"`。
- **card builder**：`_build_teams_card(subj)` 回 dict，`attachments[0].content.type == "AdaptiveCard"`，version "1.4"，含 subject 與至少一筆 health alert 摘要；無 `gui_base_url` 時不含 actions。
- **schema**：`AlertsSettings(teams_webhook_url="https://...")` 通過；`http://` 被拒（match "https"）；空字串放行；預設 `AlertsSettings().teams_webhook_url == ""`。
- **routing**：`send_alerts` 對 `active=["teams"]` 經 `TeamsAlertPlugin` 分派（鏡射 telegram routing 測試）。
- **metadata / GUI**：`/api/alert-plugins` 回的 `plugins["teams"]` display_name 與欄位 `secret is True`、`required is True`（鏡射 telegram metadata 測試）。
- **i18n parity**：新 key EN/ZH_TW 齊備且通過 audit。

## 10. 風險與緩解

- *風險*：Teams workflow webhook URL（含 `sig=` secret）入 log/`target` 造成 L-12 重演 → *緩解*：`target` 與所有輸出一律走 `redact_webhook_url`；獨立 redaction 測試把關。
- *風險*：Power Automate 期望的外層格式（`attachments` vs 純 card）誤判導致 400 → *緩解*：以 `type: "message"` + `attachments[].contentType` 標準外層；測試斷言 body 結構。
- *風險*：誤用淘汰中的 MessageCard 格式 → *緩解*：spec 鎖定 Adaptive Card v1.4；template 與測試皆以 `AdaptiveCard` type 斷言。
- *風險*：新 channel 破壞既有 registry/dispatch → *緩解*：純新增 `name="teams"` 子類，零改既有 plugin；routing 測試覆蓋。

## 11. 後續（不在本 spec）

- Teams Adaptive Card 的 `Action.Submit` 雙向互動（ack/snooze）。
- mention / 嚴重度色票（`Container.style`）細化。
- P2–P3、P5：Policy Diff、Policy Resolver、AI 輔助規則建議（各自獨立 spec）。
