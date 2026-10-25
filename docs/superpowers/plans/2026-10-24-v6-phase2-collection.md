# illumio-ops v6 P2 資料收集與取數 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 執行方式待使用者選定（見文末）。

**Goal:** 把 PCE 的流量、事件、workload 清冊與勒索防護資料，以「可多維聚合」的形狀持續收進本機，並提供唯一的取數入口（FlowSource／EventSource＋filter 模型），讓 P3 的橫向移動分析、P4 告警、P5 報表、P6 工作台都從同一處拿資料。

**Architecture:** 大量資料放獨立的 `data/flows.sqlite`（換 PCE 時整個檔案重建），應用狀態留在 P1 的 `data/app.sqlite`。PCE 存取補齊集合 GET（>500 走 async）、async 流量查詢生命週期（含 draft 重算）、事件分窗；正規化與配對規則是領域核心純函式；收集器是服務層、由同行程排程依設定的間隔執行，共用一把流量庫寫入鎖與一個行程級 PCE 限速器。

**Tech Stack:** 沿用 P1（Python 3.12、Flask、APScheduler、pydantic 2、requests、stdlib sqlite3、loguru；React＋TS＋Vite；pytest、Playwright）。不新增執行期依賴。

**Spec:** `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md`（2026-10-24 修訂版核可；本階段主要依據 §5、§6.3、§6.4、§6.5「資料收集」、§6.5.1 版本能力偵測、§6.5.6、§6.5.7、§6.6 F1–F11 與角色表、§7）；路線圖 `docs/superpowers/plans/2026-10-24-v6-roadmap.md` P2 列。

## Global Constraints

- P1 計畫的 Global Constraints 全部沿用（Python 3.12、單一鎖檔、無 `print(`、路徑只從 `InstallPaths` 推、每表單一寫入者、值域只在 `domain/values.py`、憑證不外露、英文 conventional commits＋`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`、只 `git add <明確路徑>`、測試前景＋timeout、每次 commit 後 `git status --porcelain illumio_ops tests_v6 web scripts/v6` 為空、「前端建置」＝`bash scripts/v6/gen_contracts.sh && npm --prefix web run typecheck && npm --prefix web run build`）。
- **分支**：`feat/v6-p2-collection`，自 `feat/v6-p1-foundation` 的 HEAD 開出（P1 尚未合併，使用者尚未決定合併方式）；worktree `.worktrees/v6-p2`。每個任務開始前 `pwd && git branch --show-current`。
- **時間一律帶時區的 UTC**：送 PCE 的時間戳一律 `YYYY-MM-DDTHH:MM:SSZ`（`microsecond=0`）；PCE 對沒有時區或只有日期的值回 406。存庫一律 ISO 8601 UTC 字串。
- **失敗不得看起來像空結果**：PCE 失敗、截斷、async 失敗一律 raise 或記成缺口（`ingest_gaps`），絕不回 `[]` 後前進 watermark。
- **集合 GET 截斷只看「筆數 == 500」**，不看 `X-Total-Count`（帶篩選時它是未過濾總數，5.x 真機實測）。
- **不做流量抽樣或過濾**：抽樣會讓橫向移動偵測看不到流量（spec §6.5 修訂）。
- 新增的每個設定葉都要在 `tests_v6/gates/test_settings_readers.py` 登錄讀者；新增的每張表都要在 `illumio_ops/store/ownership.py` 登錄擁有者；新增的每條 `/api` 路由都要有前端呼叫者；新增的每個 i18n 鍵兩個語系都要有。
- 閘門清單（每個任務之間親自跑，同 `ci-v6.yml`）：`bash /tmp/claude-1000/-home-harry-rd-illumio-ops/6aaabc3b-4649-4766-bbbc-257b7e298b6c/scratchpad/gates.sh`（若 session 換了，依 `ci-v6.yml` 逐條重建：contracts 產生後 `git diff --exit-code`、typecheck、build、`ruff check illumio_ops tests_v6 scripts/v6`、`mypy --config-file mypy-v6.ini`、`python -m pytest tests_v6 -n auto --dist loadfile`）。

## Review Focus

1. **一個收集視窗失敗或只拿到一部分**（PCE 斷線、async 查詢 failed、下載 0 筆但 matches>0）：watermark 不得前進、記一筆 `ingest_gaps`，下一輪重試同一視窗。→ Task 6 `test_failed_window_keeps_watermark_and_records_gap`、`test_partial_download_is_not_success`。
2. **最小分窗仍碰到 200,000 上限**：寫入已拿到的資料、記 `truncated` 缺口，資料收集頁明說「這段時間的流量不完整」。→ Task 6 `test_cap_at_bisect_floor_records_truncated_gap`、Task 12 `test_status_reports_truncated_windows`。
3. **受管 workload 超過 500 而 async 集合 GET 失敗**：保留上一份清冊、狀態寫「清冊不完整」，絕不把前 500 筆當成全部。→ Task 4 `test_collection_at_500_without_async_raises_incomplete`、Task 7 `test_inventory_keeps_previous_on_incomplete`。
4. **收集進行中換了 PCE（url 或 org 改變）**：舊 PCE 的資料一筆不留、新 PCE 的資料不會寫進舊綁定；綁定不符時收集器拒寫。→ Task 9 `test_collector_refuses_mismatched_binding`、`test_reset_waits_for_running_collector`。
5. **兩端都受管的連線被各回報一次**：聚合時只算一次，發起端與服務端的 process／使用者都保留。→ Task 5 `test_two_sided_report_counts_once`、`test_pairing_rejects_ranges_more_than_600s_apart`。

---

### Task 0: PCE 事實實測（已於計畫撰寫時完成）

- 已實測並寫入 spec §6.6（commit `e9c66d9b`）：`read_only` 可做全部新增讀取（`update_rules`、`risk_details`、`/reports/risk_summary`、`/app_groups/risk_summary`、竄改事件）；app group 逐服務 `risk_details` 端點位置未知（404）；雙端回報約 4% 的組、配對規則見 F11。
- 未驗而本階段要驗：async 集合 GET（`Prefer: respond-async`）的 Jobs API 流程——Task 4 以 lab 的 `/events`（12 萬筆）實測。

---

### Task 1: 設定 schema v2（`collection` 段）與通用版本升級

**Files:**
- Create: `illumio_ops/settings/upgrade.py`、`tests_v6/settings/test_upgrade.py`
- Modify: `illumio_ops/settings/schema.py`、`illumio_ops/settings/store.py`、`tests_v6/gates/test_settings_readers.py`、`tests_v6/settings/test_schema.py`

**Interfaces:**
- Produces:
  - `SCHEMA_VERSION: Literal[2] = 2`；`Settings.schema_version: Literal[2]`；`Settings.collection: CollectionSettings`
  - ```python
    class RetentionSettings(StrictModel):
        flow_days: int = Field(ge=1, le=3650)
        event_days: int = Field(ge=1, le=3650)
        rollup_days: int = Field(ge=1, le=3650)
        baseline_days: int = Field(ge=7, le=365)
        # model_validator: flow_days >= baseline_days 且 rollup_days >= flow_days；錯誤訊息不含數值
    class ArchiveSettings(StrictModel):
        enabled: bool
        retention_days: int = Field(ge=0, le=3650)   # 0 = 永久保留
    class CollectionSettings(StrictModel):
        enabled: bool
        traffic_interval_seconds: int = Field(ge=300, le=86400)
        events_interval_seconds: int = Field(ge=60, le=3600)
        inventory_interval_seconds: int = Field(ge=900, le=86400)
        rate_limit_per_minute: int = Field(ge=10, le=1000)
        backfill_days: int = Field(ge=0, le=90)
        disk_free_warn_gb: int = Field(ge=1, le=100000)
        retention: RetentionSettings
        archive: ArchiveSettings
    ```
  - `default_settings()` 的值：`enabled=True, traffic_interval_seconds=600, events_interval_seconds=300, inventory_interval_seconds=3600, rate_limit_per_minute=400, backfill_days=30, disk_free_warn_gb=10, retention=(flow_days=35, event_days=90, rollup_days=180, baseline_days=30), archive=(enabled=False, retention_days=0)`
  - `illumio_ops/settings/upgrade.py`：`UPGRADES: dict[int, Callable[[dict[str, Any]], dict[str, Any]]]`（鍵＝來源版本）；`def upgrade(data: dict[str, Any]) -> dict[str, Any]`：依 `schema_version` 逐版套用到 `SCHEMA_VERSION`；`1 → 2` 加入上列預設的 `collection`；`schema_version` 大於目前版本 → `SettingsInvalid([("schema_version", "newer than this program")])`；不是 dict 或沒有整數 `schema_version` → 原樣交給驗證（讓驗證報錯）。
  - `validate_settings(data)` 先 `upgrade` 再驗證——`SettingsStore.load`、`rescue`、遷移器、`install.sh` 預檢都經過它，只升級記憶體，**不寫檔**；下一次 `update` 才以 v2 寫回。

- [ ] **Step 1：寫失敗測試**：`test_v1_file_loads_as_v2_in_memory`（檔案內容與 mtime 不變）、`test_invalid_v1_file_still_writes_nothing`、`test_first_update_after_upgrade_writes_v2_without_conflict`、`test_newer_schema_version_is_refused`、`test_retention_flow_days_below_baseline_is_invalid`、`test_retention_rollup_below_flow_is_invalid`、`test_collection_unknown_key_is_invalid`；守門登錄：新葉全部登錄讀者（Task 6–8、12 的模組；尚未存在的先放 `PENDING_READERS` 標 `"P2-T6"` 等）、`pce.events_timeout_seconds` 從 PENDING 改為 `"P2-T6"`。
- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/settings tests_v6/gates/test_settings_readers.py tests_v6/test_rescue.py tests_v6/migrate -q` → FAIL。
- [ ] **Step 3：實作**（`migrate/v5.py` 只需讓輸出帶 `collection` 預設，`pce_cache` 段的對應留給 Task 13）。
- [ ] **Step 4：跑同一命令 → PASS；跑全部 `tests_v6` → PASS。**
- [ ] **Step 5：Commit** `git add illumio_ops/settings tests_v6/settings tests_v6/gates/test_settings_readers.py && git commit -m "feat(v6): settings schema v2 with collection section and in-memory version upgrade"`

---

### Task 2: 流量資料庫、跨庫單一寫入者守門與共用限速器

**Files:**
- Create: `illumio_ops/store/flowdb/__init__.py`、`illumio_ops/store/flowdb/db.py`、`illumio_ops/store/flowdb/migrations/__init__.py`、`illumio_ops/store/flowdb/migrations/0001_flows.sql`、`tests_v6/store/test_flowdb.py`
- Modify: `illumio_ops/store/db.py`（`migrate` 參數化套件名）、`illumio_ops/store/ownership.py`、`illumio_ops/paths.py`、`illumio_ops/services/context.py`、`tests_v6/gates/test_single_writer.py`、`tests_v6/test_paths.py`

**Interfaces:**
- Produces:
  - `InstallPaths.flows_db -> data/flows.sqlite`、`InstallPaths.archive_dir -> data/archive`（`ensure_dirs` 一併建立，0700）
  - `store/db.py`：`def migrate(conn, package: str = "illumio_ops.store.migrations") -> int`（行為不變，只多套件參數）
  - `store/flowdb/db.py`：`class FlowDb`：`__init__(self, path: Path)`、`connect(self) -> sqlite3.Connection`（同 `store.db.connect` 的 PRAGMA；首次連線跑 `migrate(conn, "illumio_ops.store.flowdb.migrations")`）、`write_lock: threading.Lock`（所有寫入流量庫的服務必須持有）、`reset(self) -> None`（持鎖、刪除 db／-wal／-shm 後重建並 migrate；Task 9 使用）
  - `AppContext` 新增：`flowdb: FlowDb`、`rate_limiter: RateLimiter`（行程唯一；`pce_factory` 一律注入它；設定的 `collection.rate_limit_per_minute` 改變時呼叫 `set_rate`）、`scheduler: BackgroundScheduler | None = None`
  - `0001_flows.sql`（全部表名在兩庫之間唯一；擁有者寫在註解並登錄 `TABLE_OWNERS`）：
    - `pce_binding(id INTEGER PRIMARY KEY CHECK (id=1), pce_url TEXT NOT NULL, org_id TEXT NOT NULL, bound_at TEXT NOT NULL)` → `illumio_ops.store.flowdb.binding`
    - `ingest_state(source TEXT PRIMARY KEY, watermark TEXT, last_started_at TEXT, last_finished_at TEXT, last_ok_at TEXT, last_error TEXT, last_rows INTEGER, consecutive_failures INTEGER NOT NULL DEFAULT 0, progress_json TEXT)`、`ingest_gaps(id INTEGER PRIMARY KEY, source TEXT NOT NULL, window_start TEXT NOT NULL, window_end TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('failed','truncated')), detail TEXT, recorded_at TEXT NOT NULL, resolved_at TEXT)` → `illumio_ops.store.flowdb.ingest_state`
    - `label_sets(id INTEGER PRIMARY KEY, signature TEXT NOT NULL UNIQUE)`、`label_set_members(set_id INTEGER NOT NULL REFERENCES label_sets(id), key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (set_id, key))` → `illumio_ops.store.flowdb.labels`
    - `flows(id INTEGER PRIMARY KEY, record_key TEXT NOT NULL UNIQUE, conn_key TEXT NOT NULL, is_primary INTEGER NOT NULL, direction TEXT NOT NULL, src_ip TEXT NOT NULL, dst_ip TEXT NOT NULL, src_key TEXT NOT NULL, dst_key TEXT NOT NULL, src_href TEXT, dst_href TEXT, src_hostname TEXT, dst_hostname TEXT, src_managed INTEGER NOT NULL, dst_managed INTEGER NOT NULL, src_mode TEXT, dst_mode TEXT, src_label_set INTEGER, dst_label_set INTEGER, port INTEGER, proto INTEGER NOT NULL, initiator_process TEXT, initiator_user TEXT, service_process TEXT, service_user TEXT, windows_service TEXT, policy_decision TEXT NOT NULL, first_detected TEXT NOT NULL, last_detected TEXT NOT NULL, num_connections INTEGER NOT NULL, bytes_in INTEGER, bytes_out INTEGER, state TEXT, transmission TEXT, network_href TEXT, origin TEXT NOT NULL CHECK (origin IN ('ingest','backfill')), ingested_at TEXT NOT NULL)`；索引：`last_detected`、`conn_key`、`(is_primary, last_detected)`、`src_key`、`dst_key`、`(port, proto)`、`initiator_user`、`initiator_process`、`(src_ip, dst_ip, port, proto)`
    - `flow_rollup_daily(day TEXT, src_key TEXT, dst_key TEXT, port INTEGER, proto INTEGER, policy_decision TEXT, initiator_user TEXT, initiator_process TEXT, connections INTEGER NOT NULL, flow_records INTEGER NOT NULL, bytes_in INTEGER NOT NULL, bytes_out INTEGER NOT NULL, bytes_known_records INTEGER NOT NULL, PRIMARY KEY (day, src_key, dst_key, port, proto, policy_decision, initiator_user, initiator_process))`——**主鍵欄不得為 NULL**：`port` 無值存 `-1`，使用者／process 無值存 `''`（SQLite 把 NULL 主鍵視為互不相等）
    - `connection_baseline(src_key, dst_key, port, proto, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, PRIMARY KEY (src_key, dst_key, port, proto))`、`user_baseline(initiator_user, dst_key, port, proto, first_seen, last_seen, PRIMARY KEY (initiator_user, dst_key, port, proto))`
    - 上三者 → `illumio_ops.store.flowdb.flows`
    - `events(id INTEGER PRIMARY KEY, href TEXT NOT NULL UNIQUE, event_type TEXT NOT NULL, severity TEXT, status TEXT, timestamp TEXT NOT NULL, created_by_kind TEXT, created_by_name TEXT, created_by_href TEXT, workload_href TEXT, tamper_classification TEXT, raw_json TEXT NOT NULL, origin TEXT NOT NULL, ingested_at TEXT NOT NULL)`；索引 `timestamp`、`(event_type, timestamp)`、`(workload_href, timestamp)` → `illumio_ops.store.flowdb.events`
    - `workloads(href TEXT PRIMARY KEY, hostname TEXT, name TEXT, managed INTEGER NOT NULL, enforcement_mode TEXT, visibility_level TEXT, os_id TEXT, ven_version TEXT, label_set INTEGER, online INTEGER, risk_exposure TEXT, risk_percent REAL, risk_updated_at TEXT, fetched_at TEXT NOT NULL)`、`workload_snapshot_daily(day, href, enforcement_mode, visibility_level, risk_exposure, risk_percent, PRIMARY KEY (day, href))` → `illumio_ops.store.flowdb.workloads`
    - `ransomware_services(workload_href, name, port INTEGER, proto INTEGER, severity, category, protection_state, port_status, active_policy, draft_policy, recommendation, source_updated_at, fetched_at, PRIMARY KEY (workload_href, name, port, proto))`、`ransomware_snapshot_daily(day, workload_href, name, port, proto, severity, protection_state, port_status, PRIMARY KEY (day, workload_href, name, port, proto))`、`org_risk_snapshot_daily(day TEXT PRIMARY KEY, summary_json TEXT NOT NULL)` → `illumio_ops.store.flowdb.ransomware`
    - `pce_capabilities(name TEXT PRIMARY KEY, state TEXT NOT NULL CHECK (state IN ('supported','unsupported','unknown')), detail TEXT, checked_at TEXT NOT NULL)` → `illumio_ops.store.flowdb.capabilities`
    - `archive_log(kind TEXT, day TEXT, rows INTEGER NOT NULL, path TEXT NOT NULL, written_at TEXT NOT NULL, PRIMARY KEY (kind, day))` → `illumio_ops.store.flowdb.archive`
  - 單一寫入者守門改為掃 `illumio_ops/` 全部模組、比對兩庫的所有表（表名全域唯一，已由 TABLE_OWNERS 的 dict 鍵保證）

- [ ] **Step 1：寫失敗測試**：`test_flowdb_migrates_on_first_connect`、`test_flowdb_reset_drops_all_rows_and_keeps_schema`、`test_flowdb_newer_version_is_refused`、`test_rollup_pk_has_no_nullable_columns`（讀 `PRAGMA table_info`，主鍵欄全部 `notnull` 或由寫入端保證——以寫入 NULL 失敗斷言）、守門自我測試 `test_foreign_write_to_flowdb_table_is_caught`、`test_ensure_dirs_creates_archive_dir_0700`、`test_context_injects_shared_rate_limiter`（`ctx.pce_factory(cfg)` 建出的 client 用的是 `ctx.rate_limiter`）。
- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/store tests_v6/gates/test_single_writer.py tests_v6/test_paths.py -q` → FAIL。
- [ ] **Step 3：實作。**
- [ ] **Step 4：跑同一命令 → PASS；全部 `tests_v6` → PASS。**
- [ ] **Step 5：Commit** `git add illumio_ops/store illumio_ops/paths.py illumio_ops/services/context.py tests_v6/store tests_v6/gates/test_single_writer.py tests_v6/test_paths.py && git commit -m "feat(v6): separate flow database with schema, write lock and shared PCE rate limiter"`

---

### Task 3: 正規化與配對（領域核心，純函式）

**Files:**
- Create: `illumio_ops/domain/flows.py`、`illumio_ops/domain/events.py`、`illumio_ops/domain/identity.py`、`tests_v6/domain/test_flows.py`、`tests_v6/domain/test_events.py`、`tests_v6/domain/test_identity.py`、`tests_v6/fixtures/pce/flows_sample.json`、`tests_v6/fixtures/pce/events_tamper.json`
- Modify: `illumio_ops/domain/values.py`

**Interfaces:**
- Produces:
  - `values.py` 新增：`class FlowDirection(StrEnum): INBOUND="inbound"; OUTBOUND="outbound"`；`class VisibilityLevel(StrEnum): FLOW_SUMMARY="flow_summary"; ENHANCED_DATA_COLLECTION="enhanced_data_collection"; FLOW_DROPS="flow_drops"; FLOW_OFF="flow_off"`；`class TamperClassification(StrEnum): CONFIRMED="confirmed"; SIGNAL="signal"`；`class IngestSource(StrEnum): TRAFFIC; EVENTS; INVENTORY; RANSOMWARE; BACKFILL`；`class DataOrigin(StrEnum): INGEST="ingest"; BACKFILL="backfill"`；全部加進 `_ENUMS`
  - `def visibility_sees_allowed(level: str | None) -> bool | None`：`flow_summary`、`enhanced_data_collection` → True；`flow_drops`、`flow_off` → False；其他或 None → None（未知，不猜）。依據：官方 REST API 文件（flow_drops 只記 blocked 與 potentially blocked、flow_off 不記錄）
  - `identity.py`：`def endpoint_key(href: str | None, ip: str) -> str`（有 href 用 href，否則 `"ip:" + ip`）；`def normalize_process(name: str | None) -> str | None`（去掉 `/` 與 `\` 之前的路徑；結尾 `.exe` 或原字串含 `\` 時轉小寫；空字串 → None）；`def split_user(name: str | None) -> tuple[str | None, str | None]`（`DOMAIN\acct` → `(DOMAIN, acct)`；`acct@domain` → `(domain, acct)`；`root` → `(None, "root")`）；`SYSTEM_ACCOUNTS: frozenset[str]`（比對小寫完整帳號：`nt authority\system`、`nt authority\local service`、`nt authority\network service`、`root`、`daemon`、`nobody`、`systemd-*` 前綴另以函式 `is_system_account(user: str | None) -> bool` 判斷）
  - `flows.py`：`@dataclass(frozen=True) class FlowRecord`（欄位同 `flows` 表除 `id`、`conn_key`、`is_primary`、`origin`、`ingested_at`；`src_labels`／`dst_labels: tuple[tuple[str, str], ...]`；時間為 aware `datetime`；`own_process`、`own_user` 為回報端的值）；`class FlowShapeError(ValueError)`；`def normalize_flow(raw: Mapping[str, Any]) -> FlowRecord`——欄位對應（lab 實測）：`src.ip`、`src.workload.{href,hostname,enforcement_mode,managed,labels[{key,value}]}`、`dst` 同、`service.{port,proto,process_name,user_name,windows_service_name}`、`policy_decision`、`flow_direction`、`timestamp_range.{first_detected,last_detected}`、`num_connections`、`dst_bi`→`bytes_in`、`dst_bo`→`bytes_out`（目的端視角，缺欄位 → None，**不得補 0**）、`state`、`transmission`、`network.href`；缺 `src.ip`／`dst.ip`／`timestamp_range`／`flow_direction`／`policy_decision` → `FlowShapeError`
  - `def record_key(r: FlowRecord) -> str`：`sha256("|".join([direction, src_ip, dst_ip, str(port), str(proto), first_detected_iso]))` hex
  - `def same_connection(a: FlowRecord, b: FlowRecord, *, max_gap_seconds: int = 600) -> bool`：方向相反、`(src_ip, dst_ip, port, proto)` 相同、且兩個 `[first, last]` 區間重疊或間隔 ≤ `max_gap_seconds`（spec §6.6 F11；**不得用 first_detected 相等**）
  - `events.py`：`@dataclass(frozen=True) class EventRecord`（欄位同 `events` 表除 `id`、`origin`、`ingested_at`）；`def normalize_event(raw) -> EventRecord`：`created_by` 取 `agent`／`ven`／`user`／`service_account`／`system` 其一為 `created_by_kind`；`agent.tampering` 時 `tamper_classification` 取 `notifications[].info.event_classification`，值不在 enum → 原字串保留、`None` 表示沒有該欄；`workload_href` 取 `created_by.agent.href` 對應的 workload（`created_by.ven.href` 亦同）
  - fixtures：由 lab 實際回應截取 30 筆 flow（含兩端受管且雙端回報的一對、只有使用者沒有 process 的 Linux outbound、帶 `dst_bi` 與不帶的、`enforcement_boundaries` 有值的）與 4 筆竄改事件（confirmed／signal 各 2）；主機名稱與 IP 改為 `host-NN`／`10.0.0.NN`，不得含任何憑證或客戶資料

- [ ] **Step 1：寫失敗測試**：`test_normalize_flow_maps_lab_fields`、`test_missing_bytes_stay_none`、`test_missing_required_field_raises_shape_error`、`test_record_key_differs_by_direction`、`test_same_connection_overlap_and_600s_gap`、`test_same_connection_rejects_same_direction`、`test_pairing_rejects_ranges_more_than_600s_apart`（區間相距 601 秒 → False）、`test_normalize_process_strips_path_and_lowercases_windows`、`test_split_user_three_forms`、`test_is_system_account`、`test_visibility_sees_allowed_table`（四值＋未知）、`test_tamper_classification_parsed`、`test_events_timestamps_are_aware_utc`。
- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/domain -q` → FAIL。
- [ ] **Step 3：實作。**
- [ ] **Step 4：跑同一命令 → PASS。**
- [ ] **Step 5：Commit** `git add illumio_ops/domain tests_v6/domain tests_v6/fixtures && git commit -m "feat(v6): flow and event normalization with dual-report pairing rule"`

---

### Task 4: PCE 存取補齊——集合 GET、async 流量查詢、事件分窗、能力登錄

**Files:**
- Create: `illumio_ops/pce/collections.py`、`illumio_ops/pce/async_query.py`、`illumio_ops/pce/events.py`、`illumio_ops/pce/capabilities.py`、`tests_v6/pce/test_collections.py`、`tests_v6/pce/test_async_query.py`、`tests_v6/pce/test_events.py`、`tests_v6/pce/test_capabilities.py`
- Modify: `illumio_ops/pce/client.py`（`request` 加 `headers: Mapping[str, str] | None = None`）、`tests_v6/pce/test_client.py`
- 來源（複製後改寫，commit 註明）：`src/api_client.py:1083-1145,1225-1242`（集合截斷與 Jobs API）、`src/api/traffic_query.py:690-875`（submit／poll／update_rules／download，**只留一份**）、`tests/test_api_collection_truncation.py`、`tests/test_traffic_query_retry.py`、`tests/test_api_pce_contract.py:209-241`

**Interfaces:**
- Consumes: `PceClient.request`（Task 2 後注入共用限速器）
- Produces:
  - `collections.py`：`class PceCollectionIncomplete(Exception)`（屬性 `path`、`partial_count`、`reason`）；`def get_all(client: PceClient, path: str, *, params: Mapping[str, str], deadline: float) -> list[dict[str, Any]]`：先同步 GET（`max_results=500`）；回傳筆數 < 500 → 完整；== 500 → 以同路徑同參數送 `Prefer: respond-async`，期望 202＋`Location`，輪詢該 job（`Retry-After` 夾在 [2, 10] 秒）直到 `status == "done"` 後 GET `result.href`；任一步失敗、終局狀態為 `failed`／`cancel_requested`／`cancelled`／`canceled`、或超過 deadline → `raise PceCollectionIncomplete`（**不回前 500 筆**）
  - `async_query.py`：`class PceQueryError(Exception)`（`stage: Literal["submit","poll","failed","timeout","update_rules","download"]`、`status: int | None`）；`@dataclass(frozen=True) class AsyncQueryResult: rows: list[dict[str, Any]]; matches_count: int | None; flows_count: int | None; capped: bool`；`def run_traffic_query(client: PceClient, payload: Mapping[str, Any], *, deadline: float, compute_draft: bool = False, delete_after: bool = True) -> AsyncQueryResult`：POST `/traffic_flows/async_queries` → 輪詢（間隔 2 秒起、每次 ×1.5、上限 10 秒；404／410 視為尚未就緒直到 deadline；終局失敗狀態同上加 `failed`、`killed`）→ `compute_draft` 時 `PUT {href}/update_rules {}` 並輪詢到 `status == "completed"` 且 `rules` 為 None／空字串／`"completed"`（遇失敗狀態 → `PceQueryError("update_rules")`）→ GET `{href}/download`（`Accept: application/json`；gzip 解壓失敗改當純文字；逐行解析並去掉 `[`、`]` 與行尾逗號）→ 下載 0 筆而 `matches_count > 0` → 等 3 秒重下一次，仍 0 → `PceQueryError("download")` → 成功後 `delete_after` 時 `DELETE {href}`（失敗只寫 log，不影響結果）；`capped = len(rows) >= payload["max_results"]`
  - `def traffic_payload(start: datetime, end: datetime, *, max_results: int, query_name: str, sources: dict | None = None, destinations: dict | None = None, services: dict | None = None, policy_decisions: list[str] | None = None) -> dict[str, Any]`：時間格式見 Global Constraints；預設 sources／destinations `{"include": [[]], "exclude": []}`、services `{"include": [], "exclude": []}`、`sources_destinations_query_op="and"`
  - `events.py`：`@dataclass(frozen=True) class EventsPage: items: list[dict[str, Any]]; capped: bool`；`def fetch_events(client: PceClient, *, start: datetime, end: datetime, timeout: float, deadline: float, max_results: int = 10000) -> EventsPage`：GET `/events?timestamp[gte]=…&timestamp[lte]=…&max_results=…`（bounded session，逐次 timeout＝`timeout`，在 deadline 內重試 5xx／逾時；非 2xx 其他狀態 → `PceQueryError("failed", status)`）；`capped = len(items) >= max_results`（PCE 在上限時只回最新的列，呼叫端必須分窗）；`def events_timeout(cfg: PceSettings) -> float`：`events_timeout_seconds` 有值用它，否則 SaaS 180、地端 30（5.x 契約）
  - `capabilities.py`：`CAPABILITIES: dict[str, Capability]`，`Capability(name, description_key, min_version_note)`，名稱：`ransomware_risk`（workload 有 `risk_summary` 欄）、`ransomware_org_summary`（`/reports/risk_summary` 200）、`visibility_level`（workload 有 `visibility_level` 欄）、`tamper_signal`（曾見過 `event_classification == "signal"`）、`draft_recompute`（`update_rules` 2xx）；狀態寫入由各收集器呼叫 `store.flowdb.capabilities.record(conn, name, state, detail)` 完成——偵測規則集中在 `capabilities.py` 的純函式 `detect_from_workloads(rows) -> dict[str, CapabilityState]` 等

- [ ] **Step 1：寫失敗測試**（以 `responses` 或 Task 9 的 fake PCE 模擬）：`test_collection_under_500_is_complete`、`test_collection_at_500_uses_async_and_returns_all`、`test_collection_at_500_without_async_raises_incomplete`、`test_collection_ignores_x_total_count`（header 寫 30、回 20 筆 → 完整）、`test_async_job_failed_state_raises`、`test_query_polls_until_completed_with_backoff`、`test_query_cancel_states_are_terminal`、`test_partial_download_is_not_success`（matches 5、下載 0、重下仍 0 → raise）、`test_download_retry_succeeds_second_time`、`test_compute_draft_runs_update_rules_and_waits`、`test_delete_after_failure_does_not_fail_result`、`test_payload_timestamps_have_z_and_no_microseconds`、`test_events_capped_flag_and_window_params`、`test_events_timeout_defaults_by_deployment`、`test_capability_detection_from_workload_fields`。
- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/pce -q` → FAIL。
- [ ] **Step 3：實作。**
- [ ] **Step 4：跑同一命令 → PASS；全部 `tests_v6` → PASS。**
- [ ] **Step 5：lab 實測 async 集合 GET（Task 0 未驗項）。** 寫一支一次性腳本（session scratchpad，不入庫），以 `get_all(client, "/events", params={"timestamp[gte]": <30 天前>}, deadline=…)` 對 lab 執行（lab 事件約 12 萬筆，必定觸發 async）；紀錄：202 與 `Location` 形狀、job 輪詢狀態序列、`result.href` 下載筆數與 X-Total-Count。憑證只注入子行程、不印出。若流程與實作不符 → 修正實作與測試，並把實測形狀寫進 `tests_v6/fixtures/pce/async_collection_job.json`。結果記入 `tmp/v6-p2-verification/ledger.md`。
- [ ] **Step 6：Commit** `git add illumio_ops/pce tests_v6/pce tests_v6/fixtures && git commit -m "feat(v6): PCE collections with async fallback, single async traffic query lifecycle, windowed events"`

---

### Task 5: 流量庫寫入——upsert、配對、標籤、基準期與日彙總

**Files:**
- Create: `illumio_ops/store/flowdb/flows.py`、`illumio_ops/store/flowdb/labels.py`、`illumio_ops/store/flowdb/events.py`、`tests_v6/store/test_flowdb_flows.py`、`tests_v6/store/test_flowdb_events.py`

**Interfaces:**
- Consumes: `FlowRecord`、`EventRecord`、`record_key`、`same_connection`、`endpoint_key`、`FlowDb`
- Produces:
  - `labels.py`：`def label_set_id(conn, labels: tuple[tuple[str, str], ...]) -> int | None`（空 → None；以排序後的 `key=value` 以 `\n` 串成 signature）
  - `flows.py`：`@dataclass(frozen=True) class UpsertStats: inserted: int; refreshed: int; paired: int; days_touched: frozenset[str]`；`def upsert_flows(conn, records: Sequence[FlowRecord], *, origin: DataOrigin, now: datetime) -> UpsertStats`——同一 transaction：
    1. 依 `record_key` upsert；衝突時 `last_detected`、`num_connections`、`bytes_in`、`bytes_out` 取較大值（`bytes` 一邊為 NULL 時取非 NULL），`state` 取 `last_detected` 較新一側；`origin` 已是 `ingest` 的列不得被 `backfill` 改寫
    2. 新列找配對：同 `(src_ip, dst_ip, port, proto)`、方向相反、`same_connection` 成立的既有列 → 沿用其 `conn_key`；否則 `conn_key = record_key`
    3. 自己這側寫 `initiator_*`（outbound）或 `service_*`（inbound）；配對成立時兩列互補對方欄位
    4. `is_primary`：每個 `conn_key` 恰一列為 1——有 outbound 時是 outbound，否則 inbound
    5. 更新 `connection_baseline`（主列，`first_seen = MIN`、`last_seen = MAX`）與 `user_baseline`（主列且 `initiator_user` 非空）
  - `def rebuild_rollup(conn, day: str) -> int`：刪除該日後由 `is_primary = 1` 且 `last_detected` 落在該日的列重算（`connections = SUM(num_connections)`、`flow_records = COUNT(*)`、`bytes_known_records = COUNT(bytes_in) `、主鍵欄 NULL 依 Task 2 規則轉值）；回傳列數
  - `events.py`：`def upsert_events(conn, records: Sequence[EventRecord], *, origin: DataOrigin, now: datetime) -> int`（`href` 衝突 → 不改，冪等）

- [ ] **Step 1：寫失敗測試**：`test_upsert_is_idempotent`、`test_repull_refreshes_volatile_columns_with_max`、`test_bytes_null_never_overwrites_known`、`test_backfill_does_not_downgrade_ingest_origin`、`test_two_sided_report_counts_once`（fixture 的雙端一對 → 同 `conn_key`、主列 1 筆、兩列都帶 initiator 與 service 欄）、`test_inbound_first_then_outbound_switches_primary`、`test_baseline_tracks_min_first_and_max_last`、`test_user_baseline_skips_empty_user`、`test_rollup_counts_primary_rows_only`、`test_rollup_null_keys_coalesced`、`test_events_upsert_idempotent`。
- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/store -q` → FAIL。
- [ ] **Step 3：實作。**
- [ ] **Step 4：跑同一命令 → PASS；全部 `tests_v6` → PASS（含單一寫入者守門）。**
- [ ] **Step 5：Commit** `git add illumio_ops/store/flowdb tests_v6/store && git commit -m "feat(v6): flow store upsert with connection pairing, baselines and daily rollup"`

---

### Task 6: 流量與事件收集器、收集狀態、動態排程

**Files:**
- Create: `illumio_ops/store/flowdb/ingest_state.py`、`illumio_ops/store/flowdb/binding.py`、`illumio_ops/store/flowdb/capabilities.py`、`illumio_ops/services/collect/__init__.py`、`illumio_ops/services/collect/traffic.py`、`illumio_ops/services/collect/events.py`、`illumio_ops/services/collect/guard.py`、`tests_v6/services/collect/test_traffic.py`、`tests_v6/services/collect/test_events.py`
- Modify: `illumio_ops/jobs/scheduler.py`、`illumio_ops/web/routes/system_jobs.py`、`illumio_ops/__main__.py`、`tests_v6/jobs/test_scheduler.py`

**Interfaces:**
- Produces:
  - `ingest_state.py`：`get(conn, source) -> IngestState | None`、`mark_started(conn, source, at)`、`mark_ok(conn, source, at, *, watermark: datetime, rows: int, progress: dict | None = None)`、`mark_failed(conn, source, at, error: str)`（`consecutive_failures + 1`、watermark 不動）、`record_gap(conn, source, start, end, kind, detail)`、`open_gaps(conn, source=None) -> list[Gap]`
  - `binding.py`：`current(conn) -> Binding | None`、`bind(conn, pce_url, org_id, at)`（只在空表時寫入）
  - `capabilities.py`：`record(conn, name: str, state: CapabilityState, detail: str | None, at)`、`all(conn) -> dict[str, CapabilityRow]`（`IngestState`、`Gap`、`Binding`、`CapabilityRow` 為欄位同表的 frozen dataclass）
  - `guard.py`：`class BindingMismatch(Exception)`；`def ensure_binding(conn, pce: PceSettings, now) -> None`：無綁定 → `bind`；有綁定且 `(pce_url, org_id)` 正規化後不同 → `raise BindingMismatch`（收集器拒寫，fail-closed）
  - `services/collect/__init__.py`：`@dataclass(frozen=True) class CycleResult: rows: int; windows: int; gaps: int`（所有收集器共用）
  - `traffic.py`：`def run_traffic_cycle(ctx: AppContext, *, now: datetime | None = None) -> CycleResult`：
    - `collection.enabled` 為 False 或 PCE 未設定 → 直接回傳、不算失敗
    - 視窗 `[watermark − 600 秒, now]`；無 watermark → `[now − 24 小時, now]`（回填另行處理，Task 8）
    - 每個視窗 `run_traffic_query(max_results=200000)`；`capped` → 對半分窗遞迴，最小視窗 60 秒、最大深度 12；最小視窗仍 capped → 寫入已拿到的列並 `record_gap(kind="truncated")`
    - 任一視窗 `PceQueryError`／`PceTransportError`／`PceBudgetExhausted` → `record_gap(kind="failed")`、`mark_failed`、**watermark 不前進**，例外不往上拋（由 job 記錄）
    - 成功 → 持 `ctx.flowdb.write_lock`：`ensure_binding` → `upsert_flows(origin=INGEST)` → 對 `days_touched` 逐日 `rebuild_rollup` → `mark_ok(watermark=now)`；同一視窗先前的 `failed` 缺口標 `resolved_at`
  - `events.py`：`def run_events_cycle(ctx, *, now=None) -> CycleResult`：視窗 `[watermark − 300 秒, now]`；`fetch_events(timeout=events_timeout(cfg))`；`capped` → 分窗規則同上（最小 60 秒）；寫入、狀態、缺口規則同流量；`agent.tampering` 見過 `signal` → `capabilities.record("tamper_signal", "supported")`
  - `jobs/scheduler.py`：`def job_intervals(settings: Settings) -> dict[str, int]`（取代靜態 `JOB_INTERVALS`；`pce_probe` 300、`tls_renew_check` 86400、`collect_traffic`、`collect_events`、`collect_inventory` 取自設定、`collect_retention` 86400、`collect_archive` 86400）；`def apply_schedule(sched, settings) -> None`（已存在的 job 依新間隔 `reschedule`）；`build_scheduler` 註冊全部 job（收集器 job 首次執行延後 30 秒）；`system_jobs` 與首頁過期判定改讀 `job_intervals(ctx.settings.current())`
  - `__main__.serve` 把建好的 scheduler 設進 `ctx.scheduler`

- [ ] **Step 1：寫失敗測試**（fake PCE：Task 4 的模擬層，可設定每個視窗的回應）：`test_traffic_cycle_writes_and_advances_watermark`、`test_failed_window_keeps_watermark_and_records_gap`、`test_cap_bisects_until_under_cap`、`test_cap_at_bisect_floor_records_truncated_gap`、`test_repeat_cycle_resolves_failed_gap`、`test_disabled_collection_is_noop_not_failure`、`test_events_cycle_bisects_on_10000_cap`、`test_events_timeout_from_settings`、`test_tamper_signal_marks_capability`、`test_collector_refuses_mismatched_binding`、`test_job_intervals_follow_settings`、`test_apply_schedule_reschedules_changed_interval`、`test_jobs_page_shows_settings_interval`。
- [ ] **Step 2：跑** `timeout 600 python3.12 -m pytest tests_v6/services tests_v6/jobs tests_v6/web/test_home.py -q` → FAIL。
- [ ] **Step 3：實作。**
- [ ] **Step 4：跑同一命令 → PASS；全部閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops tests_v6 && git commit -m "feat(v6): traffic and events collectors with gap tracking and settings-driven schedule"`
- [ ] **Step 6：Codex 對抗式審查**（使用者偏好）：以 `reviewer` profile 審 Task 2–6 的 diff，聚焦 Review Focus 1、2、4、5 與「watermark 何時前進」；每條 finding 親自查證再修，紀錄於 ledger。

---

### Task 7: 清冊與勒索防護收集、快照、可見度

**Files:**
- Create: `illumio_ops/store/flowdb/workloads.py`、`illumio_ops/store/flowdb/ransomware.py`、`illumio_ops/services/collect/inventory.py`、`tests_v6/services/collect/test_inventory.py`

**Interfaces:**
- Produces:
  - `workloads.py`：`@dataclass(frozen=True) class WorkloadRow`（欄位同 `workloads` 表）；`replace_inventory(conn, rows: Sequence[WorkloadRow], at)`（整份替換）、`snapshot_day(conn, day)`；`ransomware.py`：`upsert_services(conn, workload_href, services: Sequence[Mapping[str, Any]], *, source_updated_at, at)`、`snapshot_day(conn, day)`、`write_org_summary(conn, day, summary: Mapping[str, Any])`
  - `inventory.py`：`def run_inventory_cycle(ctx, *, now=None) -> CycleResult`：
    1. `get_all("/workloads", params={"managed": "true"})`——`PceCollectionIncomplete` → 保留上一份清冊、`mark_failed(source="inventory", error="incomplete")`，不往下做
    2. 寫清冊（hostname、mode、`visibility_level`、labels 經 `label_set_id`、VEN 版本、`risk_summary.ransomware`）；`detect_from_workloads` 寫能力
    3. `GET /reports/risk_summary` → 200 寫當日 `org_risk_snapshot_daily`、能力 supported；404 → unsupported；其他 → failed（不影響清冊）
    4. 對每台 `risk_summary.ransomware` 非 null 的主機，`risk_summary.last_updated_at` 與已存的 `source_updated_at` 不同才 `GET {href}/risk_details`（lab 實測全部主機時間相同：PCE 一次重算全部，所以每次重算後是一整輪；1,000 台在 400／分的預算下約 2.5 分鐘，與收集共用限速器）；路徑 `risk_details.ransomware.details[]`
    5. 每日第一次成功時寫 `workload_snapshot_daily` 與 `ransomware_snapshot_daily`
  - 可見度摘要（給 Task 12）：`def visibility_summary(conn) -> dict[str, int]`（依 `visibility_sees_allowed` 分 `sees_allowed`／`blocked_only`／`off`／`unknown` 計數）

- [ ] **Step 1：寫失敗測試**：`test_inventory_writes_visibility_and_risk`、`test_inventory_keeps_previous_on_incomplete`、`test_risk_details_fetched_only_when_updated_at_changes`、`test_risk_details_path_is_risk_details_ransomware_details`、`test_org_summary_404_marks_unsupported_not_failed`、`test_daily_snapshot_written_once_per_day`、`test_visibility_summary_buckets`。
- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/services/collect/test_inventory.py -q` → FAIL。
- [ ] **Step 3：實作。**
- [ ] **Step 4：跑同一命令 → PASS；全部閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops tests_v6 && git commit -m "feat(v6): workload inventory and ransomware protection collection with daily snapshots"`

---

### Task 8: 回填、保留、封存

**Files:**
- Create: `illumio_ops/services/collect/backfill.py`、`illumio_ops/services/collect/retention.py`、`illumio_ops/services/collect/archive.py`、`illumio_ops/store/flowdb/archive.py`、`tests_v6/services/collect/test_backfill.py`、`tests_v6/services/collect/test_retention.py`、`tests_v6/services/collect/test_archive.py`
- Modify: `illumio_ops/store/flowdb/flows.py`、`illumio_ops/store/flowdb/events.py`（加刪除函式）

**Interfaces:**
- Produces:
  - `backfill.py`：`def run_backfill(ctx, *, start: datetime, end: datetime, now=None) -> CycleResult`：以 UTC 日為單位**由舊到新**處理（基準期依時間累積），每日流量走 Task 6 的分窗規則、事件同；寫入 `origin=BACKFILL`；進度寫 `ingest_state(source="backfill").progress_json = {"start","end","done_through"}`；中斷後從 `done_through` 續做；不推進 `traffic`／`events` 的 watermark。`def ensure_initial_backfill(ctx) -> None`：綁定剛建立且 `backfill_days > 0` 時排一次 `[now − backfill_days, 流量 watermark 或 now]`
  - `retention.py`：`def run_retention(ctx, *, now=None) -> dict[str, int]`：刪 `flows.last_detected < now − flow_days`、`events.timestamp < now − event_days`、rollup 與三張每日快照 `day < now − rollup_days`、`connection_baseline`／`user_baseline` 的 `last_seen < now − baseline_days`；**封存啟用時，尚未寫入 `archive_log` 的日子不刪**；`ingest_gaps` 的 `recorded_at` 早於 `rollup_days` 刪除
  - `archive.py`：`def run_archive(ctx, *, now=None) -> int`：`archive.enabled` 時，對每個已完整過去（UTC 昨天以前）且未封存的日子，把該日 flows（表欄位，非原始 JSON）與 events（`raw_json`）寫成 `data/archive/{flows,events}-YYYY-MM-DD.jsonl.gz`（先寫暫存檔再 rename），寫 `archive_log`；`retention_days > 0` 時刪除超期檔案與其 `archive_log` 列

- [ ] **Step 1：寫失敗測試**：`test_backfill_oldest_first_and_resumes`、`test_backfill_marks_origin_and_seeds_baseline`、`test_backfill_does_not_move_ingest_watermark`、`test_initial_backfill_only_on_fresh_binding`、`test_retention_respects_unarchived_days`、`test_retention_prunes_baseline_by_last_seen`、`test_archive_writes_complete_days_once_atomically`、`test_archive_retention_deletes_old_files`。
- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/services/collect -q` → FAIL。
- [ ] **Step 3：實作。**
- [ ] **Step 4：跑同一命令 → PASS；全部閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops tests_v6 && git commit -m "feat(v6): backfill seeding the baseline, retention and daily archive"`

---

### Task 9: 換 PCE——唯一清除清單與收集器停等

**Files:**
- Create: `illumio_ops/services/collect/reset.py`、`tests_v6/services/collect/test_reset.py`
- Modify: `illumio_ops/web/routes/system_pce.py`、`illumio_ops/services/pce_health.py`、`tests_v6/web/test_system_pce.py`

**Interfaces:**
- Produces:
  - `reset.py`：`APP_DB_PCE_DERIVED: tuple[str, ...] = ("pce_probe",)`（app.sqlite 中屬於某個 PCE 的表；**唯一清單**，守門測試斷言：app.sqlite 的每張表要嘛在此、要嘛在 `APP_DB_PCE_INDEPENDENT = ("job_health",)`）；`def reset_for_new_pce(ctx, *, now=None) -> ResetReport`：持 `ctx.flowdb.write_lock`（等正在跑的收集器寫完）→ 把 `data/archive/` 現有檔案搬到 `data/archive/previous-<YYYYmmddTHHMMSSZ>/`（不刪客戶資料）→ `ctx.flowdb.reset()` → 清 `APP_DB_PCE_DERIVED` 各表（各自經擁有者模組的 `clear(conn)`）→ 回報搬移與清除的項目
  - `system.pce.update`：url 或 org_id 正規化後改變時，在寫入設定**前**呼叫 `reset_for_new_pce`；回應附 `reset: ResetReport | None`；前端顯示「已清除舊 PCE 的收集資料，並開始為新 PCE 回填」
  - `def pce_target_changed(old: PceSettings, new: PceSettings) -> bool`（同在 `reset.py`）：url 去尾斜線、小寫主機名後與 `org_id` 一起比對；P1「改 url 或 TLS 驗證要重輸憑證」的判斷不變，兩者用途不同

- [ ] **Step 1：寫失敗測試**：`test_reset_clears_flowdb_and_pce_probe`、`test_reset_moves_archive_aside_not_deletes`、`test_reset_waits_for_running_collector`（另一執行緒持鎖寫入中 → reset 在其釋放後才清）、`test_app_db_tables_are_classified`、`test_pce_update_same_target_does_not_reset`、`test_pce_update_new_org_resets_before_save`。
- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/services/collect/test_reset.py tests_v6/web/test_system_pce.py -q` → FAIL。
- [ ] **Step 3：實作。**
- [ ] **Step 4：跑同一命令 → PASS；全部閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops tests_v6 && git commit -m "feat(v6): change-PCE reset with a single derived-data list"`

---

### Task 10: filter 模型與三種編譯

**Files:**
- Create: `illumio_ops/domain/filter.py`、`tests_v6/domain/test_filter.py`

**Interfaces:**
- Produces:
  - ```python
    class LabelCond(StrictModel): key: str; values: tuple[str, ...]          # 同 key 多值 = OR
    class EndpointFilter(StrictModel):
        labels: tuple[LabelCond, ...]        # 跨 key = AND（5.x 真機事實：[[A,B]]=AND、[[A],[B]]=OR）
        hrefs: tuple[str, ...]; ips: tuple[str, ...]   # ip 或 CIDR
    class FilterSpec(StrictModel):
        start: AwareDatetime; end: AwareDatetime
        src: EndpointFilter | None; dst: EndpointFilter | None
        src_exclude: EndpointFilter | None; dst_exclude: EndpointFilter | None
        ports: tuple[PortProto, ...]; exclude_ports: tuple[PortProto, ...]   # PortProto(port: int | None, to_port: int | None, proto: int | None)
        decisions: tuple[PolicyDecision, ...]
        initiator_process: str | None; initiator_user: str | None     # 部分比對，支援 *，不分大小寫
        service_process: str | None; service_user: str | None
        text: str | None                    # 搜 hostname／IP／process／使用者，部分比對
        exclude_system_accounts: bool
    ```
  - `def to_pce_payload(spec: FilterSpec, *, max_results: int, query_name: str) -> tuple[dict[str, Any], FilterSpec]`：能下推 PCE 的（時間、label、href、IP、port／proto、decision）放進 payload；PCE 做不到的（使用者、process 部分比對、text、系統帳號排除）留在回傳的**殘餘** spec，由呼叫端逐筆套用。label 依同 key 分組 OR、跨 key AND 的 PCE 形狀編譯
  - `def to_sql(spec: FilterSpec, *, table_alias: str = "f") -> tuple[str, list[Any]]`：對 `flows`（主列）產生 `WHERE` 與參數；萬用字元 `*` 轉 `LIKE`（跳脫 `%`、`_`），一律 `COLLATE NOCASE`；label 條件以 `label_set_members` 子查詢
  - `def matches(spec: FilterSpec, record: FlowRecord | Mapping[str, Any]) -> bool`：逐筆判斷，語意與 `to_sql` 完全相同
  - **對 spec 的偏離（記入 ledger 的 Ruling）**：spec §6.3 寫三種編譯含 DataFrame；P2 以「PCE payload＋SQL＋逐筆 predicate」實作，DataFrame 形式等 P5 確定報表是否使用 pandas 再加——理由：P2 沒有 DataFrame 消費者，先做會是無讀者的程式（反目標 4）

- [ ] **Step 1：寫失敗測試**：`test_label_or_within_key_and_across_keys_in_payload`、`test_user_and_process_go_to_residual`、`test_sql_and_predicate_agree_on_fixture`（同一批 fixture 列寫入 sqlite，對 20 組 spec 比對兩者結果相同）、`test_wildcard_escapes_percent_and_underscore`、`test_cidr_match`、`test_exclude_system_accounts`、`test_spec_rejects_naive_datetime`。
- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/domain/test_filter.py -q` → FAIL。
- [ ] **Step 3：實作。**
- [ ] **Step 4：跑同一命令 → PASS。**
- [ ] **Step 5：Commit** `git add illumio_ops/domain/filter.py tests_v6/domain/test_filter.py && git commit -m "feat(v6): one filter model compiled to PCE payload, SQL and predicate"`

---

### Task 11: FlowSource／EventSource——唯一取數入口

**Files:**
- Create: `illumio_ops/services/flowsource.py`、`illumio_ops/services/eventsource.py`、`tests_v6/services/test_flowsource.py`、`tests_v6/services/test_eventsource.py`

**Interfaces:**
- Produces:
  - ```python
    class Coverage(BaseModel):
        source: Literal["store", "pce", "mixed"]   # 實際提供結果列的來源；呼叫過 PCE 但 PCE 補到 0 列仍算 "mixed"
        store_from: datetime | None; store_to: datetime | None   # 本機資料涵蓋的區間（最早保留列～流量 watermark）
        gaps: list[tuple[datetime, datetime, str]]                # 未涵蓋的區間與原因：before_retention / not_yet_collected / ingest_failed / truncated
        filled_from_pce: list[tuple[datetime, datetime]]
        truncated: bool
    class FlowRow(BaseModel): ...      # flows 表主列的欄位（不含 id、record_key），另加 src_labels／dst_labels: dict[str, str]
    class FlowQuery(BaseModel): rows: list[FlowRow]; coverage: Coverage; limit_hit: bool
    def query_flows(ctx, spec: FilterSpec, *, limit: int, order: Literal["last_detected_desc", "connections_desc"], fill_gaps: bool = False) -> FlowQuery
    ```
  - 規則：先算請求區間與本機涵蓋區間的差集；`ingest_gaps` 中尚未 resolved 的區間也列為缺口；本機部分用 `to_sql`（只取 `is_primary = 1`）；`fill_gaps=False`（預設）時缺口只列出、不打 PCE；`fill_gaps=True` 時對每個缺口 `run_traffic_query`＋`normalize_flow`＋殘餘 spec 的 `matches`，與本機結果以 `record_key` 去重、配對規則同 Task 5（記憶體內），**不寫入流量庫**；任一 PCE 呼叫失敗 → 該缺口保留在 `gaps`（原因 `ingest_failed`），不中斷整體、不偽裝成功
  - `eventsource.py`：`class EventQuery(BaseModel): rows: list[EventRow]; coverage: Coverage; limit_hit: bool`（`EventRow` 為 `events` 表欄位、`raw_json` 解析成 dict）；`def query_events(ctx, *, start, end, event_types: tuple[str, ...] = (), workload_href: str | None = None, limit: int, fill_gaps: bool = False) -> EventQuery`（`Coverage` 同義）
  - 這兩者是全專案讀流量庫與事件的唯一入口：新增守門 `tests_v6/gates/test_single_reader.py`——`illumio_ops/services/` 與 `illumio_ops/web/` 中，除 `flowsource.py`、`eventsource.py`、`collect/*` 與 Task 12 的狀態模組外，不得出現 `FROM flows`／`FROM events` 字串（附注入違規的自我測試）

- [ ] **Step 1：寫失敗測試**：`test_store_only_window_source_store`、`test_window_before_retention_lists_gap_without_pce_call`、`test_fill_gaps_queries_pce_and_marks_mixed`、`test_fill_gaps_pce_failure_keeps_gap`、`test_unresolved_ingest_gap_is_reported`、`test_dedupe_across_store_and_pce`、`test_limit_hit_flag`、`test_events_query_coverage`、守門 `test_no_direct_flow_reads_outside_sources`、`test_injected_direct_read_is_caught`。
- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/services/test_flowsource.py tests_v6/services/test_eventsource.py tests_v6/gates -q` → FAIL。
- [ ] **Step 3：實作。**
- [ ] **Step 4：跑同一命令 → PASS；全部閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/services tests_v6/services tests_v6/gates && git commit -m "feat(v6): FlowSource and EventSource as the single data entry with explicit coverage"`
- [ ] **Step 6：Codex 對抗式審查**：審 Task 7–11 的 diff，聚焦 Coverage 語意（5.x 有四份實作、兩種「mixed」定義）、換 PCE 的競態、filter 三種編譯是否一致。

---

### Task 12: 系統 › 資料收集頁與系統 › 日誌頁

**Files:**
- Create: `illumio_ops/services/collect/status.py`、`illumio_ops/web/routes/system_collection.py`、`illumio_ops/web/routes/system_logs.py`、`web/src/pages/system/Collection.tsx`、`web/src/pages/system/Logs.tsx`、`tests_v6/services/collect/test_status.py`、`tests_v6/web/test_system_collection.py`、`tests_v6/web/test_system_logs.py`、`tests_v6/e2e/test_collection_e2e.py`
- Modify: `web/src/shell/nav.ts`、`illumio_ops/web/app.py`、`illumio_ops/i18n/en.json`、`illumio_ops/i18n/zh_TW.json`

**Interfaces:**
- Produces:
  - `status.py`：`def collection_status(ctx, *, now=None) -> CollectionStatus`——每個來源（traffic、events、inventory、ransomware、backfill）：最近開始／成功、延遲秒數、`stale`（距最近成功 > 2 × 間隔）、最近錯誤、連續失敗、最近筆數；近 24 小時未 resolved 的缺口（依 kind 分）；流量庫檔案大小與 `data/` 所在磁碟剩餘空間（低於 `disk_free_warn_gb` → `disk_low=True`）；可見度摘要（Task 7）；能力狀態（Task 4/7）；綁定（PCE url 只顯示主機名）
  - Ops：`system.collection.get`／`system.collection.update`（設定，含 `revision`；更新後呼叫 `apply_schedule` 與 `ctx.rate_limiter.set_rate`）、`system.collection.status`、`system.collection.backfill`（POST，`start`／`end` 日期，排一次 `run_backfill` 背景 job；已有回填在跑 → 409 `backfill_running`）、`system.logs.tail`（GET，參數 `level`、`module`、`contains`、`limit ≤ 1000`；讀 `logs/illumio-ops.log` 與輪替檔的尾端，回傳 `[{ts, level, module, message}]`；超過上限明說 `truncated: true`）
  - 頁面「系統 › 資料收集」：上方狀態卡（每個來源一列，人話：「流量：10 分鐘前收集成功，延遲正常」「事件：連續 3 次失敗——無法連線（逾時）」）、缺口清單（「10/24 14:00–14:10 流量不完整（超過 PCE 單次查詢上限）」）、可見度（「18 台主機只記錄被擋的流量，被允許的橫向移動看不到」並連到說明）、勒索防護能力；下方設定表單（主要動作「儲存」）；次要動作「回填指定日期」
  - P4 的看門狗與資料遺失 meta-alert 以 `collection_status` 與 `open_gaps` 為輸入；P2 不發告警
  - 頁面「系統 › 日誌」：等級、模組、關鍵字篩選，最新在上；畫面不得出現憑證（log 本身由 P1 的遮罩保證，此頁只顯示）

- [ ] **Step 1：寫失敗測試**：`test_status_marks_stale_after_two_intervals`、`test_status_reports_truncated_windows`、`test_status_disk_low`、`test_collection_update_reschedules_and_sets_rate`、`test_backfill_conflict_returns_409`、`test_logs_tail_filters_and_truncation_flag`；e2e `test_collection_page_shows_failure_in_words`（fake PCE 讓流量查詢 503）、`test_collection_settings_save_and_reload`。
- [ ] **Step 2：跑** `timeout 600 python3.12 -m pytest tests_v6/services/collect/test_status.py tests_v6/web tests_v6/e2e/test_collection_e2e.py -q` → FAIL。
- [ ] **Step 3：實作後端、頁面、i18n。**
- [ ] **Step 4：前端建置；跑同一命令 → PASS；全部閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops tests_v6 web/src && git commit -m "feat(v6): data collection status and settings page, module log viewer"`

---

### Task 13: 遷移器 `pce_cache` 段與階段標示更新

**Files:**
- Modify: `illumio_ops/migrate/v5.py`、`illumio_ops/migrate/v5_models.py`、`illumio_ops/i18n/en.json`、`illumio_ops/i18n/zh_TW.json`、`tests_v6/migrate/test_v5.py`

**Interfaces:**
- Produces（每一條都產生報告項目，不無聲丟棄）：
  - 搬：`pce_cache.enabled → collection.enabled`、`events_poll_interval_seconds → collection.events_interval_seconds`（夾到 [60, 3600]，被夾 → rewritten）、`rate_limit_per_minute → collection.rate_limit_per_minute`、`events_retention_days → retention.event_days`、`traffic_agg_retention_days → retention.rollup_days`、`archive_enabled → archive.enabled`、`archive_retention_days → archive.retention_days`、`disk_free_warn_gb → collection.disk_free_warn_gb`
  - 改寫：`traffic_poll_interval_seconds` 等於 5.x 預設 3600 → 600（理由鍵 `migrate_v6_default_interval`：「v6 每 10 分鐘收集以支援橫向移動偵測」）；其他值照搬並夾到 [300, 86400]。`traffic_raw_retention_days` 小於 `baseline_days`（30）→ 提高到 35（理由 `migrate_raised_to_baseline`）；搬完後若 `rollup_days < flow_days` → 提高 `rollup_days`（理由同）
  - 丟棄並說明：`traffic_filter.*`、`traffic_sampling.*`（理由 `migrate_no_sampling`：「v6 不做流量過濾或抽樣：會讓橫向移動偵測看不到流量」）；`db_path`、`archive_dir`（固定路徑）、`archive_interval_hours`（每日）、`archive_gzip_after_days`（一律 gzip）、`async_threshold_events`（固定 10000＋分窗）、`cache_read_max_rows`、`flow_delta_enabled`、`flow_obs_retention_hours`（v6 無此機制）
  - 延後：`siem_pending_warn_rows` → `migrate_arrives_in_phase {phase: "P7"}`
  - `PHASE_OF_SECTION` 依修訂後路線圖更正（使用者看得到）：`alerts`／`email`／`smtp`／`rules` → `"P4"`、`siem` → `"P7"`、`report`／`report_schedules` → `"P5"`；`web_gui.public_url` → `"P5"`（報表信件的「GUI 對外網址」，spec §6.5.5）；移除 `pce_cache`

- [ ] **Step 1：寫失敗測試**：守門加一條斷言——`PENDING_READERS` 不得有 `P2-` 開頭的項目（P2 的讀者到此全部到位）；`test_pce_cache_carried_and_rewritten`（5.x 預設 3600 → 600；自訂 1800 → 1800）、`test_raw_retention_raised_to_baseline`、`test_filter_and_sampling_dropped_with_reason`、`test_phase_labels_follow_revised_roadmap`、以 .106 去識別化 fixture 跑一次，`pce_cache` 每個葉都有報告項目且無 `migrate_unknown_key`。
- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/migrate tests_v6/i18n -q` → FAIL。
- [ ] **Step 3：實作。**
- [ ] **Step 4：跑同一命令 → PASS；全部閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/migrate illumio_ops/i18n tests_v6/migrate && git commit -m "feat(v6): migrate 5.x pce_cache settings and correct phase labels"`

---

### Task 14: 1,000 台規模的負載量測

**Files:**
- Create: `scripts/v6/synth_flows.py`、`tests_v6/scripts/test_synth_flows.py`；量測紀錄 `tmp/v6-p2-verification/load-test.md`（gitignored）

**推算（寫進紀錄）**：lab 21 台 7 天 19,098 筆 ≈ 每台每日 130 筆 → 1,000 台約每日 13 萬筆 → 35 天保留約 455 萬列。量測以 **2 倍**產生：每日 26 萬筆主列、35 天、1,000 台受管＋2,000 個非受管 IP、標籤 4 個 key、約 4% 雙端回報、12% 有使用者、4% 有 process、5% 有位元組。

**Interfaces:**
- Produces：`python3.12 scripts/v6/synth_flows.py --root <dir> --workloads 1000 --days 35 --flows-per-day 260000 --seed 1`，直接以 `upsert_flows` 寫入 `<dir>/data/flows.sqlite`（走正式寫入路徑，量到的才是真實成本）

- [ ] **Step 1：寫測試** `test_synth_small_is_deterministic`（`--workloads 10 --days 2 --flows-per-day 500 --seed 1` 兩次結果列數與 conn_key 數相同）。
- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/scripts/test_synth_flows.py -q` → FAIL；實作；→ PASS；commit `git add scripts/v6/synth_flows.py tests_v6/scripts/test_synth_flows.py && git commit -m "feat(v6): synthetic flow generator for load measurement"`
- [ ] **Step 3：在 .106 產生資料並量測**（不在開發機：磁碟與 CPU 要接近客戶設備）。量以下各項，每項跑 5 次取 p95：
  - 一輪收集的寫入（2,000 列含配對、rollup 重算當日）：目標 ≤ 10 秒
  - 單日 `rebuild_rollup`：目標 ≤ 30 秒
  - 工作台維度欄：7 天、`is_primary = 1`，6 個維度（來源主機、目的主機、port、發起端使用者、發起端 process、reported 判定）各取前 10，**同時**執行：目標 ≤ 2 秒；同一查詢改用 `flow_rollup_daily`：記錄時間
  - 30 天 `connection_baseline` 新組合查詢（P3 偵測器的形狀）：目標 ≤ 5 秒
  - 流量庫檔案大小、每日成長
- [ ] **Step 4：裁定並記錄（Ruling）**：維度欄直接查 `flows` 達標 → P6 即時計算；只有 rollup 達標 → P6 用 rollup（並列出 rollup 無法提供的維度）；兩者皆不達標 → 先試加索引重量一次，仍不達標即**停止並回報使用者**（spec §5 的規模前提不成立）。把裁定寫進 `docs/superpowers/plans/2026-10-24-v6-roadmap.md` 的 P6 列並 commit。

---

### Task 15: 實機驗收（.106 並排 24 小時、NFR、離線 bundle）

**Files:**
- Create: `tmp/v6-p2-verification/report.md`（gitignored）
- Modify: `docs/superpowers/plans/2026-10-24-v6-roadmap.md`（P2 列標完成與實測數字）

- [ ] **Step 1：建 bundle 並更新 .106 的並排 v6**（P1 Task 14 的流程與指令；v6 服務 `illumio-ops-v6`、port 5443）；確認 v1 設定檔在升級後以 v2 載入且服務正常啟動。
- [ ] **Step 2：在資料收集頁存 lab PCE、開啟收集**；觀察首輪回填（30 天）完成、`ingest_state` 進度合理、無未預期缺口。
- [ ] **Step 3：連續 24 小時後比對**：同一 24 小時區間，v6 `flows` 依 `(src_ip, dst_ip, port, proto, first_detected)` 去重後的數量 vs 5.x `pce_traffic_flows_raw` 列數，差距 ≤ 5%（超過即查原因、寫進報告）；事件筆數一致；資料收集頁無 stale 來源。
- [ ] **Step 4：NFR SaaS**：以唯讀 service account 設定（在 NFR 以 API 建立、驗收後刪除），收集 2 小時：事件 timeout（SaaS 180 秒）生效、`/events` 延遲下無缺口、勒索與可見度資料進庫。
- [ ] **Step 5a：保留與封存到期實測**：複製一份 .106 的 `flows.sqlite` 到暫存根目錄，暫存設定檔設 `archive.enabled=true`（保留天數用預設，不違反 `flow_days ≥ baseline_days`），以 `python3.12 -P -c` 呼叫 `run_archive(now=最新資料日+2天)`，再呼叫 `run_retention(now=最新資料日+40天)`（以推移 `now` 代替縮短保留期），確認未封存的日子不被刪、封存檔可解壓且列數與 `archive_log` 相符。
- [ ] **Step 5：換 PCE 實測**：.106 的 v6 從 lab 改成 NFR 再改回，確認舊資料清除、封存搬到 `previous-*`、新綁定回填開始。
- [ ] **Step 6：寫 `report.md`**（每項的命令、輸出摘要、數字），更新路線圖 P2 列並 commit：`git add docs/superpowers/plans/2026-10-24-v6-roadmap.md && git commit -m "docs(v6): record P2 acceptance results"`
- [ ] **Step 7：全分支最終審查**（最強模型，依 executing-plans 的 Final Review 規則）。
