# SaaS PCE 監控與事件連結實作計畫

> 執行分支：`feat/saas-pce-monitoring-links`。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 illumio-ops 明確區分 SaaS／on-prem PCE，以原廠支援的端點判斷健康，並讓所有告警事件連結使用獨立且正確的 PCE Console URL。

**Architecture:** 新增 `api.deployment_type` 與 `api.console_url` 作為單一設定契約；所有部署先以 authenticated `/noop` 驗證 API access，只有 on-prem 再執行 `/health` 與 `/node_available`。事件連結透過共用 resolver 從 Console URL 組合，不再由 API hostname 猜測。既有 ingestion watermark／lag 作為資料面 freshness 訊號，官方 SaaS status page 只做人工事故關聯。

**Tech Stack:** Python 3.12、Pydantic v2、Flask、Click、pytest、原生 ES modules、Playwright

**Spec:** `docs/superpowers/specs/2026-08-29-saas-pce-monitoring-and-event-links-design.md`

## 已確認的現況與交付邊界

- `src/api_client.py::check_health()` 固定呼叫 `/api/v2/health`；`Analyzer._run_health_check()` 通過後固定探 `/node_available`。這是 on-prem 契約，不適用 SaaS。
- 官方把 `/noop` 定義為 connectivity 與新 API credentials 驗證端點；本案以它作所有部署的共同基線。
- `src/reporter.py::_console_base()` 只認 `*.illumio.com` 且 hostname 含 `scp`；實際 SaaS API hostname 不一定符合這個啟發式。
- 現有 `tests/test_event_console_link_saas.py` 的四個案例全綠，但只測虛構的 `*.illumio.com` host；它沒有覆蓋真實 URL 格式。
- 所有 event renderer 已共同消費 `_build_vendor_event_payloads()` 產生的 `pce_link`，因此只需修共同 resolver，不在 LINE／Telegram／email 各寫一份規則。
- 原 production PCE credential item 對 `/noop` 與 `/events` 都回 401；這證明 target 有回應，但該 credentials 當時不能完成 authenticated live acceptance。不得把它誤報成 SaaS 平台死亡，也不得用它宣稱 deep link 已真機驗證。

```text
設定責任

api.url             ──> REST API
api.deployment_type ──> health probe policy
api.console_url     ──> PCE Console / event link
web_gui.public_url  ──> illumio-ops dashboard CTA
```

## Global Constraints

- 使用 `venv/bin/python` 與 `venv/bin/pytest`；目前 venv 是 Python 3.12.3。
- 每個 task 都先寫會失敗的測試，再做最小實作使其通過；新增守門需做一次突變驗證（故意還原 bug → 紅，恢復修正 → 綠）。
- 所有使用者可見文案只能用 i18n key；新 key 同時加入 `src/i18n_en.json`、`src/i18n_zh_TW.json`，必要時同步 `src/i18n/data/zh_explicit.json`。
- 不把 API key、secret、完整 exception 或原始敏感 response body 寫入 log、測試 fixture、文件或 commit。
- 不根據 hostname 推測 SaaS；`deployment_type` 是唯一判準，`console_url` 是 Console host 的唯一判準。
- `deployment_type`／`console_url` 改變不觸發 PCE cache flush；`url`／`org_id` 的既有 re-point guard 不變。
- 不 scrape `status.illumio.com`，不讓外部 status page 的可達性影響 watchdog。
- 不改與本案無關的 `web_gui.public_url` CTA 行為；只把它的責任在 schema／文件中說清楚。
- 歷史 plans/specs 與既有 CHANGELOG 條目不動。
- 每個 checkpoint 只 `git add` 明確路徑，永不 `git add -A`；提交訊息用英文 conventional commits。
- 完整驗證必須涵蓋 `.github/workflows/ci.yml` 的所有 hard gates：pip-audit（online lock）、naive datetime lint、doc link check、i18n audit、mypy strict subset、完整 pytest，以及 Python 3.12 的 offline lock pip-audit。Playwright Chromium 必須已安裝，不能用 skip 偽裝通過。

---

### Task 1: 建立 deployment 與 Console URL 的設定契約

**Files:**
- Modify: `src/config_models.py` (`ApiSettings`, `WebGuiSettings`)
- Modify: `src/config.py` (`_DEFAULT_CONFIG`)
- Modify: `src/pce_target.py`
- Modify: `config/config.json.example`
- Modify: `tests/test_config_models.py`
- Modify: `tests/test_config_backwards_compat.py`
- Modify: `tests/test_pce_target_cli.py`

**Interfaces:**
- Produces: `ApiSettings.deployment_type: Literal["saas", "on_prem"]`
- Produces: `ApiSettings.console_url: str`
- Produces: `resolve_pce_console_url(api_cfg: Mapping[str, object]) -> str`
- Produces: `pce_deployment_type(api_cfg: Mapping[str, object]) -> Literal["saas", "on_prem"]`
- Consumes: 既有 `normalize_pce_url()` 與 `pce_target_changed()`

- [ ] **Step 1: 在既有測試檔加入失敗案例**

`tests/test_config_models.py` 加入：合法的兩種 deployment、未知值拒絕、空與合法
`console_url`、非 HTTP(S) Console URL 拒絕；`test_config_example_file_validates` 必須繼續通過。

```python
def test_api_settings_supports_explicit_deployment_and_console_url():
    cfg = ApiSettings(
        deployment_type="saas",
        url="https://saas-api.example.invalid",
        console_url="https://console.illum.io/",
    )
    assert cfg.deployment_type == "saas"
    assert cfg.console_url == "https://console.illum.io"


def test_api_settings_rejects_unknown_deployment_type():
    with pytest.raises(ValidationError, match="deployment_type"):
        ApiSettings(deployment_type="cloud")
```

`tests/test_config_backwards_compat.py` 加入 legacy config 缺少兩欄仍載入為
`deployment_type == "on_prem"` 與 `console_url == ""`。

`tests/test_pce_target_cli.py` 加入 resolver matrix：

```python
@pytest.mark.parametrize(("api_cfg", "expected"), [
    ({"deployment_type": "saas", "url": "https://saas-api.example.invalid", "console_url": ""},
     "https://console.illum.io"),
    ({"deployment_type": "saas", "url": "https://custom-api.example.invalid:443",
      "console_url": "https://acme.illumio.ai/"}, "https://acme.illumio.ai"),
    ({"deployment_type": "on_prem", "url": "https://pce.lab:8443/api/v2", "console_url": ""},
     "https://pce.lab:8443"),
])
def test_resolve_pce_console_url(api_cfg, expected):
    assert resolve_pce_console_url(api_cfg) == expected
```

另斷言只改 `deployment_type`／`console_url` 不會讓 `pce_target_changed()` 回 true。

- [ ] **Step 2: 跑 RED**

```bash
timeout 120 venv/bin/pytest tests/test_config_models.py tests/test_config_backwards_compat.py tests/test_pce_target_cli.py -q
```

預期：新增案例因欄位與 resolver 尚不存在而紅；既有案例維持綠。

- [ ] **Step 3: 實作最小 schema 與 resolver**

`ApiSettings` 新增：

```python
deployment_type: Literal["saas", "on_prem"] = "on_prem"
console_url: str = ""
```

`console_url` 非空時沿用 `HttpUrl` 驗證並去尾斜線。`WebGuiSettings` 正式宣告
`public_url: str = ""`，讓現有行為不再只靠 `extra="allow"` 偶然存活；其 validator
同樣只接受空值或 HTTP(S)。

`src/pce_target.py` 新增常數與純函式：

```python
DEFAULT_SAAS_CONSOLE_URL = "https://console.illum.io"

def pce_deployment_type(api_cfg) -> str:
    return str(api_cfg.get("deployment_type") or "on_prem")

def resolve_pce_console_url(api_cfg) -> str:
    explicit = normalize_pce_url(api_cfg.get("console_url", ""))
    if explicit:
        return explicit
    if pce_deployment_type(api_cfg) == "saas":
        return DEFAULT_SAAS_CONSOLE_URL
    base = normalize_pce_url(api_cfg.get("url", ""))
    for suffix in ("/api/v2", "/api/v1", "/api"):
        if base.endswith(suffix):
            return base[:-len(suffix)]
    return base
```

不要加入任何 `illum.io`／`illumio.com` suffix 判斷。

- [ ] **Step 4: 同步 default 與安裝範本**

`_DEFAULT_CONFIG.api` 加入兩欄；`config/config.json.example` 把部署型態寫成明示欄位，
並用註解無法存在於 JSON 的限制，改由相鄰文件說明可選值，不往 JSON 塞偽註解。

- [ ] **Step 5: 跑 GREEN 並做突變驗證**

```bash
timeout 120 venv/bin/pytest tests/test_config_models.py tests/test_config_backwards_compat.py tests/test_pce_target_cli.py -q
```

暫時把 SaaS fallback 改回 API URL，確認 resolver matrix 變紅；還原後再跑到綠。

- [ ] **Step 6: Commit checkpoint**

```bash
git add src/config_models.py src/config.py src/pce_target.py config/config.json.example tests/test_config_models.py tests/test_config_backwards_compat.py tests/test_pce_target_cli.py
git commit -m "feat(config): separate PCE deployment and console URL"
```

---

### Task 2: 新增共同 `/noop` connectivity probe 與狀態分類

**Files:**
- Modify: `src/api_client.py`
- Modify: `src/interfaces.py`
- Modify: `tests/test_api_client_request_contract.py`

**Interfaces:**
- Produces: `ApiClient.check_connectivity() -> tuple[int, str]`
- Produces: `pce_probe_category(status: int) -> str`
- Consumes: `ApiClient._request()` 的既有 timeout、TLS、Basic Auth 與 retry 行為

- [ ] **Step 1: 寫 endpoint 與分類失敗測試**

在 `tests/test_api_client_request_contract.py` 使用 fake session／`_request`，斷言
`check_connectivity()` 只呼叫 `<api.url>/api/v2/noop`，timeout 為 10 秒，不包含 org path，
且不在測試輸出印 credentials。

```python
@pytest.mark.parametrize(("status", "expected"), [
    (200, "ok"), (204, "ok"), (401, "auth_failed"),
    (403, "authorization_failed"), (429, "rate_limited"),
    (500, "server_error"), (0, "transport_error"), (404, "http_error"),
])
def test_pce_probe_category(status, expected):
    assert pce_probe_category(status) == expected
```

- [ ] **Step 2: 跑 RED**

```bash
timeout 120 venv/bin/pytest tests/test_api_client_request_contract.py -q
```

- [ ] **Step 3: 實作 `/noop` 與純分類函式**

```python
def pce_probe_category(status: int) -> str:
    if 200 <= status < 300:
        return "ok"
    return {
        0: "transport_error",
        401: "auth_failed",
        403: "authorization_failed",
        429: "rate_limited",
    }.get(status, "server_error" if 500 <= status < 600 else "http_error")
```

`check_connectivity()` 依 `check_health()` 的安全 decode 風格實作，但 log 名稱必須是
connectivity/noop，避免維運者以為 SaaS 回應包含 cluster health。

- [ ] **Step 4: 更新 Protocol 並跑 GREEN**

`IApiClient` 新增 `check_connectivity()`；既有 `check_health()`／
`check_node_available()` 保留，因為 Task 3 的 on-prem 分支仍需要。

```bash
timeout 120 venv/bin/pytest tests/test_api_client_request_contract.py tests/test_analyzer_with_mock_api.py -q
```

- [ ] **Step 5: 突變驗證與 commit**

暫把 endpoint 改成 `/health`，確認 URL 契約測試變紅；還原、重跑到綠。

```bash
git add src/api_client.py src/interfaces.py tests/test_api_client_request_contract.py
git commit -m "feat(api): add authenticated noop connectivity probe"
```

---

### Task 3: 讓 Analyzer 與所有連線檢查依 deployment 選擇 probe

**Files:**
- Modify: `src/analyzer.py`
- Modify: `src/gui/routes/actions.py`
- Modify: `src/gui/routes/filter_objects.py`
- Modify: `src/events/stats.py`
- Modify: `tests/test_health_body_parsing.py`
- Modify: `tests/test_gui_filter_suggest.py`
- Modify: `tests/test_gui_misc.py`

**Interfaces:**
- Consumes: Task 1 `pce_deployment_type()`
- Consumes: Task 2 `check_connectivity()` 與 `pce_probe_category()`
- Produces: `pce_stats.health_probe`、`pce_stats.deployment_type`、
  `pce_stats.health_category`、分類後的 health alert details

- [ ] **Step 1: 擴寫 health matrix 測試**

`tests/test_health_body_parsing.py` 增加：

1. SaaS `/noop` 2xx：記 success，`check_health` 與 `check_node_available` 都未呼叫。
2. SaaS 401：告警 details 指出 `auth_failed`，不是 `unreachable`。
3. SaaS 429：告警分類為 `rate_limited`。
4. on-prem `/noop` 成功後仍執行 `/health` body degraded 判讀與 `/node_available`。
5. `/noop` transport error：停止後續 probe 並累加 watchdog failure。

helper 建立 `ConfigManager` 後要明確設定 `cm.config["api"]["deployment_type"]`，避免測試
靠 default 猜分支。

- [ ] **Step 2: 釘住其他兩條連線檢查路徑**

`tests/test_gui_misc.py` 對 `/api/actions/test-connection` 加入 401 回應契約：

```python
assert body == {
    "ok": False,
    "reachable": True,
    "status": 401,
    "category": "auth_failed",
    "probe": "noop",
}
```

實作可以附安全、截斷的 `body` 欄位，但測試不得要求或回傳 secrets。另測 status 0 時
`reachable` 為 false。`tests/test_gui_filter_suggest.py` 改為 mock `check_connectivity()`，
確保 SaaS 不再間接打 `/health`。

- [ ] **Step 3: 跑 RED**

```bash
timeout 120 venv/bin/pytest tests/test_health_body_parsing.py tests/test_gui_filter_suggest.py tests/test_gui_misc.py -q
```

- [ ] **Step 4: 改 `_run_health_check()` 的順序**

最小流程：

```python
deployment = pce_deployment_type(self.cm.config.get("api", {}))
status, message = self.api.check_connectivity()
category = pce_probe_category(status)
if category != "ok":
    # 共用一次 record/alert path，details 由 i18n key 產生
elif deployment == "saas":
    # record_pce_success("health"), 不呼叫 on-prem-only endpoints
else:
    # 保留現有 /health body 判讀，成功後才 /node_available
```

抽出一個私有 helper 組合並派送 health alert，避免 401／429／on-prem degraded 各複製
一份 cooldown loop。不要重構其餘 Analyzer 流程。

規則模擬器 `src/analyzer.py` 的 `rtype == "system"` 分支也要走相同 deployment-aware
probe，否則正式監控正確、CLI 模擬仍會對 SaaS 打 `/health`。

- [ ] **Step 5: 更新測試連線與 filter suggest**

`/api/actions/test-connection` 一律用 `/noop`，回傳分類與 reachable；
`filter_objects.py` 的「PCE 不通 vs 真空集合」判斷也改用 `check_connectivity()`。
所有 client-visible 說明走新 i18n key。

- [ ] **Step 6: 擴充 stats，但不破壞 watchdog ownership**

`StatsTracker.record_pce_success/error` 接受可選的 `probe`、`deployment_type` 與
`category` metadata，成功時把 `health_category` 覆寫為 `ok`，失敗時保存分類；其餘只更新
dashboard-facing 欄位。不得改動既有 `consecutive_failures`、
`watchdog_last_alert_at` 與 cache-ingest co-ownership 規則。

- [ ] **Step 7: 跑 GREEN 與 watchdog regression**

```bash
timeout 180 venv/bin/pytest tests/test_health_body_parsing.py tests/test_gui_filter_suggest.py tests/test_gui_misc.py tests/test_watchdog_alert.py tests/test_watchdog_ingest_pipeline.py tests/test_watchdog_overflow_cache_cycle_merge.py -q
```

- [ ] **Step 8: 突變驗證與 commit**

暫時移除 SaaS early-return，確認「SaaS 不呼叫 on-prem probes」測試變紅；還原並綠。

```bash
git add src/analyzer.py src/gui/routes/actions.py src/gui/routes/filter_objects.py src/events/stats.py src/i18n_en.json src/i18n_zh_TW.json src/i18n/data/zh_explicit.json tests/test_health_body_parsing.py tests/test_gui_filter_suggest.py tests/test_gui_misc.py
git commit -m "fix(health): select supported probes by PCE deployment"
```

---

### Task 3A: 移除 SaaS events 查詢的 30 秒臨界點

**Files:**
- Modify: `src/api_client.py`
- Modify: `tests/test_api_client_request_contract.py`

**Interfaces:**
- Consumes: Task 1 `api.deployment_type`
- Produces: SaaS `fetch_events_strict()` request timeout 60 秒；legacy/on-prem 維持 30 秒

真機依據：production PCE credential item 的 `/noop` 204、org 200；events 最小查詢約 20.2 秒，產品實際
24h／10,000 筆查詢約 21.3 秒。舊版固定 30 秒只有約 9 秒餘裕，延遲尖峰會被 GET retry
包成 `Max retries exceeded`，且 watermark 不前進造成同一大視窗持續重試。

- [ ] **Step 1: 先寫 request-contract 失敗測試**

在 `tests/test_api_client_request_contract.py` 以 fake `_request`／session 釘住：

- `deployment_type="saas"` 的 `fetch_events_strict()` 傳 `timeout=60`。
- `deployment_type="on_prem"` 與缺欄位 legacy config 傳 `timeout=30`。
- URL、max_results、timestamp 與既有回傳解析行為不變。

- [ ] **Step 2: 跑 RED**

```bash
timeout 120 venv/bin/pytest tests/test_api_client_request_contract.py -q
```

預期：SaaS case 仍收到 30 秒而紅；on-prem／legacy 既有行為綠。

- [ ] **Step 3: 最小實作**

在 `ApiClient` 內用明示 `deployment_type` 選擇 events timeout；不要根據 hostname 判斷，
不要新增 GUI timeout 設定，也不要改全域 `_request()`／Retry policy。SaaS 只延長 events
read budget，timeout 後仍由既有 `last_fetch_error` 與 ingestion watermark fail-closed。

- [ ] **Step 4: GREEN、mutation 與 commit**

```bash
timeout 120 venv/bin/pytest tests/test_api_client_request_contract.py tests/test_pce_cache_ingestor_events.py tests/test_watchdog_ingest_pipeline.py -q
```

暫把 SaaS timeout 改回 30，確認新增 contract 紅；還原後重跑到綠。

```bash
git add src/api_client.py tests/test_api_client_request_contract.py
git commit -m "fix(events): allow SaaS event queries more time"
```

---

### Task 4: 將 deployment 與 Console URL 接到 GUI／CLI 設定面

**Files:**
- Modify: `src/gui/_helpers.py` (`_SETTINGS_ALLOWLISTS`)
- Modify: `src/gui/routes/config.py`
- Modify: `src/static/js/v2/areas/system.mjs`
- Modify: `src/cli/config.py`
- Modify: `src/cli/menus/_root.py`
- Modify: `src/i18n_en.json`
- Modify: `src/i18n_zh_TW.json`
- Modify: `src/i18n/data/zh_explicit.json`
- Modify: `tests/test_api_settings.py`
- Modify: `tests/test_cli_config_cmd.py`
- Modify: `tests/test_pce_target_cli.py`
- Modify: `tests/test_v2_system_e2e.py`

**Interfaces:**
- GUI payload: `api.deployment_type`, `api.console_url`
- CLI options: `config login --deployment-type [saas|on_prem] --console-url URL`
- Consumes: Task 1 schema／resolver；既有 `pce_target_change` 409 contract 不變

- [ ] **Step 1: 先寫 API allowlist 與 target guard 測試**

`tests/test_api_settings.py` 加入：兩欄可儲存並重新 load；非法 deployment／URL 回 400；
只改這兩欄不回 409、不 flush cache；GET settings 回傳非敏感值。

- [ ] **Step 2: 先寫 CLI 測試**

`tests/test_cli_config_cmd.py`／`tests/test_pce_target_cli.py` 加入：

- non-interactive 可設定兩欄；未知 deployment 由 Click 拒絕。
- 省略新 options 表示保留舊值，不用隱含值覆寫。
- 只改 deployment／Console URL 不要求 `--pce-target-change`，但
  `restart_required` 為 true 並顯示重啟提醒。
- 互動 menu 取消時整筆不存；選 SaaS 時 Console URL 預設顯示
  `https://console.illum.io`，仍允許 custom URL。

- [ ] **Step 3: 先寫 Playwright GUI 測試**

`tests/test_v2_system_e2e.py` 延伸 PCE 區：select 與 Console URL 都存在、值從
`/api/settings` 載入、存檔 body 正確；切換 SaaS 顯示官方 status page link；密碼欄與
既有 target-change modal 不受影響。

- [ ] **Step 4: 跑 RED**

```bash
timeout 180 venv/bin/pytest tests/test_api_settings.py tests/test_cli_config_cmd.py tests/test_pce_target_cli.py -q
timeout 300 venv/bin/pytest tests/test_v2_system_e2e.py -q
```

- [ ] **Step 5: 實作 GUI 儲存與表單**

allowlist 加入兩欄；`ApiSettings.model_validate()` 維持 validate-then-mutate。前端使用既有
`selectField`／`textField`／`form.track`，不自創元件。SaaS status 連結需
`target="_blank"` 且 `rel="noopener noreferrer"`；顯示文字與 help 全走 i18n。

設定表單布局：deployment select 位於 API URL 前；Console URL 位於 org id 後。on-prem
help 說明空值沿用 PCE origin；SaaS help 說明空值使用 `console.illum.io`、custom tenant
應填完整 URL。

- [ ] **Step 6: 實作兩條 CLI path**

`config login` 加 options 與 interactive prompts；`settings_menu` 收集 locals、驗證整個
`ApiSettings` 後才一次寫入。新增 `connection_runtime_changed()` 或同等純判斷，讓新欄位
改變時提醒重啟，但不要擴大 `pce_target_changed()` 的 cache identity 定義。

- [ ] **Step 7: 跑 GREEN 與 i18n targeted gates**

```bash
timeout 180 venv/bin/pytest tests/test_api_settings.py tests/test_cli_config_cmd.py tests/test_pce_target_cli.py -q
timeout 300 venv/bin/pytest tests/test_v2_system_e2e.py -q
timeout 180 venv/bin/pytest tests/test_i18n_audit.py tests/test_i18n_quality.py -q
venv/bin/python scripts/audit_i18n_usage.py
```

- [ ] **Step 8: 突變驗證與 commit**

從 allowlist 暫時拿掉 `console_url`，確認 API round-trip 測試紅；還原並綠。

```bash
git add src/gui/_helpers.py src/gui/routes/config.py src/static/js/v2/areas/system.mjs src/cli/config.py src/cli/menus/_root.py src/i18n_en.json src/i18n_zh_TW.json src/i18n/data/zh_explicit.json tests/test_api_settings.py tests/test_cli_config_cmd.py tests/test_pce_target_cli.py tests/test_v2_system_e2e.py
git commit -m "feat(settings): expose SaaS deployment and console URL"
```

---

### Task 5: 修正所有 alert event link 的共同 resolver

**Files:**
- Modify: `src/reporter.py`
- Modify: `tests/test_event_console_link_saas.py`
- Modify: `tests/test_event_monitoring.py`
- Modify: `tests/test_alerts_telegram.py`
- Modify: `tests/test_email_acceptance.py`

**Interfaces:**
- Consumes: Task 1 `resolve_pce_console_url()`
- Produces: 所有 renderer 共用的 `event_alert_payloads[*].events[*].pce_link`

- [ ] **Step 1: 用真實 host 格式取代假陽性測試**

保留 on-prem case，將 SaaS cases 改成明確設定，而不是期待 hostname 推導：

```python
def test_saas_event_link_uses_explicit_console_not_api_host():
    r = _reporter({
        "deployment_type": "saas",
        "url": "https://saas-api.example.invalid",
        "console_url": "https://console.illum.io",
    })
    assert r._event_console_link({"href": "/orgs/<org-id>/events/evt-1"}) \
        == "https://console.illum.io/#/events/evt-1"


def test_saas_custom_console_subdomain_is_preserved():
    r = _reporter({
        "deployment_type": "saas",
        "url": "https://custom-api.example.invalid:443",
        "console_url": "https://acme.illumio.ai",
    })
    assert r._event_console_link({"href": "/orgs/<org-id>/events/evt-2"}) \
        == "https://acme.illumio.ai/#/events/evt-2"
```

另測：href 缺少時回 Console landing；SaaS console_url 空值使用 default；on-prem 空值
使用 API origin；惡意／無效 URL 早在 schema 被拒絕。

- [ ] **Step 2: 釘住共同 payload 與 renderer parity**

`tests/test_event_monitoring.py` 斷言 `_build_vendor_event_payloads()` 只產生一個正確
`pce_link`；LINE／mail 的既有模板都含該 URL。`tests/test_alerts_telegram.py` 加正常長度
link case；`tests/test_email_acceptance.py` 確認 CTA href 使用 Console URL，
`web_gui.public_url` 仍只用於 illumio-ops dashboard CTA。

- [ ] **Step 3: 跑 RED**

```bash
timeout 180 venv/bin/pytest tests/test_event_console_link_saas.py tests/test_event_monitoring.py tests/test_alerts_telegram.py tests/test_email_acceptance.py -q
```

- [ ] **Step 4: 刪除 hostname heuristic，改用 resolver**

`Reporter._event_console_link()` 直接讀 `cm.config["api"]` 並呼叫
`resolve_pce_console_url()`；刪除 `_console_base()`。只保留 event href 的 org prefix
剝除與既有 hash route 組合。不要碰每個 channel renderer。

- [ ] **Step 5: 跑 GREEN 與突變驗證**

```bash
timeout 180 venv/bin/pytest tests/test_event_console_link_saas.py tests/test_event_monitoring.py tests/test_alerts_telegram.py tests/test_email_acceptance.py -q
```

暫時讓 `_event_console_link()` 再用 `api.url`，確認 SaaS API hostname 與 custom domain
兩例都紅；還原並綠。

- [ ] **Step 6: Commit checkpoint**

```bash
git add src/reporter.py tests/test_event_console_link_saas.py tests/test_event_monitoring.py tests/test_alerts_telegram.py tests/test_email_acceptance.py
git commit -m "fix(alerts): build event links from the console URL"
```

---

### Task 6: 在 Health Dashboard 顯示 probe 身分與資料面 freshness

**Files:**
- Modify: `src/gui/routes/dashboard.py`
- Modify: `src/pce_cache/health.py`
- Modify: `src/pce_cache/web.py`
- Modify: `src/static/js/v2/components/healthbar.mjs`
- Modify: `src/static/js/v2/areas/overview.mjs`
- Modify: `src/i18n_en.json`
- Modify: `src/i18n_zh_TW.json`
- Modify: `src/i18n/data/zh_explicit.json`
- Modify: `tests/test_v2_overview_e2e.py`
- Modify: `tests/test_v2_shell_e2e.py`
- Modify: `tests/test_pipeline_observability.py`
- Modify: `tests/test_dashboard_overview.py`

**Interfaces:**
- `/api/status`: 增加 `deployment_type`、`health_probe`、SaaS-only `provider_status_url`
- `pipeline_verdict(..., source_statuses=...)`: ingestion `last_status=error` 優先判 error
- Consumes: `pce_stats` 與 `check_cache_lag()` 的 lag／last_status

- [ ] **Step 1: 寫 status response 測試**

在既有 dashboard／shell e2e 測試斷言：SaaS 回 `health_probe="noop"` 與官方 status URL；
on-prem 回 `health_probe="noop+health+node_available"` 且不顯示 SaaS provider link。

- [ ] **Step 2: 寫 Health bar／Overview 行為測試**

固定三種狀態：

- 401：紅，原因顯示 credentials/auth，不顯示 generic offline。
- `/noop` success 但 events watermark error／lag：API access 可用，Pipeline 仍紅。
- SaaS 全正常：PCE health 顯示 SaaS + noop，cache lag 分別顯示 events／traffic。

`tests/test_pipeline_observability.py` 直接釘住最容易誤判的一例：

```python
assert pipeline_verdict(
    lag_levels=["ok"], source_statuses=["error"],
    siem_success_1h=100.0, denom=0, dlq=0,
) == "error"
```

`tests/test_dashboard_overview.py`／API test 再斷言 `cache_lag` response 保留每個 source 的
`last_status`；失敗 ingest 即使 `lag_s` 很小，Overview verdict 仍是 error。

- [ ] **Step 3: 跑 RED**

```bash
timeout 180 venv/bin/pytest tests/test_pipeline_observability.py tests/test_dashboard_overview.py -q
timeout 300 venv/bin/pytest tests/test_v2_overview_e2e.py tests/test_v2_shell_e2e.py -q
```

- [ ] **Step 4: 實作 status metadata 與最小 UI 調整**

`/api/status` 從 validated config 產生 deployment/probe metadata；不要把 API response body
直接傳前端。Health bar 延用 `pce_stats.consecutive_failures` tone，新增 probe／category
reason。`pipeline_verdict()` 增加 `source_statuses`，任何 `error` 優先回 error；
`dashboard.py` 與 `pce_cache/web.py` 都把 `check_cache_lag()` 的 `last_status` 傳入同一
verdict 並保留在 response。這是補齊既有 freshness 計算，不另做第二套。

- [ ] **Step 5: 跑 GREEN、突變與 commit**

```bash
timeout 180 venv/bin/pytest tests/test_pipeline_observability.py tests/test_dashboard_overview.py -q
timeout 300 venv/bin/pytest tests/test_v2_overview_e2e.py tests/test_v2_shell_e2e.py -q
timeout 180 venv/bin/pytest tests/test_i18n_audit.py tests/test_i18n_quality.py -q
```

暫把 401 label 改為 generic unreachable，確認 UI contract 紅；還原並綠。

```bash
git add src/gui/routes/dashboard.py src/pce_cache/health.py src/pce_cache/web.py src/static/js/v2/components/healthbar.mjs src/static/js/v2/areas/overview.mjs src/i18n_en.json src/i18n_zh_TW.json src/i18n/data/zh_explicit.json tests/test_pipeline_observability.py tests/test_dashboard_overview.py tests/test_v2_overview_e2e.py tests/test_v2_shell_e2e.py
git commit -m "feat(gui): show deployment-aware PCE health signals"
```

---

### Task 7: 更新操作文件與完成 SaaS 真機 acceptance

**Files:**
- Modify: `docs/guide/configuration.md`
- Modify: `docs/guide/monitoring-alerts.md`
- Modify: `docs/guide/troubleshooting.md`
- Modify: `docs/reference/cli.md`
- Modify: `tests/test_docs_contracts.py`

**Interfaces:** Consumes Task 1–6；Produces 維運 runbook 與真機證據。

- [ ] **Step 1: 先寫 docs contract**

`tests/test_docs_contracts.py` 斷言文件同時包含：兩種 deployment 值、SaaS `/noop`、
on-prem-only `/health`／`/node_available`、`api.console_url`、官方 status page，以及「401
是 credentials 問題，不等於平台離線」。

- [ ] **Step 2: 跑 RED**

```bash
timeout 120 venv/bin/pytest tests/test_docs_contracts.py -q
```

- [ ] **Step 3: 更新四份文件**

- `configuration.md`：三 URL 責任、舊設定 default、GUI／CLI 範例、改後重啟規則。
- `monitoring-alerts.md`：把現行固定 `/health` 描述改為 deployment flow ASCII 圖；說明
  API access 與 ingestion freshness 是不同訊號。
- `troubleshooting.md`：按分類列 401／403／429／5xx／transport 的處理方式；SaaS incident
  再對照官方 status page。
- `reference/cli.md`：加入兩個 `config login` options 與範例。

- [ ] **Step 4: 跑 docs GREEN**

```bash
timeout 120 venv/bin/pytest tests/test_docs_contracts.py -q
venv/bin/python scripts/check_doc_links.py
```

- [ ] **Step 5: 取得可用 SaaS key 後做無密碼輸出的 live probe**

憑證只用 `op read` 在行程內取得；輸出限定 target host、status、category、elapsed，不印
username、secret、Authorization header 或 response body。驗收：`/noop` 2xx，最近一頁
`/events` 2xx，既有 ingestion watermark 可前進。

原 production PCE credential item 曾回 401；若執行時仍為 401，將 acceptance 標成 blocked 並由操作者先更新 key，
不得把 401 當成平台 outage 或勉強宣稱完成。

- [ ] **Step 6: 驗證事件 deep link**

用 live `/events` 回傳的一個 event href 產生 alert link，在已登入的瀏覽器開啟並確認落到
同一 event。至少驗證預設 `console.illum.io`；若客戶 tenant 使用 custom subdomain，再驗一例。

若 `/#/events/<id>` 不被 Console 接受，**停止並裁決**：本 release 先回 Console landing
page，或依實際可觀察 route 修正；不得猜 undocumented path。

- [ ] **Step 7: 突變驗證、commit docs 與保存安全證據**

暫移除一個關鍵 deployment 字串，確認 docs contract 紅；還原並綠。真機證據只記 status、
category、elapsed 與 event ID 的遮罩／hash，不保存完整事件或 credentials。

```bash
git add docs/guide/configuration.md docs/guide/monitoring-alerts.md docs/guide/troubleshooting.md docs/reference/cli.md tests/test_docs_contracts.py
git commit -m "docs: document SaaS PCE monitoring and console links"
```

---

### Task 8: 完整 CI、跨 task 回歸與交付

**Files:**
- Verify only;只有驗證發現本案造成缺陷時才修改對應檔案

**Interfaces:** Consumes 所有前述 tasks；Produces 可合併的驗證證據。

- [ ] **Step 1: 先檢查工作樹與 diff 邊界**

```bash
git status --short
git diff --check
git diff --stat
git log --oneline -8
```

確認沒有 credentials、live response、暫存檔或無關格式化混入。

- [ ] **Step 2: 跑所有 targeted suites**

```bash
timeout 600 venv/bin/pytest tests/test_config_models.py tests/test_config_backwards_compat.py tests/test_api_settings.py tests/test_pce_target_cli.py tests/test_cli_config_cmd.py tests/test_api_client_request_contract.py tests/test_health_body_parsing.py tests/test_gui_filter_suggest.py tests/test_gui_misc.py tests/test_event_console_link_saas.py tests/test_event_monitoring.py tests/test_alerts_telegram.py tests/test_email_acceptance.py tests/test_watchdog_alert.py tests/test_watchdog_ingest_pipeline.py tests/test_watchdog_overflow_cache_cycle_merge.py tests/test_pipeline_observability.py tests/test_dashboard_overview.py tests/test_docs_contracts.py tests/test_i18n_audit.py tests/test_i18n_quality.py -q
timeout 900 venv/bin/pytest tests/test_v2_system_e2e.py tests/test_v2_overview_e2e.py tests/test_v2_shell_e2e.py -q
```

- [ ] **Step 3: 跑 CI hard gates（本機能跑的全部）**

```bash
venv/bin/python scripts/check_no_naive_datetime.py
venv/bin/python scripts/check_doc_links.py
venv/bin/python scripts/audit_i18n_usage.py
venv/bin/mypy --follow-imports=silent src/api_client.py src/analyzer.py src/reporter.py
timeout 1800 venv/bin/pytest --tb=short
```

- [ ] **Step 4: 跑兩份 dependency security audit**

網路／index 可用時執行；這兩道是 CI hard gate，不得用「pytest 綠」代替：

```bash
venv/bin/pip-audit -r requirements.lock --strict
venv/bin/pip-audit -r requirements-offline.lock --strict
```

offline lock 的正式 CI runner 是 Python 3.12，需在相同大版本下驗證。

- [ ] **Step 5: 最終安全與需求核對**

逐條回看本計畫與 spec 的八項驗收條件。特別確認：

- SaaS code path 沒有 `/health`／`node_available` 呼叫。
- `api.url` 沒再被用來推導 SaaS Console hostname。
- 401 UI／alert 明說 auth failed，watchdog 仍正確累積。
- events／traffic lag 沒被 `/noop` success 蓋成全綠。
- 所有 alert channels 共用同一 `pce_link`。
- 沒有 secrets 出現在 `git diff` 或測試輸出。

- [ ] **Step 6: 最後 checkpoint**

若驗證修補產生新變更，先以 `git diff --name-only` 列出它們，逐一確認都由本案造成，
再把每個確認過的路徑字面寫進 `git add path/to/file ...` 後提交；不得使用 placeholder、
glob 或 `git add -A`。提交訊息為 `test: close SaaS PCE monitoring regressions`。

若沒有新變更，不建立空 commit。回報每一道 gate 的 command、exit code、pass count，並把
live acceptance 分成「API probe」與「Console deep link」兩列，任何未完成項明確標 blocked。

## 建議執行順序與 checkpoint

```text
Task 1 設定契約
   |
Task 2 /noop primitive
   |
Task 3 health orchestration ── checkpoint A（可先停止錯誤 SaaS health 告警）
   |
Task 3A SaaS events timeout ── checkpoint A+（修正截圖中的 30 秒臨界點）
   |
Task 4 GUI/CLI settings
   |
Task 5 event links ─────────── checkpoint B（所有通道共用修正）
   |
Task 6 dashboard semantics
   |
Task 7 docs + live acceptance
   |
Task 8 full CI
```

如果要降低交付風險，可先部署到 checkpoint A：它已能停止 SaaS `/health` 誤判，但 event
link 仍未修；checkpoint B 才同時完成使用者目前看到的兩個問題。正式 release 必須完成
Task 8，不可把 checkpoint 當最終驗收。
