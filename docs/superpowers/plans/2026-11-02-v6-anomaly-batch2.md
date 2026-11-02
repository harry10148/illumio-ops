# illumio-ops v6 允許流量異常偵測第二批（F–J）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本計畫以 Native（superpowers:executing-plans）執行：使用者 2026-11-02「都照你建議做」（建議＝先做 F–J），做完一次給決策。

**Goal:** spec §6.5.8 候選表的第二批 F 方向反轉、G 既有主機對的新 port、H 安靜主機甦醒、I 資料匯集、J 時段偏離，沿用第一批的框架。

**Architecture:**
- **框架照舊**：純函式放 `domain/anomaly.py`，經 `DETECTORS` 註冊，結果寫進 `detections`；焦點清單、`lateral` 型告警、標為已知、規則排除條件全部沿用。
- **讀取照舊依鍵**：新讀取放 `services/flowsource_anomaly.py`，只查本輪候選點名的鍵，讀完比對世代（`_reading`）。
- **新表只有一張**：流量庫 0013 `destination_activity_hourly`（I 的目的端每小時歷史），寫入者 `store.flowdb.flows`，與來源每小時活動同一處彙總。
- **一件事一則**：`run_detectors` 在偵測後做一次 `drop_covered`：同一來源同一輪已有 B 量暴增時不出 H；已有 B 或 H 時不出 J；已有 A 同群偏離（同來源、同目的、同 port）時不出 G。

**Tech Stack:** 沿用，不新增依賴。

**Spec:** `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md` §6.5.8（候選表 F–J、共通原則）、§6.5.1（覆蓋率揭露、重要資產）、§4.3 反目標 1、8、§5 規模。Task 0 把本計畫的實作語意表寫進 §6.5.8「第二批」。

## Global Constraints

- P1–P8 與第一批（`2026-10-26-v6-phase45-anomaly.md`）的 Global Constraints 全部沿用，包括「新增 `DetectorKind` 一定要一起改的地方」清單，**另加** `services/reports/common.py` 的偵測器名稱對照（P5 新增）、`web/src/pages/system/Lateral.tsx` 的 `ANOMALY_DETECTORS` 與門檻欄位清單。
- 分支 `feat/v6-anomaly2`，worktree `.worktrees/v6-anomaly2`，從 main `c50562cf`。閘門 `.superpowers/sdd/2026-11-02-v6-anomaly-batch2/gates.sh`（P8 版改路徑）。每個任務前 `pwd && git branch --show-current`。
- 英文 conventional commits 加兩行 trailer；只 `git add <明確路徑>`；閘門與 commit 不串在同一行。
- 合 main、閘門全綠後可 push main（長期授權）；版本 6.1.0，CHANGELOG `[6.1.0] - unreleased`；**tag 先問使用者**。

**共通語意（F–J）**
- 只評估 origin＝`ingest`、本輪視窗 `(lo, hi]` 最後出現、沒被擋（`not_blocked`）的連線；回填與每日重讀只當基準。
- H、I、J 和 B 一樣只在即時輪評估（`data.live`），每日重讀不評估。
- 目的地（I 為匯集端本身）是重要資產時升一級；文案只說「時間上接得起來／與自己的歷史不同」，不說成攻擊。
- 管理 port（任一類）與動態 port（≥ 49152）不在 F、G 比較：新管理連線與 E 已經判。公網端點不比（F、G、I）。

| 偵測器 | 判斷 | 嚴重度 | 狀態與限制 |
|---|---|---|---|
| F `direction_reversal` | 本輪首次出現的 B→A（某 port），且 A→B 在本輪之前出現過（任一 port），而 B→A 在本輪之前從沒出現過（任一 port） | medium | 基準未滿「累積中」；基準含被擋的嘗試（第一批裁決），被擋過的反向不算新 |
| G `new_pair_port` | 本輪首次出現的 (A, B, port)，且 A→B 本輪之前出現過（別的 port） | B 在本輪之前從沒有任何來源連過這個 port（新的服務端）medium；否則 low | 來源同群組（A 的群組）已有人對同一目的簽章用過這個 port 時不出（同儕正常）；基準未滿「累積中」 |
| H `quiet_host_wakes` | 受管主機最近 60 分鐘發起 ≥ `quiet_min_connections` 條，此前 `quiet_days` 天內沒有任何即時發起紀錄，且基準在那之前就看過它發起連線 | medium | 每小時活動不足 `quiet_days` 天「累積中」；安靜期內有收集缺口時「資料不完整」且不偵測（分不出安靜與缺資料） |
| I `data_staging` | 內部目的端最近 60 分鐘從 ≥ `staging_min_sources` 個內部來源收到 ≥ `staging_min_mb` MB（連線的位元組，雙向合計），且 ≥ 自己前 7 天任一小時最大值 × `volume_surge_factor`（沒有帶位元組的歷史時只看下限） | medium | 只算帶位元組的增量並寫明覆蓋；完全沒有位元組「無資料」；比較期有缺口「資料不完整」；升級後累積 7 天 |
| J `off_hours` | 受管主機最近 60 分鐘發起 ≥ `off_hours_min_connections` 條，而它在保留期內有 ≥ `off_hours_min_days` 天有活動、這 60 分鐘跨到的兩個整點時段在那些天裡從沒有活動 | low（不進預設告警，焦點清單看得到） | 每小時活動不足 7 天「累積中」；那兩個時段在任一天有收集缺口時「資料不完整」且不偵測 |

- **保留期**：`ACTIVITY_KEEP` 由 8 天改 15 天（H 的安靜期最長 14 天、J 每個時段有 14 個樣本，週期性的工作看得到兩次）；B 仍只比前 7 天。
- **新設定**（`DetectorSettings`，schema v13，升級補預設）：`quiet_days` 7（2–14）、`quiet_min_connections` 100（10–10,000,000）、`staging_min_sources` 5（2–1000）、`staging_min_mb` 1024（1–10,000,000）、`off_hours_min_connections` 100（10–10,000,000）、`off_hours_min_days` 5（3–14）。
- **規則包**：加 `rule_anomaly_direction`（F）、`rule_anomaly_pair_port`（G，min_severity medium＝只有新服務端）、`rule_anomaly_quiet`（H）、`rule_anomaly_staging`（I）；J 不進包（同新程式）。新安裝送通知；v12→v13 升級加入時只記錄（`notify=False`）。

## Review Focus

1. **反向其實早就有**：B→A 在基準裡只有被擋的紀錄 → 不算新（不出 F）；A→B 只有回填紀錄 → 算「之前出現過」。（Task 2 測試）
2. **安靜與缺資料分不出來**：收集停了三天後恢復，每台主機看起來都「甦醒」→ 安靜期內有缺口時不偵測、狀態「資料不完整」。（Task 3 測試）
3. **新主機不是甦醒**：第一次出現的受管主機大量發起連線 → 基準在安靜期前沒看過它發起 → 不出 H。（Task 3 測試）
4. **備份伺服器每晚都大量收**：I 以目的端自己前 7 天的最大小時比較 → 不出；位元組欄位全空 → 狀態「無資料」，不是「沒有偵測」。（Task 4 測試）
5. **一件事兩則**：同一來源同一輪 B 與 H 同時成立 → 只留 B；A 與 G 同一條連線 → 只留 A。（Task 5 測試）

---

### Task 0：開工

- [ ] `pwd && git branch --show-current` → `.worktrees/v6-anomaly2`、`feat/v6-anomaly2`。
- [ ] 跑 `gates.sh`。Expected：`ALL GATES GREEN`。
- [ ] spec §6.5.8 加「第二批」段（上表＋保留期、規則包、一件事一則），路線圖 P4.5 節寫第二批；commit 計畫與文件（`docs(v6): plan the second batch of allowed-traffic anomalies (F–J)`）。

### Task 1：值域、設定 v13、流量庫 0013 與讀取

**Files:** `domain/values.py`、`settings/schema.py`、`settings/upgrade.py`、`store/flowdb/migrations/0013_destination_activity.sql`、`store/flowdb/flows.py`、`store/ownership.py`、`services/flowsource_anomaly.py`；測試 `tests/domain/test_values.py`、`tests/settings/test_schema.py`、`tests/settings/test_upgrade.py`、`tests/store/flowdb/test_*`、`tests/services/test_flowsource_anomaly.py`（沿用既有檔名）。

**Produces:**
- `DetectorKind.DIRECTION_REVERSAL / NEW_PAIR_PORT / QUIET_HOST_WAKES / DATA_STAGING / OFF_HOURS`（值同上表）。
- `DetectorSettings` 六個新欄位（見上）；`SCHEMA_VERSION = 13`；`_v12_to_v13` 補 detectors 預設、加入四條新規則（`notify=False`，已有同 `pack_key` 不重加）。
- `destination_activity_hourly(hour, dst_key, connections, bytes, bytes_known, PRIMARY KEY(hour, dst_key)) WITHOUT ROWID`；`_add_activity` 同時累加目的端（只算即時輪、沒被擋），保留 `ACTIVITY_KEEP = 15 天`（兩表同刪）。
- 讀取（全部依鍵、`_reading`）：
  - `pairs_before(ctx, pairs, *, before) -> set[tuple[str, str]]`：基準有任一 port 的 (src, dst) 且 `first_seen <= before`。
  - `ports_served_before(ctx, keys: Collection[tuple[str, int, int]], *, before) -> set[tuple[str, int, int]]`：(dst, port, proto) 在 `before` 之前有任何來源連過。
  - `sources_known_before(ctx, srcs, *, before) -> set[str]`：基準在 `before` 之前看過它發起連線。
  - `activity_hours(ctx, srcs, *, start, end) -> dict[str, list[datetime]]`：'all' 類每小時有活動的整點。
  - `fan_in_now(ctx, *, since, until) -> dict[str, FanIn]`：目的端最近一段的連線、帶位元組的來源集合大小、位元組、帶位元組與全部增量數（沒被擋、非 late）。
  - `destination_history(ctx, dsts, *, start, end) -> dict[str, int | None]`：目的端任一小時最多位元組（沒有帶位元組的小時為 None）。

**Tests（先紅）：**
- `test_v12_settings_gain_batch2_detector_defaults`：v12 檔升級後六個欄位為預設，原有值不變。
- `test_destination_activity_counts_live_unblocked_growth_only`：cycle 增量進表；late、backfill、blocked 不進。
- `test_activity_kept_fifteen_days`。
- `test_pairs_before_counts_any_port_and_blocked_rows`、`test_ports_served_before_any_source`、`test_sources_known_before`、`test_activity_hours`、`test_fan_in_now_counts_byte_carrying_sources`、`test_destination_history_none_when_no_bytes`。
- `test_batch2_reads_raise_stale_generation`（換 PCE 讀到一半，每支新讀取都丟 `StaleGeneration`）。

> Task 2–5 共用一個綠點：新的 `DetectorKind` 一加，`DETECTORS`、i18n、TS 對照與契約就要同時有（閘門逐一檢查），所以四個任務在同一分支上依序以先紅測試推進，最後一起提交。規則包與升級加規則的測試（`test_v12_settings_gain_batch2_rules_recording_only` 等）也在 Task 5。

### Task 2：F 方向反轉、G 既有主機對的新 port

**Files:** `domain/anomaly.py`、`domain/detectors.py`（`AnomalyData` 新欄位、`DETECTORS`、`dedup_windows`：F、G 30 天）、`services/analysis/anomaly_inputs.py`；測試 `tests/domain/test_anomaly.py`、`tests/services/analysis/test_anomaly_inputs.py`。

**Produces:** `AnomalyData.pairs_before: frozenset[tuple[str, str]]`、`ports_served: frozenset[tuple[str, int, int]]`；`detect_direction_reversal`、`detect_new_pair_port`。指紋 `reverse|{B}|{A}`、`pairport|{A}|{B}|{port}|{proto}`；主體為發起端；ends＝(s 發起端, t 目的端)；證據為該對主機該 port 的明細 segment。

**Tests（先紅）：** 反向首次出現 → F；反向本輪前出現過（含被擋）→ 不出；A→B 從沒出現 → 不出；管理 port／動態 port／公網 → 不出；基準未滿 → `accumulating`。G：新 port 且目的端沒人用過 → medium；目的端別人用過 → low；同群組已用過同目的簽章＋port → 不出；A→B 之前沒出現 → 不出（那是新連線，不是新 port）；重要資產目的 → 升一級。服務層：只對候選查鍵（候選數＝查詢鍵數）。

### Task 3：H 安靜主機甦醒、J 時段偏離

**Files:** 同 Task 2，`AnomalyData` 加 `quiet: Mapping[str, Quiet]`（或同義結構：每個候選來源的有活動整點與是否早已知）、`hours_days: float`；`dedup_windows`：H、J＝`SURGE_WINDOW`。

**Produces:** `detect_quiet_host_wakes`、`detect_off_hours`；指紋 `quiet|{src}`、`offhours|{src}|{slot}`；證據為來源最近 60 分鐘、沒被擋的明細。

**Tests（先紅）：** H：安靜 7 天後 150 條 → medium；安靜期內有任一小時活動 → 不出；基準在安靜期前沒看過它 → 不出（新主機）；非受管來源 → 不出；安靜期有收集缺口 → `incomplete`、零偵測；活動表不足 `quiet_days` 天 → `accumulating`；每日重讀 → 不評估。J：14 天裡 6 天在 01–09 時有活動，現在 14 時 → low；那個時段某天有活動 → 不出；有活動的天數 < 5 → 不出；時段某天有缺口 → `incomplete`、零偵測；活動表不足 7 天 → `accumulating`。

### Task 4：I 資料匯集

**Files:** 同 Task 2，`AnomalyData` 加 `fan_in: Mapping[str, FanInFact]`、`fan_in_coverage: tuple[int, int]`；`dedup_windows`：I＝`SURGE_WINDOW`。

**Produces:** `detect_data_staging`；指紋 `staging|{dst}`；主體為匯集端；ends＝所有來源（s）＋匯集端（t）；證據為往匯集端最近 60 分鐘、沒被擋的明細；`confidence.field = "bytes"`。

**Tests（先紅）：** 6 個內部來源合計 2 GB、前 7 天最大 300 MB → medium；前 7 天最大 1 GB（< 3 倍）→ 不出；來源 4 個 → 不出；目的端公網 → 不出；完全沒有帶位元組的增量 → `no_data`；部分帶位元組 → 狀態寫覆蓋；比較期有缺口 → `incomplete`（仍偵測，同 B）；活動不足 7 天 → `accumulating`。

### Task 5：一件事一則、焦點、告警、i18n、GUI、報表

**Files:** `domain/anomaly.py`（`drop_covered`）、`domain/detectors.py`（`run_detectors` 呼叫）、`domain/focus.py`、`domain/alertpack.py`、`services/reports/common.py`、`i18n/zh_TW.json`、`i18n/en.json`、`web/src/pages/system/Lateral.tsx`、`web/src/pages/alerts/RuleEditor.tsx`、`web/src/api/*`（`gen_contracts.sh`）；測試 `tests/domain/test_anomaly.py`、`tests/domain/test_alertrules.py`、i18n 與 glossary 既有閘門、e2e（Lateral 設定往返）。

**Tests（先紅）：** `drop_covered`：B＋H 同來源 → 只留 B；H＋J → 只留 H；A＋G 同 (src, dst, port) → 只留 A；不同來源都留。每個新 kind 都有 `detector_name_*`、`focus_title_*`（兩語系）、狀態原因鍵；`PACK_KEYS` 含四條新規則。

### Task 6：規模、.106 驗收、文件、全分支審查、合併

- [ ] 規模：1,000 台合成資料（`scripts/synth_flows.py`＋第一批的 `scale_p45.py` 改寫），量偵測一輪的新讀取耗時與每小時活動兩表大小；寫進 spec §5。
- [ ] 合成情境：H、I、J（lab 沒有 7 天以上的 v6 每小時活動，.106 切換在 11-01）各一個情境，經真寫入路徑觸發並在 GUI 看到偵測與句子。
- [ ] .106 部署：F、G 由 dev（有 VEN）對 lab 主機做反向連線與新 port 連線，等 ≥ 20 分鐘看偵測；H、I、J 看狀態（累積中／無資料），截圖兩種寬度。
- [ ] `docs/guide` 對應偵測器說明、CHANGELOG `[6.1.0] - unreleased`、`__version__ = "6.1.0"`。
- [ ] Codex 全分支審查（`TASK: code review only…`），Important 以上一次修完（各附先紅測試）。
- [ ] 合 main、閘門全綠、push、盯 CI；部署 .106、.135。
