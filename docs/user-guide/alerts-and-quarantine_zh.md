---
title: Alerts and Quarantine
audience: [operator]
last_verified: 2026-05-15
verified_against:
  - src/alerts/
  - src/alerts/templates/
  - src/events/matcher.py
  - src/events/throttle.py
  - src/config.py
  - src/gui/routes/actions.py
  - src/static/js/quarantine.js
  - python illumio-ops.py rule --help
  - commit 58103c4
related_docs:
  - dashboard.md
  - siem-integration.md
  - rule-scheduler.md
  - ../architecture/i18n-contract.md
---

> 🌐 [English](alerts-and-quarantine.md) | **[繁體中文](alerts-and-quarantine_zh.md)**
> 📍 [INDEX](../INDEX.md) › 使用者指引 › 警示與隔離
> 🔍 最後驗證 **2026-05-15** 對 commit `58103c4` — 詳見 frontmatter

# 警示與隔離

---

## 警示類型

規則依 `config/alerts.json` 中的 `"type"` 欄位分為兩大類。

### 事件規則（`"type": "event"`）

每列將 `name_key` 對應到所監控的 PCE 事件類型。

| `name_key` | 顯示名稱 | PCE 事件模式 |
|---|---|---|
| `rule_agent_tampering` | 偵測到 Agent 竄改 | `agent.tampering` |
| `rule_agent_suspend` | Agent 已暫停 | `agent.suspend` |
| `rule_agent_clone` | 偵測到 Agent 複製 | `agent.clone_detected` |
| `rule_agent_heartbeat` | Agent 遺失心跳 | `system_task.agent_missed_heartbeats_check` |
| `rule_agent_offline` | Agent 標記為離線 | `system_task.agent_offline_check` |
| `rule_lost_agent` | 遺失 Agent 已找回 | `lost_agent.found` |
| `rule_login_failed` | 登入失敗 | `user.sign_in,user.login`（status=failure） |
| `rule_api_auth_failed` | API 驗證失敗 | `request.authentication_failed` |
| `rule_api_authz_failed` | API 授權失敗 | `request.authorization_failed` |
| `rule_api_key_change` | API 金鑰建立／刪除 | `api_key.create,api_key.delete` |
| `rule_policy_fail` | 政策更新失敗 | `agent.refresh_policy`（status=failure） |
| `rule_ruleset_change` | 規則集已變更 | `rule_set.create,rule_set.update,rule_set.delete` |
| `rule_policy_provision` | 安全政策已佈建 | `sec_policy.create` |
| `rule_sec_rule_change` | 安全規則已變更 | `sec_rule.create,sec_rule.update,sec_rule.delete` |
| `rule_bulk_unpair` | 大量工作負載取消配對 | `workloads.unpair,agents.unpair` |
| `rule_auth_settings_change` | 驗證設定已變更 | `authentication_settings.update` |

### 流量規則（`"type": "traffic"`）

| `name_key` | 顯示名稱 | 觸發條件 |
|---|---|---|
| `rule_high_blocked` | 大量封鎖流量 | 10 分鐘內 ≥ 25 筆封鎖流量 |

> [!TODO] @harry: 確認 `rule_pce_health`（`"type": "system"`）是否出現在預設安裝的
> `alerts.json` 中，或僅可透過自訂新增 — `src/config.py` 在 i18n 中有定義，但未列在
> `_best_practice_rules` 中。

---

## 設定警示規則

### 透過 Web UI（設定 → 警示）

1. 前往 **設定 › 警示**（或深層連結 `?stab=alerts`）。
2. 每張規則卡顯示其名稱、觸發條件及目前的節流設定。
3. 使用 **編輯**（鉛筆圖示）變更閾值、冷卻時間、節流或篩選欄位。
4. 點擊 **載入最佳實踐** 可從 `src/config.py:_best_practice_rules()` 附加或取代規則。
   模式下拉選單提供：
   - `append_missing` — 僅新增尚未存在的規則（預設）。
   - `replace` — 以標準規則集完整取代目前所有規則。

### 直接編輯 `config/alerts.json`

守護程序將規則儲存於 `config/alerts.json`（非 `config.json`）。
檔案以原子方式寫入，權限為 `0o600`。

最小事件規則範例：

```json
{
  "rules": [
    {
      "id": 1,
      "type": "event",
      "name_key": "rule_agent_tampering",
      "filter_key": "event_type",
      "filter_value": "agent.tampering",
      "filter_status": "all",
      "filter_severity": "all",
      "threshold_type": "immediate",
      "threshold_count": 1,
      "threshold_window": 10,
      "cooldown_minutes": 30,
      "throttle": ""
    }
  ]
}
```

主要欄位說明：

| 欄位 | 說明 |
|---|---|
| `name_key` | i18n 鍵；顯示名稱在載入時透過 `_resolve_rule_keys()` 解析 |
| `filter_value` | 逗號分隔的 PCE 事件類型；支援正則表達式及管道（`\|`）交替 |
| `filter_status` | `"all"`、`"success"`、`"failure"`，或否定前綴 `"!"` |
| `filter_severity` | `"all"`、`"err"`、`"warning"`、`"info"` 等 |
| `threshold_type` | `"immediate"`（第一個符合即觸發）或 `"count"`（時間窗內 N 個事件） |
| `throttle` | 速率限制格式 `"N/Tm"`，例如 `"1/15m"` = 每 15 分鐘至多觸發一次 |
| `match_fields` | 可選的巢狀 PCE 事件欄位路徑 → 比對模式字典 |

### 透過 CLI

```bash
# 列出所有已設定的規則（1 為基底索引）
python3 illumio-ops.py rule list

# 互動式編輯索引 3 的規則
python3 illumio-ops.py rule edit 3
```

---

## 通知通道

Illumio PCE Ops 內建三個輸出插件。所有插件可在 **設定 › 警示**（子分頁 **通道**）
或直接在 `config.json`（非 `alerts.json`）中設定。

### 電子郵件（SMTP）— 插件 `mail`

使用 `src/alerts/templates/mail_wrapper.html.tmpl` 範本傳送 HTML 電子郵件。

必填欄位：`sender`、`recipients`（逗號分隔）、`smtp.host`、`smtp.port`。
選填：`smtp.user`、`smtp.password`、`smtp.enable_tls`（STARTTLS）、`smtp.enable_auth`。

從 UI 測試：**設定 › 警示 › 測試** 按鈕，或：
```bash
# POST 至 test-alert 端點（需 Web GUI 正在執行）
curl -s -X POST http://localhost:8443/api/actions/test-alert \
  -H 'Content-Type: application/json' \
  -d '{"channel": "mail"}'
```

### LINE Messaging API — 插件 `line`

使用 `src/alerts/templates/line_digest.txt.tmpl` 範本傳送精簡文字摘要。

必填欄位：`alerts.line_channel_access_token`、`alerts.line_target_id`
（以 `U` 開頭的使用者 ID、房間 ID 或群組 ID）。

### Webhook — 插件 `webhook`

將 `src/alerts/templates/webhook_payload.json.tmpl` 渲染的 JSON 以 POST 方式傳送至任何 HTTP 端點。
預期回應 2xx；非 2xx 記錄為失敗。

必填欄位：`alerts.webhook_url`。

> [!TODO] @harry: 確認是否存在獨立於 webhook 插件的 SIEM 轉發插件，
> 或 SIEM 轉發是否由 `illumio-ops.py siem` 負責（`siem` CLI 子命令存在
> 但未連接至警示插件登錄檔）。請參閱 [SIEM 整合](siem-integration.md)。

---

## 隔離工作流程

隔離會將 PCE 標籤（`key=Quarantine`，值為 `Mild` / `Moderate` / `Severe`）套用至一個或多個工作負載。
標籤在首次使用時透過 `/api/init_quarantine` 自動建立。

僅工作負載物件（受管理及非受管理）可接收隔離標籤。
容器工作負載設定檔及其他資源類型不受支援。

### 手動隔離（單一工作負載）

1. 在 **隔離** 分頁或工作負載搜尋中找到目標工作負載。
2. 點擊嚴重程度按鈕：**輕度**、**中度** 或 **嚴重**。
3. 在對話框中確認 — UI 呼叫 `POST /api/quarantine/apply`，傳送 `{ href, level }`。
4. 後端透過 `check_and_create_quarantine_labels()` 取得目標標籤 href，
   移除現有的 Quarantine 標籤，並透過 PCE API 附加新標籤。

### 批次隔離

1. 透過核取方塊選取多個工作負載。
2. 選擇嚴重程度並確認 — UI 呼叫 `POST /api/quarantine/bulk_apply`，
   傳送 `{ hrefs: [...], level }`。後端使用並行 PCE 更新提升吞吐量。

### 移除隔離

重新套用不同嚴重程度，或直接在 PCE 中編輯工作負載標籤以移除 `Quarantine` 標籤。

### 自動隔離

> [!TODO] @harry: 在 commit `58103c4` 的 `src/gui/routes/actions.py` 或
> `src/config.py` 中，未找到警示規則觸發自動標籤套用的實作。若此功能存在，
> 可能位於尚未合併的分支中。請在記錄前先行確認。

---

## 加速工作負載按鈕

**加速**（Accelerate）按鈕出現在隔離分頁的每列工作負載及批次操作列中。
截至 commit `58103c4`，此功能已完整實作。

**功能說明：** 呼叫 `POST /api/workloads/accelerate`，傳送 `{ hrefs, duration_minutes }`。
後端呼叫 `api.set_flow_reporting_frequency(hrefs)` 至 PCE，暫時提高工作負載的流量遙測更新頻率。

**架構說明（摘自 `actions.py` 說明文字）：**
> 後端無狀態：每次請求僅發出一次 PCE 呼叫。持續模式（每 10 分鐘重新發出）
> 由前端透過 `setInterval` 處理。無效的 href 會被捨棄並計入 `skipped_invalid`。

**僅限受管理工作負載。** 非受管理工作負載的列按鈕會停用（灰色），
並顯示提示 `gui_accel_unmanaged_tip`。批次加速會跳過非工作負載 href。

**典型使用場景：** 在調查事件時，對可疑工作負載啟用加速，以提高對其即時流量的可見度，
同時不修改強制執行政策。

---

## 舊版規則遷移

較舊的 `alerts.json` 可能包含缺少 `name_key` / `desc_key` / `rec_key` 欄位的規則
（由工具的早期版本寫入）。

`src/config.py:_resolve_rule_keys()` 在每次 `load()` 呼叫時執行，自動處理三種情況：

1. **基於鍵的規則**（含 `name_key`）：在載入時透過 `t(key, lang=lang)` 解析。
   渲染後的文字在儲存前由 `_write_alerts_file()` 移除 — 磁碟上僅儲存鍵。

2. **`[MISSING:key]` 標記**：由 `apply_best_practices()` 在 i18n 鍵缺失時寫入。
   下次載入時，若鍵已存在於翻譯檔中，標記會被取代，並回填 `name_key`
   以便後續儲存時持久化。

3. **純舊版字面名稱**：若儲存的 `name` / `desc` / `rec` 符合已知最佳實踐鍵
   的標準英文或繁體中文翻譯（透過 `_LEGACY_FILTER_TO_NAME_KEY`），
   規則會被提升為基於鍵的儲存。不符合任何標準翻譯的使用者自訂名稱保持不變。

**`_LEGACY_FILTER_TO_NAME_KEY` 對應表**（來源：`src/config.py` 第 202–219 行）：

```json
{
  "agent.tampering":                              "rule_agent_tampering",
  "user.sign_in,user.login":                     "rule_login_failed",
  "lost_agent.found":                            "rule_lost_agent",
  "system_task.agent_missed_heartbeats_check":   "rule_agent_heartbeat",
  "system_task.agent_offline_check":             "rule_agent_offline",
  "agent.suspend":                               "rule_agent_suspend",
  "agent.clone_detected":                        "rule_agent_clone",
  "request.authentication_failed":               "rule_api_auth_failed",
  "agent.refresh_policy":                        "rule_policy_fail",
  "rule_set.create,rule_set.update,rule_set.delete": "rule_ruleset_change",
  "sec_policy.create":                           "rule_policy_provision",
  "request.authorization_failed":               "rule_api_authz_failed",
  "api_key.create,api_key.delete":              "rule_api_key_change",
  "sec_rule.create,sec_rule.update,sec_rule.delete": "rule_sec_rule_change",
  "workloads.unpair,agents.unpair":             "rule_bulk_unpair",
  "authentication_settings.update":             "rule_auth_settings_change"
}
```

無需手動遷移步驟 — 提升會在下次載入／儲存週期中靜默完成。

---

## i18n 行為

警示標籤會在語言切換時重新渲染。機制遵循
[i18n 契約](../architecture/i18n-contract.md)：

- **載入時**：`_resolve_rule_keys()` 對每條含 `name_key` 的規則呼叫
  `t(name_key, lang=lang)`，在記憶體中填入 `name` / `desc` / `rec` 欄位。
- **儲存時**：`_write_alerts_file()` 從含有 `*_key` 對應的規則中移除渲染後的
  `name` / `desc` / `rec` 欄位，因此磁碟上的檔案始終儲存鍵，而非特定語言的字串。
- **渲染時**：Web GUI 在語言切換後重新取得 `/api/status`（其中包含規則標籤）。
  插件顯示名稱透過 `src/alerts/metadata.py` 中 `PluginMeta` 物件的
  `resolved_display_name(lang=lang)` 解析。
- **語言範圍**：`lang` 在載入時取自 `config.settings.language`；GUI 使用
  `window._uiLang`（透過快照回應從相同設定欄位解析）。

---

## 相關文件

- [儀表板](dashboard.md) — 顯示警示狀態的 KPI
- [SIEM 整合](siem-integration.md) — 將警示轉發至外部系統
- [規則排程器](rule-scheduler.md) — 由警示驅動的臨時規則
- [i18n 契約](../architecture/i18n-contract.md) — 警示標籤如何隨語言切換保持同步
