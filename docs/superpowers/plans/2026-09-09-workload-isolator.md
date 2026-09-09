# Workload Isolator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** EDR／SOAR 可用 API key 呼叫 webhook 隔離／釋放 workload（label、full 或兩者），TTL 自動還原，紀錄可還原，GUI 可管理。

**Architecture:** `src/isolation/{keys.py,store.py,service.py}` 純服務層；`src/gui/routes/isolation.py` 兩個 API-key 路由＋session 路由；`tick_isolation_ttl` 排程；`#/investigate/isolation` 頁與 `#/system/security` API keys 卡。

**Tech Stack:** Flask／flask-limiter／argon2（`src/config.py`）／APScheduler；ES modules；Playwright。

**Spec:** `docs/superpowers/specs/2026-09-09-workload-isolator-design.md`

## Global Constraints

- 分支 `feat/workload-isolator` 自 main，**在 fleet 合併之後**（依賴 `ApiClient.bulk_update_workloads`）。
- 既有 `/api/quarantine/*` 與 Mild/Moderate/Severe 不動；isolator 用 `Quarantine=<isolation.label_value>`（預設 `Isolated`）。
- API key 明文只在建立回應出現一次；任何 log、回應、GET 都不得含 secret 或 hash。
- webhook 路由必須：加進 `src/gui/__init__.py:568` 公開清單、`@csrf.exempt`、限流、423 gate 豁免；IP allowlist 不豁免。
- `previous_mode` 缺→不還原、標 `needs_manual_review`。
- 提交只 `git add <路徑>`；全套閘門同其他子專案。

---

### Task 1: keys 與 store

**Files:**
- Create: `src/isolation/__init__.py`、`src/isolation/keys.py`、`src/isolation/store.py`
- Test: `tests/test_isolation_keys.py`、`tests/test_isolation_store.py`

**Interfaces（Produces）:**
```python
# keys.py
class ApiKeyStore(path="config/isolation_api_keys.json")   # ScheduleDB 模式（file_lock + mkstemp + corrupt 隔離）
    def create(self, name: str, created_by: str) -> tuple[str, dict]   # (plaintext "iok_<id8>.<secret32>", public record)
    def verify(self, presented: str) -> dict | None          # 找不到 id 亦跑 dummy argon2；revoked→None；成功回 public record
    def revoke(self, key_id: str) -> bool
    def list_public(self) -> list[dict]                      # 不含 secret_hash
    def touch(self, key_id: str, now) -> None               # last_used_at，60 秒節流
# store.py
class IsolationStore(path="config/isolations.json")
    def put(self, record: dict) -> None; def get(self, record_id) -> dict|None
    def active(self) -> list[dict]; def by_href(self, href) -> dict|None; def recent(self, limit=50) -> list[dict]
    def with_lock(self)  # contextmanager，供 service 做「檢查上限＋寫 pending」原子操作
```
record 欄位照 spec §4。

**Acceptance / Tests（TDD）:** create→verify 通過；錯 secret／錯 id／revoked→None；`list_public` 無 hash 欄；壞檔隔離；store `active()` 只回 status ∈ {pending, active, needs_manual_review}；`with_lock` 內兩執行緒競爭只有一個過上限。

Run: `timeout 600 python3 -m pytest tests/test_isolation_keys.py tests/test_isolation_store.py -q`

Commit: `feat(isolation): revocable API keys and a restorable isolation record store`

---

### Task 2: 服務層

**Files:**
- Create: `src/isolation/service.py`
- Modify: `src/api_client.py`（若尚無 `search_workloads` 精確過濾 helper，於 service 內做）
- Test: `tests/test_isolation_service.py`

**Interfaces:**
```python
METHODS = ("label", "full", "both")
def find_workload(api, target: str) -> dict            # raise NotFound / Ambiguous(candidates)
def isolate(api, cm, store, target, *, reason, source, ttl_seconds, method, actor, dry_run=False) -> dict
def release(api, cm, store, target_or_id, *, reason, actor) -> dict
def notify(cm, summary: str, payload: dict) -> None    # 新 Reporter(cm) 實例 → add_health_alert → send_alerts(channels=None)；例外吞並 log
```
- `isolate` 回 `{status: "isolated"|"already_isolated"|"dry_run"|"failed", record}`；限制與順序照 spec §4（鎖內寫 pending、both 半途回滾、unmanaged→`UnprocessableTarget`）。
- label 步驟照 `actions.py:530-572` 的整組替換；full 步驟 `api.bulk_update_workloads([{"href":..., "enforcement_mode":"full"}])` 並檢查逐筆 status。
- `release`：依 record 的 method 還原；label 只移除 `isolation.label_value` 那一個 href（不碰 Mild/Moderate/Severe）。

**Acceptance / Tests（fake api 記錄呼叫）:** 三 method 呼叫序列；both 第二步失敗回滾第一步且 status failed；already_isolated；max 109 上限；previous_mode 缺→needs_manual_review；dry_run 零呼叫；notify 後 AlertStore 只多一列 type=system（用 `_isolate_alert_store` fixture）；ambiguous。

Run: `timeout 600 python3 -m pytest tests/test_isolation_service.py -q`

Commit: `feat(isolation): isolate/release with label, full or both, and a single-alert notification`

---

### Task 3: 路由、TTL job、設定鍵

**Files:**
- Create: `src/gui/routes/isolation.py`（`make_isolation_blueprint(cm, csrf, limiter, login_required)`）
- Modify: `src/gui/__init__.py:503-512`（註冊）、`:568`（公開清單加兩 webhook 路徑）、423 gate 豁免 endpoint 名
- Modify: `src/gui/routes/config.py:46-130` 或同檔新路由（`GET/POST /api/security/api-keys`、`DELETE /api/security/api-keys/<id>`，`@limiter.limit("10 per hour")`）
- Modify: `src/scheduler/jobs.py`（`tick_isolation_ttl(cm)`）、`src/scheduler/__init__.py:134-142` 註冊（`isolation.ttl_check_interval_seconds` 預設 60）
- Modify: `src/gui/_helpers.py:177-179`（settings allowlist 加 `isolation_default_method`、`isolation_label_value`、`isolation_max_isolated`）
- Modify: `docs/reference/rest-api.md`（先寫端點，讓 `tests/test_docs_check.py` 同步）
- Test: `tests/test_isolation_webhook.py`、`tests/test_isolation_ttl_job.py`、`tests/test_isolation_api_keys_api.py`

**Interfaces（路由）:**
- `POST /api/isolation/webhook/isolate`、`/release`：Bearer 驗證（`ApiKeyStore.verify`）；body 照 spec §3；回應碼 200／401／404／409／422；限流 IP `120 per minute`＋key id `60 per minute`（記憶體 sliding window）。
- session 路由：`GET /api/isolation/records?status=&limit=`、`POST /api/isolation/isolate`（同 body，actor＝使用者）、`POST /api/isolation/release`、`POST /api/isolation/extend {id, ttl_seconds}`。
- `GET /api/isolation/status` → `{active_count, max, ruleset_warning, default_method, label_value}`（ruleset_warning 由 job 首跑寫入 `dashboard_summary.isolation`）。

**Acceptance / Tests:** 無 key 401、錯 key 401、CSRF 不擋 webhook；session 路由需登入；121 次→429；到期釋放；失敗 5 次→needs_manual_review＋告警；注入測試：把路徑從公開清單移除→401。

Run: `timeout 600 python3 -m pytest tests/test_isolation_webhook.py tests/test_isolation_ttl_job.py tests/test_isolation_api_keys_api.py tests/test_docs_check.py -q`

Commit: `feat(isolation): API-key webhook, session routes, TTL job and settings`

---

### Task 4: GUI

**Files:**
- Create: `src/static/js/v2/areas/isolation.mjs`（`mountIsolation`）
- Modify: `app.mjs:138-148`、`shell.mjs:39-44`、`page.mjs:160-199`、`store-map.mjs`（`isolation_records(params)`、`isolation_status`、`security_api_keys`）、`design/v2/tools/endpoints.yaml`、`tests/test_v2_coverage_live.py:183`（計數 +3）
- Modify: `src/static/js/v2/areas/system.mjs:2190-2296`（第三個 `panel("SY-17", …)` API keys：建立→modal 顯示明文一次＋複製；撤銷 confirm；last_used）
- Modify: `design/v3/coverage.yaml`（IV-25 清單、IV-26 手動隔離抽屜、IV-27 釋放／延長、IV-28 ruleset 警示條；SY-17）、`docs/guide/gui-tour.md`、i18n 三檔（`gui_iso_*`）
- Test: `tests/test_v2_isolation_e2e.py`

**Acceptance / Tests（stub）:** route mount＋anchors；method 選項旁 `full` 註記文案（catalogue 真值）；建立 key 後明文只出現一次且重新載入不再出現；釋放走 confirm modal；注入測試 IV-26。

Run: `timeout 900 python3 -m pytest tests/test_v2_isolation_e2e.py tests/test_v2_system_e2e.py tests/test_v2_coverage_live.py tests/test_docs_gui_tour_routes.py tests/test_i18n_js_key_refs.py -q`

Commit: `feat(gui): isolation page and API key management`

---

### Task 5: 文件、changelog、全套閘門、真機

`docs/reference/rest-api.md`（認證段落 :45 改寫、限流彙整、總數對帳）、`docs/guide/gui-tour.md`、`CHANGELOG.md`、spec 狀態；全套閘門；真機（lab）：建 key→對一台 selective workload 用 curl 跑 `both`＋TTL 120 秒，驗 label 加上、mode=full、到期還原、告警一列；結果附回報。

Commit: `docs(isolation): reference, guide and changelog`
