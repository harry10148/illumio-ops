# illumio-ops v6 P4.5 允許流量的異常偵測 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本計畫以 Native（superpowers:executing-plans）執行：使用者 2026-10-26 指示「都照你建議」，做完再一次給決策。

**Goal:** 在沒被擋的正常流量裡找出原廠沒有的異常（spec §6.5.8 第一批 A、B、C、D、E），並把管理 port 分成遠端執行、目錄／認證、資料庫三類，讓 P3 偵測器只看該看的 port。

**Architecture:**
- **偵測仍是純函式**：新偵測器放在 `domain/anomaly.py`，共用 `domain/detectors.py` 的 `Obs`、`Detection`、`DetectorStatus`，由同一個 `run_detectors` 依 `DetectorKind` 執行，結果寫進同一張 `detections` 表，所以首頁焦點、`lateral` 型告警、冷卻與嚴重度上升語意（spec §6.5.2）全部沿用。
- **讀取分兩組**：P3 偵測器照舊讀管理 port（含回看期）；新偵測器另讀本輪視窗內**所有 port、沒被擋**的連線。基準與歷史由服務層先查好，以資料結構交給領域函式（`AnomalyData`），領域不做 I/O。
- **新基準在寫入時維護**：流量庫 0006 新增「帳號 × 來源主機」「主機 × 發起程式」兩張基準（升級時從 `flow_rollup_daily` 種入），以及「來源每小時活動」表（由 `_record_growth` 的增量在寫入時彙總，不另掃 flows）。
- **已知標記**：操作者可在告警詳情把某則偵測（或某台主機的某類偵測）標為已知；之後同樣的偵測照樣記錄告警，但歸組不送通知（沿用竄改歸組的 `grouped_annotation` 路徑）。

**Tech Stack:** 沿用 P1–P4，不新增執行期依賴。

**Spec:** `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md`。本階段依據：
- §6.5.8（定位、正常流量＝not_blocked、共通原則、port 三分類、候選表 A–E、E③ 改黑名單）；使用者 2026-10-26「都照你建議」：第一批 A、B、C、D、E＋三分類；A 用 PCE 標籤（預設 app＋role）；同意三分類改變 P3 偵測器行為；排在 P5 之前。
- §6.5.1（偵測器、前兆加權、冷啟動、覆蓋率揭露、重要資產）、§6.5.2（告警語意）、§6.5.4（竄改已知原因的歸組做法）。
- §4.3 反目標 1（不得假裝成功）、8（不得把「無法判斷」說成「沒有」）；§5 規模（1,000 台、每輪 10 分鐘）。

路線圖 `docs/superpowers/plans/2026-10-24-v6-roadmap.md` 的「P4.5 允許流量的異常偵測」節。

## Global Constraints

**沿用**
- P1–P4 的 Global Constraints 全部沿用：Python 3.12、無 `print(`、路徑只從 `InstallPaths` 推、每表單一寫入者、值域只在 `domain/values.py`、領域不 import 其他子套件且不做 I/O、時間一律帶時區的 UTC、失敗不得看起來像空結果、不做流量抽樣。
- 英文 conventional commits，結尾附 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` 與 `Claude-Session: https://claude.ai/code/session_013iFADnkFuumZxobTw5jFC3`；只 `git add <明確路徑>`；每次 commit 後 `git status --porcelain illumio_ops tests_v6 web scripts/v6` 為空。
- 測試在前景跑並加 timeout，一律用 `.venv/bin/python`。

**分支、worktree、閘門**
- 分支 `feat/v6-p45-anomaly`，worktree `.worktrees/v6-p45`，從 main `3f1b99e2` 開（已建立，`.venv` 與 `web/node_modules` 已安裝）。每個任務開始前 `pwd && git branch --show-current`。
- 閘門腳本 `.superpowers/sdd/2026-10-26-v6-phase45-anomaly/gates.sh`：內容同 P4 的 `gates.sh`，路徑改成 `.worktrees/v6-p45`。每個任務之間親自跑；先 commit 再跑閘門。
- 不 push、不合併；完成後在最後的回報請使用者決定。

**新增一個 `DetectorKind` 時一定要一起改的地方**（漏一處會在執行期壞，不一定有測試先紅）
1. `domain/values.py` 的 `DetectorKind`；`tests_v6/domain/test_values.py` 的列舉清單。
2. `domain/detectors.py` 的 `DETECTORS`、`dedup_windows()`；`MANAGEMENT_DETECTORS` 改成**明列**的集合（不得再用 `frozenset(DetectorKind) - {...}`，否則新偵測器沒設管理 port 時會被停用）。
3. 帳號為主體的偵測器加進 `apply_precursors` 的跳過集合（前兆是主機的事）。
4. `domain/focus.py` 的 `DETECTION_TITLE_KEYS`（`LATERAL_MESSAGE_KEYS` 引用它）。
5. `i18n/zh_TW.json` 與 `i18n/en.json` 的 `detector_name_<kind>`、`focus_title_<kind>`，以及新的狀態原因鍵。
6. `web/src/pages/system/Lateral.tsx` 與 `web/src/pages/alerts/RuleEditor.tsx` 的偵測器名稱對照；`bash scripts/v6/gen_contracts.sh` 重產契約。
7. `services/analysis/detect.py` 的 `_lookback()`（偵測器有自己的視窗時）。

**語意（全部偵測器共通，spec §6.5.8 共通原則）**
- 只評估 origin＝`ingest`、在本輪視窗 `(lo, hi]` 最後出現的連線；回填只當基準。
- 「沒被擋」＝ `allowed`、`potentially_blocked`、`unknown`（`not_blocked()`）。
- 依賴基準的偵測器（A、C、D 新程式、E②）在 `baseline_full()` 為假時狀態寫 `accumulating`（`detector_baseline_accumulating`），不發偵測。
- 依賴選用欄位的偵測器（C 帳號、D 程式）照 `_coverage_status` 寫明覆蓋；視窗內完全沒有該欄位時 `no_data`。
- 目的地是重要資產時嚴重度升一級（`raise_severity`）。
- 時間只能判「時間上接得起來」，文案不得寫成確定的攻擊。

## Review Focus

1. **升級既有設定**：v4 設定裡 `extra_admin_ports` 沒有 `category`、`removed_admin_ports` 也沒有 → 載入成功，新增的 port 視為遠端執行類，移除不看類別。（Task 1 測試）
2. **換 PCE 發生在讀取途中**：新增的每個讀取函式在讀完後比對流量庫世代，不同就丟 `StaleGeneration`，不得把上一台的基準交給偵測器。（Task 3 測試）
3. **群組邊界**：主機缺任一群組 label、群組剛好等於下限、整個群組同時開始做同一件事（部署）→ 前兩者照規則、第三者不偵測。（Task 4 測試）
4. **帳號大小寫**：`CORP\Alice` 與 `corp\alice` 在寫基準與讀基準時都用 `account_key()` 視為同一帳號。（Task 3、5 測試）
5. **每日重讀（late pass）**：量暴增與目錄量暴增不在 late pass 評估、也不重複計數；late 增量不進每小時活動。（Task 3、7 測試）

---

### Task 0：開工

- [ ] **Step 1**：`pwd && git branch --show-current` → `.worktrees/v6-p45`、`feat/v6-p45-anomaly`。
- [ ] **Step 2**：`scripts/sdd-workspace` 取得工作區，建立帳本（第一行 `# SDD ledger — plan: docs/superpowers/plans/2026-10-26-v6-phase45-anomaly.md`）與 `gates.sh`（見 Global Constraints）。
- [ ] **Step 3**：跑 `gates.sh`。Expected：`ALL GATES GREEN`，pytest 1213 passed、1 skipped。
- [ ] **Step 4**：commit 本計畫（`docs(v6): plan P4.5 anomaly detection on allowed traffic`）。

---

### Task 1：設定 schema v5

**Files:**
- Modify: `illumio_ops/domain/values.py`（`PortClass`、`DEFAULT_SUSPICIOUS_TOOLS`）
- Modify: `illumio_ops/settings/schema.py`、`illumio_ops/settings/upgrade.py`
- Test: `tests_v6/settings/test_schema.py`、`tests_v6/settings/test_upgrade.py`、`tests_v6/domain/test_values.py`

**Interfaces:**
- Produces:
  - `class PortClass(StrEnum)`: `REMOTE = "remote"`、`DIRECTORY = "directory"`、`DATABASE = "database"`。
  - `DEFAULT_SUSPICIOUS_TOOLS: tuple[str, ...]`（以 `normalize_process` 後的形式存）：`powershell.exe pwsh.exe wmic.exe psexec.exe psexesvc.exe paexec.exe winrs.exe certutil.exe mshta.exe rundll32.exe regsvr32.exe cscript.exe wscript.exe bitsadmin.exe rubeus.exe mimikatz.exe sharphound.exe adfind.exe nc ncat socat nmap masscan`。
  - `PortEntry.category: PortClass = PortClass.REMOTE`（有預設，舊檔與移除項不必帶）。
  - `LateralSettings` 新欄位：`peer_group_keys: tuple[str, ...]`（1–4 個、各 1–255 字、不得重複）、`directory_servers: tuple[LabelSelector, ...]`、`directory_server_ips: tuple[str, ...]`（≤100 個，`parse_ip_token` 解析且必須是單一位址，不收網段）、`suspicious_tools: tuple[str, ...]`（經 `_process_names`，可為空）。
  - `DetectorSettings` 新欄位：`peer_min_group: int`（3–1000）、`volume_surge_factor: float`（1.5–100）、`volume_min_connections: int`（10–10,000,000）、`volume_min_mb: int`（1–10,000,000）、`directory_min_connections: int`（10–10,000,000）、`account_history_days: int`（1–90）、`process_history_days: int`（1–90）、`directory_min_sources: int`（2–1000）、`directory_followup_minutes: int`（10–1440）。
  - `default_lateral()` 的預設：`peer_group_keys=("app", "role")`、`directory_servers=()`、`directory_server_ips=()`、`suspicious_tools=DEFAULT_SUSPICIOUS_TOOLS`、`peer_min_group=5`、`volume_surge_factor=3.0`、`volume_min_connections=1000`、`volume_min_mb=1024`、`directory_min_connections=500`、`account_history_days=7`、`process_history_days=7`、`directory_min_sources=3`、`directory_followup_minutes=30`。
  - `SCHEMA_VERSION = 5`；`UPGRADES[4] = _v4_to_v5`：只補缺的鍵（`lateral` 與 `lateral.detectors` 用 `default_lateral()` 的值 `setdefault`），既有值一律保留。

`directory_min_sources=3` 的依據（計畫撰寫時 .106 唯讀查詢，`connection_baseline` 的目錄 port）：兩台 lab 目錄伺服器分別被 12 與 4 個來源連；其餘目的只有 1–2 個來源，含兩個外部 IP（88）。下限 3 推論出這兩台、不推論外部 IP 與單一來源的主機。

- [ ] **Step 1：寫會紅的測試**
  - `test_v4_file_upgrades_to_v5_keeping_values`：一份 v4 檔（`extra_admin_ports=[{"port": 8443, "proto": 6}]`、`detectors.fanout_targets=12`）經 `upgrade()` 後 `schema_version == 5`、`fanout_targets == 12`、`extra_admin_ports[0].category == "remote"`、`peer_group_keys == ("app", "role")`、`directory_min_sources == 3`。
  - `test_peer_group_keys_rejects_empty_and_duplicates`、`test_directory_server_ips_rejects_networks`（`"10.0.0.0/24"` → ValidationError）、`test_suspicious_tools_are_normalized`（`"C:\\Tools\\PsExec.EXE"` → `"psexec.exe"`）。
  - `test_values.py`：`PortClass` 三個值。
- [ ] **Step 2**：`timeout 300 .venv/bin/python -m pytest tests_v6/settings tests_v6/domain/test_values.py -q` → FAIL（`PortClass` 不存在等）。
- [ ] **Step 3**：實作上述介面。
- [ ] **Step 4**：同一指令 → PASS；`bash scripts/v6/gen_contracts.sh` 後 `npm --prefix web run --silent typecheck` 通過（前端若有讀這些型別的地方要補欄位；`Lateral.tsx` 的表單欄位在 Task 8 做，這裡只讓型別過）。
- [ ] **Step 5**：commit `feat(v6): settings v5 for the allowed-traffic anomaly detectors`，跑閘門。

---

### Task 2：管理 port 三分類

**Files:**
- Modify: `illumio_ops/domain/values.py`（`LATERAL_PORTS_DEFAULT` 加類別與新 port）
- Modify: `illumio_ops/domain/lateral.py`（`AdminPort.category`、`AdminPortSet` 依類別查詢）
- Modify: `illumio_ops/domain/detectors.py`（每個 P3 偵測器依類別過濾；`MANAGEMENT_DETECTORS` 明列）
- Modify: `illumio_ops/services/analysis/context.py`、`illumio_ops/services/analysis/status.py`、`illumio_ops/services/flowsource.py:489`（曝露圖）
- Modify: `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md` §6.5.1「管理／橫向 port 集合」改寫成三分類（與 §6.5.8 一致）
- Test: `tests_v6/domain/test_lateral.py`、`tests_v6/domain/test_detectors.py`、`tests_v6/services/analysis/test_exposure.py`、`tests_v6/domain/test_values.py`

**Interfaces:**
- Consumes: Task 1 的 `PortClass`、`PortEntry.category`。
- Produces:
  - `LATERAL_PORTS_DEFAULT: tuple[tuple[int, str, PortClass], ...]`：原 18 個，其中 88、389、636 為 `DIRECTORY`，1433、3306、5432 為 `DATABASE`，其餘 `REMOTE`；另加 `(464, "Kerberos-PW", DIRECTORY)`、`(3268, "LDAP-GC", DIRECTORY)`、`(3269, "LDAPS-GC", DIRECTORY)`、`(9389, "ADWS", DIRECTORY)`，共 22 個。
  - `DIRECTORY_PORTS: frozenset[int]`：上面所有 `DIRECTORY` 類的 port（流量庫寫入時用，Task 3）。
  - `AdminPort.category: PortClass`；PCE admin 類服務一律 `REMOTE`；新增的 port 取 `PortEntry.category`。
  - `AdminPortSet.matches(port, proto, classes: Collection[PortClass] | None = None) -> bool`、`port_filters(classes=None) -> tuple[PortProto, ...]`、`class_of(port, proto) -> PortClass | None`（`classes=None` 表示全部類別，維持舊呼叫者的行為）。
  - 模組常數 `EXECUTION = frozenset({REMOTE})`、`EXECUTION_OR_DATA = frozenset({REMOTE, DATABASE})`（放 `domain/lateral.py`）。

**偵測器與類別的對照**（spec §6.5.8）：

| 偵測器 | 讀的類別 |
|---|---|
| 扇出、新的管理連線、跨環境 | 遠端執行＋資料庫 |
| 跳板鏈、非管理群組、帳號扇出、非預期發起 process | 遠端執行 |
| 大量被擋嘗試 | 不限 port（不變） |
| E（Task 6） | 目錄／認證 |

**曝露圖**（`flowsource.py` 的基準邊與 `status.py` 的 port 清單）：圖只畫「遠端執行＋資料庫」。這是使用者同意範圍外的行為改變，記成 Ruling 並放進最後的決策清單：理由是 Kerberos／LDAP 邊讓每台網域成員都「可觸及」目錄伺服器，圖的可觸及數會被灌大；成本是看不到「誰能連 DC 的 LDAP」，這由 E 偵測器補。狀態頁列出全部 22 個 port 並標類別。

**偵測證據段落**：`evidence()` 帶的 port 篩選改成該偵測器讀的類別（`cfg.admin_ports.port_filters(classes)`），否則工作台會列出無關的 port。

- [ ] **Step 1：寫會紅的測試**（每個 P3 偵測器一條，名稱 `test_<detector>_port_classes`）：同一組資料含 389、88、1433、445 的連線，斷言扇出／新管理連線／跨環境看得到 1433 與 445、看不到 389 與 88；跳板鏈／非管理群組／帳號扇出／非預期發起只看得到 445。另加 `test_admin_port_set_class_of`、`test_added_port_keeps_its_category`、`test_exposure_graph_excludes_directory_ports`、`test_no_admin_ports_disables_only_management_detectors`（`MANAGEMENT_DETECTORS` 明列後 BLOCKED_SURGE 仍執行）。
- [ ] **Step 2**：`timeout 300 .venv/bin/python -m pytest tests_v6/domain/test_lateral.py tests_v6/domain/test_detectors.py tests_v6/services/analysis/test_exposure.py -q` → FAIL。
- [ ] **Step 3**：實作。`run_detection` 的管理 port 讀取仍讀全部類別（E 之後也要），各偵測器自行過濾。
- [ ] **Step 4**：同一指令 → PASS；`timeout 900 .venv/bin/python -m pytest tests_v6 -q -n auto --dist loadfile -p no:logging` 全綠（`test_values` 等釘住 port 清單的測試照新清單更新）。
- [ ] **Step 5**：改 spec §6.5.1 共用定義段落：三分類、各類交給哪些偵測器、曝露圖只畫遠端執行＋資料庫。commit `feat(v6): management ports in three classes; each lateral detector reads its own`，跑閘門。

---

### Task 3：流量庫 0006——新基準、每小時活動與讀取

**Files:**
- Create: `illumio_ops/store/flowdb/migrations/0006_anomaly_baselines.sql`
- Modify: `illumio_ops/store/flowdb/flows.py`（基準維護、活動彙總、修剪）、`illumio_ops/store/ownership.py`
- Modify: `illumio_ops/store/flowdb/analysis.py`（`recent_detections`）
- Create: `illumio_ops/services/flowsource_anomaly.py`（讀取；名稱以 `flowsource` 開頭，單一讀取者閘門允許它讀 flows）
- Test: `tests_v6/store/test_flowdb_0006.py`、`tests_v6/store/test_query_plans.py`、`tests_v6/services/test_flowsource_anomaly.py`

**Interfaces:**
- Produces（SQL）：
```sql
DROP INDEX ix_baseline_port;
CREATE INDEX ix_baseline_port_src ON connection_baseline (port, src_key);   -- A 的同群查詢；曝露圖的 port 讀取仍走它
CREATE TABLE account_source_baseline (
    account    TEXT NOT NULL,   -- account_key(initiator_user)
    src_key    TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    PRIMARY KEY (account, src_key)
) WITHOUT ROWID;
CREATE TABLE process_baseline (
    src_key    TEXT NOT NULL,
    process    TEXT NOT NULL,   -- normalize_process 後的發起程式
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    PRIMARY KEY (src_key, process)
) WITHOUT ROWID;
CREATE TABLE source_activity_hourly (
    hour        TEXT NOT NULL,  -- 增量 observed_at 所在的整點（db_time 格式）
    src_key     TEXT NOT NULL,
    port_class  TEXT NOT NULL CHECK (port_class IN ('all', 'directory')),
    connections INTEGER NOT NULL,
    bytes       INTEGER NOT NULL,
    bytes_known INTEGER NOT NULL,  -- 有位元組資料的增量筆數
    PRIMARY KEY (hour, src_key, port_class)
) WITHOUT ROWID;
```
  兩張基準從 `flow_rollup_daily` 種入：`first_seen` 取該組最早一天的 00:00、`last_seen` 取最晚一天的 23:59:59；帳號在 SQL 裡照 `account_key()` 的規則轉（含 `\` 或 `@` 才轉小寫）。`source_activity_hourly` 不種（增量只保留 26 小時，無從回推），升級後量暴增「累積中」7 天——記成 Ruling。
- Produces（寫入，`store/flowdb/flows.py`）：
  - `PRIMARY_OF_CONNECTION` 加 `initiator_process`；`_update_baselines` 另寫 `account_source_baseline`（有使用者時）與 `process_baseline`（有程式時），upsert 規則同 `user_baseline`。
  - `_record_growth(...) -> tuple[int, int | None]` 回傳本次記下的增量（沒有記就回 `(0, None)`）。`upsert_flows` 在 `increments == "cycle"` 且該連線判定沒被擋時，把增量累加到 `(hour, src_key, 'all')`，port 在 `DIRECTORY_PORTS` 時也加到 `(hour, src_key, 'directory')`；批次結束時一次 upsert（相加）。`late` 與 `none` 不寫活動。
  - 修剪：`source_activity_hourly` 刪掉早於 `now - ACTIVITY_KEEP`（`timedelta(days=8)`）的整點，與 `flow_increments` 的刪除放在一起；兩張新基準跟 `connection_baseline` 一起依 `baseline_days` 修剪（`flows.py:445` 那段）。
  - `ownership.py` 登錄三張新表的寫入者 `illumio_ops.store.flowdb.flows`。
- Produces（讀取，`services/flowsource_anomaly.py`；每個函式讀完比對世代，不同就 `raise StaleGeneration`）：
  - `account_first_seen(ctx, pairs: Collection[tuple[str, str]]) -> dict[tuple[str, str], datetime]`（(account, src) → first_seen）
  - `account_history(ctx, accounts: Collection[str], before: datetime) -> dict[str, int]`（帳號在 before 以前出現過的來源數；沒有就不在結果裡）
  - `account_since(ctx, accounts) -> dict[str, datetime]`（帳號最早的 first_seen）
  - `process_first_seen(ctx, pairs: Collection[tuple[str, str]]) -> dict[tuple[str, str], datetime]`、`process_since(ctx, srcs) -> dict[str, datetime]`
  - `peer_seen(ctx, members: Collection[str], port: int, proto: int, before: datetime) -> set[str]`（這些來源在 before 以前用過這個 port 的目的 key）
  - `directory_sources(ctx, ports: Collection[int], since: datetime) -> dict[str, int]`（目的 key → 在 since 之後仍出現的不同來源數，只看這些 port）
  - `directory_clients_before(ctx, srcs, servers: Collection[str], ports, before) -> set[str]`（before 以前就連過任一目錄伺服器的來源）
  - `activity_now(ctx, since: datetime, until: datetime) -> dict[tuple[str, str], tuple[int, int | None]]`（((src, class)) → (連線, 位元組；沒有位元組資料為 None)；讀 `flow_increments` join flows，`late = 0` 且沒被擋，class 依 `DIRECTORY_PORTS`）
  - `activity_history(ctx, srcs, start: datetime, end: datetime) -> dict[tuple[str, str], tuple[int, int]]`（各來源各類別在 [start, end) 任一整點的最大連線數與最大位元組）、`activity_coverage(ctx) -> datetime | None`（表中最早的整點）
- Produces（`store/flowdb/analysis.py`）：`recent_detections(conn, detectors: Collection[str], since: datetime) -> list[sqlite3.Row]`（subject_key、detector、first_seen、last_seen）。

- [ ] **Step 1：寫會紅的測試**
  - `test_0006_seeds_baselines_from_rollup`：0005 狀態的庫有 rollup 列（`CORP\Alice`、`powershell.exe`）→ 遷移後 `account_source_baseline` 有 `corp\alice`、`process_baseline` 有該程式，first_seen 是那天 00:00。
  - `test_upsert_writes_account_and_process_baselines`；`test_case_variants_are_one_account`（Review Focus 4）。
  - `test_activity_counts_cycle_growth_not_blocked`：兩批 cycle 寫入同一連線，活動等於增量總和；被擋的連線、`late` 與 `none` 寫入都不進表（Review Focus 5）；389 的增量同時進 `all` 與 `directory`。
  - `test_activity_pruned_after_eight_days`、`test_new_baselines_pruned_with_baseline_days`。
  - `test_query_plans`：`peer_seen` 的查詢用 `ix_baseline_port_src`；`activity_now` 用 `ix_increments_observed`；原本釘 `ix_baseline_port` 的斷言改名。
  - `test_reads_raise_stale_after_pce_switch`（Review Focus 2）：每個讀取函式在讀取中途世代改變時丟 `StaleGeneration`（用 monkeypatch 改 generation，比照 `baseline_first_seen` 既有測試）。
- [ ] **Step 2**：`timeout 300 .venv/bin/python -m pytest tests_v6/store tests_v6/services/test_flowsource_anomaly.py -q` → FAIL。
- [ ] **Step 3**：實作。
- [ ] **Step 4**：同一指令 → PASS；全套 pytest 綠（`test_single_writer`、`test_single_reader`、表擁有者測試要過）。
- [ ] **Step 5**：commit `feat(v6): flow db 0006 keeps account, process and hourly activity baselines`，跑閘門。

---

### Task 4：偵測框架、A 同群偏離、B 量暴增

**Files:**
- Create: `illumio_ops/domain/anomaly.py`
- Modify: `illumio_ops/domain/detectors.py`（`DetectorInput` 加欄位、`DetectorConfig` 加欄位、註冊）
- Modify: 「新增 DetectorKind」清單上的所有檔案
- Test: `tests_v6/domain/test_anomaly.py`

**Interfaces:**
- Consumes: Task 2 的 `AdminPortSet.class_of`；Task 1 的設定值（Task 7 才接到服務層，這裡由測試直接建 `DetectorConfig`）。
- Produces:
  - `DetectorKind.PEER_DEVIATION = "peer_deviation"`、`DetectorKind.VOLUME_SURGE = "volume_surge"`。
  - `DetectorConfig` 新欄位（全部帶預設值，P3 既有測試不必改）：`peer_group_keys: tuple[str, ...] = ("app", "role")`、`peer_min_group: int = 5`、`volume_surge_factor: float = 3.0`、`volume_min_connections: int = 1000`、`volume_min_bytes: int = 1024 * 2**20`、`directory_min_connections: int = 500`、`account_history: timedelta = timedelta(days=7)`、`process_history: timedelta = timedelta(days=7)`、`suspicious_tools: frozenset[str] = frozenset()`、`directory_followup: timedelta = timedelta(minutes=30)`。
  - `@dataclass(frozen=True) class Activity: connections: int; bytes: int | None; previous_connections: int; previous_bytes: int`
  - `@dataclass(frozen=True) class AnomalyData`（全部有空預設）：`peer_seen: Mapping[tuple[str, int, int], frozenset[str]]`、`group_sizes: Mapping[str, int]`、`activity: Mapping[tuple[str, str], Activity]`、`activity_days: float`、`live: bool = True`（late pass 為 False），以及 Task 5、6 加的欄位。
  - `DetectorInput` 新欄位：`traffic_obs: Sequence[Obs] = ()`（本輪視窗內所有 port、沒被擋）、`anomaly: AnomalyData = AnomalyData()`。
  - `group_of(labels: Mapping[str, str], keys: Sequence[str]) -> str | None`：全部 key 都有值時回 `"|".join(values)`，否則 None。
  - `target_signature(key: str, ip: str, host: HostInfo, keys) -> str | None`：受管且有群組 → `"g:" + group`；受管無群組或私有位址的非受管 → `key`；公網位址 → None（不評估，egress 不在 A 的範圍——記成 Ruling）。偵測器對本輪連線用 `(o.dst_key, o.dst_ip, ...)`；服務層把 `peer_seen` 查回的目的 key 轉簽章時，非受管 key `ip:<位址>` 取出位址。
  - `detect_peer_deviation(inp) -> tuple[list[Detection], DetectorStatus]`、`detect_volume_surge(inp) -> ...`。

**A 同群偏離的判斷**（spec 表 A）：
- 候選：`traffic_obs` 中可評估、port 不是 None、port < 49152（動態 port 不比）、**port 不屬於任何管理類別**（管理 port 的新連線已由「新的管理連線」與 E 處理，避免同一件事兩則告警——Ruling）、`inp.baseline_first_seen` 顯示這組 (src, dst, port, proto) 首次出現在本輪視窗、來源有群組且 `group_sizes[group] >= peer_min_group`、目的簽章不是 None。
- 行為鍵 `(group, port, proto)`；`peer_seen[(group, port, proto)]` 是群組成員在 lo 以前用過的目的簽章。目的簽章不在其中才算偏離。
- 同一行為鍵在本輪有幾台「開始做」：達群組一半（`starters * 2 >= group_size`）視為群組整體的變更（部署），不偵測（Review Focus 3）。
- 基準未滿 → `accumulating`；沒有任何群組達下限 → `no_data`，原因 `detector_no_peer_groups`（參數 `keys`、`min`）。
- 偵測：fingerprint `peer|{src}|{sig}|{port}|{proto}`、主體來源、嚴重度 medium（目的重要資產 → high）、summary `{"target", "target_group", "port", "proto", "group", "group_size", "starters"}`、證據段落 = 該 src→dst 在本輪視窗、該 port。dedup 30 天。

**B 量暴增**：
- `activity[(src, "all")]`：`connections >= volume_min_connections` 且（`previous_connections == 0` 或 `connections >= factor * previous_connections`），或位元組同理（`bytes` 不是 None、`bytes >= volume_min_bytes`、對 `previous_bytes`）。
- `activity_days < 7` → `accumulating`（原因 `detector_activity_accumulating`，參數 `days`、`required: 7`）；`live` 為假（late pass）→ 不評估，狀態 ok、原因 `detector_live_only`。
- 偵測：fingerprint `volume|{src}`、嚴重度 medium（來源是重要資產 → high）、summary `{"connections", "bytes", "previous_max", "previous_max_bytes", "window_minutes": 60}`、證據段落 = 該來源在 `(hi - 60 分, hi]` 沒被擋的連線。dedup 60 分鐘。

- [ ] **Step 1：寫會紅的測試**（`tests_v6/domain/test_anomaly.py`）
  - A：`test_peer_deviation_fires_for_a_lone_starter`（群組 6 台、成員從沒連過 `g:Finance|DB` 的 8443，一台開始連 → 一則，summary group_size 6、starters 1）；`test_peer_seen_suppresses`；`test_whole_group_rollout_is_not_a_deviation`（6 台中 3 台同輪開始 → 0）；`test_group_below_minimum_is_not_evaluated`（4 台）與 `test_group_at_minimum_is_evaluated`（5 台）；`test_host_missing_a_group_label_is_skipped`；`test_management_and_dynamic_ports_skipped`（445、389、50000）；`test_public_destination_skipped`；`test_peer_accumulating_until_baseline_full`；`test_no_groups_status`。
  - B：`test_volume_surge_on_connections`（previous 300、now 1200、factor 3 → 偵測）；`test_volume_below_floor`（previous 0、now 900 → 無）；`test_volume_surge_on_bytes_only`；`test_volume_accumulating_before_seven_days`；`test_volume_not_evaluated_in_late_pass`。
  - 註冊：`test_every_detector_kind_is_registered`（`DETECTORS`、`dedup_windows`、`DETECTION_TITLE_KEYS` 涵蓋每個 `DetectorKind`；i18n 兩語系都有 `detector_name_*` 與 `focus_title_*`）。
- [ ] **Step 2**：`timeout 300 .venv/bin/python -m pytest tests_v6/domain/test_anomaly.py -q` → FAIL。
- [ ] **Step 3**：實作，並照「新增 DetectorKind」清單補齊。文案：
  - `focus_title_peer_deviation`：zh「{host} 開始連到 {target}（port {port}），同群組 {group_size} 台中沒有其他主機這樣做過」；en「{host} started connecting to {target} on port {port}; none of the other hosts in its group of {group_size} ever has」
  - `focus_title_volume_surge`：zh「{host} 一小時內 {connections} 條連線（前 7 天任一小時最多 {previous_max} 條）」；en「{host} made {connections} connections in an hour (at most {previous_max} in any hour of the previous 7 days)」
  - `detector_name_peer_deviation`「同群偏離」／「Peer-group deviation」；`detector_name_volume_surge`「量暴增」／「Volume surge」。
  - `detector_no_peer_groups`：zh「沒有任何群組達 {min} 台（群組 label：{keys}）。」；`detector_activity_accumulating`：zh「每小時活動已累積 {days}／{required} 天。」；`detector_live_only`：zh「只評估即時收集的資料，每日重讀補到的不計入。」（en 對應）。
- [ ] **Step 4**：同一指令 → PASS；全套 pytest、`gen_contracts.sh` 後 typecheck 綠。
- [ ] **Step 5**：commit `feat(v6): peer-group deviation and volume surge detectors`，跑閘門。

---

### Task 5：C 帳號新來源、D 可疑工具與新程式

**Files:**
- Modify: `illumio_ops/domain/anomaly.py`、`illumio_ops/domain/detectors.py`（註冊、`apply_precursors` 跳過帳號偵測）＋「新增 DetectorKind」清單
- Test: `tests_v6/domain/test_anomaly.py`

**Interfaces:**
- Produces:
  - `DetectorKind.ACCOUNT_NEW_SOURCE = "account_new_source"`、`SUSPICIOUS_TOOL = "suspicious_tool"`、`NEW_PROCESS = "new_process"`。
  - `AnomalyData` 加：`account_first: Mapping[tuple[str, str], datetime]`、`account_since: Mapping[str, datetime]`、`account_sources: Mapping[str, int]`、`process_first: Mapping[tuple[str, str], datetime]`、`process_since: Mapping[str, datetime]`。
  - `detect_account_new_source`、`detect_suspicious_tool`、`detect_new_process`。

**C**：`traffic_obs` 中可評估、有 `initiator_user` 的列，帳號 `account_key()`；`exclude_system_accounts` 時跳過系統帳號。`account_first[(account, src)]` 在本輪視窗，且 `account_since[account] <= lo - account_history` → 偵測。基準未滿 → `accumulating`。fingerprint `acctsrc|{account}|{src}`、主體帳號、嚴重度 medium（任一目的是重要資產 → high）、summary `{"user", "source", "known_sources", "sample_targets"}`、證據段落 = 該使用者從該來源在本輪視窗的連線。dedup 30 天。覆蓋：`DetectionConfidence(field="initiator_user", ...)`，狀態用 `_coverage_status`（`detector_no_user_data`／`detector_partial_users*` 沿用）。

**D 可疑工具**：可評估、`initiator_process in suspicious_tools`、目的在內部（受管，或非受管但私有位址）的列；port 有「預期發起 process」清單者跳過（由「非預期的發起 process」判斷，避免兩則）。fingerprint `tool|{src}|{process}`、嚴重度 medium（重要資產 → high）、summary `{"process", "port", "target", "targets"}`。dedup 24 小時。清單為空 → `disabled`，原因 `detector_no_tools`。

**D 新程式**：`process_first[(src, process)]` 在本輪視窗、`process_since[src] <= lo - process_history`、程式不在可疑工具清單 → 偵測。基準未滿 → `accumulating`。fingerprint `newproc|{src}|{process}`、嚴重度 **low**（不進預設告警；首頁焦點與狀態頁看得到——Ruling）、summary `{"process", "port", "target"}`。dedup 30 天。兩者覆蓋都用 `initiator_process`。

- [ ] **Step 1：寫會紅的測試**：`test_account_from_new_source`（帳號 10 天前起只從 A 主機，今天從 B → 一則，known_sources 1）；`test_new_account_is_not_judged`（帳號 3 天前才出現 → 0）；`test_system_account_skipped`；`test_account_case_variants_match`（Review Focus 4）；`test_account_detection_skips_precursor_raise`；`test_tool_to_internal_target`；`test_tool_to_public_target_skipped`；`test_tool_on_port_with_expected_list_skipped`（445＋powershell.exe → 只由 unexpected_initiator 判）；`test_empty_tool_list_disabled`；`test_first_process_on_established_host`；`test_new_process_on_new_host_skipped`；`test_tool_is_not_also_new_process`；`test_no_process_data_status`。
- [ ] **Step 2**：`timeout 300 .venv/bin/python -m pytest tests_v6/domain/test_anomaly.py -q` → FAIL。
- [ ] **Step 3**：實作並補齊清單。文案：
  - `focus_title_account_new_source`：zh「帳號 {user} 首次從 {source} 發起連線（之前只從 {known_sources} 台主機）」
  - `focus_title_suspicious_tool`：zh「{host} 上的 {process} 連到內部主機 {target}（port {port}）」
  - `focus_title_new_process`：zh「{process} 首次在 {host} 上發起連線」
  - 名稱：帳號新來源、可疑工具連線、新的發起程式（en 對應）；`detector_no_tools`：zh「可疑工具清單是空的。」
- [ ] **Step 4**：同一指令 → PASS；全套 pytest、契約、typecheck 綠。
- [ ] **Step 5**：commit `feat(v6): account-new-source, suspicious-tool and new-process detectors`，跑閘門。

---

### Task 6：E 目錄／認證

**Files:**
- Modify: `illumio_ops/domain/anomaly.py`、`illumio_ops/domain/detectors.py`（註冊、E④ 後處理）＋「新增 DetectorKind」清單
- Test: `tests_v6/domain/test_anomaly.py`

**Interfaces:**
- Produces:
  - `DetectorKind.AUTH_TO_NON_DC = "auth_to_non_dc"`、`NEW_DC_CLIENT = "new_dc_client"`、`DIRECTORY_SURGE = "directory_surge"`。
  - `AnomalyData` 加：`directory_servers: frozenset[str]`（推論 ∪ 宣告的目的 key）、`directory_ips: frozenset[str]`（宣告的 IP）、`directory_inferred: int`、`directory_declared_missing: int`（宣告了但流量推論不出的台數）、`directory_clients_before: frozenset[str]`、`recent_directory: Sequence[tuple[str, str, datetime, datetime]]`（主體、偵測器、first、last；來自先前幾輪已存的目錄類偵測）。
  - `detect_auth_to_non_dc`、`detect_new_dc_client`、`detect_directory_surge`、`apply_directory_followup(dets, recent, *, window) -> list[Detection]`。
  - `EXECUTION_DETECTORS = frozenset({FANOUT, NEW_ADMIN_CONNECTION, PIVOT_CHAIN, NON_ADMIN_GROUP, UNEXPECTED_INITIATOR, SUSPICIOUS_TOOL})`、`DIRECTORY_DETECTORS = frozenset({AUTH_TO_NON_DC, NEW_DC_CLIENT, DIRECTORY_SURGE})`。

**判斷**（spec 表 E；目錄 port 取 `AdminPortSet` 中 `DIRECTORY` 類；一個都沒有 → 三者 `disabled`，原因 `detector_no_directory_ports`）：
- 目錄伺服器：服務層推論（Task 7：`directory_sources` 中不同來源數 ≥ `directory_min_sources`、目的是受管主機或私有位址），聯集設定裡 label 選定的主機與 IP。兩者都空 → ①② `no_data`，原因 `detector_no_directory_servers`。宣告了但推論不出的有 N 台 → 狀態 ok、原因 `detector_directory_mismatch`（參數 `missing`）。
- ① `traffic_obs` 中可評估、目錄類 port、目的不是目錄伺服器（key 與 IP 都不符）→ fingerprint `authdst|{src}|{dst}|{port}`；目的是公網位址 high，否則 medium；summary `{"target", "port", "decision"}`；dedup 24 小時。
- ② 可評估、目錄類 port、目的是目錄伺服器、該 (src, dst, port, proto) 首次出現在本輪視窗、來源不在 `directory_clients_before` → fingerprint `dcclient|{src}`；來源非受管 medium，受管 low；summary `{"target", "port", "managed"}`；dedup 30 天；基準未滿 → `accumulating`。spec 原文「非受管或基準外來源連 DC」若照字面，每台非受管工作站第一天都會被標（lab 4 個連 DC 的來源全是非受管）——改成「基準外的新客戶端，非受管加重」，記成 Ruling。
- ③ `activity[(src, "directory")]` 同 B 的判斷，下限 `directory_min_connections`、倍數 `volume_surge_factor`；fingerprint `dirsurge|{src}`；medium；dedup 60 分鐘；累積中與 late pass 同 B。只算內建目錄 port（`DIRECTORY_PORTS`，寫入層不讀設定）——Ruling。攻擊工具黑名單（Rubeus 等）併入「可疑工具」偵測器的預設清單，不另立偵測器——Ruling。
- ④ `run_detectors` 在前兆加權之後呼叫 `apply_directory_followup`：執行類偵測的主體在 `recent_directory`（含本輪的目錄類偵測）中有一筆，且 `d.last_seen >= r.first_seen` 且 `d.first_seen <= r.last_seen + directory_followup` → 嚴重度升一級，summary 加 `"after_directory": {"detector", "last_seen"}`。只升級「之後」的執行類偵測；同一則不重複升。

- [ ] **Step 1：寫會紅的測試**：`test_ldap_to_non_directory_server`；`test_kerberos_to_public_ip_is_high`；`test_traffic_to_declared_ip_is_not_flagged`；`test_no_directory_servers_status`；`test_declared_but_not_inferred_status`；`test_new_dc_client_unmanaged_medium_managed_low`；`test_known_dc_client_not_flagged`；`test_directory_surge`；`test_directory_ports_removed_disables_e`；`test_fanout_after_directory_is_raised`（目錄偵測 10:00–10:05、扇出 10:20 → 升一級並帶 after_directory）；`test_fanout_before_directory_not_raised`；`test_followup_reads_stored_directory_detections`。
- [ ] **Step 2**：`timeout 300 .venv/bin/python -m pytest tests_v6/domain/test_anomaly.py -q` → FAIL。
- [ ] **Step 3**：實作並補齊清單。文案：
  - `focus_title_auth_to_non_dc`：zh「{host} 的認證／目錄連線（port {port}）流向非目錄伺服器 {target}」
  - `focus_title_new_dc_client`：zh「{host} 首次連目錄伺服器 {target}（port {port}）」
  - `focus_title_directory_surge`：zh「{host} 一小時內對目錄服務 {connections} 條連線（前 7 天任一小時最多 {previous_max} 條）」
  - 名稱：認證流向非目錄伺服器、目錄伺服器的新客戶端、目錄查詢暴增；狀態：`detector_no_directory_ports`「沒有目錄／認證類 port。」、`detector_no_directory_servers`「流量中推論不出目錄伺服器，也沒有宣告；請在下方設定。」、`detector_directory_mismatch`「宣告的目錄伺服器中有 {missing} 台在流量中看不到多個來源連線。」；`after_directory` 在告警與焦點的呈現沿用前兆的寫法（「之前 {minutes} 分鐘內有目錄偵測」）。
- [ ] **Step 4**：同一指令 → PASS；全套 pytest、契約、typecheck 綠。
- [ ] **Step 5**：commit `feat(v6): directory and authentication detectors with follow-up escalation`，跑閘門。

---

### Task 7：服務接線

**Files:**
- Modify: `illumio_ops/services/analysis/detect.py`
- Create: `illumio_ops/services/analysis/anomaly_inputs.py`
- Modify: `illumio_ops/services/analysis/context.py`（`LateralContext` 帶目錄宣告與群組大小）、`illumio_ops/services/analysis/status.py`
- Test: `tests_v6/services/analysis/test_detect.py`、`tests_v6/services/analysis/test_anomaly_scenarios.py`

**Interfaces:**
- Consumes: Task 3 的讀取函式；Task 4–6 的 `AnomalyData`、偵測器。
- Produces:
  - `load_anomaly_data(ctx, lc: LateralContext, inp: DetectorInput, *, at: datetime, live: bool) -> AnomalyData`：依候選只查需要的鍵（帳號、程式、同群行為、目錄客戶端），不整表讀。
  - `run_detection` 另讀 `traffic = observations(ctx, FilterSpec(start=lo, end=hi, decisions=(ALLOWED, POTENTIALLY_BLOCKED, UNKNOWN)), now=at)`；其 coverage gaps 併入 `gaps`；`late=True` 時 `live=False`。
  - `_config(lc)` 把 Task 1 的設定值帶進 `DetectorConfig`；`_lookback` 不變（新偵測器不回看）。
  - 狀態頁（`status.py`）列出新偵測器的狀態與目錄伺服器推論結果（推論 N 台、宣告 M 台、對不上的清單）。

- [ ] **Step 1：寫會紅的情境測試**（`test_anomaly_scenarios.py`，資料準備比照 `test_detect.py`：`configured_ctx`、`upsert_flows` 寫入 30 天以上的回填基準與本輪 ingest 紀錄、`_collected`）。每個情境斷言 `run_detection` 存下且只存下預期的那種偵測：
  - `scenario_peer`：app=Pay、role=Web 6 台 31 天只連 `g:Pay|DB` 的 5432，其中一台本輪開始連 `g:HR|App` 的 8443 → 一則 `peer_deviation`。
  - `scenario_account`：`corp\alice` 30 天只從 ws-1，本輪從 srv-9 → 一則 `account_new_source`。
  - `scenario_tool`：srv-3 的 `psexec.exe` 本輪連內部 10.0.5.7:8080 → `suspicious_tool`。
  - `scenario_new_process`：srv-3 30 天有程式基準，本輪 `curl` 首次發起 → `new_process`。
  - `scenario_directory`：3 個來源連 dc-1 的 88、389 達 30 天；本輪 ws-4 對 10.0.9.9 的 389 → `auth_to_non_dc`；新的非受管 10.0.8.8 首次連 dc-1:88 → `new_dc_client`；10.0.8.8 隨後 15 分鐘對 10 台主機 445 → `fanout` 嚴重度被 E④ 升一級。
  - `test_late_pass_skips_volume`（Review Focus 5）；`test_switch_during_anomaly_reads_stores_nothing`（Review Focus 2）。
- [ ] **Step 2**：`timeout 300 .venv/bin/python -m pytest tests_v6/services/analysis -q` → FAIL。
- [ ] **Step 3**：實作。
- [ ] **Step 4**：同一指令 → PASS；全套閘門綠。
- [ ] **Step 5**：commit `feat(v6): the detection run reads allowed traffic and feeds the anomaly detectors`，跑閘門。

---

### Task 8：告警、GUI 與「標為已知」

**Files:**
- Modify: `illumio_ops/domain/alertpack.py`、`illumio_ops/settings/upgrade.py`（`_v4_to_v5` 補新規則）
- Create: `illumio_ops/store/migrations/0006_detection_annotations.sql`、`illumio_ops/store/detection_annotations.py`；Modify: `illumio_ops/store/ownership.py`
- Modify: `illumio_ops/services/alerts/evaluate.py`（已知標記歸組）、`illumio_ops/services/alerts/views.py`
- Modify: `illumio_ops/web/routes/alerts.py`、`illumio_ops/web/routes/system_lateral.py`
- Modify: `web/src/pages/alerts/AlertDetail.tsx`、`web/src/pages/alerts/RuleEditor.tsx`、`web/src/pages/system/Lateral.tsx`
- Test: `tests_v6/domain/test_alertrules.py`（或 alertpack 測試所在檔）、`tests_v6/settings/test_upgrade.py`、`tests_v6/services/alerts/test_evaluate.py`、`tests_v6/web/` 的路由測試、`tests_v6/e2e/test_alerts_e2e.py`、`tests_v6/e2e/test_lateral_settings.py`

**Interfaces:**
- Produces:
  - 規則包新增 `_ANOMALY: tuple[tuple[str, tuple[DetectorKind, ...]], ...]`：`rule_anomaly_peer`（PEER_DEVIATION）、`rule_anomaly_volume`（VOLUME_SURGE）、`rule_anomaly_account_source`（ACCOUNT_NEW_SOURCE）、`rule_anomaly_tool`（SUSPICIOUS_TOOL）、`rule_anomaly_directory`（AUTH_TO_NON_DC、NEW_DC_CLIENT、DIRECTORY_SURGE）。全部 enabled、`notify=notify_new_defaults`、`min_severity=MEDIUM`、冷卻 0。NEW_PROCESS 不進規則包（low）。
  - `_v4_to_v5` 對 `alerts.rules` 補上缺的上述 `pack_key`，`notify=False`（升級的安裝先只記錄，由操作者逐條開——與 P4 對 5.x 升級的做法一致；.106 目前 5.x 與 v6 都會送通知，不再加噪）。新安裝 `notify=True`。
  - App DB 0006：
```sql
CREATE TABLE detection_annotations (
    id          INTEGER PRIMARY KEY,
    pce_url     TEXT NOT NULL,
    org_id      TEXT NOT NULL,
    detector    TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    fingerprint TEXT,           -- NULL：這個主體這類偵測全部
    reason      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    created_by  TEXT NOT NULL
);
```
  - `store/detection_annotations.py`：`add(conn, *, pce_url, org_id, detector, subject_key, fingerprint, reason, created_by, at) -> int`、`remove(conn, id, *, pce_url, org_id) -> bool`、`for_pce(conn, pce_url, org_id) -> list[sqlite3.Row]`。
  - `evaluate_lateral`：載入目前 PCE 的標記；trigger 的偵測器、主體（facts 加 `"subject"`）、fingerprint 符合任一標記時 `grouped_annotation = 標記 id`，facts 加 `"known_reason"`。記錄照常，`DeliveryStatus.GROUPED`。
  - API：`POST /api/alerts/<id>/known`（body `{"scope": "detection" | "subject", "reason": str 1–500}`；只接受 `lateral` 型告警，否則 400）、`GET /api/lateral/known`、`DELETE /api/lateral/known/<id>`。寫入動作沿用既有 CSRF 與權限。
  - GUI：
    - `AlertDetail.tsx`：lateral 型告警顯示「標為已知」按鈕 → 對話框（原因必填、範圍「只這一則偵測／這台主機的這類偵測」）；已歸組的告警顯示「已標為已知：{原因}」。
    - `Lateral.tsx`：偵測器分「橫向移動」「允許流量異常」兩組列出；新增設定欄位（群組 label、群組下限、量暴增倍數與下限、目錄伺服器 label／IP、目錄下限、可疑工具清單、帳號／程式基準天數、目錄後續分鐘）；新增 port 時可選類別；「已知的偵測」清單可刪除。
    - `RuleEditor.tsx`：偵測器勾選分兩組。

- [ ] **Step 1：寫會紅的測試**：`test_pack_has_anomaly_rules`；`test_v4_upgrade_adds_anomaly_rules_record_only`；`test_known_detection_is_grouped`（fingerprint 範圍）與 `test_known_subject_groups_every_detection_of_that_kind`；`test_known_mark_of_other_pce_ignored`；路由：`test_mark_known_rejects_non_lateral_alert`、`test_known_list_and_delete`；e2e：告警詳情標為已知後清單出現、再刪除；Lateral 頁新欄位存檔後重新載入仍在（展開 `<details>` 再操作，P4 教訓）。
- [ ] **Step 2**：`timeout 600 .venv/bin/python -m pytest tests_v6/domain tests_v6/settings tests_v6/services/alerts tests_v6/web -q` → FAIL。
- [ ] **Step 3**：實作。
- [ ] **Step 4**：同一指令 → PASS；`timeout 900 .venv/bin/python -m pytest tests_v6/e2e -q -p no:logging` 綠；全套閘門綠。
- [ ] **Step 5**：commit（後端與前端可分兩個 commit），跑閘門。

---

### Task 9：規模、.106 驗收、文件、全分支審查

**Files:**
- Create: `tmp/v6-p45-verification/`（腳本與 `report.md`，不 commit 進 repo 的 tmp 以外位置）
- Modify: spec §6.5.8（第一批已實作、各偵測器的實際語意與 Ruling）、§6.5.1（已在 Task 2 改）；路線圖 P4.5 標完成
- Modify: memory `v6-rebuild-decided.md`、`v6-alerts-beyond-vendor.md`

- [ ] **Step 1：規模**：沿用 `.worktrees/v6-p4/tmp/v6-p4-verification/scale_p4.py` 的做法（.106、MemoryMax=4G、1,000 台、8 天 × 1M 合成，`--cycles 16`），量兩件事：
  - 尖峰每輪持鎖（含活動彙總與新基準）中位數 ≤ 30.9 秒（P4 為 18.5 秒）。
  - 偵測一輪（含第二組觀測與異常輸入）比 P4 的 58–74 秒增加不超過 30 秒。超過就先找熱點再決定，結果記帳本。
  合成庫用完即刪。
- [ ] **Step 2：部署 .106**（沿用 P4 的 `deploy106.sh`，路徑改 v6-p45；不碰 5.x）。確認：流量庫 6、應用庫 6、設定 v5；5.x 與 v6 都 active；第一輪偵測後狀態頁列出 8 個新偵測器、目錄伺服器推論出兩台（`2c10dcd1…`、`743a6abc…`）；新規則為「只記錄」。
- [ ] **Step 3：lab 觀察 2 小時**：數各新偵測器的偵測數。① 若被 1 來源主機的 3268／9389 洗版（計畫撰寫時的查詢看到 5 台這種目的），決定是否把 ① 限縮到 88、389、636，記 Ruling。
- [ ] **Step 4：lab 觸發一次**：從 batch.lab.local 對一台非目錄伺服器的 lab 主機 `nc -z -w1 <host> 389`（只連線），預期 10–20 分鐘內出現 `auth_to_non_dc` 偵測與「只記錄」告警。量暴增在 .106 要 7 天後才有判斷——記在報告的未驗項目。
- [ ] **Step 5：文件**：spec §6.5.8 改成已實作的語意（每個偵測器的判斷、預設、狀態、Ruling 摘要）；路線圖 P4.5 完成；報告 `tmp/v6-p45-verification/report.md`。
- [ ] **Step 6：全分支審查**：`review-package` 後派 Codex reviewer（gpt-6.1-sol、xhigh），附本計畫、spec、帳本 Ruling 行與 Review Focus。Critical／Important 一次修完（每項先紅後綠＋全套閘門），Minor 記帳本。
- [ ] **Step 7**：更新 memory；帳本收尾；最後回報（做了什麼、驗證證據、Rulings、Deferred minors、需要使用者決定的事），不 push、不合併。
