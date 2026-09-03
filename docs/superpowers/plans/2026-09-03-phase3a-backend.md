# Phase 3A — 後端契約（告警落地、查詢重建、flow→rule 解釋）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 v3 主場景「告警→流量→規則→行動」在後端有軌道：每則派送過的告警落地可查、可改狀態；一則告警能重建它的流量查詢；一條 flow 能問出涵蓋它的 PCE rule。純後端＋守門，**不動任何前端檔案**。

**Architecture:** 新增一個獨立 SQLite `logs/alerts.sqlite`（`src/alerts/store.py`，stdlib `sqlite3`，WAL），在 `Reporter.send_alerts` 派送結果確定後逐則寫入、DLQ 重播時以同列更新；一個新 blueprint `src/gui/routes/alerts.py` 提供清單／詳情／狀態／查詢重建；一個新模組 `src/api/policy_explain.py` 把 (src, dst, port, proto) 對回 PCE href 後呼叫 Rule Search，對不到 href 的純 IP 走本地 iplist CIDR 比對；retention job 順手清舊告警。

**Tech Stack:** Python 3.10+、Flask blueprint（既有 CSRF／before_request 認證）、stdlib `sqlite3`、`ipaddress`、pytest；真機驗證走測試機 `illumio-ops-test`（`/root/illumio-ops`，service 帳號 `illumio-ops`，直譯器 `/root/illumio-ops/venv/bin/python`）。

**Spec:** `docs/superpowers/specs/2026-09-03-ui-redesign-v3-design.md` §4a／§4b（後端半）／§4c；路線圖 `docs/superpowers/plans/2026-09-03-ui-redesign-v3-roadmap.md`。

## Global Constraints

- 路線圖「全程約束」整段適用（零 build、CSRF/auth 不動、i18n 七層鏈、守門沿用、service 帳號建檔 0600、英文 conventional commits、CI 每道閘門）。
- **本計畫不改任何 `src/static/**`、`src/templates/**`、`design/**`**；前端契約（`?alert=`、`?f=`）在 3B。
- 新 SQLite 只放 `logs/`（`ROOT_DIR/logs`，同 `state.json` 的解析法 `src/config.py:53-61`；systemd `ReadWritePaths` 只開 `logs/ config/ data/ reports/`）。檔案由程式在 service 帳號下建立，`os.chmod(path, 0o600)`；`-wal`／`-shm` 同目錄。
- 告警識別用 **`rule_id`（rules 的 uuid，`src/rule_id.py`）**，不是 spec 寫的 `rule_index`——index 只在 `src/gui/routes/rules.py:109` 讀取時計算、不可持久化。看門狗／overflow 類 health 告警沒有規則物件，`rule_id` 為 NULL。
- `send_alerts` 內 `alert["time"]` 在派送前已被改寫成本地化顯示字串（`src/reporter.py:916-921`）；落地的 `fired_at` 一律用派送當下 UTC，不用 `alert["time"]`。
- `force_test=True` 的派送不落地（spec §4a）。
- PCE Rule Search 是 Public Experimental；**欄位語意以 Task 4 在 lab PCE 實測結果為準**，不憑文件或記憶寫對應。`rule_types` 白名單 `["sec_rules","deny_rules","override_deny_rules"]`。
- 測試資料：真快照或 Task 4 錄下的（遮罩後）fixture；禁手寫 PCE 回應形狀。
- 每任務結束：該任務測試檔＋`tests/test_siem_traffic_pd.py`（最近改過的相鄰守門）綠 → commit；orchestrator 在任務之間跑全套閘門。

## File Structure

| 檔案 | 責任 |
|---|---|
| `src/alerts/store.py`（新） | `AlertStore`：schema、insert／update_dispatch／get／list／set_status／prune；唯一碰 `alerts.sqlite` 的地方 |
| `src/analyzer.py`（改三處） | 三個 `alert_data` 建構點加 `"rule_id": rule["id"]`、`"rule_type": rule["type"]` |
| `src/reporter.py`（改一處＋DLQ 兩處） | 派送結果確定後呼叫 store；`_alert_ids` 平行清單隨 DLQ entry 進出 state，不碰告警 item |
| `src/scheduler/jobs.py`＋`src/scheduler/__init__.py` | 新 job `run_alerts_retention` 每日無條件排程（不依賴 `pce_cache.enabled`） |
| `src/gui/routes/alerts.py`（新） | `make_alerts_blueprint(cm, login_required)`：`/api/alerts*` |
| `src/gui/__init__.py`（改一處） | 註冊 alerts 與 policy blueprint |
| `src/api_client.py`（加一個方法） | `rule_search(body, pversion, timeout) -> (status, body_or_error)` 保留錯誤本文 |
| `src/api/policy_explain.py`（新） | actor 解析（href／IP→workload／IP→iplist）、Rule Search 呼叫、本地備援、TTL 快取、結果整形 |
| `src/gui/routes/policy.py`（新） | `make_policy_blueprint(cm, login_required)`：`POST /api/policy/explain` |
| `tests/test_alert_store.py`、`tests/test_alert_persistence.py`、`tests/test_gui_alerts_api.py`、`tests/test_policy_explain.py`、`tests/test_gui_policy_explain.py`（新） | 各任務守門 |
| `tests/fixtures/pce_rule_search/*.json`（新，Task 4 錄製） | 真 PCE 回應（遮罩） |
| `docs/reference/rest-api.md`、`docs/guide/monitoring-alerts.md`、`CHANGELOG.md` | Task 6 |

---

### Task 1: AlertStore（SQLite 落地層）＋告警項目帶規則識別

**Files:**
- Create: `src/alerts/store.py`
- Modify: `src/analyzer.py:1330-1335`（health）、`:1637-1654`（event）、`:2308-2314`（traffic／metric）
- Test: `tests/test_alert_store.py`

**Interfaces（Produces）:**
```python
# src/alerts/store.py
ALERT_TYPES = ("event", "traffic", "bandwidth", "system")
ALERT_STATUSES = ("new", "ack", "done")

def default_alerts_db_path() -> str:  # os.path.join(ROOT_DIR, "logs", "alerts.sqlite")，ROOT_DIR 取自 src.config

class AlertStore:
    def __init__(self, path: str | None = None): ...   # 建目錄不存在時不建目錄（logs/ 由安裝腳本建）；首次開啟建 schema、chmod 0600
    def insert(self, *, fired_at: str, type: str, rule_id: str | None, rule_name: str,
               severity: str, summary: str, criteria: str, payload: dict,
               dispatch: list[dict]) -> int                      # 回 row id
    def update_dispatch(self, alert_id: int, dispatch: list[dict]) -> None
    def get(self, alert_id: int) -> dict | None                  # payload/dispatch 已 json.loads
    def list(self, *, status: str | None = None, type: str | None = None,
             since: str | None = None, page: int = 1, page_size: int = 50) -> dict
             # {"items": [...不含 payload...], "total": int, "page": int, "page_size": int}
    def count(self, *, status: str = "new") -> int
    def set_status(self, alert_id: int, status: str, by: str) -> bool   # 不存在回 False；status 不在 ALERT_STATUSES raise ValueError
    def prune(self, *, days: int) -> int                          # 刪 fired_at 早於 now-days 的列，回筆數
```
Schema（SQL 字面，`user_version=1`）：
```sql
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fired_at TEXT NOT NULL,            -- ISO8601 UTC 'YYYY-MM-DDTHH:MM:SSZ'
  type TEXT NOT NULL CHECK (type IN ('event','traffic','bandwidth','system')),
  rule_id TEXT,                      -- rules[].id (uuid hex) 或 NULL（watchdog/overflow）
  rule_name TEXT NOT NULL,
  severity TEXT NOT NULL,            -- info|warning|critical（見下方對照）
  summary TEXT NOT NULL,
  criteria TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL,        -- 原 bucket item（raw_data 最多 10 筆）
  dispatch_json TEXT NOT NULL,       -- send_alerts 回傳的 results 子集 [{channel,status,target,error}]
  status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','ack','done')),
  status_by TEXT, status_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_alerts_status_fired ON alerts(status, fired_at DESC);
CREATE INDEX IF NOT EXISTS ix_alerts_type_fired ON alerts(type, fired_at DESC);
```
Severity 對照（store 不決定，Task 2 的 hook 決定，這裡只驗值）：event → item `severity`（PCE 值 info/warning/error/critical 直接存）；traffic／bandwidth → `warning`；system → item `status` 為 `critical`/`degraded` → `critical`，其餘 `warning`。

**analyzer 改動（三處各加兩鍵）**：`"rule_id": str(rule["id"])`（lab 快照的 rules 有整數 id，`_check_cooldown` 也是 `str(rule["id"])` 鍵，`src/analyzer.py:2325`）、`"rule_type": rule["type"]`（health 規則型告警 `:1330` 同樣；watchdog `:1354` 與 overflow `:1459` 不動，它們沒有 rule 物件）。

**外送影響（已查證）**：webhook 與 mail 模板把四個 bucket **整包** `json.dumps`（`src/reporter.py:436-440` 與 `_build_webhook_payload`），所以這兩個鍵會出現在 webhook JSON 裡——視為**新增欄位**（有助 SIEM 對應），Task 6 的 CHANGELOG 要寫；也因此**任何內部標記都不得掛在告警項目上**（Task 2 的 `_alert_id` 放 DLQ 項目，不放 item）。`tests/test_alert_mail_samples*`／`test_reporter_*` 必須維持綠。

`AlertStore.__init__`：`sqlite3.connect(path, timeout=5.0)`＋`PRAGMA journal_mode=WAL`——CLI 選單是另一個行程，monitor＋GUI 同行程，跨行程鎖等待要有上限（本專案跨行程鎖曾實測過，memory `review2-unreviewed-subsystems`）。

- [ ] **Step 1 — 紅**：`tests/test_alert_store.py`：(a) 新檔開啟後 `os.stat(path).st_mode & 0o777 == 0o600` 且 `PRAGMA user_version` 為 1；(b) insert→get 往返 payload/dispatch 相等；(c) `list(status="new")` 分頁與 total；(d) `set_status` 合法／非法／不存在；(e) `prune(days=30)` 只刪舊列；(f) `type` 非法 raise。用 `tmp_path`。
- [ ] **Step 2 — 紅**：`tests/test_alert_store.py::test_alert_items_carry_rule_identity`：以既有 `tests/test_analyzer_with_mock_api.py`／`tests/test_analyzer.py` 的最小 Analyzer 夾具觸發一條 traffic 規則與一條 event 規則（照那兩檔既有做法建 rule dict，必含 `id`），斷言 `reporter.traffic_alerts[0]["rule_id"] == rule["id"]`、`["rule_type"] == "traffic"`；event 同。
- [ ] **Step 3 — 綠**：實作 store 與 analyzer 三處。
- [ ] **Step 4 — 驗證**：`timeout 600 python3 -m pytest tests/test_alert_store.py tests/test_analyzer.py tests/test_analyzer_with_mock_api.py tests/test_analyzer_decomposition.py tests/test_reporter_body_hardening.py tests/test_reporter_severity_badge.py -q`；再 `ls tests | grep -i mail` 找到 mail 樣本測試一併跑。
- [ ] **Step 5 — Commit**：`feat(alerts): persist-ready alert store and rule identity on alert items`

---

### Task 2: 派送後落地＋DLQ 重播更新＋retention

**Files:**
- Modify: `src/reporter.py:1007`（`self.last_dispatch_results = results` 之後、DLQ push `:1017` 之前）、`:842 _push_alert_dlq`、`:880-893` DLQ 合併處
- Modify: `src/scheduler/jobs.py`（新增 `run_alerts_retention`）、`src/scheduler/__init__.py:189-240`（新增排程）
- Test: `tests/test_alert_persistence.py`

**Interfaces（Consumes）:** Task 1 的 `AlertStore`。
**Interfaces（Produces）:**
```python
# src/reporter.py
class Reporter:
    alert_store_factory = staticmethod(AlertStore)   # 測試可換成 tmp_path 版本
    def _persist_alerts(self, results: list[dict], *, now_utc: str) -> None
```
規則：
- 呼叫時機：`send_alerts` 內、`self.last_dispatch_results = results` 之後，`force_test` 時直接 return。
- 識別靠 **Reporter 實例上的平行清單** `self._alert_ids = {"health": [], "event": [], "traffic": [], "metric": []}`（與四個 bucket 同序、同長；`add_*_alert` 追加 `None`）。逐 bucket 逐 index：`_alert_ids[b][i]` 非 None → `store.update_dispatch(id, results_subset)`；None → `store.insert(...)`，回傳 id 填回 `_alert_ids[b][i]`。**不在告警 item 上掛任何鍵**（webhook 整包序列化，見 Task 1）。
- type 對照：bucket `health_alerts`→`system`、`event_alerts`→`event`、`traffic_alerts`→`traffic`、`metric_alerts`→`bandwidth`。
- `summary`：event → `f'{rule} · {source} → {target}'`（缺值省略）；traffic／bandwidth → `f'{rule} · {count} · {criteria}'`；system → `f'{rule} · {status}'`。`criteria`：item.get("criteria","")。`payload`：item 去掉 `_alert_id`，`raw_data` 截至 10 筆。
- `dispatch`：`[{k: r.get(k) for k in ("channel","status","target","error")} for r in results]`。
- 任何 store 例外 `logger.error("alert persistence failed: {}", exc)` 後不重拋——落地失敗不得阻斷派送（派送已完成）；這是**有意識的吞錯**，驗證步驟要跑既有吞錯守門（見 Step 3）。
- DLQ：`_push_alert_dlq(self, buckets, attempts, first_failed_at)` 簽名不改，但 entry 多一鍵 `"alert_ids": {"health": [...], "event": [...], "traffic": [...], "metric": [...]}`（與 `buckets` 各清單同序）；`:880-893` 合併重播時同步把 `entry.get("alert_ids", {})` 接到 `self._alert_ids`（缺鍵＝舊格式，補 `None`）。
- retention：**不能**掛在 `run_cache_retention`——它只在 `pce_cache.enabled` 時排程（`src/scheduler/__init__.py:189`），cache 關閉的部署告警會永遠不清。改為 `src/scheduler/jobs.py` 新增 `run_alerts_retention(cm)`：`AlertStore().prune(days=cm.models.pce_cache.archive_retention_days)`、log 筆數；在 `src/scheduler/__init__.py` **無條件**排程 `_instrument("alerts_retention", run_alerts_retention, 86400)`，`_IT(hours=24)`，id `alerts_retention`（`next_run_time` 比照該檔其他 24h job 的「啟動後先跑一次」寫法）。job 健康表會多一列，`docs/handover/architecture.md:193` 的 14 個 job 數字在 Task 6 更新。

- [ ] **Step 1 — 紅**：`tests/test_alert_persistence.py`：(a) 用 `Reporter(cm)` 塞一則 traffic、一則 event、一則 health bucket，monkeypatch plugins 讓一個管道成功；`send_alerts()` 後 store 有 3 列，`dispatch_json` 含該管道 `status=="success"`，`fired_at` 是 UTC 格式；(b) `force_test=True` 不新增列；(c) **重播不重複**：讓全部管道失敗 → DLQ push；把 `state["alert_dlq"]` 讀回、再建一個新 Reporter 觸發 `send_alerts()`（會 pop DLQ）並讓管道成功 → 列數仍 3、原列 `dispatch_json` 更新為 success；(d) store 拋例外時 `send_alerts` 仍回傳 results 且不 raise；(e) `run_alerts_retention(cm)` 呼叫 `prune(days=cfg.archive_retention_days)`（monkeypatch `AlertStore`），且 `pce_cache.enabled=False` 時 scheduler 仍註冊 `alerts_retention`（照 `tests/test_scheduler*.py` 既有的 job 註冊斷言寫法；檔名以 `ls tests | grep scheduler` 為準）。state 檔用 `monkeypatch.setattr("src.reporter.STATE_FILE", tmp)`（reporter 有自己的 STATE_FILE 常數，`src/reporter.py:23-25`）。
- [ ] **Step 2 — 綠**：實作。
- [ ] **Step 3 — 驗證**：`timeout 600 python3 -m pytest tests/test_alert_persistence.py tests/test_alert_dlq.py tests/test_reporter_body_hardening.py tests/test_reporter_tz.py tests/test_pce_cache_retention.py tests/test_analyzer_review2_gates.py tests/test_cli_flows_parity.py tests/test_log_layer_english.py-q`（後面那幾檔是吞錯 AST 守門；若它們對新的 `except` 亮紅，依守門要求登記理由，不放寬守門）。
- [ ] **Step 4 — Commit**：`feat(alerts): persist dispatched alerts and update them on DLQ replay`

---

### Task 3: `/api/alerts` blueprint（清單／詳情／狀態／查詢重建）

**Files:**
- Create: `src/gui/routes/alerts.py`
- Modify: `src/gui/__init__.py:491-492` 附近（照 `make_rules_blueprint` 的註冊寫法）
- Test: `tests/test_gui_alerts_api.py`

**Interfaces（Produces）:**
```
GET   /api/alerts?status=new|ack|done&type=event|traffic|bandwidth|system&since=<ISO>&page=1&page_size=50
      → {"ok": true, "items": [...], "total": n, "page": p, "page_size": s, "counts": {"new": n1, "ack": n2, "done": n3}}
GET   /api/alerts/<int:id>            → {"ok": true, "alert": {...含 payload/dispatch...}}；404 {"ok": false, "error": ...}
PATCH /api/alerts/<int:id>  {"status": "ack"|"done"|"new"}
      → {"ok": true}；400 非法值；404 不存在；status_by = current_user 名稱
GET   /api/alerts/<int:id>/traffic_query
      → {"ok": true, "rule": {"id","name","type"}, "query": {...}}；
        rule_id 為 NULL 或規則已不存在 → 404 {"ok": false, "code": "rule_missing"}
        type 不是 traffic/bandwidth → 400 {"ok": false, "code": "not_traffic"}
```
`query` 內容＝該規則 dict 中與流量查詢有關的鍵**原樣**回傳（不重新詮釋；3B 負責映射到 FilterBar）：`filters`（若有）、`pd`、`threshold_window`、`type`，再加 `TRAFFIC_FILTER_KEYS`／`BW_FILTER_KEYS` 列出的純量鍵（清單見 `src/static/js/v2/areas/alerting.mjs:704-706`，抄成 Python 常數放在 `src/gui/routes/alerts.py` 頂端並附來源註解），存在才回。
- 認證：沿用 `before_request` 全域閘（不需額外裝飾）；PATCH 走既有 CSRF（`X-CSRF-Token`）。
- 錯誤：`_err(msg, status)`；未預期例外 `_err_with_log("alerts_api", exc, lang=lang)`。
- `page_size` 上限 200；`since` 非 ISO → 400。
- 規則查找：`cm.config["rules"]` 內 `str(r.get("id")) == rule_id`（id 可能是整數，store 存字串）。

- [ ] **Step 1 — 紅**：`tests/test_gui_alerts_api.py`：照 `tests/test_gui_rules.py:32-41` 的 login＋`_csrf` 夾具；用 `monkeypatch.setattr("src.gui.routes.alerts.AlertStore", lambda: AlertStore(tmp_path/"a.sqlite"))` 隔離。案例：清單分頁與 counts；type/status 篩選；詳情 404；PATCH 合法／非法／缺 CSRF 回 400 `csrf_error`；`traffic_query` 三種回應（traffic 規則、event 規則→400、rule_id 缺→404）。
- [ ] **Step 2 — 綠**：實作 blueprint、註冊。
- [ ] **Step 3 — 驗證**：`timeout 600 python3 -m pytest tests/test_gui_alerts_api.py tests/test_gui_rules.py tests/test_gui_routes_robustness.py tests/test_gui_routes_lang_param.py -q`；`python3 scripts/audit_i18n_usage.py`（新錯誤文案若用 `t()` 必須入庫 en/zh）。
- [ ] **Step 4 — Commit**：`feat(gui): alerts inbox API with status changes and traffic-query rebuild`

---

### Task 4: PCE Rule Search 真機探測＋`ApiClient.rule_search`

**Files:**
- Create: `tools/probe_rule_search.py`（一次性探測腳本，留在 repo 供重測）
- Create: `tests/fixtures/pce_rule_search/{allow_hit,no_match,deny_hit,iplist_actor,k8s_actor}.json`（deny_hit 沒有可用規則時記錄「lab 無 deny 規則」並省略）
- Modify: `src/api_client.py`（新增方法，放在 `provision_changes` 附近）
- Test: `tests/test_api_client_rule_search.py`

**Interfaces（Produces）:**
```python
# src/api_client.py
def rule_search(self, body: dict, *, pversion: str = "active", timeout: int = 30) -> tuple[int, Any]:
    """POST /orgs/{org}/sec_policy/{pversion}/rule_search. Returns (status, parsed body);
    on non-2xx the parsed PCE error body (list/dict) is returned instead of None so callers can show it."""
```
探測腳本（在測試機以 service venv 執行，不落任何憑證到檔案）：
1. `fetch_managed_workloads()` 取兩台有 label 的 workload href；`get_active_rulesets(raise_on_error=True)` 找一條 enabled allow rule，取它的 consumers／providers 的 label href 與 ingress_services。
2. 對 `rule_search` 依序送四個 body，逐一印出 `status` 與回應頂層鍵、`sec_rules` 長度：
   - A：`{"consumers":[{"label":{"href":...}}],"providers":[{"label":{"href":...}}],"ingress_services":[{"port":P,"proto":6}],"rule_types":["sec_rules"]}`
   - B：同 A 但 consumers／providers 對調
   - C：用 workload href 取代 label href
   - D：`{"providers":[...], "destinations":[...]}`（KB 文件的寫法）
   - E：A 的勝出組合改 `pversion="draft"`，比較 active／draft 回應差異（本計畫預設 active）
   - F：actor 換成一個 `ip_list` href（`get_ip_lists(raise_on_error=True)` 任取一個含 CIDR 的）——Task 5 的備援整個押在 Rule Search 接受 ip_list actor 上
   - G：一組明知沒有規則涵蓋的 (actor, port)（例如 port 65000）——錄下空結果的形狀（`sec_rules: []` 還是別的）
   - H：actor 用 `/orgs/{org}/kubernetes_workloads/<id>` href（lab 的 onlineboutique 流量來源就是這種，見 `design/v2/snapshots/traffic_search.json`）；同時記錄 `fetch_managed_workloads()`（`/workloads?managed=true`）是否**不含** K8s workload
3. 結論寫進腳本頂端 docstring 與 fixture：**哪一組欄位名對應「來源／目的」**、回應中 rule 與 `rule_set` 的鍵（href、name、enabled、`provision_state`？）、deny 的鍵名。遮罩：org id 換 `1`、href uuid 保留（非機密）、hostname/IP 換假值。
4. 不確定就停下來回報，不猜。

- [ ] **Step 1 — 探測**：`scp tools/probe_rule_search.py illumio-ops-test:/tmp/ && ssh illumio-ops-test 'cd /root/illumio-ops && sudo -u illumio-ops PYTHONNOUSERSITE=1 venv/bin/python /tmp/probe_rule_search.py'`，把三種回應存成 fixture（遮罩後）。
- [ ] **Step 2 — 紅**：`tests/test_api_client_rule_search.py`：以 `responses`／既有 `_request` monkeypatch 慣例（看 `tests/test_api_client*.py` 怎麼假造 `_request`）驗證 URL 為 `/api/v2/orgs/{org}/sec_policy/active/rule_search`、method POST、非 2xx 時回傳解析後的錯誤本文而非 None。
- [ ] **Step 3 — 綠**：實作。
- [ ] **Step 4 — 驗證**：`timeout 600 python3 -m pytest tests/test_api_client_rule_search.py tests/test_api_client.py tests/test_api_client_request_contract.py tests/test_api_client_error_signals.py -q`；`mypy --follow-imports=silent src/api_client.py src/analyzer.py src/reporter.py`。
- [ ] **Step 5 — Commit**：`feat(api): PCE rule_search call and recorded lab fixtures`（fixture 與探測結論一起進）

---

### Task 5: `policy_explain`（actor 解析＋Rule Search＋本地備援）＋`POST /api/policy/explain`

**Files:**
- Create: `src/api/policy_explain.py`、`src/gui/routes/policy.py`
- Modify: `src/gui/__init__.py`（註冊）
- Test: `tests/test_policy_explain.py`、`tests/test_gui_policy_explain.py`

**Interfaces（Consumes）:** Task 4 `ApiClient.rule_search`；`ApiClient.fetch_managed_workloads()`、`get_ip_lists(raise_on_error=True)`；`src/gui/filter_object_cache._get_or_fill(api, key, fetch)`（TTL 300s）；`src/report/policy_resolver_report.build_workload_to_ips` / `build_iplist_to_cidrs`。
**Interfaces（Produces）:**
```python
# src/api/policy_explain.py
PROTO_BY_NAME = {"TCP": 6, "UDP": 17, "ICMP": 1, "ICMPV6": 58}
RULE_TYPES = ["sec_rules", "deny_rules", "override_deny_rules"]

@dataclass
class Actor:
    href: str | None          # workload 或 ip_list href；None = 未解析
    kind: str                 # "workload" | "kubernetes_workload" | "container_workload" | "ip_list" | "unresolved"
    ip: str | None

def resolve_actor(api, *, href: str | None, ip: str | None) -> Actor
    # href 給了直接用（kind 由 href 路徑判斷：/workloads/、/kubernetes_workloads/、/container_workloads/、/sec_policy/.../ip_lists/；Rule Search body 的 actor 鍵名＝kind）
    # 否則 IP→workload（build_workload_to_ips 反轉，經 _get_or_fill 快取 key "explain_wl_by_ip"）
    # 再否則 IP→第一個包含它的 ip_list（build_iplist_to_cidrs，range 'a-b' 與 cidr 都算，fqdn 略過）
    # 都對不到 → Actor(None, "unresolved", ip)
    # 注意：IP→workload 只涵蓋 managed VEN workload；K8s/container workload 只能靠流量列自帶的 href 解析（Task 4-H 記錄），IP-only 的 K8s 端點解析列為 follow-up

def explain_flow(api, *, src: dict, dst: dict, port: int, proto: int | str,
                 basis: str = "active") -> dict
    # src/dst = {"href": str|None, "ip": str|None}；proto 名稱或數字皆可
    # 回傳（固定形狀）：
    # {"basis": basis, "evaluated_at": "<ISO UTC>", "source": "pce_rule_search"|"local_resolver"|"none",
    #  "src": Actor 欄位, "dst": Actor 欄位,
    #  "allow": [RuleHit...], "deny": [RuleHit...], "override_deny": [RuleHit...],
    #  "pce_status": int|None, "pce_error": Any|None, "truncated": bool}
    # RuleHit = {"ruleset_href","ruleset_name","ruleset_enabled","rule_href","rule_enabled",
    #            "consumers": [display], "providers": [display], "ingress_services": [display],
    #            "provision_state": str|None}  —— display 規則：label → "key=value"，workload → name，
    #            ip_list → name，all → "All"；服務 → "port/PROTO" 或 service name
```
規則：
- 兩個 actor 至少一個解析成功才打 PCE；兩個都 `unresolved` → `source="none"`，allow/deny 空。
- PCE 呼叫 body 欄位名**依 Task 4 結論**；`rule_types` 用 `RULE_TYPES`。
- PCE 回非 2xx → `source="pce_rule_search"`、`pce_status`/`pce_error` 帶回、allow/deny 空——**不吞錯**，路由回 502 並附 `pce_error`。
- 本地備援只用於「某一側 unresolved 但另一側解析成功」的情況：以 `build_iplist_to_cidrs` 找包含該 IP 的 iplist，改用該 iplist href 再打一次 PCE；仍找不到即 `source="none"`。（純本地展開規則不做；`truncated` 保留欄位為 False。）
- 60 秒結果快取：`(src.href|ip, dst.href|ip, port, proto, basis)` → 結果，模組層 dict＋timestamp，上限 256 筆。
- 路由 `POST /api/policy/explain`，body `{"src": {"href","ip"}, "dst": {"href","ip"}, "port": int, "proto": str|int, "basis": "active"|"draft"}`；缺 port/proto → 400；`basis` 非法 → 400；`with ApiClient(cm) as api:`；成功 `{"ok": true, **result}`；PCE 錯誤 → 502 `{"ok": false, "code": "pce_error", ...result}`；例外 `_err_with_log("policy_explain", exc, lang=lang)`。

- [ ] **Step 1 — 紅**：`tests/test_policy_explain.py`：用 Task 4 fixture 假造 `api.rule_search`、固定的 `fetch_managed_workloads`／`get_ip_lists` 回傳（照 `design/v2/snapshots` 的 workload 形狀：`href` 與 `interfaces[].address`）。案例：href 直接用；IP→workload；IP→iplist（cidr 與 range）；兩側 unresolved 不打 PCE；PCE 4xx 帶回 `pce_error`；proto 名稱→數字；快取命中不重打（計數 mock 呼叫次數）；allow_hit fixture 整形成 RuleHit 的每個鍵都有值。
- [ ] **Step 2 — 紅**：`tests/test_gui_policy_explain.py`：登入＋CSRF；400 缺欄位；200 正常（monkeypatch `explain_flow`）；502 PCE 錯誤。
- [ ] **Step 3 — 綠**：實作兩檔＋註冊。
- [ ] **Step 4 — 驗證**：`timeout 600 python3 -m pytest tests/test_policy_explain.py tests/test_gui_policy_explain.py tests/test_filter_object_cache.py -q`；`python3 scripts/audit_i18n_usage.py`。
- [ ] **Step 5 — Commit**：`feat(policy): explain which PCE rules cover a flow`

---

### Task 6: 文件、CHANGELOG、真機驗證

**Files:**
- Modify: `docs/reference/rest-api.md`（三組端點）、`docs/guide/monitoring-alerts.md`（「告警紀錄」一節：落地位置、狀態、保留期＝archive retention、force_test 不落地、重播更新）、`docs/guide/configuration.md`（無新鍵，只在 retention 說明處加一句）、`CHANGELOG.md` Unreleased
- Test: 既有 `scripts/check_doc_links.py`、`tests/test_docs_check.py`

真機驗證（測試機，全部以 service 帳號執行，證據存 `tmp/phase3a-verification/`，gitignored）：
1. 部署：`ssh illumio-ops-test 'cd /root/illumio-ops && git pull --ff-only -q origin main && git rev-parse --short HEAD && systemctl restart illumio-ops && sleep 6 && systemctl is-active illumio-ops'`。
2. 等兩個 monitor cycle（lab 24h 約 50 則告警），`ls -l logs/alerts.sqlite` 必須 `illumio-ops illumio-ops` 0600；`GET /api/alerts` 用 GUI 帳密（1Password `op://Lab/<item>/...`，僅注入子程序）取回列數＞0、`counts.new`＞0；隨機一則 `traffic_query` 回 200。
3. `PATCH` 一則為 `ack` 再改回 `new`。
4. `POST /api/policy/explain` 三種：lab 已知 allow 規則涵蓋的 flow（Task 4 用的那組）→ `allow` 非空；同來源打一個沒有 rule 的 port → `allow` 空、`source="pce_rule_search"`；未管理 IP（例如 8.8.8.8）→ 走 iplist 或 `source="none"`。
5. journal 無 traceback：`journalctl -u illumio-ops --since "15 min ago" | grep -i traceback`。
6. 清理：只刪測試建立的東西（PATCH 已還原；alerts.sqlite **保留**——它是產品資料）。

- [ ] **Step 1**：寫文件與 CHANGELOG；`python3 scripts/check_doc_links.py`、`timeout 300 python3 -m pytest tests/test_docs_check.py -q`。
- [ ] **Step 2**：全套閘門（路線圖清單）。
- [ ] **Step 3 — Commit**：`docs(alerts): document the alert record API and policy explain`；push；`gh run watch`。
- [ ] **Step 4**：真機驗證 1–6，結果寫 `tmp/phase3a-verification/report.md`，交使用者。

---

## 自審紀錄（撰寫時）

- spec §4a 欄位 `rule_index` → 本計畫改 `rule_id`（原因見 Global Constraints）；spec 需在 3A 合入時同步一行更正。
- spec §4a「首次派送就寫、重播更新」→ Task 2 以 DLQ entry 的 `alert_ids` 平行清單實現，不需要 (type, rule, fired_at) 複合鍵；告警 item 本身不加內部鍵（webhook 整包序列化）。
- spec §4a `rule_index` 已於本計畫同一 commit 更正為 `rule_id`（使用者核可的段落有改動，交付時明說）。
- advisor 2026-09-03 審後補：K8s/container workload actor、Rule Search 探測 E–H、retention 獨立 job、`str(rule["id"])`。
- spec §4b 的 `GET /api/alerts/<id>/traffic_query` 在 Task 3；`?alert=`／`?f=` 路由讀取在 3B。
- spec §4c「本地 resolver 展開規則」縮小為「本地 iplist 對應後再問 PCE」；純本地展開留為 3B 之後的 follow-up（若 lab 實測 Rule Search 對 ip_list actor 不支援才需要）。
- 型別一致性：`AlertStore.insert` 的 `type` 值集合＝schema CHECK＝`/api/alerts?type=` 白名單；`Actor`／`RuleHit` 鍵名在 Task 5 與 3B 的規則面板契約一致（3B 撰寫時抄本檔）。
