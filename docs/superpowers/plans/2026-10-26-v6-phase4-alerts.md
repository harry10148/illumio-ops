# illumio-ops v6 P4 告警 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本計畫以 Native（superpowers:executing-plans）執行：使用者 2026-10-26 指示「做完再一次給決策」。

**Goal:** 依設定的規則，從 PCE 事件、流量、PCE 與收集的健康狀態、橫向移動偵測產生告警，記錄、保留並送到通知通道（email、LINE、Telegram、Teams、webhook）；GUI 能管理規則與通道、檢視最近告警與單筆詳情、留註記；5.x 的規則與通道設定能遷移過來。

**Architecture:**
- **規則是設定**：存在設定檔新的 `alerts` 段，寫入時整份驗證（反目標 6）。六型規則是 pydantic 判別聯集，定義在 `domain/alertrules.py`，設定 schema 引用它。
- **評估是純函式**：比對、門檻、冷卻、throttle 在 `domain/alerting.py`；服務層 `services/alerts/` 組裝輸入、呼叫領域函式、寫紀錄。
- **流量門檻用增量**（spec §6.6 F12）：PCE 給的是日級累計值，所以流量庫寫入時把每個 (來源 IP, 目的 IP, port, 協定) 這一輪「長了多少」記進新表 `flow_increments`，規則對增量加總。
- **告警紀錄在應用狀態庫**（spec §6.4：換 PCE 不碰告警紀錄），標記所屬 PCE，畫面只列目前這台的。
- **評估與派送分開**：評估接在收集之後同步跑，只寫紀錄與待送項；派送是獨立的每分鐘 job，負責重試與通道冷卻，HTTP 逾時不會拖住收集。

**Tech Stack:** 沿用 P1–P3，不新增執行期依賴：通道用標準庫 `urllib.request`、`smtplib`。

**Spec:** `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md`（2026-10-24 修訂版核可）。本階段依據：
- §4.2 告警只做註記、不做狀態流；§4.3 反目標 1、2、4、5、6、8。
- §6.4 設定與執行期狀態；§6.5「告警」「管理」段；§6.5.1 偵測器與前兆；§6.5.2 告警補充；§6.5.4 竄改已知原因。
- §6.6 F12（流量是日級累計）；§7 升級（規則、通道、SMTP；新預設規則對升級客戶先不送通知；回填不進告警評估）；§9 驗收。

路線圖 `docs/superpowers/plans/2026-10-24-v6-roadmap.md` 的 P4 列，含 P3 留下的前置工作（7 天被擋歷史改每小時快取）。

## Global Constraints

**沿用與基本規則**
- P1–P3 的 Global Constraints 全部沿用：
  - Python 3.12、單一鎖檔、無 `print(`；路徑只從 `InstallPaths` 推；每表單一寫入者；值域只在 `domain/values.py`。
  - 英文 conventional commits，結尾附 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` 與 `Claude-Session: https://claude.ai/code/session_013iFADnkFuumZxobTw5jFC3`；只 `git add <明確路徑>`。
  - 測試在前景跑並加 timeout；每次 commit 後 `git status --porcelain illumio_ops tests_v6 web scripts/v6` 為空。
  - 時間一律帶時區的 UTC；失敗不得看起來像空結果；不做流量抽樣。

**分支與 worktree**
- 分支 `feat/v6-p4-alerts`，worktree `.worktrees/v6-p4`，從 main `035f7519` 開（已建立）。
- 每個任務開始前執行 `pwd && git branch --show-current`。

**閘門**
每個任務之間都要親自跑，內容同 `ci-v6.yml`。Task 0 在 P4 的 SDD 工作區建立 `gates.sh`，內容同 P3（`.superpowers/sdd/2026-10-25-v6-phase3-lateral/gates.sh`），路徑改成 `.worktrees/v6-p4`：pip-audit、契約產生後 `git diff --exit-code`、前端 typecheck 與 build、ruff、mypy、`pytest tests_v6 -n auto --dist loadfile`，最後印 `ALL GATES GREEN`。先 commit 再跑閘門；閘門後的 commit 用 `rc=$?` 守住。

**分層與單一來源**
- 領域核心不得 import `illumio_ops` 的其他子套件，也不讀設定、不做 I/O（`tests_v6/gates/test_layering.py`）。`domain/alertrules.py` 是 pydantic 模型，與 `domain/filter.py` 同性質，可被 `settings/schema.py` 引用。
- 流量與事件只經 FlowSource／EventSource 讀（`test_single_reader.py`）；`flow_increments` 與 flows 的 JOIN 也放在 `services/flowsource.py`。
- 每張新表都登錄 `TABLE_OWNERS`；每個新設定葉都登錄讀者；每條新 `/api` 路由都要有前端呼叫者；每個新 i18n 鍵兩個語系都要有。
- P1 起掛在 `PENDING_READERS` 的 `pce.console_url` 與 `display.timezone` 由本階段補上讀者（告警詳情的主控台連結、告警訊息的時間），清單清空。

**祕密**
- 通道的祕密欄位：SMTP 密碼、LINE token、Telegram bot token、Teams webhook URL、webhook URL（URL 本身內含祕密，5.x L-12）。
- 這些欄位加入 `SECRET_FIELDS`。API 回應以 `MASK` 遮罩；PUT 收到空字串或 `MASK` 表示「不變」，與 `system_pce.py` 的 `api_secret` 同慣例。
- 送出失敗的錯誤文字在寫入紀錄、log、API 之前先去掉 token 與 URL（回收 5.x `redact_webhook_url`／`scrub_webhook_url`／Telegram `_redact_token`）。遷移報告只列鍵名。

**告警語意**（本計畫的裁定，Task 1–7 依此實作，Task 11 寫回 spec §6.5.2）
- **回填與歷史不告警**（spec §7）：只評估 origin = `ingest` 的事件與增量。各來源第一次評估時，水位設成「現在」，之前的資料不評估。
- **晚到的資料**：每日重讀補到的事件照常評估，告警標「晚到」；流量增量標 `late`，流量型規則不計入（理由見 Task 3），只出現在報表與工作台。晚到的橫向移動偵測照常告警並標「晚到」。
- **冷卻**以（規則、對象）為單位：
  - 事件：對象是事件所屬主機，沒有主機時是事件型別；
  - 流量型：對象是規則本身；
  - 橫向移動：對象是偵測的 fingerprint；
  - 系統檢查：對象是檢查項目加來源。
- **throttle** 是滑動視窗計數，週期上限 7 天且如實遵守（5.x 在 24 小時處截斷）。
- **嚴重度**：每條規則宣告嚴重度；事件規則可設成「依事件」，對照表在 `values.py`：err→high、warning→medium、info→low，其他→medium。
- **不送通知的告警照樣記錄**：規則 `notify=false`、竄改已標已知原因而歸組、沒有啟用任何通道時，告警都寫入紀錄並顯示原因，不得當作沒發生。

## Review Focus

1. **祕密外洩**：通道失敗的錯誤文字、log、API 回應、遷移報告都不得出現 token 或 webhook URL；PUT 帶 `MASK` 不得把祕密改成字面的 `********`。
   - → Task 6 `test_delivery_error_scrubs_secrets`（四個通道）；Task 8 `test_channels_get_masks_secrets`、`test_channels_put_mask_keeps_secret`；Task 10 `test_report_never_contains_secret_values`。
2. **同一條連線被兩端各回報一次**：增量只算一次；重新配對不得產生負數或重複。
   - → Task 4 `test_both_sides_reported_counted_once`、`test_repairing_does_not_double_count`。
3. **換 PCE**：前一台的告警不出現在清單；新 PCE 的評估水位從「現在」開始，初次回填不會灌出告警。
   - → Task 5 `test_previous_pce_alerts_hidden`、`test_first_run_after_switch_starts_now`。
4. **回填資料不告警**：回填來源的事件與流量從不評估；初次啟動時既有資料不評估。
   - → Task 4 `test_backfill_writes_no_increment`；Task 5 `test_backfill_events_not_evaluated`、`test_first_run_does_not_alert_history`。
5. **沒有通道或通道全掛**：告警照樣記錄，派送狀態寫明「沒有啟用的通道」或「失敗（第 N 次）」，畫面看得到；5.x 的 `alert_dlq` 沒有讀者，v6 不得重演。
   - → Task 6 `test_no_enabled_channel_marks_undelivered`、`test_failed_delivery_retried_then_final`；Task 9 e2e `test_alert_detail_shows_delivery_status`。

另：不合法的正規表示式在儲存時拒收（5.x 靜默退回精確比對）→ Task 2 `test_event_rule_invalid_regex_rejected`。

---

### Task 0：開工與計畫撰寫時的實測（實測已完成）

**開工步驟**
- 建立虛擬環境：`python3.12 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements-v6.lock && .venv/bin/pip install -r requirements-v6-dev.txt && npm ci --prefix web`。
- 執行 `superpowers:executing-plans` 的 `sdd-workspace` 取得工作區，建立帳本與 `gates.sh`，跑一次閘門確認全綠再開始 Task 1。

**計畫撰寫時已查證（2026-10-26，唯讀）**

- **.106 的 5.x 規則**（`/root/illumio-ops/config/alerts.json`，19 條）：
  - 16 條事件規則，全是 5.x 最佳實務包（`name_key` 為 `rule_agent_tampering` 等），其中 `rule_agent_tampering` 有 `enabled: true`，其餘沒有 `enabled` 鍵（＝啟用）。
  - 1 條 traffic：`pd=2`、count 25、視窗 10 分鐘、冷卻 30、throttle `1/15m`，名稱「高 Blocked 流量」，legacy 純量鍵全為 null。
  - 1 條 system：`filter_value=pce_health`，`enabled: false`，帶 `threshold_*` 與 `match_fields`（5.x 不讀）。
  - 1 條 bandwidth：`pd=-1`，門檻 999999 Mbps、視窗 60，`enabled: false`，帶全部 legacy 純量鍵（皆 null）。
  - id 混用整數（最佳實務包）與 32 字元 hex（GUI 建立）。
- **.106 的 5.x 通道**：`alerts.active = ["line", "mail"]`；`alerts` 段有 line／telegram／teams／webhook 欄位；`email` 有 `sender`、`recipients`；`smtp` 有 `host`、`port`、`user`、`password`、`enable_auth`、`enable_tls`。
  - 5.x 的 SMTP 密碼可由環境變數 `ILLUMIO_SMTP_PASSWORD` 覆寫，遷移器讀不到環境變數，報告要提醒。
- **5.x 語意**（盤點 `tmp/rearch-2026-10-24/survey/c-monitor-alert-siem.md` §2、§3，並讀原始碼核對）：
  - 事件比對 `src/events/matcher.py`：
    - `filter_value` 逗號分隔，每段可為精確值、`a|b`、或正規表示式；
    - status／severity 支援 `all`、`*`、`any`、空字串、`!` 否定、`a|b`、正規表示式；severity 的 `error` 視同 PCE 的 `err`；
    - `match_fields` 以點路徑取值，`notification_type` 掃 `notifications[]`。
  - 門檻：
    - immediate：本批命中數 ≥ 門檻；
    - count：視窗內命中數 ≥ 門檻，且本批要有新命中。
  - 冷卻：缺省用 `threshold_window`，0 表示停用。
  - throttle：`N/M[smhd]`，5.x 的 prune 地平線固定 24 小時。
  - `pd` 序數：0 allowed、1 potentially_blocked、2 blocked；`-1` 與 `3` 都表示全部。
  - system 型只有 `pce_health`，`threshold_*` 不參與。
  - 看門狗：PCE 連續失敗 ≥ 3 次就自我告警，冷卻 60 分；資料遺失類 meta-alert 各自冷卻 60 分，訊號解除時清冷卻。
  - 通道：
    - LINE push API 本文截 4500 字，連續 3 次失敗冷卻 5 分，冷卻中回 skipped、不耗重試額度；
    - Telegram 截 3300 字、HTML parse mode；Teams 是 Adaptive Card，前 5 則摘要；mail 是 HTML＋純文字；webhook 送整包。
  - 5.x 一輪的所有告警合併成每通道一則訊息。
  - 告警 DLQ 在 `state.json`，整批、3 次後丟棄，沒有任何讀者。
- **5.x 最佳實務包**（`src/config.py` `_best_practice_rules`）：16 條事件規則加 1 條 traffic（blocked 10 分鐘 25 次）。欄位：型別、immediate／count、門檻、視窗、冷卻、status、severity、throttle。Task 2 照抄成 v6 預設包。
- **v6 既有可用的狀態**：
  - `ingest_state.consecutive_failures`、`ingest_gaps`（failed／truncated）、`collection_status().disk_low`；
  - `pce_health.latest()`；
  - `job_health`（有 `last_ok`、`failures` 累計，沒有連續失敗數）；
  - `detections`（`created_at`、`updated_at`、`severity`、`late`）；
  - 竄改 `explained_by` 與 `tamper_annotations`。
- **前端**：`nav.ts` 只有 `system` 一個區段，`Shell.tsx` 寫死；元件只有 `ProbeResults`。

---

### Task 1：7 天被擋歷史改成每小時快取（P3 留下的前置工作）

1,000 台最壞情況下，每輪偵測 85 秒中有 40 秒花在 `_blocked_history` 重讀 7 天被擋流量（P3 Task 15）。告警延遲取決於偵測，所以先處理。

**Files:**
- Create: `illumio_ops/services/analysis/blocked_history.py`、`tests_v6/services/analysis/test_blocked_history.py`
- Modify: `illumio_ops/services/analysis/hourly.py`、`illumio_ops/services/analysis/detect.py`、`tests_v6/services/analysis/test_detect.py`

**Interfaces:**
- `blocked_history.py`：
  ```python
  KIND = "blocked_history"
  def build_blocked_history(ctx: AppContext, now: datetime) -> None   # 每小時步驟
  def cached_history(ctx: AppContext, *, window: timedelta, before: datetime, now: datetime) -> CachedHistory | None
  @dataclass(frozen=True)
  class CachedHistory:
      through: datetime          # 快取涵蓋到這個時間（計算時的流量水位）
      max_targets: Mapping[str, int]   # 來源 → 7 天內任一 blocked_window 長度視窗的最多不重複被擋目標數
  ```
  - `build_blocked_history`：讀 `[through − 7 天, through]` 的 blocked obs（`through` = 流量 `ingest_state.watermark`），對每個來源用 `max_window_targets` 算出最大值，寫進 `analysis_results`，kind 為 `blocked_history`，`params` 帶 `blocked_window_minutes` 與 `through`。
  - `cached_history` 在下列情況回 `None`：沒有結果、`params` 的視窗與目前設定不同、`computed_at` 早於 `now − 2 小時`。
- `detect._blocked_history` 改寫：
  - 有快取時，只對超過門檻的來源讀尾段 `(through − blocked_window, lo]`，取 `max(快取值, 尾段值)`。尾段從 `through − blocked_window` 起讀，才不會漏掉跨在 `through` 前後的視窗。
  - 沒有快取時，照舊讀完整 7 天。
  - 大量被擋偵測器的狀態 `params` 加 `history`：值為 `"cached"` 或 `"live"`。
- `HOURLY_STEPS` 在 `focus` 之前加入 `("blocked_history", build_blocked_history)`。

- [ ] **Step 1：失敗測試**：
  - `test_cache_matches_live_computation`：同一份 fixture，快取加尾段的結果等於完整 7 天的即時計算；含一個跨在 `through` 前後的視窗。
  - `test_stale_cache_falls_back_to_live`：`computed_at` 超過 2 小時時不用快取，狀態 `history=live`。
  - `test_window_change_invalidates_cache`。
  - `test_detection_reads_only_tail_with_cache`：以計數包裝 `observations` 斷言讀取範圍的起點是 `through − blocked_window`。
- [ ] **Step 2：** `timeout 600 .venv/bin/python -m pytest tests_v6/services/analysis/test_blocked_history.py tests_v6/services/analysis/test_detect.py -q` → FAIL
- [ ] **Step 3：實作。**
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/services/analysis/blocked_history.py illumio_ops/services/analysis/hourly.py illumio_ops/services/analysis/detect.py tests_v6/services/analysis/test_blocked_history.py tests_v6/services/analysis/test_detect.py && git commit -m "perf(v6): blocked-surge history from an hourly cache plus a live tail"`

---

### Task 2：值域、FlowCondition、規則模型、設定 schema v4

**Files:**
- Create: `illumio_ops/domain/alertrules.py`、`illumio_ops/domain/alertpack.py`、`tests_v6/domain/test_alertrules.py`
- Modify: `illumio_ops/domain/values.py`、`illumio_ops/domain/filter.py`、`illumio_ops/settings/schema.py`、`illumio_ops/settings/upgrade.py`、`illumio_ops/settings/secrets.py`、`tests_v6/domain/test_filter.py`、`tests_v6/domain/test_values.py`、`tests_v6/settings/test_schema.py`、`tests_v6/settings/test_upgrade.py`、`tests_v6/gates/test_settings_readers.py`

**Interfaces:**
- **`values.py`**：
  ```python
  class AlertRuleType(StrEnum): EVENT; TRAFFIC; BANDWIDTH; VOLUME; SYSTEM; LATERAL = "lateral"
  class ThresholdType(StrEnum): IMMEDIATE = "immediate"; COUNT = "count"
  class ChannelKind(StrEnum): SMTP = "smtp"; LINE = "line"; TELEGRAM = "telegram"; TEAMS = "teams"; WEBHOOK = "webhook"
  class SystemCheck(StrEnum): PCE_HEALTH = "pce_health"; COLLECTION_FAILING = "collection_failing"
                              DATA_LOSS = "data_loss"; JOB_FAILING = "job_failing"; DISK_LOW = "disk_low"
  class DeliveryStatus(StrEnum): PENDING = "pending"; SENT = "sent"; FAILED = "failed"
                                 NOT_NOTIFIED = "not_notified"; GROUPED = "grouped"; NO_CHANNEL = "no_channel"
  EVENT_SEVERITY_TO_ALERT: Mapping[str, Severity]   # err/error→HIGH, warning→MEDIUM, info→LOW；其他→MEDIUM（函式 alert_severity_of_event）
  ```
  新列舉加入 `_ENUMS`。
- **`filter.py`**：
  ```python
  class FlowCondition(_Model):        # FilterSpec 去掉 start／end，其餘欄位、預設、驗證完全相同
      ...
      def within(self, start: datetime, end: datetime) -> FilterSpec
  class FilterSpec:  def condition(self) -> FlowCondition
  ```
- **`domain/alertrules.py`**（設定 schema 引用的模型；全部 `extra="forbid"`、`frozen`）：
  ```python
  class Throttle(_Model): count: int (1..1000); period_minutes: int (1..10080)
  class RuleBase(_Model):            # 六型規則的共同欄位；Task 3 的 gate 收它
      id: str                         # 32 個小寫十六進位字元
      name: str (0..120)              # 空字串 = 用 pack_key 的翻譯
      pack_key: str | None            # 最佳實務包的 i18n 鍵（如 "rule_agent_tampering"），使用者自建為 None
      enabled: bool
      notify: bool                    # false = 只記錄不送（§7 升級客戶的新預設規則）
      severity: Severity | None       # None 只允許事件規則（= 依事件）
      cooldown_minutes: int (0..10080)
      throttle: Throttle | None
  class EventRule(RuleBase):
      type: Literal["event"]; event_types: tuple[str, ...] (≥1); status: str; event_severity: str
      match_fields: dict[str, str]; threshold: ThresholdType; threshold_count: int (≥1); window_minutes: int (1..1440)
  class TrafficRule(RuleBase):   type: Literal["traffic"];   condition: FlowCondition; threshold_connections: int (≥1); window_minutes: int (10..1440)
  class BandwidthRule(RuleBase): type: Literal["bandwidth"]; condition: FlowCondition; threshold_mbps: float (>0);     window_minutes: int (10..1440)
  class VolumeRule(RuleBase):    type: Literal["volume"];    condition: FlowCondition; threshold_mb: float (>0);       window_minutes: int (10..1440)
  class SystemRule(RuleBase):    type: Literal["system"];    check: SystemCheck
  class LateralRule(RuleBase):   type: Literal["lateral"];   detectors: tuple[DetectorKind, ...] (≥1); min_severity: Severity; critical_assets_only: bool
  AlertRule = Annotated[EventRule | TrafficRule | BandwidthRule | VolumeRule | SystemRule | LateralRule, Field(discriminator="type")]
  def event_matches(rule: EventRule, event: Mapping[str, Any]) -> bool    # 5.x matches_event_rule 的語意
  ```
  - **pattern 驗證**：`event_types` 的每段、`status`、`event_severity`、`match_fields` 的值，凡是「看起來像正規表示式」（5.x `_looks_like_regex`）就必須能編譯，否則驗證錯誤，錯誤只指出欄位，不回顯內容。
  - **視窗下限**：流量型規則的視窗下限 10 分鐘，等於流量收集的最短間隔，更短沒有意義。
  - **`event_matches`**：從 `src/events/matcher.py` 回收，commit 訊息註明來源檔案與 5.x commit `035f7519`。差異只有一處：正規表示式已在儲存時驗證，執行時不再有「編譯失敗退回精確比對」的分支。
- **`domain/alertpack.py`**：
  ```python
  def best_practice_rules(*, notify_new_defaults: bool) -> tuple[AlertRule, ...]
  PACK_KEYS: frozenset[str]
  ```
  - 內容：
    - 5.x 的 16 條事件規則與 1 條 traffic 規則。traffic 規則條件為 `decisions=(blocked,)`、門檻 25 連線、視窗 10 分鐘、冷卻 30、throttle 1/15m。
    - 系統檢查五條：pce_health、collection_failing、data_loss、job_failing、disk_low。冷卻 60 分、嚴重度 high；`disk_low` 為 medium。
    - 橫向移動三條（spec §6.5.2 預設開啟的三種）：扇出、新的管理連線、跨環境管理 port。`min_severity=medium`。
  - id 由 `pack_key` 決定：`md5(pack_key)` 的十六進位，所以「附加缺少的」能以 id 判斷。
  - 事件規則的嚴重度：
    - tampering、clone、suspend、lost_agent、bulk_unpair、auth_settings_change、api_key_change 為 high；
    - 其餘事件規則為 None（依事件）。
  - `notify_new_defaults=False` 只套用在橫向移動三條；事件、traffic、系統檢查一律 `notify=True`。這是 spec §7 對升級客戶的規定，詳見 Task 10。
- **設定 schema v4**：
  ```python
  class SmtpChannel(StrictModel):     enabled: bool; host: str; port: int (1..65535); security: Literal["none", "starttls", "tls"]
                                      username: str; password: str; sender: str; recipients: tuple[str, ...]
  class LineChannel(StrictModel):     enabled: bool; access_token: str; target_id: str
  class TelegramChannel(StrictModel): enabled: bool; bot_token: str; chat_id: str
  class TeamsChannel(StrictModel):    enabled: bool; webhook_url: str      # https:// 或空字串
  class WebhookChannel(StrictModel):  enabled: bool; url: str              # https:// 或空字串
  class AlertChannels(StrictModel):   smtp: SmtpChannel; line: LineChannel; telegram: TelegramChannel; teams: TeamsChannel; webhook: WebhookChannel
  class AlertSettings(StrictModel):   channels: AlertChannels; rules: tuple[AlertRule, ...] (≤ 300); retention_days: int (1..3650)
  class Settings: ... alerts: AlertSettings      # schema_version Literal[4]
  def default_alerts(*, notify_new_defaults: bool) -> AlertSettings   # 通道全關、retention 90、rules = 最佳實務包
  ```
  - 驗證規則：
    - 啟用的通道，其必要欄位不得為空；例如啟用 SMTP 時，host、sender、recipients 都不得為空。
    - 收件人須含 `@`。
    - 規則 id 不得重複。
  - `_v3_to_v4`：加入 `default_alerts(notify_new_defaults=True)`。v3 是 v6 自己的安裝，不是 5.x 升級。
  - `SECRET_FIELDS` 加入：`alerts.channels.smtp.password`、`alerts.channels.line.access_token`、`alerts.channels.telegram.bot_token`、`alerts.channels.teams.webhook_url`、`alerts.channels.webhook.url`。
  - 讀者登錄：
    - `alerts.channels.*` 指向 `illumio_ops.services.alerts.channels`；
    - `alerts.rules` 指向 `illumio_ops.services.alerts.evaluate`；
    - `alerts.retention_days` 指向 `illumio_ops.services.alerts.retention`。
    - 這些模組要到 Task 5、6 才存在，先登錄進 `PENDING_READERS`（值 `"P4-T5"`、`"P4-T6"`），Task 5、6 再移到 `SETTINGS_READERS`，並加一支 `test_no_p4_pending_left`，Task 9 結束前必須為綠。

- [ ] **Step 1：失敗測試**：
  - 比對：`test_event_rule_matches_like_5x`。把 `tests/test_event_core.py` 中與 `matches_event_rule` 有關的案例逐條改寫成參數化表，含精確、`a|b`、正規表示式、`!` 否定、status、severity `error`→`err`、`match_fields` 點路徑、`notification_type`。
  - 驗證：`test_event_rule_invalid_regex_rejected`、`test_lateral_rule_needs_a_detector`、`test_traffic_window_minimum`、`test_duplicate_rule_ids_rejected`、`test_enabled_smtp_requires_host_sender_recipients`、`test_channel_urls_must_be_https`。
  - FlowCondition：`test_flow_condition_fields_equal_filter_spec_minus_window`、`test_within_round_trips`。
  - 最佳實務包：`test_pack_ids_stable_and_unique`、`test_pack_matches_5x_event_specs`（16 條的型別、門檻、視窗、冷卻、status、throttle 與 5.x `_best_practice_rules` 逐欄相同，期望值寫成表）、`test_pack_lateral_notify_follows_flag`。
  - 設定：`test_v3_file_upgrades_to_v4_with_pack`、`test_redact_masks_channel_secrets`、`test_severity_none_only_for_event_rules`。
- [ ] **Step 2：** `timeout 600 .venv/bin/python -m pytest tests_v6/domain/test_alertrules.py tests_v6/domain/test_filter.py tests_v6/domain/test_values.py tests_v6/settings tests_v6/gates -q` → FAIL
- [ ] **Step 3：實作**；跑 `bash scripts/v6/gen_contracts.sh`（值域匯出會變）。
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/domain illumio_ops/settings tests_v6/domain tests_v6/settings tests_v6/gates/test_settings_readers.py web/src/api/contracts.json web/src/api/generated.ts && git commit -m "feat(v6): alert rule models, best-practice pack and settings schema v4"`

---

### Task 3：評估核心（純函式）

**Files:**
- Create: `illumio_ops/domain/alerting.py`、`tests_v6/domain/test_alerting.py`

**Interfaces:**
```python
@dataclass(frozen=True)
class Confidence:                      # 反目標 8
    latency_seconds: int | None; window: tuple[datetime, datetime] | None
    field: str | None; covered: int | None; total: int | None
    incomplete_gaps: tuple[tuple[datetime, datetime, str], ...]
@dataclass(frozen=True)
class Trigger:
    rule_id: str; rule_type: AlertRuleType; subject_key: str; severity: Severity
    first_seen: datetime; last_seen: datetime; late: bool
    message_key: str; params: Mapping[str, Any]          # 訊息只帶鍵與參數，文字由服務層產生
    facts: Mapping[str, Any]                             # 數字：命中數、門檻、增量、目標數…
    evidence: FlowSegment | EventSegment | None          # 重現證據的分析段落；系統檢查為 None
    confidence: Confidence
    grouped_annotation: int | None = None                # 竄改已知原因
@dataclass(frozen=True)
class RuleState:
    last_fired_at: datetime | None; recent: tuple[datetime, ...]   # throttle 視窗內的放行時間
@dataclass(frozen=True)
class GateResult:
    allowed: bool; reason: Literal["ok", "cooldown", "throttle"]; next_allowed_at: datetime | None; state: RuleState

def gate(rule: RuleBase, state: RuleState | None, now: datetime) -> GateResult
def evaluate_event_rule(rule: EventRule, new: Sequence[EventFact], window_matches: int, *, now: datetime) -> list[Trigger]
def evaluate_traffic_rule(rule: TrafficRule, totals: IncrementFacts, *, now: datetime, window: tuple[datetime, datetime]) -> Trigger | None
def evaluate_bandwidth_rule(rule: BandwidthRule, totals: IncrementFacts, *, now, window) -> Trigger | None
def evaluate_volume_rule(rule: VolumeRule, totals: IncrementFacts, *, now, window) -> Trigger | None
def evaluate_lateral_rule(rule: LateralRule, changed: Sequence[DetectionFact]) -> list[Trigger]
def evaluate_system(rule: SystemRule, facts: SystemFacts, *, now: datetime) -> list[Trigger]
```
- **輸入事實型別**（frozen dataclass，服務層從 store 轉換）：
  - `EventFact`：href、event_type、status、severity、timestamp、host_key（主機 href 或 None）、hostname、raw。
  - `IncrementFacts`：connections、bytes、bytes_rows、rows、new_rows、max_mbps、top（前 10 條連線：src／dst 名稱、port、proto、connections、mbps）、coverage gaps。
  - `DetectionFact`：id、detector、fingerprint、severity、critical_asset、late、summary、segment、confidence、is_new、severity_rose。
  - `SystemFacts`：probe（最新探測時間與失敗項目）、sources（來源 → 連續失敗數、最後錯誤、失敗起點）、new_gaps（來源、種類、視窗）、jobs（job id → 連續失敗數、最後錯誤）、disk（free_bytes、warn_bytes）。
- **語意**：
  - **事件**：
    - immediate：本次新命中依對象分組，每組命中數 ≥ 門檻就產生一個 Trigger。
    - count：視窗 `(now − W, now]` 內的命中數（`window_matches`，由服務層算）≥ 門檻，且本次至少一筆新命中；對象是規則本身。
    - 嚴重度：規則宣告的值，或 `alert_severity_of_event` 取命中事件中最高者。
    - 證據段落：事件段落，時間窗為命中事件的期間，條件是命中的事件型別與主機。
  - **流量型**（增量只計 `late=0`）：
    - traffic：`connections ≥ threshold_connections` 且 `new_rows > 0`。
    - volume：`bytes / 2²⁰ ≥ threshold_mb` 且 `new_rows > 0`。
    - bandwidth：`max_mbps ≥ threshold_mbps`。
    - 位元組覆蓋為 0 時不產生 Trigger。服務層把規則狀態記成 `no_data`（Task 5），不是「沒超過」。
    - 證據段落：流量段落，`condition.within(window)`，detail 視角。
    - **晚到不計入的理由**：每日重讀一次補進的可能是一整天的晚到成長，計入會在補到的那一刻偽造出突增。
  - **頻寬算法**：增量 `bytes × 8 / max(seconds, 1) / 10⁶`。`seconds` 是這段成長涵蓋的流量時間，新連線取 `last − first + 1` 秒，所以和 5.x `calculate_mbps` 一樣是**下界**；訊息寫明「至少」。
  - **橫向移動**：
    - 只看 `is_new` 或 `severity_rose` 的偵測；
    - 偵測器在規則清單內、嚴重度 ≥ `min_severity`；`critical_assets_only` 時要求 `critical_asset`。
    - 對象是 fingerprint；`late` 照抄偵測。
  - **系統檢查**：
    - pce_health：最新探測有失敗項。
    - collection_failing：任一被收集的來源連續失敗 ≥ 3，等同 5.x 看門狗。
    - data_loss：本次新記錄的 gap，種類 failed 或 truncated。
    - job_failing：任一 job 連續失敗 ≥ 3。
    - disk_low：剩餘空間低於門檻。
    - 每個（檢查、來源或 job）是一個對象。
  - **`gate`**：
    - 冷卻：`last_fired_at + cooldown > now` 時擋下，`reason="cooldown"`；`cooldown_minutes=0` 不擋。
    - throttle：`recent` 只留週期內的時間，數量 ≥ count 時擋下，`next_allowed_at = recent[0] + 週期`。
    - 放行時回傳更新後的 `state`：`last_fired_at=now`，`recent` 加上 now。

- [ ] **Step 1：失敗測試**：
  - gate：`test_cooldown_blocks_then_releases`、`test_zero_cooldown_never_blocks`、`test_throttle_period_longer_than_a_day_is_honoured`、`test_throttle_next_allowed_at`。
  - 事件：`test_immediate_groups_by_host`、`test_count_needs_window_total_and_a_new_match`、`test_count_without_new_match_does_not_fire`、`test_severity_from_event_takes_highest`。
  - 流量型：`test_traffic_fires_on_window_growth_not_cumulative`、`test_traffic_needs_new_rows`、`test_volume_converts_mib`、`test_bandwidth_reports_lower_bound_flag`、`test_no_byte_data_is_not_a_pass`。
  - 橫向移動：`test_lateral_only_new_or_risen`、`test_lateral_min_severity_and_critical_only`。
  - 系統檢查：`test_collection_failing_at_three`、`test_data_loss_per_new_gap`、`test_job_failing_at_three`、`test_disk_low`。
- [ ] **Step 2：** `timeout 600 .venv/bin/python -m pytest tests_v6/domain/test_alerting.py -q` → FAIL
- [ ] **Step 3：實作。**
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/domain/alerting.py tests_v6/domain/test_alerting.py && git commit -m "feat(v6): pure alert evaluation, cooldown and throttle"`

---

### Task 4：流量增量（flowdb 0003）與告警用的讀取

**Files:**
- Create: `illumio_ops/store/flowdb/migrations/0003_increments.sql`、`tests_v6/store/test_flow_increments.py`
- Modify: `illumio_ops/store/flowdb/flows.py`、`illumio_ops/store/ownership.py`、`illumio_ops/services/collect/traffic.py`、`illumio_ops/services/collect/reread.py`、`illumio_ops/services/flowsource.py`、`illumio_ops/services/eventsource.py`、`tests_v6/services/test_flowsource.py`、`tests_v6/services/test_eventsource.py`

**Interfaces:**
- **0003**（owner `store.flowdb.flows`）：
  ```sql
  CREATE TABLE flow_increments (
      id          INTEGER PRIMARY KEY,
      conn_key    TEXT NOT NULL,      -- 該 tuple 最新的主列，供 JOIN 取維度
      observed_at TEXT NOT NULL,      -- 寫入這一輪的時間（upsert 的 now）
      connections INTEGER NOT NULL,   -- 連線數成長（≥ 0）
      bytes       INTEGER,            -- bytes_in + bytes_out 成長；NULL = 沒有位元組資料
      seconds     REAL NOT NULL,      -- 這段成長涵蓋的流量時間
      late        INTEGER NOT NULL CHECK (late IN (0, 1))
  );
  CREATE INDEX ix_increments_observed ON flow_increments (observed_at);
  ```
- **`upsert_flows(..., increments: Literal["cycle", "late", "none"] = "none")`**：
  - 呼叫端：traffic 收集傳 `"cycle"`，每日重讀傳 `"late"`，回填維持 `"none"`。
  - 演算法（在同一個 transaction 內）：
    1. 寫入前，對這批涉及的每個 tuple `(src_ip, dst_ip, port, proto)`，讀 `last_detected ≥ now − 48h` 的主列，加總 `num_connections` 與 `bytes_in + bytes_out`（沒有位元組資料的列不計入位元組，並記下是否有位元組），並記最新的 `last_detected`。
    2. 照舊寫入、配對、合併（`_repair_tuple`、`_merge_connection`）。
    3. 寫入後對同一組 tuple 再讀一次。
    4. 每個 tuple 一筆增量：`connections = max(0, 後 − 前)`；`bytes` 同理，前後都沒有位元組資料時為 NULL；`seconds = 後的最新 last − 前的最新 last`，前面沒有主列時用 `last − first + 1`；`conn_key` 取寫入後最新主列。
    5. `connections` 與 `bytes` 都是 0 時不寫。
    6. 刪除 `observed_at < now − 26h` 的增量。上限理由：規則視窗最長 24 小時，加上 30 分鐘重疊與餘裕。
  - 以 tuple 而非 conn_key 計算：重新配對會換掉 conn_key，以連線為單位比會把同一條連線算兩次；以 tuple 加總，兩端各回報一次的情況也自然只算一次，因為主列只有一筆。
- **flowsource 新增**：
  ```python
  class IncrementTop(BaseModel): src: str; dst: str; port: int | None; proto: int; connections: int; mbps: float | None
  class IncrementTotals(BaseModel):
      connections: int; bytes: int | None; bytes_rows: int; rows: int; new_rows: int
      max_mbps: float | None; top: list[IncrementTop]; coverage: Coverage
  def increment_totals(ctx, cond: FlowCondition, *, start: datetime, end: datetime, new_after: datetime,
                       rank_by: Literal["connections", "mbps"]) -> IncrementTotals
  def increments_watermark(ctx) -> datetime | None     # 最新的 observed_at
  ```
  - SQL：`flow_increments i JOIN flows f ON f.conn_key = i.conn_key AND f.is_primary = 1`，加上 `to_sql(cond.within(start − 24h, end + 1h))` 與 `i.late = 0 AND i.observed_at > start AND i.observed_at <= end`。flow 時間放寬，真正的視窗由 `observed_at` 決定。
  - `new_rows` 是 `observed_at > new_after` 的列數。
  - `coverage` 沿用流量來源的 `store_coverage`，所以缺口與僅事件模式照常揭露。
- **eventsource 新增**：
  ```python
  class NewEvent(EventRow): id: int; host_key: str | None; hostname: str | None
  def events_after(ctx, after_id: int, *, limit: int) -> tuple[list[NewEvent], bool]   # origin = ingest、id 遞增；第二個值為「還有更多」
  def max_event_id(ctx) -> int
  def events_in_window(ctx, *, start: datetime, end: datetime, exact_types: tuple[str, ...] | None) -> list[NewEvent]
  ```
  - `events_in_window` 只回 ingest 列。`exact_types` 為 None 時不篩型別，讀整個視窗；呼叫端只在規則含正規表示式時這樣做。
  - `host_key` 經 `workloads.ven_href` 對到主機 href，沿用 `EVENT_FROM` 的 JOIN。

- [ ] **Step 1：失敗測試**：
  - 增量：`test_new_record_increment_is_its_counts`、`test_repull_grown_records_only_growth`、`test_smaller_repull_writes_nothing`、`test_both_sides_reported_counted_once`、`test_repairing_does_not_double_count`、`test_backfill_writes_no_increment`、`test_reread_increment_marked_late`、`test_increments_older_than_26h_deleted`、`test_no_byte_data_is_null_not_zero`。
  - flowsource：`test_increment_totals_window_by_observed_at`、`test_increment_totals_excludes_late`、`test_increment_totals_condition_applies`、`test_increment_totals_reports_gaps`。
  - eventsource：`test_events_after_skips_backfill`、`test_events_after_limit_and_more`、`test_events_in_window_exact_types`。
- [ ] **Step 2：** `timeout 600 .venv/bin/python -m pytest tests_v6/store/test_flow_increments.py tests_v6/store/test_flowdb_flows.py tests_v6/services/test_flowsource.py tests_v6/services/test_eventsource.py tests_v6/services/collect -q` → FAIL
- [ ] **Step 3：實作。** 量一次寫入成本：`tests_v6/store/test_query_plans.py` 加一條斷言，寫入前後的 tuple 讀取走 `ix_flows_tuple`。
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/store illumio_ops/services/collect/traffic.py illumio_ops/services/collect/reread.py illumio_ops/services/flowsource.py illumio_ops/services/eventsource.py tests_v6/store tests_v6/services && git commit -m "feat(v6): per-cycle flow increments for threshold rules (F12)"`

---

### Task 5：告警紀錄、評估服務與排程

**Files:**
- Create: `illumio_ops/store/migrations/0004_alerts.sql`、`illumio_ops/store/alerts.py`、`illumio_ops/services/alerts/__init__.py`、`illumio_ops/services/alerts/evaluate.py`、`illumio_ops/services/alerts/system.py`、`illumio_ops/services/alerts/retention.py`、`tests_v6/store/test_alert_store.py`、`tests_v6/services/alerts/test_evaluate.py`、`tests_v6/services/alerts/test_system.py`
- Modify: `illumio_ops/store/ownership.py`、`illumio_ops/jobs/health.py`、`illumio_ops/jobs/scheduler.py`、`illumio_ops/store/flowdb/analysis.py`、`tests_v6/jobs/test_scheduler.py`、`tests_v6/jobs/test_health.py`、`tests_v6/gates/test_settings_readers.py`

**Interfaces:**
- **0004**（app.sqlite；owner `illumio_ops.store.alerts`，job_health 的新欄位 owner 仍是 `jobs.health`）：
  ```sql
  CREATE TABLE alerts (
      id INTEGER PRIMARY KEY, pce_url TEXT NOT NULL, org_id TEXT NOT NULL,
      rule_id TEXT NOT NULL, rule_type TEXT NOT NULL, rule_name TEXT NOT NULL, severity TEXT NOT NULL,
      subject_key TEXT NOT NULL, fired_at TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
      late INTEGER NOT NULL CHECK (late IN (0, 1)), notify INTEGER NOT NULL CHECK (notify IN (0, 1)),
      grouped_annotation INTEGER, message_key TEXT NOT NULL, params_json TEXT NOT NULL, facts_json TEXT NOT NULL,
      evidence_json TEXT, confidence_json TEXT NOT NULL);
  CREATE INDEX ix_alerts_pce_fired ON alerts (pce_url, org_id, fired_at);
  CREATE TABLE alert_deliveries (
      id INTEGER PRIMARY KEY, alert_id INTEGER NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
      channel TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL, next_attempt_at TEXT,
      sent_at TEXT, last_error TEXT);
  CREATE INDEX ix_deliveries_due ON alert_deliveries (status, next_attempt_at);
  CREATE TABLE alert_notes (
      id INTEGER PRIMARY KEY, alert_id INTEGER NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
      body TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL);
  CREATE TABLE alert_rule_state (
      rule_id TEXT NOT NULL, subject_key TEXT NOT NULL, last_fired_at TEXT, recent_json TEXT NOT NULL,
      suppressed_cooldown INTEGER NOT NULL, suppressed_throttle INTEGER NOT NULL, last_status TEXT,
      PRIMARY KEY (rule_id, subject_key));
  CREATE TABLE alert_eval_state (
      source TEXT PRIMARY KEY, pce_url TEXT NOT NULL, org_id TEXT NOT NULL, watermark TEXT NOT NULL);
  CREATE TABLE channel_state (
      channel TEXT PRIMARY KEY, consecutive_failures INTEGER NOT NULL, cooldown_until TEXT,
      last_error TEXT, last_ok_at TEXT);
  ALTER TABLE job_health ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0;
  ```
  - `alert_notes` 不設存工作台條件的欄位：條件來自工作台，P6 才有寫入者，屆時再加（ruling：沒有寫入者的欄位不出貨）。
  - `alert_rule_state.last_status` 記規則最近一次評估的狀態：`ok`、`no_data`、`incomplete`、`collection_off`，供規則頁顯示。
- **`store/alerts.py`**：
  ```python
  def insert_alert(conn, *, pce_url: str, org_id: str, rule_name: str, trigger: Trigger, at: datetime,
                   channels: Sequence[str], deliver: bool) -> int   # Trigger 來自 domain.alerting，序列化在這裡做
  # deliver=False → 一筆 status=not_notified 或 grouped 的 delivery，channel 為 "-"；
  # channels 空 → 一筆 no_channel。
  def list_alerts(conn, *, pce_url, org_id, since, rule_type=None, severity=None, rule_id=None, limit, offset) -> tuple[list[Row], int]
  def get_alert(conn, alert_id, *, pce_url, org_id) -> Row | None
  def deliveries(conn, alert_id) -> list[Row]
  def add_note(conn, alert_id, *, body, created_by, at) -> int
  def notes(conn, alert_id) -> list[Row]
  def rule_state(conn, rule_id, subject_key) -> RuleState | None
  def save_rule_state(conn, rule_id, subject_key, state: RuleState, *, suppressed: Literal["cooldown", "throttle"] | None, status: str) -> None
  def eval_watermark(conn, source, *, pce_url, org_id) -> str | None    # PCE 不同時回 None
  def set_eval_watermark(conn, source, value, *, pce_url, org_id) -> None
  def due_deliveries(conn, now, limit) -> list[Row]; mark_delivery(...); channel_state(...); save_channel_state(...)
  def delete_alerts_before(conn, cutoff: datetime) -> int
  @dataclass(frozen=True)
  class RuleSummary: last_fired_at: datetime | None; fired_7d: int; suppressed_cooldown: int; suppressed_throttle: int; last_status: str | None
  def rule_summaries(conn, *, pce_url, org_id, since) -> dict[str, RuleSummary]
  ```
- **`services/alerts/evaluate.py`**：
  ```python
  def evaluate_events(ctx, *, now=None) -> EvalRun
  def evaluate_traffic(ctx, *, now=None) -> EvalRun        # traffic、bandwidth、volume
  def evaluate_lateral(ctx, *, now=None) -> EvalRun
  def evaluate_system(ctx, *, now=None, checks: Collection[SystemCheck] | None = None) -> EvalRun
  class EvalRun(BaseModel): source: str; evaluated: int; fired: int; suppressed: int; statuses: dict[str, str]
  ```
  - **共同流程**：
    1. 讀水位，`pce_url`／`org_id` 不同視同沒有。
    2. 沒有水位時設成「現在」的對應值，本次不評估，回 `evaluated=0`：
       - 事件：`max_event_id`；
       - 流量：`increments_watermark` 或 now；
       - 橫向移動：detections 的最大 `updated_at`；
       - 系統：gap 的最大 id。
    3. 評估規則，每個 Trigger 過 `gate`；擋下的只更新規則狀態並計數。
    4. 放行的寫入 `alerts`。`deliver = rule.notify and grouped_annotation is None`；通道是目前啟用的通道。
    5. 前進水位。寫入失敗時水位不前進。
  - **事件**：
    - 每次最多讀 5,000 筆新事件；有更多時同一次迴圈繼續讀，最多 10 批。剩下的下次再讀，並記 log。
    - count 規則的 `window_matches`：用 `events_in_window` 讀視窗內事件，在 Python 以 `event_matches` 計數。規則的所有 pattern 都是精確值時，以 `exact_types` 預先篩選。
  - **竄改告警的內容**（spec §6.5.2）：`agent.tampering` 的 Trigger 參數帶判讀：分類（signal／confirmed）、signal 型的 process、PID 與動作、主機的規律類型；confirmed 型照實寫「這類事件不帶 process 資訊」。
  - **竄改歸組**：`agent.tampering` 命中時，以 `domain.tamper.interpret` 取讀法，以主機的竄改模式（`tamper_summary` 結果，沒有就 `too_few`）和 `explained_by` 比對 annotations。比得到時，`grouped_annotation` 設成該 id，告警照記但不送。
  - **流量型**：
    - 每條規則：`window = (now − W, now]`，`new_after` = 上次水位；`increment_totals` 的結果轉成 `IncrementFacts`。
    - 依 `IncrementTotals.coverage` 定 `last_status`：
      - 僅事件模式為 `collection_off`；
      - 視窗內有缺口為 `incomplete`，Trigger 的 confidence 附缺口；
      - 頻寬或量規則在 `bytes_rows == 0` 時為 `no_data`。
  - **橫向移動**：
    - 讀 `updated_at > 水位` 的偵測。新增 `analysis.detections_changed_since(conn, since, limit)`，回傳列與 `created_at`。
    - `is_new` = `created_at > 水位`。
    - `severity_rose`：同一 fingerprint 已有告警（`alerts` 以 `rule_id`＋`subject_key` 查最近一筆的嚴重度）且這次較高。
  - **系統檢查**：輸入由 `services/alerts/system.py` 的 `system_facts(ctx, *, since_gap_id) -> SystemFacts` 組出：
    - `collection_status(ctx)` 的 sources 與 `disk_low`；
    - `ingest_state.open_gaps` 中 id 大於水位者；
    - `pce_health.latest(ctx)`；
    - `job_health` 的 `consecutive_failures`。
  - **`jobs/health.record_finish`**：失敗時 `consecutive_failures + 1`，成功歸零。
- **`services/alerts/retention.py`**：`run_alert_retention(ctx, *, now=None) -> int`，刪 `fired_at < now − retention_days` 的告警，備註與派送隨 CASCADE 刪除。
- **排程**（`jobs/scheduler.py`）：
  - 事件 job：`run_events_cycle` 之後 `evaluate_events`。
  - 流量 job：`run_traffic_cycle` → `run_detection` → `evaluate_traffic` → `evaluate_lateral`。每一步獨立 try，失敗記 log 並讓 job 以第一個錯誤結束，後面的步驟照跑。
  - 回填 job：晚到偵測補跑之後 `evaluate_lateral`。
  - 探測 job：`run_probe` 之後 `evaluate_system(checks={PCE_HEALTH})`。
  - 新 job `alerts_system`（60 秒）：`evaluate_system`，檢查 PCE_HEALTH 以外的四項。
  - 新 job `alerts_retention`（每日）。
  - 兩個新 job 加進 `job_intervals`。
  - 讀者登錄：`alerts.rules` → `services.alerts.evaluate`、`alerts.retention_days` → `services.alerts.retention`，從 PENDING 移出。

- [ ] **Step 1：失敗測試**：
  - store：`test_previous_pce_alerts_hidden`、`test_not_notified_and_grouped_recorded`、`test_no_channel_delivery_row`、`test_retention_cascades`、`test_watermark_ignored_for_other_pce`。
  - 事件：`test_first_run_does_not_alert_history`、`test_backfill_events_not_evaluated`、`test_immediate_event_alert_recorded_with_evidence`、`test_count_rule_window`、`test_cooldown_suppresses_and_counts`、`test_tamper_with_known_cause_grouped_not_sent`、`test_late_event_marked_late`、`test_event_batches_capped`。
  - 流量型：`test_traffic_rule_fires_on_growth`、`test_traffic_rule_incomplete_with_gap`、`test_events_only_mode_collection_off`、`test_volume_no_byte_data_status`。
  - 橫向移動：`test_lateral_alert_on_new_detection`、`test_lateral_realert_on_severity_rise_only`、`test_lateral_notify_false_recorded`。
  - 系統：`test_collection_failing_after_three`、`test_data_loss_new_gap_once`、`test_job_failing_uses_consecutive`、`test_pce_health_from_probe`。
  - 換 PCE：`test_first_run_after_switch_starts_now`。
  - 排程：`test_traffic_job_order_and_isolation`、`test_new_jobs_in_intervals`。
- [ ] **Step 2：** `timeout 900 .venv/bin/python -m pytest tests_v6/store/test_alert_store.py tests_v6/services/alerts tests_v6/jobs tests_v6/gates -q` → FAIL
- [ ] **Step 3：實作。**
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/store illumio_ops/services/alerts illumio_ops/jobs tests_v6/store tests_v6/services/alerts tests_v6/jobs tests_v6/gates && git commit -m "feat(v6): alert records and evaluation after each collection cycle"`

---

### Task 6：訊息、通道與派送

**Files:**
- Create: `illumio_ops/services/alerts/messages.py`、`illumio_ops/services/alerts/channels.py`、`illumio_ops/services/alerts/dispatch.py`、`tests_v6/services/alerts/test_messages.py`、`tests_v6/services/alerts/test_channels.py`、`tests_v6/services/alerts/test_dispatch.py`
- Modify: `illumio_ops/jobs/scheduler.py`、`illumio_ops/i18n/en.json`、`illumio_ops/i18n/zh_TW.json`、`tests_v6/gates/test_settings_readers.py`

**Interfaces:**
- **`messages.py`**（文字由 i18n 產生，語系取 `display.language`，時間依 `display.timezone` 顯示）：
  ```python
  @dataclass(frozen=True)
  class Rendered: subject: str; text: str; html: str | None; card: dict[str, Any] | None; payload: dict[str, Any] | None
  @dataclass(frozen=True)
  class AlertView:      # 由 alerts 列轉成，派送與 GUI 共用
      id: int; rule_name: str; severity: Severity; subject_key: str; fired_at: datetime; late: bool
      message_key: str; params: Mapping[str, Any]; facts: Mapping[str, Any]; confidence: Mapping[str, Any]
  def alert_view(row: sqlite3.Row, *, lang: Language) -> AlertView   # rule_name 為空時翻譯 pack_key
  def render(alerts: Sequence[AlertView], channel: ChannelKind, *, lang: Language, tz: tzinfo | None, console_url: str | None) -> Rendered
  ```
  - 主旨：`[illumio-ops] <最高嚴重度> <第一則規則名稱>`，多則時加「等 N 則」。
  - 每則告警：規則名稱、嚴重度、對象、一句話摘要、關鍵數字、可信度警語（延遲、覆蓋率、缺口）；晚到的標「晚到」。
  - **長度上限與截斷**（反目標 5，每種都要寫明省略了什麼）：
    - LINE：4,500 字（API 上限 5,000）；
    - Telegram：3,800 字（上限 4,096，HTML 標籤另計）；
    - Teams：最多 10 則；
    - mail：最多 50 則，每則證據摘要最多 10 列；
    - webhook：最多 100 則，JSON 內每則完整欄位。
    - 超過時以「…另有 N 則，請到 illumio-ops 檢視」收尾。
  - 單則告警本身超過上限時，截斷摘要並標「（已截斷）」。
- **`channels.py`**：
  ```python
  @dataclass(frozen=True)
  class SendResult: ok: bool; error: str | None   # error 已去除祕密
  def send(channel: ChannelKind, cfg: AlertChannels, rendered: Rendered, *, timeout: float = 10.0) -> SendResult
  def scrub(text: str, cfg: AlertChannels) -> str
  ```
  - 從 5.x `src/alerts/plugins.py` 回收：LINE push、Telegram sendMessage、Teams card POST、webhook POST、SMTP，以及 `redact_webhook_url`、`scrub_webhook_url`、Telegram token 遮罩、`_sanitize_header`（CR/LF）。
  - SMTP：`security` 為 `starttls` 時用 `starttls()`；為 `tls` 時用 `SMTP_SSL`；`username` 非空才登入；檢查 `sendmail` 的 refused。5.x 的 `ILLUMIO_SMTP_PASSWORD` 環境變數不支援，因為設定是唯一來源。
  - 成功判定：LINE／Telegram 200，Teams／webhook 200–204。
  - `scrub` 移除：所有通道祕密的字面值、webhook／Teams URL 的路徑與查詢、Telegram token。
- **`dispatch.py`**：
  ```python
  def run_dispatch(ctx, *, now=None) -> DispatchRun
  def send_test(ctx, channel: ChannelKind, *, cfg: AlertChannels | None = None) -> SendResult   # 同步、不寫任何紀錄
  ```
  - 每次：
    1. 取到期的 pending 派送，最多 200 則告警，依通道分組。
    2. 每個通道合併成一則訊息送出。
    3. 成功：該批全部 `sent`。
    4. 失敗：`attempts + 1`，退避 1、5、15 分；第 3 次失敗為 `failed`（最終），錯誤寫入 `last_error`。
  - 通道連續失敗 3 次（不分批）進入 5 分鐘冷卻。冷卻中不送，也不增加 attempts（沿用 5.x B2）。
  - 通道在送出前被停用時，其 pending 改為 `failed`，`last_error="channel_disabled"`。
  - `send_test` 用傳入的 `cfg`（設定頁未儲存的值）或目前設定，送一則固定的測試訊息。
- **排程**：新 job `alerts_dispatch`（60 秒），加入 `job_intervals`。
- 讀者登錄：`alerts.channels.*` → `services.alerts.channels`；`pce.console_url` 與 `display.timezone` → `services.alerts.messages`，從 PENDING 移出。

- [ ] **Step 1：失敗測試**：
  - 訊息：`test_line_truncates_with_remaining_count`、`test_telegram_limit_counts_markup`、`test_mail_has_plain_and_html`、`test_teams_card_caps_items`、`test_webhook_payload_fields`、`test_time_in_display_timezone`、`test_zh_tw_and_en_rendered`、`test_late_and_confidence_caveats_shown`。
  - 通道（以本機 HTTP 伺服器與本機 SMTP 收信器測試，後者用標準庫 `socketserver` 寫最小 SMTP 對話）：`test_line_success_and_failure`、`test_smtp_starttls_and_auth`、`test_smtp_refused_recipient_is_failure`、`test_delivery_error_scrubs_secrets`（四個 HTTP 通道各一，錯誤 body 回顯 URL 與 token）、`test_header_injection_sanitized`。
  - 派送：`test_batches_per_channel`、`test_failed_delivery_retried_then_final`、`test_channel_cooldown_does_not_consume_attempts`、`test_no_enabled_channel_marks_undelivered`、`test_disabled_channel_pending_failed`、`test_send_test_writes_nothing`。
- [ ] **Step 2：** `timeout 900 .venv/bin/python -m pytest tests_v6/services/alerts tests_v6/i18n tests_v6/gates tests_v6/jobs -q` → FAIL
- [ ] **Step 3：實作。**
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/services/alerts illumio_ops/jobs/scheduler.py illumio_ops/i18n tests_v6/services/alerts tests_v6/gates tests_v6/jobs && git commit -m "feat(v6): alert messages, five channels and the dispatcher"`

---

### Task 7：規則試算與最佳實務包套用（服務層）

**Files:**
- Create: `illumio_ops/services/alerts/rules.py`、`tests_v6/services/alerts/test_rules.py`

**Interfaces:**
```python
def preview_rule(ctx, rule: AlertRule, *, hours: int, now=None) -> RulePreview
class RulePreview(BaseModel):
    would_fire: int; samples: list[dict[str, Any]]; status: str; coverage_note: str | None
def apply_pack(current: tuple[AlertRule, ...], *, mode: Literal["append_missing", "replace"], notify_new_defaults: bool) -> tuple[AlertRule, ...]
class RuleListItem(BaseModel): rule: AlertRule; display_name: str; summary: RuleSummary | None   # display_name：name 為空時翻譯 pack_key
def rule_list(ctx, *, now=None) -> list[RuleListItem]
```
- **試算**：用最近 `hours` 小時（1–168）的資料、同一套評估函式，不寫任何紀錄、不更新冷卻。
  - 事件：讀視窗內事件，逐一以「當時」為 now 重播。
  - 流量型：以每小時一個視窗算增量。
  - 橫向移動：讀期間內的偵測。
  - 系統檢查：不支援試算，回 `status="not_applicable"`。
- **套用最佳實務包**：
  - `append_missing`：只加 id 不存在的包內規則，既有規則（含使用者改過的包內規則）不動。
  - `replace`：包內規則全部回到預設，使用者自建的規則保留。這和 5.x 的 replace 不同：5.x 會刪光自建規則，所以才需要 `rule_backups`。v6 不刪自建規則，不需要備份（ruling）。

- [ ] **Step 1：失敗測試**：`test_preview_counts_without_writing`、`test_preview_does_not_touch_cooldown`、`test_preview_system_not_applicable`、`test_append_missing_keeps_edits`、`test_replace_restores_pack_keeps_custom`、`test_rule_list_includes_last_status`。
- [ ] **Step 2：** `timeout 600 .venv/bin/python -m pytest tests_v6/services/alerts/test_rules.py -q` → FAIL
- [ ] **Step 3：實作。**
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/services/alerts/rules.py tests_v6/services/alerts/test_rules.py && git commit -m "feat(v6): alert rule preview and best-practice pack apply"`

---

### Task 8：API 路由

**Files:**
- Create: `illumio_ops/web/routes/alerts.py`、`illumio_ops/web/routes/alert_rules.py`、`illumio_ops/web/routes/system_channels.py`、`tests_v6/web/test_alerts_routes.py`、`tests_v6/web/test_alert_rules_routes.py`、`tests_v6/web/test_system_channels.py`
- Modify: `illumio_ops/web/app.py`、`web/src/api/contracts.json`、`web/src/api/generated.ts`

**Interfaces**（op id／方法／路徑／請求 → 回應）：

| op id | 方法與路徑 | 說明 |
|---|---|---|
| `alerts.list` | GET `/api/alerts?since=&type=&severity=&rule=&page=` | 目前 PCE 的告警，每頁 50，回總數；每列帶派送狀態摘要 |
| `alerts.get` | GET `/api/alerts/<id>` | 詳情：訊息參數、數字、可信度、派送明細、註記、主控台連結 |
| `alerts.evidence` | GET `/api/alerts/<id>/evidence` | 執行證據段落：流量走 `query_flows` 的 detail（上限 200 列，`limit_hit` 照實回報），事件走 `event_detail` |
| `alerts.note_add` | POST `/api/alerts/<id>/notes` | `{body}`，1–4,000 字；`created_by` 取登入帳號 |
| `alerts.explain` | POST `/api/alerts/<id>/explain` | `{row: int}`：對證據第 row 列呼叫 P3 `explain_flow`，只有流量告警可用 |
| `alert_rules.list` | GET `/api/alert-rules` | `revision`、規則清單（`rule_list`）、最佳實務包是否有缺 |
| `alert_rules.create` | POST `/api/alert-rules` | `{revision, rule}`；伺服器產生 id，`pack_key` 一律 None |
| `alert_rules.update` | PUT `/api/alert-rules/<id>` | `{revision, rule}`；id 不可改 |
| `alert_rules.delete` | DELETE `/api/alert-rules/<id>?revision=` | |
| `alert_rules.preview` | POST `/api/alert-rules/preview` | `{rule, hours}` → `RulePreview` |
| `alert_rules.pack` | POST `/api/alert-rules/pack` | `{revision, mode}` |
| `system.channels.get` | GET `/api/system/channels` | `revision`、遮罩後的通道設定、`channel_state`（最近錯誤、冷卻） |
| `system.channels.update` | PUT `/api/system/channels` | `{revision, channels}`；祕密欄位為空字串或 `MASK` 時保留原值 |
| `system.channels.test` | POST `/api/system/channels/test` | `{channel, channels?}`：未儲存的值也能測；祕密欄位 `MASK` 時用已存的值 |

- **主控台連結**：
  - `console_url` 留空時，SaaS 用 `https://console.illum.io`，地端用 API 網址（spec §6.5 PCE 健康檢查段）。
  - 對象是主機時加 `/#/workloads/<uuid>`；其他對象只連主控台首頁。
  - 主機路徑的正確性在 Task 11 Step 3 於 lab 實機確認；不對就改成只連首頁並記 ruling。
- **路由與服務層的分工**：路由只做驗證輸入、呼叫服務、包信封；規則的 CRUD 經 `SettingsStore.update`，所以 revision 衝突與驗證錯誤沿用 P1 的對應。

- [ ] **Step 1：失敗測試**：
  - 告警：`test_list_filters_and_pages`、`test_get_other_pce_alert_404`、`test_evidence_limit_hit_reported`、`test_note_add_requires_body`、`test_explain_only_for_traffic_alerts`、`test_console_link_by_deployment`。
  - 規則：`test_create_assigns_id`、`test_update_keeps_id`、`test_invalid_regex_400_with_field`、`test_stale_revision_409`、`test_preview_route`、`test_pack_modes`。
  - 通道：`test_channels_get_masks_secrets`、`test_channels_put_mask_keeps_secret`、`test_channels_test_uses_unsaved_values`、`test_channels_test_mask_uses_stored_secret`。
- [ ] **Step 2：** `timeout 600 .venv/bin/python -m pytest tests_v6/web tests_v6/gates -q` → FAIL
- [ ] **Step 3：實作**；`bash scripts/v6/gen_contracts.sh`。契約覆蓋守門會因前端還沒呼叫而紅，Task 9 補上；本任務的 commit 先不跑閘門，Task 9 結束時跑。這是本計畫唯一一處先 commit 後閘門延後，帳本記 Ruling。
- [ ] **Step 4：** 上列測試 PASS（不含 `test_contract_coverage`）。
- [ ] **Step 5：Commit** `git add illumio_ops/web tests_v6/web web/src/api/contracts.json web/src/api/generated.ts && git commit -m "feat(v6): alert, alert-rule and channel API"`

---

### Task 9：GUI——告警、規則、通知通道

**Files:**
- Create: `web/src/pages/alerts/AlertList.tsx`、`web/src/pages/alerts/AlertDetail.tsx`、`web/src/pages/alerts/Rules.tsx`、`web/src/pages/alerts/RuleEditor.tsx`、`web/src/components/ConditionEditor.tsx`、`web/src/pages/system/Channels.tsx`、`tests_v6/e2e/test_alerts_e2e.py`、`tests_v6/e2e/test_channels_e2e.py`
- Modify: `web/src/shell/nav.ts`、`web/src/shell/Shell.tsx`、i18n 兩個語系、`web/src/styles/*`（必要時）

**Interfaces 與頁面**（Direction D、人話文案、每頁一顆主要動作）：
- **導覽**：`NavSection` 改為 `"main" | "system"`。Shell 先列 main 區（首頁、告警），再列「設定」區。「告警」在 main，路徑 `/alerts`；「通知通道」在設定區，路徑 `/system/channels`。
- **告警清單** `/alerts`：
  - 篩選列：期間（24 小時、7 天、30 天）、型別、嚴重度、規則。
  - 每列：時間（顯示時區）、嚴重度、規則名稱、對象、一句話摘要，以及派送狀態徽章：已送、失敗、未通知（規則設定）、歸組（已知原因）、沒有啟用的通道。
  - 分頁，寫明「共 N 則」。主要動作：無（檢視頁）；右上「規則」連結。
- **告警詳情** `/alerts/:id`：
  - 上段：一句話摘要與「為什麼重要」、數字、可信度警語（延遲、覆蓋率、缺口，反目標 8）、晚到標記。
  - 證據區：呼叫 `alerts.evidence`，以表格呈現；`limit_hit` 時寫明「只列前 200 列」。流量告警每列有「政策解釋」按鈕，呼叫 `alerts.explain`，結果展開在該列下方。
  - 動作：主要動作「在工作台開啟」**P4 不出現**（工作台在 P6；ruling：證據直接在本頁呈現，按鈕隨 P6 加入，已寫入路線圖 P6 列）。次要動作「在 PCE 主控台開啟」。
  - 派送明細：每通道的狀態、次數、最後錯誤。
  - 註記：清單（誰、何時）與新增表單。
- **規則** `/alerts/rules`：
  - 清單：每列名稱、型別、啟用與通知開關、最後觸發、近 7 天次數、被冷卻或 throttle 擋下的次數、狀態（`no_data`、`incomplete`、`collection_off` 用人話說明）。
  - 主要動作「新增規則」；次要動作「載入最佳實務規則」，選附加缺少的或重設包內規則，執行前說明影響。
  - 最佳實務包裡 `notify=false` 的規則顯示「只記錄，不送通知」並可一鍵開啟。
- **規則編輯器** `/alerts/rules/new`、`/alerts/rules/:id`：
  - 先選型別，再依型別顯示欄位；每個欄位附一句說明。門檻與視窗同一列寫成句子，例如「10 分鐘內 ≥ 25 條被擋連線」。
  - 流量型用 `ConditionEditor`：
    - 來源、目的各自可加 label（從 `system.lateral.get` 的 `label_choices` 取，值超過上限時寫明）、IP／網段、排除；
    - port／協定；reported 判定；發起端 process／使用者；排除系統帳號。
  - 事件型：事件型別（可多個）、status、事件嚴重度、進階的欄位比對。
  - 橫向移動型：偵測器多選、最低嚴重度、只限重要資產。
  - 系統型：檢查項目。
  - 按鈕：「試算最近 24 小時」顯示會觸發幾次與樣本；主要動作「儲存」。
  - 驗證錯誤顯示在對應欄位。
- **通知通道** `/system/channels`：
  - 五張卡片，每張有啟用開關、欄位（祕密欄位顯示遮罩，留空表示不變）、「送出測試」（不必先儲存）、最近一次錯誤與冷卻狀態。
  - 主要動作「儲存」。

- [ ] **Step 1：失敗測試**（Playwright 對本機測試伺服器，比照 P3 的 e2e；webhook 測試用本機 HTTP 收信器）：
  - `test_alerts_nav_and_list`：種一則告警，清單看得到、徽章正確。
  - `test_alert_detail_shows_delivery_status`：失敗的派送顯示次數與已去除祕密的錯誤。
  - `test_alert_note_persists`：新增註記、重新載入後仍在。
  - `test_rule_create_traffic_with_condition`：建立 port 22、判定 blocked 的規則，儲存後清單出現。
  - `test_rule_invalid_regex_field_error`。
  - `test_pack_append_missing`。
  - `test_channels_mask_and_test_webhook`：填 webhook URL、送出測試，收信器收到、頁面顯示成功；重新載入後 URL 顯示遮罩。
- [ ] **Step 2：** `timeout 900 .venv/bin/python -m pytest tests_v6/e2e/test_alerts_e2e.py tests_v6/e2e/test_channels_e2e.py tests_v6/gates -q` → FAIL
- [ ] **Step 3：實作**；`npm --prefix web run typecheck && npm --prefix web run build`。
- [ ] **Step 4：PASS；閘門**（含 Task 8 延後的契約覆蓋與 `test_no_p4_pending_left`）。
- [ ] **Step 5：Commit** `git add web/src illumio_ops/i18n tests_v6/e2e/test_alerts_e2e.py tests_v6/e2e/test_channels_e2e.py && git commit -m "feat(v6): Alerts, alert rules and notification channel pages"`

---

### Task 10：遷移器——規則、通道、SMTP

**Files:**
- Create: `illumio_ops/migrate/v5_alerts.py`、`tests_v6/migrate/test_v5_alerts.py`、`tests_v6/fixtures/migrate/v5_106_alerts.json`、`tests_v6/fixtures/migrate/v5_0_0_alerts.json`
- Modify: `illumio_ops/migrate/v5.py`、`illumio_ops/migrate/v5_models.py`、`illumio_ops/migrate/__main__.py`、`tests_v6/migrate/test_v5.py`、i18n 兩個語系

**Interfaces:**
```python
def read_v5_rules(v5_root: Path) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]
# (config/alerts.json 的 rules；舊版 alerts.json 是通道設定時改回傳第二個值。檔案不存在時兩者都 None)
def migrate_alerts(raw_config: dict[str, Any], rules: list[dict[str, Any]] | None,
                   legacy_channels: dict[str, Any] | None) -> tuple[AlertSettings, list[MigrationItem], list[tuple[str, str]]]
```
- `migrate_v5` 改為同時讀規則檔，`PHASE_OF_SECTION` 刪掉 alerts、email、smtp、rules 四項。報告的 source 名稱：
  - 規則：`rules[<序號>] <名稱或 name_key>`；
  - 通道：原鍵路徑。
- **通道對應**：

  | 5.x | v6 |
  |---|---|
  | `alerts.active` 含 `mail` | `smtp.enabled` |
  | `email.sender`、`email.recipients` | `smtp.sender`、`smtp.recipients` |
  | `smtp.host`、`smtp.port` | 同名 |
  | `smtp.user` | `smtp.username`（`enable_auth=false` 時寫空字串，報告記 rewritten） |
  | `smtp.password` | 同（`enable_auth=false` 時丟棄並記 dropped） |
  | `smtp.enable_tls` | `security="starttls"`，否則 `"none"` |
  | `line_channel_access_token`、`line_token`（別名）、`line_target_id` | `line.*`；`active` 含 `line` 時啟用 |
  | `telegram_*`、`teams_webhook_url`、`webhook_url` | 對應通道；`active` 決定啟用 |

  - 啟用但必要欄位不全的通道：改成停用並報告（rewritten），不擋遷移。
  - 報告附一句提醒：5.x 若用環境變數 `ILLUMIO_SMTP_PASSWORD` 提供密碼，需到通知通道頁補填。
- **規則對應**：
  - **共同欄位**：
    - id：整數或非 32 hex 的 id 改成新的 32 hex（報告記 rewritten）；
    - `enabled` 缺省為 true，只有 `False` 停用（5.x 語意）；
    - `cooldown_minutes` 缺省用 `threshold_window`（5.x 引擎語意）；
    - `throttle`／`alert_throttle`：字串 `N/M[smhd]` 或 dict 轉成 `Throttle`，週期超過 7 天時降到 7 天並報告；
    - `name_key` 在最佳實務包內時設 `pack_key`、`name=""`；否則用 `name`。
  - **event**：
    - `filter_value` 逗號拆成 `event_types`；`filter_status`、`filter_severity` 照搬，`error` 保留，因為比對時視同 `err`；
    - `match_fields`／`filter_match_fields` 照搬；
    - `threshold_type`、`threshold_count`（`threshold` 是 CLI 誤寫的別名，§7）、`threshold_window`；
    - 嚴重度：包內規則用包內設定，其餘 None（依事件，與 5.x 相同）；
    - pattern 不合法時，規則以停用狀態搬入並報告 unsupported 與原因，不擋其他規則。
  - **traffic／bandwidth／volume**：
    - `pd`：0、1、2 對應單一判定；-1、3 或缺省表示不篩。
    - legacy 純量鍵與 FilterBar 鍵依下表轉成 `FlowCondition`。
    - 門檻：`threshold_count` 對應連線數、Mbps 或 MB；視窗不足 10 分鐘時升到 10 並報告。

    | 5.x 鍵 | v6 |
    |---|---|
    | `src_label`／`dst_label`／`ex_*_label`（`key=value` 或 `key:value`，取先出現的分隔符）、`src_labels` 等 | `EndpointFilter.labels` |
    | `src_ip_in`／`dst_ip_in`／`ex_src_ip`／`ex_dst_ip`（IP、CIDR；IPv4 區間用 `summarize_address_range` 轉成 CIDR） | `ips` |
    | `src_workloads` 等 | `hrefs` |
    | `port`、`proto`、`ex_port`、`ports`、`ex_ports` | `ports`／`exclude_ports` |
    | `process_name` | `initiator_process`（5.x 比對回報端 process，outbound 時即發起端；報告記 rewritten 並說明） |

  - **不支援的鍵**：`*_iplists`、`any_*`、`services`／`ex_services`（href）、`windows_service_name`、`transmission`、label group。帶這些鍵的規則以停用狀態搬入，條件去掉這些鍵，報告逐鍵列為 unsupported 並說明 v6.0 不支援。
  - **system**（`pce_health`）：`SystemRule(check=pce_health)`；`threshold_*` 與 `match_fields` 記 dropped（5.x 不讀）。
  - **新預設規則**：5.x 沒有的包內規則（系統檢查四項、橫向移動三條）加入；橫向移動三條 `notify=false`（spec §7），報告列出這些規則與開啟方式。
- **fixture**：
  - `v5_106_alerts.json`：.106 的 19 條規則加通道設定的形狀。祕密換成 `"<redacted-NN>"`，名稱保留。
  - `v5_0_0_alerts.json`：由 git tag `v5.0.0` 的 `_best_practice_rules` 與 GUI 寫入端推出 5.0.0 的形狀：舊版 alerts.json 是通道設定，加上 legacy 純量鍵的 traffic 規則與 CLI 的 `threshold` 誤寫。

- [ ] **Step 1：失敗測試**：
  - `test_106_rules_all_accounted`：19 條每條都有報告項目，16 條事件規則的 `pack_key` 正確。
  - `test_106_traffic_rule_to_blocked_condition`、`test_bandwidth_pd_minus_one_means_all`、`test_system_threshold_keys_dropped`、`test_integer_ids_rewritten`。
  - `test_cooldown_defaults_to_window`、`test_threshold_alias`、`test_throttle_dict_and_string`。
  - `test_unsupported_filterbar_key_disables_rule`、`test_invalid_regex_rule_disabled_not_blocking`。
  - `test_old_alerts_json_channel_shape`、`test_active_list_enables_channels`、`test_incomplete_channel_disabled`。
  - `test_new_lateral_defaults_not_notified`、`test_report_never_contains_secret_values`（把報告整個轉成字串，fixture 的祕密字面值不得出現）。
- [ ] **Step 2：** `timeout 600 .venv/bin/python -m pytest tests_v6/migrate -q` → FAIL
- [ ] **Step 3：實作。**
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/migrate illumio_ops/i18n tests_v6/migrate tests_v6/fixtures/migrate && git commit -m "feat(v6): migrate 5.x alert rules, channels and SMTP"`

---

### Task 11：驗收（.106、lab、NFR、規模）、文件回寫與全分支審查

驗證腳本放 `tmp/v6-p4-verification/`（gitignored）；部署腳本從主 checkout 的 `tmp/v6-p3-verification/` 複製並改路徑。

- [ ] **Step 1：打包並部署到 .106**：
  - `PYTHON=.venv/bin/python bash scripts/v6/build_bundle.sh`；
  - 套件交換部署：停服務、備份、換上、離線 pip、啟動、登入頁 200；
  - 確認 0003、0004 遷移成功、5.x 仍 active。
- [ ] **Step 2：遷移器與 .106 的 19 條規則**：
  - 在 .106 以 `python -m illumio_ops.migrate --report-only` 對 5.x 安裝產出報告，逐條核對。
  - **評估比對**：腳本取 .106 v6 店內近 30 天的事件 `raw_json`，對 16 條事件規則分別以 5.x `matches_event_rule`（.106 的 5.x checkout）與 v6 `event_matches` 判斷每筆事件，結果必須完全相同。traffic 規則比對資料模型不同，改為列出兩邊在同一 24 小時的觸發次數並說明差異來源（5.x 游標少收、v6 用增量）。
  - **套用通道**：停 v6 服務，以腳本把遷移結果的 `alerts` 段寫進 v6 設定（經 `SettingsStore`，不印任何值），啟動。
  - 報告註明：v6 與 5.x 會對同一個 LINE 與信箱各送一份，屬預期。
- [ ] **Step 3：事件告警真實送達**（spec 路線圖驗收）：
  - 經 lab MCP 建立再刪除一個 draft ruleset，觸發 `rule_set.create`、`rule_set.delete`。
  - 下一輪事件收集後，`alerts` 出現對應告警，LINE 與 email 的派送為 `sent`。
  - 請使用者確認 LINE 與信箱實際收到（寫進決策清單）。
  - 在 GUI 開告警詳情，「在 PCE 主控台開啟」的落點以瀏覽器實際確認；主機路徑不對時依 Task 8 的 ruling 處理。
- [ ] **Step 4：橫向移動告警送達**：
  - 比照 P3 Task 15 Step 6，從一台非 idle 的 lab 受管主機在 60 分鐘內對 ≥ 10 台主機的 22 port 發起連線。
  - 在 10–20 分鐘內產生扇出偵測，對應的 `lateral` 告警送達。.106 是升級安裝，橫向移動預設規則 `notify=false`：先在規則頁開啟通知，這一步也驗證「只記錄」到「送出」的切換。
- [ ] **Step 5：NFR SaaS 觸發一次**：
  - **不得把 .106 的 v6 換到 NFR**：換 PCE 會清空流量庫，並重置正在累積的 30 天基準期。
  - 在本機開第二個 v6 根目錄：不同 port、僅事件模式、通道只開 webhook，送到本機收信器。用 NFR 的臨時 read_only service account，比照 P2 `nfr_switch.py` 的建立與刪除方式。
  - 加一條 `label.create,label.delete` 事件規則，經 NFR MCP 建刪一個 label，收信器收到告警。
  - 測完刪除 service account 與本機根目錄。
- [ ] **Step 6：規模**（1,000 台合成庫副本，比照 P3 Task 15 Step 7）：
  - 尖峰每輪持鎖：含增量寫入，不得超過 P3 實測最大 28.1 秒的 10%（≤ 30.9 秒）。
  - `flow_increments` 一天的列數與大小。
  - `evaluate_traffic`：最佳實務 traffic 規則在 10 分鐘視窗的耗時 ≤ 5 秒。
  - 偵測（Task 1 之後）熱跑耗時，目標比 P3 的 85 秒少約 40 秒。
  - 超過目標時記 Ruling 並回報使用者。
- [ ] **Step 7：最終全分支審查**：
  - Codex reviewer（`reviewer` profile、effort xhigh），範圍從 `035f7519` 到 HEAD。
  - 每一項 finding 都對照原始碼查證；Critical／Important 一次修完，每項先有變紅的測試；Minor 記入帳本延後。
- [ ] **Step 8：文件回寫**：
  - spec §6.5.2 寫入本計畫「告警語意」各項裁定；§6.6 F12 補「增量表」做法；§5 補規模實測。
  - 路線圖 P4 標「完成」並附驗收結果；P6 列加「告警詳情的『在工作台開啟』」。
  - 驗收報告 `tmp/v6-p4-verification/report.md`。
- [ ] **Step 9：Commit** `git add docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md docs/superpowers/plans/2026-10-24-v6-roadmap.md && git commit -m "docs(v6): record P4 acceptance and alert semantics"`，之後依使用者決定合併。
