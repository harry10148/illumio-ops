# illumio-ops v6 P3 分析核心：橫向移動 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 執行方式待使用者選定（見文末）。

**Goal:** 在 P2 收進來的流量、事件、清冊與勒索防護資料上建出橫向移動的分析核心：暴露面圖、八個偵測器與前兆加權、deny rule 試算、預計阻擋、政策解釋、勒索防護拆解、竄改判讀、關注清單，以及分析段落。這些都是領域核心純函式加上服務層，結果存進流量庫，P4 告警、P5 報表、P6 工作台直接取用。GUI 只加一頁「設定 › 橫向移動」。

**Architecture:**
- 演算法與判斷放在 `illumio_ops/domain/`，不做 I/O、不讀設定。
- 取數一律經 FlowSource／EventSource。FlowSource 新增四種讀法：聚合、觀測列、基準期邊、服務流量摘要。EventSource 新增兩種：聚合、前兆事件。
- 服務層 `illumio_ops/services/analysis/` 組裝輸入、呼叫領域函式，把結果寫進流量庫的新表。這些表換 PCE 時隨流量庫一起清除。
- 執行時機：
  - 偵測在每輪流量收集之後執行，每日重讀之後再補跑一次。
  - 暴露面圖、勒索疊加、竄改摘要、關注清單每小時重算一次並存起來，不在請求時計算（spec §5）。

**Tech Stack:** 沿用 P1／P2，不新增執行期依賴。圖演算法自寫，可達數用 Python 整數當位元集合。

**Spec:** `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md`（2026-10-24 修訂版核可）。本階段依據：
- §4.3 反目標 1、5、8、9；§5 客戶規模；§6.3 第 4 點；§6.4 基準期、快照、使用者標註、收集模式。
- §6.5「告警」的 lateral 型別；§6.5.1、§6.5.2、§6.5.4、§6.5.6、§6.5.7。
- §6.6 F1–F12 與角色表；§7「回填不進告警評估」；§9 修訂版驗收；§10 交給 builder 的門檻與上限。

路線圖 `docs/superpowers/plans/2026-10-24-v6-roadmap.md` 的 P3 列，含 P2 留下的追蹤項 F10、F7、F15。

## Global Constraints

**沿用與基本規則**
- P1／P2 的 Global Constraints 全部沿用：
  - Python 3.12、單一鎖檔、無 `print(`。
  - 路徑只從 `InstallPaths` 推；每表單一寫入者；值域只在 `domain/values.py`；憑證不外露。
  - 英文 conventional commits，結尾附 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`；只 `git add <明確路徑>`。
  - 測試在前景跑並加 timeout；每次 commit 後 `git status --porcelain illumio_ops tests_v6 web scripts/v6` 為空。
  - 時間一律帶時區的 UTC；失敗不得看起來像空結果；不做流量抽樣。

**分支與 worktree**
- 分支 `feat/v6-p3-lateral`，worktree `.worktrees/v6-p3`。P1、P2 已合入 main 就從 main 開；否則從 `feat/v6-p2-collection` 的 HEAD 開。
- 每個任務開始前執行 `pwd && git branch --show-current`。

**閘門**
每個任務之間都要親自跑，內容同 `ci-v6.yml`。Task 0 在 P3 的 SDD 工作區建立 `gates.sh`：
```bash
#!/usr/bin/env bash
set -euo pipefail
cd /home/harry/rd/illumio-ops/.worktrees/v6-p3
export PATH="$PWD/.venv/bin:$PATH" PYTHON="$PWD/.venv/bin/python"
echo "== pip-audit";  timeout 600 pip-audit -r requirements-v6.lock --strict 2>&1 | tail -1
echo "== contracts";  bash scripts/v6/gen_contracts.sh && git diff --exit-code --stat web/src/api/contracts.json web/src/api/generated.ts
echo "== typecheck";  npm --prefix web run --silent typecheck
echo "== build";      npm --prefix web run --silent build > /dev/null
echo "== ruff";       ruff check illumio_ops tests_v6 scripts/v6
echo "== mypy";       mypy --config-file mypy-v6.ini
echo "== pytest";     timeout 900 python -m pytest tests_v6 -q -p no:logging -n auto --dist loadfile 2>&1 | tail -1
echo "ALL GATES GREEN"
```
先 commit 再跑閘門；閘門後的 commit 用 `rc=$?` 守住。

**分層與單一來源**
- 領域核心不得 import `illumio_ops` 的其他子套件（`tests_v6/gates/test_layering.py`），也不讀設定、不做 I/O。
- 領域結果只帶 i18n 訊息鍵與參數，文字由呼叫端產生。設定模型轉成領域的 dataclass 由服務層負責。
- 流量與事件只經 FlowSource／EventSource 讀（`test_single_reader.py`）。
- 每張新表都登錄 `TABLE_OWNERS`；每個新設定葉都登錄讀者；每條新 `/api` 路由都要有前端呼叫者；每個新 i18n 鍵兩個語系都要有。

**資料語意**
- **可信度**（反目標 8）：每個偵測、排名、分數都附三項——資料延遲（現在減流量收集水位）、觀察期間、欄位覆蓋率。
  - 欄位覆蓋為 0 時，狀態是「無資料可判斷」（`no_data`），不是「沒偵測到」。
  - 視窗內有收集缺口時，狀態標「資料不完整」並列出缺口。
- **收集模式**：
  - 僅事件模式：所有需要流量的分析回報 `collection_off`，沿用 `services.coverage.GapReason`。
  - 告警模式照常運作：基準期表保留基準期，圖由基準期表建。
- **回填不進偵測評估**（spec §7）：偵測只評估 origin = `ingest` 的列。每日重讀補到的晚到紀錄是 ingest，會以「晚到」評估。回填資料照樣寫入基準期，所以會出現在暴露圖。
- **原廠數字**（反目標 9）：照實轉述並附拆解；矛盾要標出來，不拿來排序。
- **不寫 PCE**：隔離在 P6，RHC 在 P5。讀 PCE 只用 `read_only` 角色能做的呼叫（spec §6.6 角色表）。

**每小時分析的工作量上限**
- 目標：1,000 台受管 workload、觀察期 30 天，在 .106（4 vCPU）60 秒內完成，記憶體增量小於 500 MB。
- 超過上限時，結果標 `limits_hit` 並寫明是哪個上限，不無聲截斷（反目標 5）。

## Review Focus

1. **reported 決定為 `unknown` 的管理 port 連線**（lab 佔 24%，Task 0）：
   - 「現在」的圖要包含它，但標成 `unknown` 並計數揭露；「全部強制後」不含它。
   - 偵測器把它當成「沒被擋」。
   - → Task 5 `test_unknown_edges_in_now_marked`；Task 7 `test_fanout_counts_unknown_decision`。
2. **VEN 重新配對**：主機的 `ven_href` 變了，舊 VEN 發的竄改或離線事件不得因此對不到主機。前兆歸屬改用唯一的主機名稱比對，比不到的事件計入 `unmatched`，不默默丟掉。
   - → Task 8 `test_repaired_ven_matched_by_unique_hostname`、`test_unmatched_precursor_counted`。
3. **某類主機 process／使用者覆蓋為 0**（Linux outbound 只有使用者沒有 process）：
   - 帳號扇出、非預期 process 的狀態是 `no_data` 並附覆蓋率，不是「沒偵測到」。
   - 分析段落的結果附「此分析只涵蓋 N% 的 flow」。
   - → Task 8 `test_account_fanout_no_data_when_no_users`；Task 3 `test_bytes_metric_reports_coverage`。
4. **重要資產或管理群組未設定，或設定的 label 在 PCE 上已不存在**：
   - 依賴它們的項目不出現，不顯示成 0。
   - 關注清單出現「尚未設定」或「設定的 label 已不存在」，非管理群組偵測器的狀態是 `disabled`。
   - → Task 4 `test_stale_selector_detected`；Task 8 `test_non_admin_group_disabled_without_groups`；Task 13 `test_setup_required_when_unset`、`test_stale_selector_item`。
5. **偵測視窗內有收集缺口**（PCE 失敗、截斷）：該輪狀態標 `incomplete` 並列出缺口；水位照常前進，缺口補回後由重讀觸發晚到評估。
   - → Task 7 `test_gap_in_window_marks_incomplete`。

---

### Task 0：開工與計畫撰寫時的實測（實測已完成）

**開工步驟**
- 建 worktree 與分支（見 Global Constraints）。
- 建立虛擬環境：`python3.12 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements-v6.lock && .venv/bin/pip install -r requirements-v6-dev.txt && npm ci --prefix web`。
- 執行 `superpowers:executing-plans` 的 `sdd-workspace` 取得工作區，建立帳本與上面的 `gates.sh`，跑一次閘門確認全綠再開始 Task 1。

**計畫撰寫時已實測（2026-10-25，唯讀；數字是 Task 5、7、8、11、12 預設值的依據，Task 16 寫回 spec）**

.106 v6 流量庫，lab 21 台，資料期間 9/21–10/25，共 56.9 萬筆主列。原始輸出在 gitignored 的 `tmp/v6-p2-verification/p3-store-facts.json`。

- **欄位覆蓋率**（主列）：
  - 發起端 process 1.6%、發起端使用者 9.8%、服務端 process 0.8%、位元組 3.1%。
  - 只看 16 個管理 port 的 1,088 列：process 15%、使用者 44%。
- **管理 port 連線的 reported 決定**：potentially_blocked 818、unknown 263（24%）、allowed 5、blocked 2。
- **管理 port 的圖**：65 個節點；「現在」113 條邊，「全部強制後」3 條。
- **扇出**（一台來源在時間桶內的不重複目的數）：

  | 時間桶 | p99 | 最大 | ≥10 的桶數（34 天內） |
  |---|---|---|---|
  | 10 分鐘 | 2 | 22 | 3 |
  | 60 分鐘 | 3 | 22 | 3 |
  | 24 小時 | 22 | — | — |

  所以預設 N = 10、視窗 60 分鐘，在 lab 上 34 天約觸發 3 次。
- **新的管理連線**（基準期首見落在當天的管理 port 組合）：滿 30 天後每天 1–9 組。
- **使用者**：11 個使用者用過管理 port，整段期間最多的對 29 台、次多 7 台。
- **管理 port 的發起 process**：

  | port | 觀察到的 process |
  |---|---|
  | 445 | system 30、powershell.exe 2 |
  | 135 | lsass、backgroundtaskhost、svchost、powershell、dsregcmd |
  | 389 | svchost、taskhostw、lsass、backgroundtaskhost |
  | 88 | lsass |
  | 22 | ssh 12、powershell.exe 1 |
  | 5985 | powershell.exe 2 |
  | 3389 | powershell.exe 1 |

- **被擋連線**：管理 port 只有 2 列。大量被擋偵測器的門檻 lab 無法提供依據，只能用 fixture 定。
- **跨環境的管理 port 連線**：272 列，10 組 env 對。
- **竄改事件**：
  - 店內 30 天 215 筆，3 台：一台中位數 10.1 分鐘（q1 9.6、q3 10.6、n 201），一台 26.9 分鐘（IQR 19–583），一台 0.6 分鐘（q3 12.6）。
  - 店內每筆竄改事件的 `workload_href` 都是 NULL。P2 的裁定是事件經 `events.created_by_href = workloads.ven_href` 對到主機。
  - 離線事件 `system_task.agent_offline_check` 把主機放在 `resource_changes[].resource.workload.href`，變更是 `changes.online.before=true → after=false`。
  - signal 型的 `kernel_functions` 是用逗號串起來的字串，例如 `["nfnetlink_rcv_batch,nf_tables_deltable"]`。
- **勒索防護**：
  - `protection_state` × `port_status`：protected_closed／inactive 291、protected_closed／listening 27、unprotected／inactive 44、unprotected／listening 4。
  - lab 的 `active_policy`、`draft_policy` 只出現 `blocked_by_override_deny`；`recommendation` 一律是空字串。
  - 13 台 `fully_protected` 主機的 `risk_percent` 都是 0.0，即 F5 的矛盾。

lab PCE（地端 26.2.20）。

- **60 天竄改事件**：已錄下並去識別，主機名改成 host-NN，不含 href、IP、主機名稱。檔案在 `tmp/v6-p2-verification/p3-tamper_60d.json`，共 335 筆、7 台主機：

  | 主機 | 筆數 | 中位間隔（分鐘） | 四分位 | 分類 |
  |---|---|---|---|---|
  | host-01 | 201 | 10.1 | 9.6／10.6 | confirmed |
  | host-04 | 10 | 10.1 | 9.4／10.9 | confirmed |
  | host-05 | 51 | 10.1 | 9.5／10.6 | confirmed |
  | host-07 | 56 | 10.1 | 9.5／10.5 | confirmed |
  | host-02 | 8 | 26.9 | 13.6／1100 | — |
  | host-03 | 8 | 0.6 | 0.1／12.6 | — |
  | host-06 | 1 | — | — | — |

  spec F4 寫「3 台約 10 分鐘」，用的是較早的 60 天視窗；這份錄製檔是 4 台。驗收以這份錄製檔為準，Task 16 更正 F4。
- **draft 重算**（2 天、5,000 筆，跑完 `update_rules`）：
  - `draft_policy_decision`：potentially_blocked 4,816、blocked_by_boundary 148、allowed 36。
  - `enforcement_boundaries` 的形狀是 `[{"href": "<deny rule href>"}]`。
  - `rules` 是清單，lab 樣本裡每個元素都是 `{"essential_service_rule": "<字串>"}`；一般 allow rule 的元素預期是 `{"href": ...}`。
  - `override_deny_rules` 有欄位但為空；`boundary_decision` 全為 null。
- **draft 規則集**（經 Illumio LAB MCP 讀取）：
  - deny rule 沒有名稱欄，`description` 多半是空字串。
  - 可辨識一條 deny rule 的是：規則集名稱、規則型別（deny／override_deny）、consumers、providers、services。
  - lab 有規則集 `tedt`（env=Server → env=Server、All Services、deny）與 `Quarantine` 的兩條 override_deny。

規模：.106 上 1,000 台合成庫的 `connection_baseline` 全表掃描，冷快取超過 25 分鐘仍未完成，所以圖不得做全表掃描。Task 2 加 `ix_baseline_port`，見下面的 Ruling。

**撰寫計畫時已做的裁定**（執行時照抄進帳本，格式 `Ruling: 決定 — 理由 — 錯了的代價`）
- **圖由 `connection_baseline` 加上新的 `last_decision` 欄建**，不由 flows 建：
  - 基準期表在三種收集模式下都保留基準期，告警模式的流量只留 3 天。
  - 基準期表已在每次連線變更時更新；P2 刻意拿掉 flows 的 `(port, proto)` 索引，這裡不加回去。
  - 代價：多一個欄與一個索引的寫入成本。Task 16 重量 1,000 台尖峰持鎖。
- **`ix_baseline_port ON connection_baseline(port)`**：
  - `port` 與主鍵寫入後不再改變，所以只在新組合寫入時多寫一筆索引，更新 `last_seen` 不碰它。
  - 不做含 `last_seen` 的覆蓋索引：每輪每條活躍連線都會改 `last_seen`，那樣索引會一直改寫。
- **「現在」含 `unknown` 決定（標記並計數），「全部強制後」不含**：
  - spec §6.5.1 對 unknown 沒有說法；unknown 沒有被擋，流量確實通了。
  - 代價：若 PCE 的 unknown 其實代表被擋，暴露面會高估——但會揭露數量。
- **重要資產與管理群組的 label 選擇是聯集**：任一 key=value 相符就算。spec 的例子 `app=Finance`、`role=DB` 是兩個各自成立的選擇。不做 AND 組合。
- **環境 label 的 key 是設定項 `environment_label_key`，預設 `env`**，因為客戶可能自訂 label 型別。
- **不納入大量被擋偵測的 port**：任何 port 都算，因為掃描不限管理 port。lab 沒有樣本，門檻由 fixture 定，Task 16 註明「未經實測」。

---

### Task 1：值域與設定 schema v3（`lateral` 段）

**Files:**
- Modify: `illumio_ops/domain/values.py`、`illumio_ops/settings/schema.py`、`illumio_ops/settings/upgrade.py`、`illumio_ops/migrate/v5.py`、`tests_v6/settings/test_schema.py`、`tests_v6/settings/test_upgrade.py`、`tests_v6/gates/test_settings_readers.py`、`tests_v6/domain/test_values.py`（不存在就建立）、`web/src/api/contracts.json`、`web/src/api/generated.ts`（以 `scripts/v6/gen_contracts.sh` 產生）

**Interfaces:**
- Produces:
  - **`values.py` 新增的值域**，全部加進 `_ENUMS`：
    - `Severity`：low、medium、high、critical；`SEVERITY_ORDER`；`def raise_severity(s: Severity, steps: int = 1) -> Severity`（最高到 critical）。
    - `DetectorKind`：fanout、new_admin_connection、pivot_chain、blocked_surge、non_admin_group、cross_env、account_fanout、unexpected_initiator。
    - `DetectorState`：ok、disabled、accumulating、no_data、collection_off、incomplete。
    - `SegmentDimension`：
      - 流量用：src_host、dst_host、src_label、dst_label、service、initiator_process、initiator_user、service_process、service_user、decision、direction。
      - 事件用：event_type、event_host、event_severity、actor。
    - `SegmentMetric`：flows、connections、distinct_dst、distinct_src、distinct_ports、bytes、events。
    - `SegmentView`：detail、ranking、predicted_block。
    - `EdgeState`：allowed、potentially_blocked、unknown。
    - `TamperPattern`：regular_cycle、burst、sporadic、too_few。
    - `TamperAction`：add_rule、delete_rule、add_chain、delete_chain、add_table、delete_table。
    - `PrecursorKind`：tamper、suspend、offline。
    - `RansomwareTrafficClass`：priority、safe_to_block、suspicious、protected、unknown。
    - `FocusKind`：detection、exposure_asset、pivot_host、cross_env、tamper、ransomware_priority、vendor_contradiction、mode_switch_blocker、data_coverage、visibility、collection_gap、system_health、setup_required、stale_selector。
    - `Confidence`：high、medium、low。
  - **`LATERAL_PORTS_DEFAULT: tuple[tuple[int, str], ...]`**：5.x `_LATERAL_PORTS` 的 16 項，依原順序，名稱照抄：445 SMB、135 RPC、139 NetBIOS、3389 RDP、22 SSH、5985 WinRM-HTTP、5986 WinRM-HTTPS、23 Telnet、2049 NFS、111 RPC Portmapper、389 LDAP、636 LDAPS、88 Kerberos、1433 MSSQL、3306 MySQL、5432 PostgreSQL。出處是 `src/report/analysis/mod15_lateral_movement.py`（5.x `f022272e`），commit 訊息註明。
  - **`schema.py`**：`SCHEMA_VERSION: Literal[3] = 3`，`Settings.schema_version: Literal[3]`；`Settings.lateral: LateralSettings`，宣告在 `collection` 之後。各模型照 P1 規則，沒有欄位預設值：
    ```python
    class PortEntry(StrictModel):
        port: int = Field(ge=0, le=65535)
        proto: int | None = Field(ge=0, le=255)        # None = 任何協定
    class LabelSelector(StrictModel):
        key: str = Field(min_length=1, max_length=255)
        value: str = Field(min_length=1, max_length=255)
    class ExpectedInitiators(StrictModel):
        port: int = Field(ge=0, le=65535)
        proto: int | None = Field(ge=0, le=255)
        processes: tuple[str, ...] = Field(min_length=1)   # 驗證時以 domain.identity.normalize_process 正規化，空值拒絕
    class DetectorSettings(StrictModel):
        fanout_targets: int = Field(ge=2, le=10000)
        fanout_window_minutes: int = Field(ge=10, le=1440)
        account_fanout_targets: int = Field(ge=2, le=10000)
        account_fanout_window_minutes: int = Field(ge=10, le=1440)
        chain_window_minutes: int = Field(ge=10, le=1440)
        blocked_targets: int = Field(ge=2, le=10000)
        blocked_window_minutes: int = Field(ge=10, le=1440)
        blocked_surge_factor: float = Field(ge=1.0, le=100.0)
        exclude_system_accounts: bool
        precursor_hours: int = Field(ge=1, le=168)
    class LateralSettings(StrictModel):
        extra_admin_ports: tuple[PortEntry, ...]
        removed_admin_ports: tuple[PortEntry, ...]
        include_pce_admin_services: bool
        critical_assets: tuple[LabelSelector, ...]
        admin_groups: tuple[LabelSelector, ...]
        environment_label_key: str = Field(min_length=1, max_length=255)
        graph_hops: int = Field(ge=1, le=6)
        observation_days: int = Field(ge=1, le=365)
        expected_initiators: tuple[ExpectedInitiators, ...]
        detectors: DetectorSettings
    ```
  - **驗證規則**（錯誤訊息不含值，比照 P1／P2）：
    - 同一 port／proto 不能同時在加入與移除清單；
    - `expected_initiators` 的 `(port, proto)` 不得重複；
    - `Settings` 的 `lateral` field_validator 檢查 `observation_days <= collection.retention.baseline_days`，錯誤路徑落在 `lateral.observation_days`。
  - **`default_lateral() -> LateralSettings`**：
    - 加入與移除清單為空，`include_pce_admin_services=True`；重要資產、管理群組為空；`environment_label_key="env"`；`graph_hops=3`；`observation_days=30`。
    - `detectors`：`fanout_targets=10`、`fanout_window_minutes=60`、`account_fanout_targets=10`、`account_fanout_window_minutes=60`、`chain_window_minutes=30`、`blocked_targets=5`、`blocked_window_minutes=60`、`blocked_surge_factor=3.0`、`exclude_system_accounts=True`、`precursor_hours=24`。
    - `expected_initiators`，依據 Task 0 的 lab 量測：

      | port／proto | processes |
      |---|---|
      | 445／6 | system、svchost.exe、lsass.exe、explorer.exe、services.exe、mount.cifs、smbclient |
      | 3389／6 | mstsc.exe、msrdc.exe、rdcman.exe、xfreerdp、remmina |
      | 22／6 | ssh、scp、sftp、rsync、git、ssh.exe、putty.exe、plink.exe、winscp.exe |
      | 5985／6、5986／6 | powershell.exe、pwsh.exe、pwsh、wsmprovhost.exe、svchost.exe |
      | 135／6 | lsass.exe、svchost.exe、services.exe、backgroundtaskhost.exe、wmiprvse.exe、dsregcmd.exe、mmc.exe |

      389、88 不列：lab 上合法發起者太多。
  - **`upgrade.py`**：`UPGRADES[2]` 把 v2 升為 v3，加入 `default_lateral()` 的 dump。
  - **`migrate/v5.py`**：輸出帶預設 `lateral`。5.x 沒有對應設定；5.x 的 `report_config.yaml` `lateral_movement_ports` 不搬，遷移報告列一行說明。
  - **讀者登錄**：新設定葉先放 `PENDING_READERS`，標上真正讀它的任務：
    - port、重要資產、管理群組、環境 key → `"P3-T4"`；
    - `graph_hops`、`observation_days` → `"P3-T5"`；
    - `detectors.*`、`expected_initiators` → `"P3-T7"`／`"P3-T8"`。

- [ ] **Step 1：寫失敗測試**：
  - 設定與升級：`test_v2_file_loads_as_v3_with_default_lateral`（檔案內容不變，比照 P2 Task 1）、`test_lateral_unknown_key_invalid`、`test_observation_days_beyond_baseline_invalid`、`test_port_both_added_and_removed_invalid`、`test_duplicate_expected_initiator_port_invalid`、`test_expected_initiator_processes_normalized`（`C:\Windows\System32\MSTSC.EXE` → `mstsc.exe`）、`test_default_lateral_pins_values`。
  - 值域：`test_raise_severity_caps_at_critical`、`test_new_value_domains_exported`。
  - 遷移：`test_migrator_output_has_default_lateral`。
- [ ] **Step 2：跑** `timeout 300 .venv/bin/python -m pytest tests_v6/settings tests_v6/domain/test_values.py tests_v6/gates/test_settings_readers.py tests_v6/migrate tests_v6/test_rescue.py -q` → FAIL。
- [ ] **Step 3：實作**，然後跑 `bash scripts/v6/gen_contracts.sh`，把產生的兩個檔案一併 commit。
- [ ] **Step 4：跑同一命令 → PASS；再跑閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/domain/values.py illumio_ops/settings illumio_ops/migrate tests_v6/settings tests_v6/domain/test_values.py tests_v6/gates/test_settings_readers.py tests_v6/migrate web/src/api/contracts.json web/src/api/generated.ts && git commit -m "feat(v6): lateral-movement value domains and settings schema v3"`

---

### Task 2：流量庫 0002（F10 自有計數、基準期判定與 port 索引、分析結果表）

**Files:**
- Create: `illumio_ops/store/flowdb/migrations/0002_analysis.sql`、`illumio_ops/store/flowdb/analysis.py`、`tests_v6/store/test_analysis_store.py`、`tests_v6/store/test_flows_0002.py`
- Modify: `illumio_ops/store/flowdb/flows.py`、`illumio_ops/store/ownership.py`、`illumio_ops/services/collect/retention.py`、`tests_v6/services/collect/test_retention.py`

**Interfaces:**
- Produces：`0002_analysis.sql`，各表擁有者都是 `illumio_ops.store.flowdb.analysis`；`flows` 與 `connection_baseline` 的改動仍由 `store.flowdb.flows` 擁有。
  - **F10 自有計數**：
    - `ALTER TABLE flows ADD COLUMN own_bytes_in INTEGER`、`own_bytes_out INTEGER`。
    - 回填範圍只限單列連線，因為它的值就是自己的：`UPDATE flows SET own_bytes_in = bytes_in, own_bytes_out = bytes_out WHERE conn_key IN (SELECT conn_key FROM flows GROUP BY conn_key HAVING COUNT(*) = 1)`。
    - 多列連線的舊列維持 NULL，語意是「0002 之前寫入、自有值不明」。合併時以 `COALESCE(own_bytes_*, bytes_*)` 取代，舊列沿用舊行為並在 docstring 寫明。
    - 實際上只影響 .106 的開發資料；客戶在 P8 全新安裝，從 0002 開始寫。
  - **基準期判定與 port 索引**：
    - `ALTER TABLE connection_baseline ADD COLUMN last_decision TEXT`。
    - 一次性回填：用視窗函式 `ROW_NUMBER() OVER (PARTITION BY src_key, dst_key, COALESCE(port,-1), proto ORDER BY last_detected DESC)` 從 `flows` 主列取最新決定，再 `UPDATE ... FROM` 寫入。不得用逐列的相關子查詢——flows 沒有 `src_key` 索引。
    - `CREATE INDEX ix_baseline_port ON connection_baseline (port)`。
  - **新表**：
    - `detections`：
      ```
      id INTEGER PRIMARY KEY, detector TEXT NOT NULL, fingerprint TEXT NOT NULL, subject_key TEXT NOT NULL,
      severity TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, occurrences INTEGER NOT NULL,
      late INTEGER NOT NULL, critical_asset INTEGER NOT NULL, summary_json TEXT NOT NULL,
      segment_json TEXT NOT NULL, confidence_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
      ```
      索引：`(detector, fingerprint, last_seen)`、`(last_seen)`、`(subject_key, last_seen)`。
    - `analysis_runs(kind TEXT PRIMARY KEY, watermark TEXT, last_started_at TEXT, last_ok_at TEXT, last_error TEXT, status_json TEXT)`
    - `analysis_results(kind TEXT PRIMARY KEY, computed_at TEXT NOT NULL, params_json TEXT NOT NULL, result_json TEXT NOT NULL)`
    - `lateral_snapshot_daily(day TEXT PRIMARY KEY, metrics_json TEXT NOT NULL)`
    - `focus_items(fingerprint TEXT PRIMARY KEY, kind TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, active INTEGER NOT NULL, score REAL NOT NULL, item_json TEXT NOT NULL)`
- Produces：`flows.py` 的行為改變。
  - 新增一列時 `own_bytes_* = bytes_*`；更新時 `own_bytes_* = MAX(own, 新值)`，兩者都 NULL-aware。
  - `_merge_connection` 每次都由目前各列的 `COALESCE(own_bytes_*, bytes_*)` 重算主列的 `bytes_*`，取最大值；非主列的 `bytes_*` 等於它自己的值。
  - `_update_baselines` 寫入 `last_decision`：新觀測的 `last_seen >= 既有 last_seen` 時，採用新觀測的決定。
- Produces：`store/flowdb/analysis.py`。偵測的 dataclass 由 Task 7 定義；這裡收的是序列化後的列 `DetectionWrite`。
  ```python
  @dataclass(frozen=True)
  class DetectionWrite:
      detector: str; fingerprint: str; subject_key: str; severity: str
      first_seen: datetime; last_seen: datetime; critical_asset: bool
      summary_json: str; segment_json: str; confidence_json: str
  def upsert_detections(conn, rows: Sequence[DetectionWrite], *, dedup: Mapping[str, timedelta], late: bool, at: datetime) -> tuple[int, int]  # (新增, 更新)
  def detections_since(conn, since: datetime, *, detectors: Collection[str] = (), limit: int) -> list[sqlite3.Row]
  def get_run(conn, kind: str) -> sqlite3.Row | None
  def set_run(conn, kind: str, *, started_at: datetime | None = None, ok_at: datetime | None = None,
              watermark: datetime | None = None, error: str | None = None, status: Mapping[str, Any] | None = None) -> None
  def write_result(conn, kind: str, *, params: Mapping[str, Any], result: Mapping[str, Any], at: datetime) -> None
  def read_result(conn, kind: str) -> sqlite3.Row | None
  def write_lateral_snapshot(conn, day: str, metrics: Mapping[str, Any]) -> None
  @dataclass(frozen=True)
  class FocusWrite:
      fingerprint: str; kind: str; score: float; item_json: str
  def upsert_focus(conn, items: Sequence[FocusWrite], *, at: datetime) -> dict[str, datetime]  # 回傳每個 fingerprint 的 first_seen；不在 items 裡的設為 active=0
  def delete_expired(conn, *, detections_before: datetime, focus_before: datetime, snapshot_day_before: str) -> int
  ```
  - `upsert_detections` 的語意：同一 `(detector, fingerprint)`，若最新一列的 `last_seen` 在 `dedup[detector]` 之內，就更新該列——`last_seen`、`occurrences + 1`、取較高的嚴重度、更新 `summary_json`；否則新增一列，代表安靜一段時間後再出現。
  - `late=True` 只影響新增的列。
- Produces：保留清理（`services/collect/retention.py`），在既有交易批次中呼叫 `delete_expired`：
  - `detections_before` 與 `focus_before` = now − `event_days`；
  - `snapshot_day_before` = `rollup_days` 的截止日。

- [ ] **Step 1：寫失敗測試**：
  - F10 與 flows：
    - `test_repair_does_not_double_count_bytes`（F10）：outbound A（100）與 inbound B（500）配成一對，主列 bytes = 500。之後寫入一筆時間更早、也落在配對間隔內的 outbound A2，B 被重新配給 A2。斷言 A 的連線 bytes = 100、A2＋B = 500，兩個連線合計 600 而不是 1,000。
    - `test_refresh_grows_own_bytes`
    - `test_legacy_multi_row_connection_keeps_bytes_after_0002`：在 v1 庫建一個兩列連線，跑 0002 後兩列的 own 都是 NULL、主列 bytes 不變。
  - 基準期：
    - `test_baseline_tracks_newest_decision`
    - `test_0002_backfills_last_decision`
    - `test_baseline_port_query_uses_index`：`EXPLAIN QUERY PLAN SELECT src_key, dst_key, port, proto FROM connection_baseline WHERE port IN (22, 445)` 含 `ix_baseline_port`。
  - 分析表：`test_detection_upsert_dedups_within_window`、`test_detection_after_quiet_period_is_new_row`、`test_focus_first_seen_kept_and_missing_marked_inactive`、`test_reset_clears_analysis_tables`、`test_retention_drops_expired_detections_and_snapshots`。
  - 守門：單一寫入者守門保持綠。
- [ ] **Step 2：跑** `timeout 600 .venv/bin/python -m pytest tests_v6/store tests_v6/services/collect/test_retention.py tests_v6/gates/test_single_writer.py -q` → FAIL。
- [ ] **Step 3：實作。**
- [ ] **Step 4：同一命令 → PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/store illumio_ops/services/collect/retention.py tests_v6/store tests_v6/services/collect/test_retention.py && git commit -m "feat(v6): flow db 0002 with own byte counters (F10), baseline decision and analysis tables"`

---

### Task 2b：F15——換 PCE 時進行中的探測寫回舊結果

**Files:** Create `illumio_ops/store/migrations/0002_probe_pce.sql`；Modify `illumio_ops/services/pce_health.py`、`tests_v6/services/test_pce_health.py`

**Interfaces:**
- 遷移：`pce_probe` 加 `pce_url TEXT NOT NULL DEFAULT ''` 與 `org_id TEXT NOT NULL DEFAULT ''`。
- `run_probe`：
  - 寫入的是探測開始時那份設定的 url／org；
  - 寫入前若目前設定的 url／org 已經不同，就不寫並 log 一行。
- `latest`：存的 url／org 與目前設定不符時回 `None`。

- [ ] **Step 1：失敗測試**：
  - `test_probe_of_previous_pce_is_not_written_after_switch`：fake PCE 在回應前改掉設定。
  - `test_latest_ignores_result_of_other_pce`。
- [ ] **Step 2：** `timeout 300 .venv/bin/python -m pytest tests_v6/services/test_pce_health.py tests_v6/store -q` → FAIL
- [ ] **Step 3：實作。**
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/store/migrations illumio_ops/services/pce_health.py tests_v6/services/test_pce_health.py && git commit -m "fix(v6): a probe of the previous PCE never becomes the current result (F15)"`

---

### Task 3：分析段落與聚合讀取（含 F7）

**Files:**
- Create: `illumio_ops/domain/segment.py`、`illumio_ops/services/analysis/__init__.py`、`illumio_ops/services/analysis/segments.py`、`tests_v6/domain/test_segment.py`、`tests_v6/services/analysis/__init__.py`、`tests_v6/services/analysis/test_segments.py`、`tests_v6/services/test_flowsource_aggregate.py`、`tests_v6/services/test_eventsource_aggregate.py`
- Modify: `illumio_ops/services/flowsource.py`、`illumio_ops/services/eventsource.py`、`illumio_ops/domain/filter.py`、`tests_v6/services/test_flowsource.py`

**Interfaces:**
- **`domain/filter.py`**：公開 `def endpoint_matches(ep: EndpointFilter, *, href: str | None, ip: str, labels: Mapping[str, str]) -> bool`，語意同 `_side_matches`；`matches` 改用它，行為不變。
- **`domain/segment.py`**（pydantic，`extra="forbid"`、frozen）：
  ```python
  class GroupBy(_Model):
      dimension: SegmentDimension
      label_key: str | None = None        # src_label/dst_label 必填，其他必須為 None
  class FlowSegment(_Model):
      filter: FilterSpec
      group_by: tuple[GroupBy, ...] = Field(default=(), max_length=2)
      metric: SegmentMetric = SegmentMetric.FLOWS
      view: SegmentView
      limit: int = Field(ge=1, le=1000)
  class EventFilter(_Model):
      start: AwareDatetime; end: AwareDatetime
      event_types: tuple[str, ...] = (); severities: tuple[str, ...] = ()
      host_hrefs: tuple[str, ...] = (); actor: str | None = None   # actor 為部分比對，語意同 like_pattern
  class EventSegment(_Model):
      filter: EventFilter
      group_by: tuple[GroupBy, ...] = Field(default=(), max_length=2)
      view: SegmentView                    # 只接受 detail 或 ranking
      limit: int = Field(ge=1, le=1000)
  def compile_flow_ranking(seg: FlowSegment) -> tuple[str, list[Any]]
  ```
  - **規則**：
    - ranking 至少一層分組，detail 與 predicted_block 不得分組；
    - 流量段落不得用事件維度或 `events` 指標，事件段落只能用事件維度。
  - **維度的 SQL 運算式**（`f` 為 flows）：

    | 維度 | 運算式 |
    |---|---|
    | src_host／dst_host | `f.src_key`／`f.dst_key`（顯示時改成主機名稱或 IP） |
    | src_label／dst_label | `LEFT JOIN label_set_members l1 ON l1.set_id = f.src_label_set AND l1.key = ?` 取 `l1.value` |
    | service | `COALESCE(f.port,-1)` 與 `f.proto` 兩欄 |
    | process 欄 | 原值（P2 寫入時已正規化） |
    | 使用者欄 | `CASE WHEN instr(u,'\')>0 OR instr(u,'@')>0 THEN lower(u) ELSE u END`（網域帳號不分大小寫） |
    | decision | `f.policy_decision` |
    | direction | `f.direction` |

  - **指標的 SQL**：

    | 指標 | 運算式 |
    |---|---|
    | flows | `COUNT(*)` |
    | connections | `SUM(f.num_connections)` |
    | distinct_dst | `COUNT(DISTINCT f.dst_key)` |
    | distinct_src | `COUNT(DISTINCT f.src_key)` |
    | distinct_ports | `COUNT(DISTINCT COALESCE(f.port,-1) || '/' || f.proto)` |
    | bytes | `SUM(COALESCE(f.bytes_in,0)+COALESCE(f.bytes_out,0))`，另回 `COUNT(f.bytes_in)` 當覆蓋率 |

  - 排序與截斷：`ORDER BY 指標 DESC, 分組鍵`，`LIMIT seg.limit + 1`。
  - **針對橫向移動的預設分析**（spec §6.5.7）：`def lateral_default_segments(admin_ports: Sequence[PortProto], *, start: datetime, end: datetime) -> dict[str, FlowSegment]`，鍵與定義如下。P5 的「使用者與 process」節、P6 工作台的預設排名都用它，不各自定義。

    | 鍵 | 分組 | 指標 | 其他條件 |
    |---|---|---|---|
    | `admin_initiator_users` | initiator_user | distinct_dst | 管理 port、排除系統帳號 |
    | `admin_initiator_processes` | initiator_process | distinct_dst | 管理 port |
    | `system_accounts_on_admin` | initiator_user | distinct_dst | 管理 port；`text` 不設，結果在服務層只留 `is_system_account` 為真的列 |

  - 「使用者 × 主機的新組合（對照基準期）」不是段落：由 flowsource 的 `new_user_pairs(ctx, ports, *, since) -> list[UserPair(user, dst_key, port, proto, first_seen)]` 讀 `user_baseline` 首見 ≥ since 的列。該表只有帶使用者的連線，在 lab 上不到全部的 10%，全表掃描可接受，docstring 寫明。
- **`services/flowsource.py` 新增**（只讀店內，不向 PCE 補缺口；裁定：店外的部分照 coverage 揭露）：
  ```python
  class AggRow(BaseModel):
      keys: list[str | int | None]; display: list[str | None]; value: int; bytes_known: int | None
  class FieldCoverage(BaseModel):
      total: int; initiator_process: int; initiator_user: int; service_process: int; service_user: int; bytes: int
  class FlowAggregate(BaseModel):
      rows: list[AggRow]; coverage: Coverage; field_coverage: FieldCoverage; limit_hit: bool
  def aggregate_flows(ctx, seg: FlowSegment, *, now: datetime | None = None) -> FlowAggregate
  ```
  - `field_coverage` 用同一個 WHERE 一次 COUNT 算出。
  - 註冊 SQL 函式、`require_same_pce`、`StaleGeneration` 的處理，比照 `query_flows`。
- **F7**：`_live_rows` 改成先用 `ix_flows_tuple` 讀出補到的紀錄所屬組合的已存紀錄，跟補到的一起 `merge_sightings`／`group_pairs`。
  - 只有在連線**全部**的紀錄都已存在時才丟給店內；含有補到紀錄的連線照樣回傳，並帶上已存那一半的屬性。
- **`services/eventsource.py` 新增** `aggregate_events(ctx, seg: EventSegment, *, now=None) -> EventAggregate(rows: list[AggRow], coverage: Coverage, limit_hit: bool)`：
  - event_host 經 `workloads.ven_href = events.created_by_href` 取主機名稱，取不到就用 `created_by_name`；
  - actor 取 `created_by_name`。
- **`services/analysis/segments.py`**：
  ```python
  class SegmentResult(BaseModel):
      view: SegmentView
      detail: list[FlowRow] | list[EventRow] | None = None
      ranking: list[AggRow] | None = None
      predicted: Any = None                 # Task 9 填入 PredictedBlock
      coverage: Coverage
      field_coverage: FieldCoverage | None
      limit_hit: bool
      observed_from: datetime; observed_to: datetime
      latency_seconds: int | None           # 現在 − 流量收集水位；事件段落用事件水位
  def run_segment(ctx, seg: FlowSegment | EventSegment, *, now=None) -> SegmentResult
  ```
  - 畫面與報表都經由這一個入口，這樣同一份定義算出同一個數字。
  - predicted_block 在 Task 9 接上；在那之前 raise `NotImplementedError("P3-T9")`，並有測試釘住。

- [ ] **Step 1：寫失敗測試**：
  - domain：`test_ranking_requires_group_by`、`test_more_than_two_levels_rejected`、`test_label_dimension_requires_key`、`test_event_dimension_on_flow_segment_rejected`、`test_compiled_sql_params_order`、`test_lateral_default_segments_keys_and_shapes`。
  - 新組合：`test_new_user_pairs_since`。
  - FlowSource 聚合：`test_ranking_two_levels_src_then_user`、`test_label_dimension_groups_by_key_value`、`test_metric_distinct_dst`、`test_bytes_metric_reports_coverage`、`test_windows_user_grouped_case_insensitive`、`test_aggregate_total_equals_detail_count`（同一 filter 以 decision 分組加總 = `query_flows` 的列數）、`test_events_only_mode_reports_collection_off`、`test_gap_listed_in_aggregate_coverage`。
  - EventSource 聚合：`test_event_ranking_by_type_and_host`。
  - F7：`test_fill_keeps_connection_whose_partner_is_stored`。
  - 入口：`test_run_segment_dispatches_detail_and_ranking`、`test_predicted_block_view_not_yet_wired`。
- [ ] **Step 2：跑** `timeout 600 .venv/bin/python -m pytest tests_v6/domain/test_segment.py tests_v6/domain/test_filter.py tests_v6/services/test_flowsource.py tests_v6/services/test_flowsource_aggregate.py tests_v6/services/test_eventsource_aggregate.py tests_v6/services/analysis -q` → FAIL
- [ ] **Step 3：實作。**
- [ ] **Step 4：PASS；閘門（含 `test_single_reader.py`）。**
- [ ] **Step 5：Commit** `git add illumio_ops/domain/segment.py illumio_ops/domain/filter.py illumio_ops/services/flowsource.py illumio_ops/services/eventsource.py illumio_ops/services/analysis tests_v6/domain tests_v6/services && git commit -m "feat(v6): analysis segments with store aggregation, and keep half-stored filled connections (F7)"`

---

### Task 4：橫向移動的共用脈絡（管理 port、重要資產、管理群組、主機索引）

**Files:**
- Create: `illumio_ops/domain/lateral.py`、`illumio_ops/services/analysis/context.py`、`tests_v6/domain/test_lateral.py`、`tests_v6/services/analysis/test_context.py`
- Modify: `illumio_ops/store/flowdb/workloads.py`、`illumio_ops/store/flowdb/ransomware.py`、`illumio_ops/store/flowdb/labels.py`、`tests_v6/gates/test_settings_readers.py`

**Interfaces:**
- **`domain/lateral.py`**：
  ```python
  @dataclass(frozen=True)
  class AdminPort:
      port: int; proto: int | None; name: str | None
      source: Literal["builtin", "pce", "added"]
  @dataclass(frozen=True)
  class AdminPortSet:
      entries: tuple[AdminPort, ...]
      def matches(self, port: int | None, proto: int) -> bool
      def port_filters(self) -> tuple[PortProto, ...]        # 給 FilterSpec.ports
  def effective_admin_ports(builtin: Sequence[tuple[int, str]], pce_admin: Sequence[tuple[int, int, str]],
                            extra: Sequence[tuple[int, int | None]], removed: Sequence[tuple[int, int | None]],
                            include_pce: bool) -> AdminPortSet
  @dataclass(frozen=True)
  class HostInfo:
      key: str; href: str | None; hostname: str | None; managed: bool
      labels: Mapping[str, str]; enforcement_mode: str | None; visibility_level: str | None
      os_id: str | None; ven_href: str | None; critical: bool; admin_group: bool
  Selector = tuple[str, str]   # (key, value)
  def selector_matches(labels: Mapping[str, str], selectors: Sequence[Selector]) -> bool   # 聯集
  def stale_selectors(selectors: Sequence[Selector], known: Collection[Selector]) -> list[Selector]
  ```
  - 移除清單的比對：proto 為 None 的移除項，會移除該 port 的所有協定。
  - 加入項的 `name` 是 None。
- **store 讀取函式**（各模組既有擁有者，只讀）：
  - `workloads.all_workloads(conn) -> list[WorkloadRow]`
  - `ransomware.admin_services(conn) -> list[tuple[int, int, str]]`：`category='admin'` 的不重複 `(port, proto, name)`
  - `labels.label_sets(conn, ids: Collection[int] | None = None) -> dict[int, dict[str, str]]`
  - `labels.known_labels(conn) -> set[tuple[str, str]]`
- **`services/analysis/context.py`**：
  ```python
  @dataclass(frozen=True)
  class LateralContext:
      settings: LateralSettings; admin_ports: AdminPortSet; hosts: Mapping[str, HostInfo]   # 鍵 = endpoint_key(href)
      label_sets: Mapping[int, Mapping[str, str]]; collected: bool
      baseline_days: float; baseline_required: int
      stale: tuple[tuple[Literal["critical_assets", "admin_groups"], str, str], ...]
      traffic_watermark: datetime | None; generation: int
  def load_lateral_context(ctx, *, now: datetime) -> LateralContext
  def host_for(lc: LateralContext, key: str, *, ip: str, hostname: str | None) -> HostInfo   # 非受管端點給一個 managed=False、不在任何群組的 HostInfo
  ```
  - `baseline_days` = now − `ingest_coverage`（TRAFFIC）最早的 `range_start`，以天計、上限 `baseline_days` 設定。沒有涵蓋時為 0。
  - `collected` = 收集已開啟且 `collects(settings, TRAFFIC)`。
  - `generation` 在讀設定之前記下，比照 `FlowDb.generation` 的用法。
- 讀者登錄：Task 1 標 `"P3-T4"` 的設定葉，改指向 `illumio_ops.services.analysis.context`。

- [ ] **Step 1：失敗測試**：
  - domain：`test_effective_ports_union_and_removal`、`test_pce_admin_services_toggle`、`test_any_protocol_entry_matches_both`、`test_removed_without_proto_removes_all_protocols`、`test_selector_union_semantics`、`test_stale_selector_detected`。
  - service：`test_host_index_marks_critical_and_admin`、`test_context_events_only_mode_not_collected`、`test_baseline_days_from_traffic_coverage`。
- [ ] **Step 2：** `timeout 300 .venv/bin/python -m pytest tests_v6/domain/test_lateral.py tests_v6/services/analysis/test_context.py tests_v6/store tests_v6/gates -q` → FAIL
- [ ] **Step 3：實作。**
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/domain/lateral.py illumio_ops/services/analysis/context.py illumio_ops/store/flowdb tests_v6/domain/test_lateral.py tests_v6/services/analysis/test_context.py tests_v6/gates/test_settings_readers.py && git commit -m "feat(v6): shared lateral context with admin ports, critical assets and admin groups"`

---

### Task 5：暴露面圖與每小時分析工作

**Files:**
- Create: `illumio_ops/domain/exposure.py`、`illumio_ops/services/analysis/exposure.py`、`illumio_ops/services/analysis/hourly.py`、`tests_v6/domain/test_exposure.py`、`tests_v6/services/analysis/test_exposure.py`、`tests_v6/services/analysis/test_hourly.py`
- Modify: `illumio_ops/services/flowsource.py`、`illumio_ops/store/flowdb/ransomware.py`、`illumio_ops/jobs/scheduler.py`、`tests_v6/jobs/test_scheduler.py`、`tests_v6/gates/test_settings_readers.py`

**Interfaces:**
- **flowsource**：
  ```python
  @dataclass(frozen=True)
  class BaselineEdge:
      src_key: str; dst_key: str; port: int; proto: int
      first_seen: datetime; last_seen: datetime; decision: str | None
  class BaselineEdges(BaseModel):
      edges: list[BaselineEdge]; baseline_from: datetime | None; collected: bool
  def baseline_edges(ctx, ports: AdminPortSet, *, since: datetime, now=None) -> BaselineEdges
  ```
  - SQL 只用 `port IN (...)` 走 `ix_baseline_port`；協定與 `last_seen >= since` 在 Python 篩。
  - 不收集流量時 `collected=False`、`edges=[]`。
- **store**：`ransomware.unprotected_listening(conn) -> list[tuple[str, str, int, int, str | None]]`，回傳 `(workload_href, name, port, proto, severity)`。
- **`domain/exposure.py`**：
  ```python
  @dataclass(frozen=True)
  class EdgeIn:
      src: str; dst: str; port: int; proto: int; state: EdgeState
  def edge_state(decision: str | None) -> EdgeState | None
  # allowed → ALLOWED；potentially_blocked → POTENTIALLY_BLOCKED；
  # blocked（含 blocked_*）→ None，表示整條邊不進圖；其餘值與 None → UNKNOWN
  @dataclass(frozen=True)
  class Graph:
      nodes: tuple[str, ...]; index: Mapping[str, int]; out: tuple[tuple[int, ...], ...]
      edge_info: Mapping[tuple[int, int], tuple[frozenset[tuple[int, int]], EdgeState]]
  def build_graph(edges: Iterable[EdgeIn], *, enforced: bool) -> Graph
  # enforced 只留 ALLOWED；同一對主機的多個 port 合成一條邊，狀態取最強（allowed > potentially_blocked > unknown）
  def reach_counts(g: Graph, hops: int) -> list[int]
  def paths_to(g: Graph, target: str, hops: int) -> dict[str, tuple[str, ...]]
  # 反向 BFS；鄰居依節點名排序，所以路徑固定
  def articulation_points(g: Graph) -> frozenset[str]
  # 無向視角、迭代式 Tarjan，不用遞迴；5.x 的遞迴版在深圖上會中途放棄
  def cross_env(g: Graph, env_of: Mapping[str, str | None]) -> list[CrossEnvEdge]
  def suggest_cuts(g: Graph, target: str, hops: int, *, top: int = 3, max_candidates: int = 60) -> list[Cut]
  def collapse(g: Graph, group_of: Mapping[str, str | None]) -> GroupGraph
  def compute_exposure(edges: Sequence[EdgeIn], hosts: Mapping[str, HostInfo], footholds: Sequence[Foothold], *,
                       hops: int, critical: frozenset[str], env_of: Mapping[str, str | None],
                       max_assets: int = 50) -> ExposureResult
  ```
  - 結果型別（pydantic）：
    ```python
    class CrossEnvEdge(BaseModel):
        src: str; dst: str; src_env: str; dst_env: str
        ports: list[tuple[int, int]]; state: EdgeState
    class Foothold(BaseModel):
        host: str; name: str; port: int; proto: int; severity: str | None
    class GroupGraph(BaseModel):
        groups: list[str | None]                       # None = 沒有該 label
        edges: list[tuple[str | None, str | None, int, EdgeState]]   # (來源群組, 目的群組, 主機邊數, 最強狀態)
    class Cut(BaseModel):
        kind: Literal["edge", "node"]; src: str; dst: str | None
        ports: list[tuple[int, int]]; before: int; after: int
    ```
  - `reach_counts`（位元集合 DP，取代逐點 BFS）：
    ```
    R1[v] = 鄰居位元集合
    R_{i+1}[v] = R_i[v] | OR_{u∈out(v)} R_i[u]，做 hops 次
    每點的可觸及數 = popcount(R_hops[v] 去掉自己)
    ```
  - `suggest_cuts`（貪婪單切）：
    1. 候選 = 所有 `paths_to(target)` 路徑上的邊與中間節點，依出現次數取前 `max_candidates`。
    2. 對每個候選，移除後重算 `len(paths_to(target))`。
    3. 依減少量排序取前 `top`，同分時取 ports 較少的邊。
    4. `Cut` 包含 `kind: Literal["edge","node"]`、`src`、`dst | None`、`ports`、`before`、`after`。
  - `ExposureResult`（pydantic，用來 JSON 往返）：
    - 參數：`computed_at`、`observation_from`、`observation_to`、`hops`。
    - 規模：`nodes`、`edges_now`、`edges_enforced`、`unknown_edges`。
    - `hosts`：`list[HostExposure(key, reach_now, reach_enforced, pivot_now, pivot_enforced)]`，依 `reach_now` 排序。
    - `assets`：`list[AssetExposure(key, sources_now, sources_enforced, paths: list[list[str]]（最多 5 條）, cuts: list[Cut])]`。
    - `cross_env`、`footholds`、`limits_hit: list[str]`。
  - 超過 `max_assets` 的資產只列數字、不算路徑與切點，並在 `limits_hit` 記 `"assets"`。
- **`services/analysis/exposure.py`**：`def run_exposure(ctx, *, now: datetime) -> ExposureResult | None`
  - 圖用 `baseline_edges(since = now − observation_days)` 建，再疊上 `unprotected_listening` 的落腳點。
  - 結果寫入 `analysis_results('exposure')`；今日的 `lateral_snapshot_daily` 寫入 metrics：`nodes`、`edges_now`、`edges_enforced`、`unknown_edges`、`pivots_now`、`assets_reachable_now`、`assets_reachable_enforced`、`cross_env_edges`、`max_reach_now`。同一天後面的執行會覆蓋。
  - 不收集流量時寫 `analysis_runs('exposure')` 狀態 `collection_off` 並回 None。
  - 換 PCE（`StaleGeneration`）時不寫。
- **`services/analysis/hourly.py`**：
  ```python
  HourlyStep = Callable[[AppContext, datetime], None]
  HOURLY_STEPS: list[tuple[str, HourlyStep]]           # 本任務註冊 ("exposure", ...)；Task 11–13 依序附加
  def run_hourly_analysis(ctx, *, now: datetime | None = None) -> dict[str, str]
  # 回傳每步的 "ok" 或錯誤摘要
  ```
  - 單步失敗時記進 `analysis_runs(step)`，其他步照跑。
  - `StaleGeneration` 會停掉整輪。
- **scheduler**：新增 job `analysis_hourly`，間隔固定 3600 秒，`coalesce=True`、`max_instances=1`，經 `instrument` 記錄健康狀態。間隔是常數不是設定，理由是 spec §5 說每輪收集後或定時重算。
- 讀者登錄：`graph_hops`、`observation_days` 指向 `illumio_ops.services.analysis.exposure`。

- [ ] **Step 1：失敗測試**：
  - 圖與可觸及：
    - `test_reach_counts_match_bfs_on_random_graphs`：200 張隨機圖，與逐點 BFS 的結果一致。
    - `test_enforced_graph_keeps_only_allowed`、`test_unknown_edges_in_now_marked`、`test_blocked_edges_excluded`。
    - `test_articulation_points_on_deep_chain`：10,000 個節點的鏈，不得出現 RecursionError、結果正確。
    - `test_paths_shortest_and_deterministic`、`test_cross_env_requires_both_envs`、`test_collapse_by_label`。
  - 切點：`test_cut_suggestion_reduces_reach`，在 fixture 圖上切一條邊，可觸及的來源數從 7 降到 2，比照 spec 的寫法。
  - 上限與效能：
    - `test_assets_beyond_limit_listed_without_paths`
    - `test_compute_exposure_performance`：2,000 個節點、60,000 條邊、hops 3、20 個重要資產，120 秒內完成。超時算失敗、不跳過。
  - service：`test_exposure_respects_observation_days`、`test_events_only_mode_stores_collection_off`、`test_footholds_from_unprotected_listening`、`test_snapshot_written_for_today`、`test_hourly_step_failure_does_not_stop_others`、`test_stale_generation_drops_exposure`、`test_scheduler_registers_analysis_hourly`。
- [ ] **Step 2：** `timeout 900 .venv/bin/python -m pytest tests_v6/domain/test_exposure.py tests_v6/services/analysis tests_v6/jobs/test_scheduler.py -q` → FAIL
- [ ] **Step 3：實作。**
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/domain/exposure.py illumio_ops/services/analysis illumio_ops/services/flowsource.py illumio_ops/store/flowdb/ransomware.py illumio_ops/jobs/scheduler.py tests_v6/domain/test_exposure.py tests_v6/services/analysis tests_v6/jobs/test_scheduler.py tests_v6/gates/test_settings_readers.py && git commit -m "feat(v6): lateral exposure graph from the connection baseline, recomputed hourly"`

---

### Task 6：deny rule 試算（唯讀）

**Files:** Create `illumio_ops/domain/deny.py`、`illumio_ops/services/analysis/deny_sim.py`、`tests_v6/domain/test_deny.py`、`tests_v6/services/analysis/test_deny_sim.py`

**Interfaces:**
- **`domain/deny.py`**：
  ```python
  class DenyProposal(_Model):
      src: EndpointFilter; dst: EndpointFilter
      ports: tuple[PortProto, ...] = ()            # 空 = 所有服務
  def proposal_filter(p: DenyProposal, *, start: datetime, end: datetime) -> FilterSpec
  # 只取非 blocked 的決定：已被擋的連線不算「會被擋」
  def edge_matches(p: DenyProposal, src: HostInfo, dst: HostInfo, *, src_ip: str, dst_ip: str, port: int, proto: int) -> bool
  def apply_deny(edges: Sequence[EdgeIn], p: DenyProposal, hosts: Callable[[str], HostInfo]) -> list[EdgeIn]
  def cut_to_proposal(cut: Cut, hosts: Mapping[str, HostInfo]) -> DenyProposal
  # 用主機 href；非受管端點用 IP
  ```
- **`services/analysis/deny_sim.py`**：
  ```python
  class AssetReachChange(BaseModel):
      asset: str; before: int; after: int
  class DenySimulation(BaseModel):
      window: tuple[datetime, datetime]; blocked_connections: int; blocked_flows: int
      sources: list[AggRow]; destinations: list[AggRow]           # 各取前 50
      sample: list[FlowRow]; limit_hit: bool
      reach_change: list[AssetReachChange]
      coverage: Coverage; field_coverage: FieldCoverage
  def simulate_deny(ctx, proposal: DenyProposal, *, now=None, sample: int = 200) -> DenySimulation
  ```
  - 觀察期 = `observation_days`；用 `aggregate_flows` 與 `query_flows` 讀店內，對重要資產的可觸及數用基準期邊重算。
  - 絕不呼叫 PCE。

- [ ] **Step 1：失敗測試**：`test_simulation_counts_blocked_connections_and_sources`、`test_already_blocked_flows_not_counted`、`test_label_proposal_matches_by_host_labels`、`test_all_services_proposal`、`test_reach_change_for_critical_asset`、`test_cut_converts_to_proposal_and_reduces_reach`、`test_simulation_never_calls_pce`（fake PCE 收到任何請求即失敗）。
- [ ] **Step 2：** `timeout 300 .venv/bin/python -m pytest tests_v6/domain/test_deny.py tests_v6/services/analysis/test_deny_sim.py -q` → FAIL
- [ ] **Step 3：實作。**
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/domain/deny.py illumio_ops/services/analysis/deny_sim.py tests_v6/domain/test_deny.py tests_v6/services/analysis/test_deny_sim.py && git commit -m "feat(v6): read-only deny rule simulation against collected traffic"`

---

### Task 7：偵測管線、扇出與新的管理連線

**Files:**
- Create: `illumio_ops/domain/detectors.py`、`illumio_ops/services/analysis/detect.py`、`tests_v6/domain/test_detectors.py`、`tests_v6/services/analysis/test_detect.py`、`tests_v6/fixtures/pce/lateral_obs.json`
- Modify: `illumio_ops/services/flowsource.py`、`illumio_ops/services/collect/reread.py`、`illumio_ops/jobs/scheduler.py`、`tests_v6/jobs/test_scheduler.py`、`tests_v6/gates/test_settings_readers.py`

**Interfaces:**
- **`domain/detectors.py`**：
  ```python
  @dataclass(frozen=True)
  class Obs:
      src_key: str; dst_key: str; src_href: str | None; dst_href: str | None; src_ip: str; dst_ip: str
      src_hostname: str | None; dst_hostname: str | None; port: int | None; proto: int; decision: str
      first: datetime; last: datetime; num_connections: int
      initiator_user: str | None; initiator_process: str | None
      src_labels: Mapping[str, str]; dst_labels: Mapping[str, str]; src_managed: bool; origin: str
  @dataclass(frozen=True)
  class DetectionConfidence:
      field: str | None; covered: int | None; total: int | None; baseline_days: float | None
      incomplete_gaps: tuple[tuple[datetime, datetime, str], ...]
  @dataclass(frozen=True)
  class Detection:
      detector: DetectorKind; fingerprint: str; subject_key: str; severity: Severity
      first_seen: datetime; last_seen: datetime; critical_asset: bool
      summary: Mapping[str, Any]          # 訊息參數：targets（總數）、sample_targets（最多 10 個主機名稱）、ports、precursors…
      segment: FlowSegment                # 重現證據的分析段落：detail 視角、時間窗 = 證據期間
      confidence: DetectionConfidence
  @dataclass(frozen=True)
  class DetectorStatus:
      detector: DetectorKind; state: DetectorState; reason_key: str | None; params: Mapping[str, Any]
  @dataclass(frozen=True)
  class Precursor:                        # Task 8 由 EventSource 產生；本任務先傳空序列
      host_key: str; kind: PrecursorKind; at: datetime; signal: bool
  @dataclass(frozen=True)
  class DetectorConfig:                   # DetectorSettings 等設定的領域鏡像，由服務層轉換
      fanout_targets: int; fanout_window: timedelta
      account_fanout_targets: int; account_fanout_window: timedelta
      chain_window: timedelta; blocked_targets: int; blocked_window: timedelta; blocked_surge_factor: float
      exclude_system_accounts: bool; precursor_window: timedelta
      expected: Mapping[tuple[int, int | None], frozenset[str]]
      admin_ports: AdminPortSet; environment_label_key: str; admin_groups_configured: bool
  @dataclass(frozen=True)
  class DetectorInput:
      window: tuple[datetime, datetime]; obs: Sequence[Obs]; blocked_obs: Sequence[Obs]
      hosts: Callable[[str, str, str | None], HostInfo]
      baseline_first_seen: Mapping[tuple[str, str, int, int], datetime]
      precursors: Sequence[Precursor]; config: DetectorConfig
      baseline_days: float; baseline_required: int; gaps: tuple[tuple[datetime, datetime, str], ...]
  DETECTORS: dict[DetectorKind, Callable[[DetectorInput], tuple[list[Detection], DetectorStatus]]]
  def run_detectors(inp: DetectorInput) -> tuple[list[Detection], list[DetectorStatus]]
  DEDUP: dict[DetectorKind, Callable[[DetectorConfig], timedelta]]
  ```
  - `DEDUP` 各偵測器的去重視窗：

    | 偵測器 | 視窗 |
    |---|---|
    | 扇出 | `fanout_window` |
    | 新的管理連線 | 30 天 |
    | 跳板鏈、非管理群組、跨環境、非預期 process | 24 小時 |
    | 帳號扇出 | `account_fanout_window` |
    | 大量被擋 | `blocked_window` |

- **評估集合**：`origin == "ingest"` 且 `last ∈ (lo, hi]` 的 obs。回顧用的 obs（`last ∈ [lo − 回顧, hi]`）可以含回填列。
- **本任務的偵測器**：
  - **扇出**：
    1. 每個 src 的非 blocked 管理 port obs，依 `last` 排序，做滑動視窗。
    2. 只考慮結尾落在 `(lo, hi]` 的視窗，視窗長度 `fanout_window`，計算不重複 `dst_key`；≥ `fanout_targets` 就成立。
    3. 嚴重度：目標中有 allowed 邊為 high，否則 medium（比照 5.x B006）。目標含重要資產再升一級。
    4. fingerprint 是 `fanout|<src_key>`；summary 帶目標數、最多 10 個樣本、port 清單。
  - **新的管理連線**：
    1. 評估集合中管理 port 的組合 `(src_key, dst_key, port|-1, proto)`，其基準期首見落在 `(lo, hi]`。
    2. 每個組合一筆，fingerprint 是 `new|<src>|<dst>|<port>|<proto>`。
    3. 嚴重度 medium；目的是重要資產為 high。
    4. 冷啟動：`baseline_days < baseline_required` 時不產生偵測，狀態 `accumulating`，參數帶 `days`（四捨五入到 0.1 天）。
  - 其餘六個偵測器在 Task 7 先註冊成回 `DetectorStatus(state=disabled, reason_key="detector_pending")`，Task 8 取代。
- **flowsource 新增**：
  ```python
  class Observations(BaseModel):
      rows: list[Obs]; coverage: Coverage                  # Obs 是 dataclass，model_config arbitrary_types_allowed
  def observations(ctx, spec: FilterSpec, *, now=None) -> Observations   # 只讀店內主列，不設筆數上限：呼叫端以時間窗與 port 限定範圍
  def baseline_first_seen(ctx, tuples: Collection[tuple[str, str, int, int]]) -> dict[tuple[str, str, int, int], datetime]
  # 依主鍵每 500 筆一批查
  ```
- **`services/analysis/detect.py`**：
  ```python
  class DetectionRun(BaseModel):
      window: tuple[datetime, datetime] | None; new: int; updated: int; statuses: list[dict[str, Any]]
      gaps: list[tuple[datetime, datetime, str]]; late: bool
  def run_detection(ctx, *, now=None, window: tuple[datetime, datetime] | None = None, late: bool = False) -> DetectionRun
  ```
  - **視窗**：
    - 預設 `hi` = 流量的 `ingest_state.watermark`，`lo` = 上次偵測水位 − `traffic.OVERLAP`（30 分鐘）。
    - 第一次執行時 `lo = hi − fanout_window`。
    - `hi <= 上次水位` 時什麼都不做，回傳 `window=None`。
  - **讀取**：
    - 管理 port 的 obs，範圍 `[lo − max(各偵測器回顧), hi]`；
    - 大量被擋要的 blocked obs，所有 port，範圍 `[lo − blocked_window, hi]`。
  - **寫入**：在 `fdb.writing(gen)` 內 `upsert_detections`，成功後才把偵測水位設成 `hi`，並寫入 `analysis_runs('detect')` 的狀態。
  - **其他規則**：
    - 換 PCE 時回傳 `new=0` 的空結果（比照 `drops_stale`）。
    - 不收集流量時，全部狀態為 `collection_off`，只寫 run 狀態。
    - 視窗內有缺口時，每個狀態加 `incomplete`，並在 `gaps` 列出。
- **scheduler**：
  - 流量 job：`run_traffic_cycle(ctx)` 之後呼叫 `run_detection(ctx)`。
  - 回填 job：`ensure_daily_reread(ctx)` 回傳 `rows > 0` 時，呼叫 `run_detection(ctx, window=(該日 00:00Z, 次日 00:00Z), late=True)`。
  - `reread.py` 新增 `def last_reread_day(ctx) -> date | None`，讀 BACKFILL 的 `progress["reread"]["day"]`。
- **fixture `lateral_obs.json`**：
  - 在 .106 以唯讀連線從 v6 流量庫匯出 lab 管理 port 主列，欄位同 `Obs`、不含 `raw_json`。
  - 去識別：
    - href → `/orgs/1/workloads/w-NN`；IP → `10.0.<a>.<b>`，同一來源對應同一值；
    - 主機名稱 → `host-NN`；使用者 → `user-NN`，保留 `\` 前的網域形狀 `DOM-NN\user-NN`；
    - process 名稱保留，它們是產品的可執行檔名；label 值 → `<key>-NN`。
  - 匯出腳本放 `tmp/v6-p3-verification/record_obs.py`（gitignored），沿用 Task 0 量測腳本的唯讀連線方式 `file:...?mode=ro`。
  - 寫進 fixture 前，用 `grep -E 'lab\.local|192\.168\.|172\.16\.'` 確認沒有東西漏網。
- 讀者登錄：`detectors.fanout_*` 指向 `illumio_ops.services.analysis.detect`。

- [ ] **Step 1：失敗測試**：
  - 扇出：`test_fanout_fires_at_threshold_within_window`、`test_fanout_ignores_targets_outside_window`、`test_fanout_blocked_targets_not_counted`、`test_fanout_counts_unknown_decision`、`test_fanout_severity_high_with_allowed_medium_otherwise`、`test_fanout_critical_target_raises_severity`。
  - 新的管理連線：`test_new_admin_tuple_first_seen_in_window`、`test_new_admin_accumulating_before_baseline_full`。
  - 共通：`test_backfill_origin_not_evaluated`、`test_lab_fixture_fanout_is_rare`（fixture 上以預設值，34 天的扇出偵測 ≤ 5 筆，而且都來自同一個來源）。
  - service：`test_detection_watermark_advances_only_after_write`、`test_overlap_reevaluation_does_not_duplicate`、`test_late_reread_pass_marks_late`、`test_events_only_mode_collection_off`、`test_gap_in_window_marks_incomplete`、`test_pce_switch_during_run_writes_nothing`。
  - 排程：`test_traffic_job_runs_detection_after_cycle`、`test_reread_with_rows_triggers_late_detection`。
- [ ] **Step 2：** `timeout 600 .venv/bin/python -m pytest tests_v6/domain/test_detectors.py tests_v6/services/analysis/test_detect.py tests_v6/services/collect/test_reread.py tests_v6/jobs/test_scheduler.py -q` → FAIL
- [ ] **Step 3：實作。**
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/domain/detectors.py illumio_ops/services/analysis/detect.py illumio_ops/services/flowsource.py illumio_ops/services/collect/reread.py illumio_ops/jobs/scheduler.py tests_v6/domain/test_detectors.py tests_v6/services/analysis/test_detect.py tests_v6/fixtures/pce/lateral_obs.json tests_v6/jobs/test_scheduler.py tests_v6/gates/test_settings_readers.py && git commit -m "feat(v6): detection pipeline after each traffic cycle with fan-out and new admin connections"`

---

### Task 8：其餘六個偵測器與前兆加權

**Files:** Modify `illumio_ops/domain/detectors.py`、`illumio_ops/domain/events.py`、`illumio_ops/services/eventsource.py`、`illumio_ops/services/analysis/detect.py`、`tests_v6/domain/test_detectors.py`、`tests_v6/domain/test_events.py`、`tests_v6/services/analysis/test_detect.py`、`tests_v6/gates/test_settings_readers.py`

**Interfaces:**
- **`domain/events.py`**：
  ```python
  @dataclass(frozen=True)
  class EventHosts:
      ven_hrefs: frozenset[str]; workload_hrefs: frozenset[str]; hostnames: frozenset[str]
  def event_hosts(raw: Mapping[str, Any]) -> EventHosts
  PRECURSOR_EVENT_TYPES: Mapping[str, PrecursorKind] = {
      "agent.tampering": TAMPER, "agent.suspend": SUSPEND, "system_task.agent_offline_check": OFFLINE}
  ```
  - `Precursor` 沿用 Task 7 在 `domain/detectors.py` 定義的型別，不在這裡重複定義。
  - `event_hosts` 涵蓋三種形狀：`created_by.ven`、`created_by.agent` 的 href 與 hostname，以及 `resource_changes[].resource.workload` 的 href 與 hostname。
  - offline 只認 `changes.online.before == true` 且 `after == false` 的那台。
- **`services/eventsource.py`**：`def precursor_events(ctx, *, start: datetime, end: datetime) -> PrecursorEvents(items: list[Precursor], unmatched: int)`
  - VEN href 經 `workloads.ven_href` 對到主機。
  - 對不到時，若主機名稱在 workloads 中唯一，就用主機名稱比對，處理重新配對的 VEN。
  - 仍對不到的計入 `unmatched`。
- **偵測器**（取代 Task 7 的佔位）：
  - **跳板鏈**：
    - 條件：存在非 blocked 的管理 port 邊 A→B 與 B→C，C ≠ A，而且 `BC.last >= AB.first` 且 `BC.first <= AB.last + chain_window`。即「時間上接得起來」：允許兩段落在同一個回報桶，但 B→C 不能整段發生在 A→B 開始之前。
    - 至少一段在評估集合內才算。
    - fingerprint 是 `chain|A|B|C`；嚴重度 medium，C 是重要資產為 high。
    - 每個 B 最多記 20 條鏈，summary 帶總數。
    - 文字鍵使用「時間上接得起來」的措辭。
  - **大量被擋**：
    - 每個 src 在 `blocked_window` 內被擋的不重複目的數 ≥ `blocked_targets`，而且 ≥ `blocked_surge_factor ×` 該 src 前 7 天同長度視窗的最大值。前 7 天沒有被擋紀錄時只看門檻。
    - 服務層只對超過門檻的 src 讀前 7 天的 blocked obs。
    - fingerprint 是 `blocked|<src>`；嚴重度 medium。
  - **非管理群組用管理協定**：
    - 未設定管理群組時狀態 `disabled`、`reason_key="admin_groups_unset"`。
    - 否則，不在管理群組（含非受管來源）的非 blocked 管理 port obs，每個組合一筆，fingerprint 是 `nag|<src>|<dst>|<port>|<proto>`。
    - 嚴重度 medium，目的是重要資產為 high。
  - **跨環境管理 port**：
    - 兩端的 `environment_label_key` 都有值且不同，決定為 allowed、potentially_blocked 或 unknown。
    - 每個組合一筆，fingerprint 是 `xenv|…`；allowed 為 high（5.x L010 是 CRITICAL，這裡留一級給前兆加權），其餘 medium。
    - 店內沒有任何該 key 的 label 時狀態 `no_data`。
  - **帳號扇出**：
    - 依正規化後的 `initiator_user` 分組（Task 3 的使用者規則）；`exclude_system_accounts` 為 true 時用 `is_system_account` 排除系統帳號。
    - `account_fanout_window` 內不重複目的數 ≥ 門檻即成立；fingerprint 是 `acct|<user>`；嚴重度 high。
    - 評估集合裡沒有任何帶使用者的 obs 時狀態 `no_data`，參數帶覆蓋率。
    - 每筆偵測的 confidence 帶 `field="initiator_user"` 與覆蓋數。
  - **非預期的發起 process**：
    - 只評估 `expected_initiators` 列出的 port／proto，而且 obs 要有 `initiator_process`。
    - 不在清單內就成立；fingerprint 是 `proc|<src>|<process>|<port>|<proto>`；嚴重度 medium，目的是重要資產為 high。
    - 沒有 process 的 obs 是「不可評估」，計入狀態的 `not_evaluable`，不得當成非預期。
- **前兆**：`def apply_precursors(dets: Sequence[Detection], precursors: Sequence[Precursor], *, hours: int) -> list[Detection]`
  - 偵測主體主機在 `first_seen − hours` 到 `last_seen` 之間有前兆時，嚴重度升一級，summary 加 `precursors=[{kind, at, signal}]`。
  - 只對以主機為主體的偵測生效；帳號扇出不升。
- 讀者登錄：其餘 `detectors.*` 與 `expected_initiators` 指向 `illumio_ops.services.analysis.detect`。

- [ ] **Step 1：失敗測試**：
  - 跳板鏈：`test_chain_same_bucket_counts`、`test_chain_second_leg_before_first_rejected`、`test_chain_excludes_return_to_origin`、`test_chain_needs_a_leg_in_window`。
  - 大量被擋：`test_blocked_surge_needs_factor_over_history`、`test_blocked_surge_threshold_without_history`。
  - 非管理群組：`test_non_admin_group_disabled_without_groups`、`test_non_admin_group_flags_unmanaged_source`。
  - 跨環境：`test_cross_env_needs_both_env_labels`、`test_cross_env_allowed_is_high`、`test_cross_env_no_data_without_env_labels`、`test_cross_env_uses_configured_label_key`。
  - 帳號扇出：`test_account_fanout_excludes_system_accounts`、`test_account_fanout_no_data_when_no_users`、`test_account_fanout_confidence_has_coverage`。
  - 非預期 process：`test_unexpected_initiator_flags_powershell_smb`、`test_unexpected_initiator_unknown_process_not_evaluable`、`test_unexpected_initiator_unlisted_port_not_evaluated`、`test_lab_fixture_unexpected_initiators`（fixture 上 445 與 3389 的 powershell.exe 會被標出，135 的 lsass.exe 不會）。
  - 前兆與事件主機：`test_precursor_raises_one_level_and_lists_reason`、`test_event_hosts_three_shapes`、`test_offline_precursor_only_on_online_to_offline`、`test_repaired_ven_matched_by_unique_hostname`、`test_unmatched_precursor_counted`。
- [ ] **Step 2：** `timeout 600 .venv/bin/python -m pytest tests_v6/domain/test_detectors.py tests_v6/domain/test_events.py tests_v6/services/analysis/test_detect.py tests_v6/services/test_eventsource.py -q` → FAIL
- [ ] **Step 3：實作。**
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/domain illumio_ops/services/eventsource.py illumio_ops/services/analysis/detect.py tests_v6/domain tests_v6/services tests_v6/gates/test_settings_readers.py && git commit -m "feat(v6): pivot chain, blocked surge, admin-group, cross-environment, account and process detectors with precursors"`

---

### Task 9：政策物件與預計阻擋

**Files:**
- Create: `illumio_ops/pce/policy.py`、`illumio_ops/domain/policy.py`、`illumio_ops/services/analysis/predicted_block.py`、`tests_v6/pce/test_policy.py`、`tests_v6/domain/test_policy.py`、`tests_v6/services/analysis/test_predicted_block.py`、`tests_v6/fixtures/pce/rule_sets_draft.json`、`tests_v6/fixtures/pce/draft_rows.json`
- Modify: `illumio_ops/services/analysis/segments.py`、`illumio_ops/pce/capabilities.py`（`draft_recompute` 已登錄，確認偵測寫入）

**Interfaces:**
- **`pce/policy.py`**：`def fetch_rule_sets(client: PceClient, pversion: Literal["draft", "active"], *, deadline: float) -> list[dict[str, Any]]`
  - 用 `collections.get_all` 讀 `/sec_policy/{pversion}/rule_sets`。
  - 規則集物件沒有 `deny_rules` 鍵時，補 `GET {href}/deny_rules`，`org_scoped=False`。
- **`domain/policy.py`**：
  ```python
  @dataclass(frozen=True)
  class ActorRef:
      kind: Literal["label", "label_group", "ip_list", "workload", "all_workloads", "virtual_service", "other"]
      key: str | None; value: str | None; name: str | None; href: str | None
  @dataclass(frozen=True)
  class ServiceRef:
      port: int | None; to_port: int | None; proto: int | None; name: str | None; href: str | None
  @dataclass(frozen=True)
  class RuleRef:
      href: str; rule_type: RuleAction; enabled: bool; ruleset_name: str; ruleset_href: str
      description: str | None; consumers: tuple[ActorRef, ...]; providers: tuple[ActorRef, ...]
      services: tuple[ServiceRef, ...]
  def index_rules(rule_sets: Sequence[Mapping[str, Any]]) -> dict[str, RuleRef]
  @dataclass(frozen=True)
  class DraftView:
      draft_decision: str; deny_rule_hrefs: tuple[str, ...]; override_deny_hrefs: tuple[str, ...]
      allow_rule_hrefs: tuple[str, ...]; essential_service_rules: tuple[str, ...]
  def parse_draft(raw: Mapping[str, Any]) -> DraftView
  ```
  - `index_rules`：`sec_rules` 為 ALLOW；`deny_rules` 依 `override` 是否為 true 分成 OVERRIDE_DENY 或 DENY，同時接受 `rule_type` 欄位的寫法。
  - `parse_draft` 的欄位對應，依據 Task 0 實測：
    - `draft_policy_decision` 用 `parse_draft_policy_decision` 解析，未知值照原樣保留；
    - `enforcement_boundaries[].href`、`override_deny_rules[].href`；
    - `rules[]` 的元素：有 `href` 就是 allow rule，有 `essential_service_rule` 就放進該欄位的名稱。
- **`services/analysis/predicted_block.py`**：
  ```python
  class PredictedRow(BaseModel):
      flow: FlowRow; draft_decision: str; blocking_rules: list[str]; allow_rules: list[str]
      essential_service_rules: list[str]
  class PredictedBlock(BaseModel):
      rows: list[PredictedRow]; rules: dict[str, RuleRef]; capped: bool; limit_hit: bool
      computed_at: datetime; unsupported: bool; missing_rules: list[str]
  def predict_blocks(ctx, spec: FilterSpec, *, limit: int = 1000, max_results: int = 200_000,
                     deadline_seconds: int = 900) -> PredictedBlock
  ```
  - 用 `to_pce_payload` 加上 `run_traffic_query(compute_draft=True)`；下載的列先正規化成 `FlowRow`，再套用殘餘條件 `matches`。
  - 用 `fetch_rule_sets("draft")` 對應規則；hrefs 不在 draft 裡的列進 `missing_rules`，畫面會說「規則已不存在於 draft」。
  - `update_rules` 回 404 時，記錄能力 `draft_recompute` 為 unsupported，並回 `unsupported=True`。
  - 結果不存庫，因為它隨 draft 政策變動（spec §6.4）。
  - `run_segment` 的 predicted_block 視角接到這裡。
- **fixtures**（去識別，比照 P2 Task 3）：
  - `rule_sets_draft.json`：lab 的 draft 規則集，含 `tedt` 的 deny rule 與 Quarantine 的 override_deny，物件名稱保留，那是本人 lab 的測試物件。
  - `draft_rows.json`：20 列，含 blocked_by_boundary 帶 `enforcement_boundaries`、allowed 帶 `essential_service_rule`、potentially_blocked。

- [ ] **Step 1：失敗測試**：
  - 解析：`test_parse_draft_boundary_href`、`test_parse_draft_essential_service_rule`、`test_parse_draft_unknown_decision_passes_through`。
  - 規則集：`test_index_rules_allow_deny_override`、`test_ruleset_without_inline_deny_rules_fetches_them`。
  - 預計阻擋：`test_predict_blocks_maps_deny_rule_names`（fake PCE 依序回應：送出、輪詢、`update_rules`、輪詢、下載、規則集）、`test_update_rules_404_marks_unsupported`、`test_residual_filter_applied_to_rows`、`test_missing_rule_href_listed`、`test_predicted_block_segment_dispatch`。
- [ ] **Step 2：** `timeout 300 .venv/bin/python -m pytest tests_v6/pce/test_policy.py tests_v6/domain/test_policy.py tests_v6/services/analysis/test_predicted_block.py tests_v6/services/analysis/test_segments.py -q` → FAIL
- [ ] **Step 3：實作。**
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/pce/policy.py illumio_ops/domain/policy.py illumio_ops/services/analysis tests_v6/pce/test_policy.py tests_v6/domain/test_policy.py tests_v6/services/analysis tests_v6/fixtures/pce && git commit -m "feat(v6): predicted blocks from a draft recompute with the deny rules that block each flow"`

---

### Task 10：政策解釋（Rule Search）回收

**Files:** Create `illumio_ops/pce/rule_search.py`、`illumio_ops/services/analysis/explain.py`、`tests_v6/pce/test_rule_search.py`、`tests_v6/services/analysis/test_explain.py`、`tests_v6/fixtures/pce/rule_search/`。fixtures 從 `tests/fixtures/pce_rule_search/` 複製六個 JSON：`allow_hit`、`iplist_actor`、`k8s_actor`、`no_match`、`schema_error_destinations`、`swapped_miss`。

**來源：** 5.x `src/api/policy_explain.py`（`aa81f477`）與 `src/api_client.py` 的 `rule_search`。docstring 保留實測過的契約事實：consumers 是來源；providers 是目的；省略一側等於 any；active 與 draft 各自獨立。commit 訊息註明來源。

**Interfaces:**
- `pce/rule_search.py`：`def rule_search(client, *, consumers: list[dict] | None, providers: list[dict] | None, port: int, proto: int, pversion: Literal["active", "draft"], deadline: float) -> RuleSearchResult(status: int, body: Any, error: str | None)`
- `domain/policy.py` 新增 `def parse_rule_search(body: Any) -> list[RuleRef]`。
- `services/analysis/explain.py`：
  ```python
  @dataclass(frozen=True)
  class Endpoint:
      href: str | None; ip: str | None
  class PolicyExplanation(BaseModel):
      basis: Literal["active", "draft"]; source: Literal["pce", "none"]
      allow: list[RuleRef]; deny: list[RuleRef]; override_deny: list[RuleRef]
      pce_status: int | None; pce_error: str | None; unresolved: list[str]
  def explain_flow(ctx, src: Endpoint, dst: Endpoint, port: int, proto: int, *, basis="active") -> PolicyExplanation
  def explain_service(ctx, workload_href: str, port: int, proto: int, *, basis="active") -> PolicyExplanation
  ```
  - 端點解析：有 href 用 href；只有 IP 時比對 `/sec_policy/{basis}/ip_lists` 的範圍（5.x 邏輯），ip_list 在同一次呼叫內快取。
  - 兩端都解析不到時不送查詢，回 `source="none"`。
  - `explain_service` 只送 providers：任何來源都能到該服務的規則，就是勒索拆解要找的 allow rule。
  - 非 2xx 填 `pce_status`／`pce_error`，清單留空，不吞錯。

- [ ] **Step 1：失敗測試**：
  - 六個 fixture 的行為測試，從 5.x 移植，斷言內容照舊。
  - `test_neither_end_resolved_no_search`、`test_service_explain_sends_providers_only`、`test_pce_error_reported_not_empty`、`test_ip_resolved_to_ip_list`。
- [ ] **Step 2：** `timeout 300 .venv/bin/python -m pytest tests_v6/pce/test_rule_search.py tests_v6/services/analysis/test_explain.py -q` → FAIL
- [ ] **Step 3：實作。**
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/pce/rule_search.py illumio_ops/domain/policy.py illumio_ops/services/analysis/explain.py tests_v6/pce/test_rule_search.py tests_v6/services/analysis/test_explain.py tests_v6/fixtures/pce/rule_search && git commit -m "feat(v6): policy explanation through PCE rule search (recovered from 5.x policy_explain)"`

---

### Task 11：勒索防護拆解與流量疊加

**Files:**
- Create: `illumio_ops/domain/ransomware.py`、`illumio_ops/services/analysis/ransomware.py`、`tests_v6/domain/test_ransomware.py`、`tests_v6/services/analysis/test_ransomware.py`
- Modify: `illumio_ops/services/flowsource.py`、`illumio_ops/store/flowdb/ransomware.py`、`illumio_ops/services/analysis/hourly.py`

**Interfaces:**
- **`domain/ransomware.py`**：
  ```python
  SEVERITY_WEIGHT: Mapping[str, int] = {"critical": 40, "high": 30, "medium": 20, "low": 10}   # spec §6.6 F6
  def service_coverage(protection_state: str | None) -> float | None
  # protected_* → 1.0；unprotected → 0.0；其他與 None → None
  # 屬於近似：精確的逐服務覆蓋率 API 不提供，spec §6.5.6
  @dataclass(frozen=True)
  class ServiceContribution:
      name: str; port: int; proto: int; severity: str | None; category: str | None
      protection_state: str | None; port_status: str | None; active_policy: str | None
      weight: int | None; coverage: float | None; contribution: float | None
      traffic: RansomwareTrafficClass; recent_sources: int | None
  @dataclass(frozen=True)
  class HostBreakdown:
      href: str; hostname: str | None; enforcement_mode: str | None
      pce_percent: float | None; pce_exposure: str | None; computed_percent: float | None
      approximate: bool; contradiction: bool; services: tuple[ServiceContribution, ...]
  def host_breakdown(href, hostname, enforcement_mode, pce_percent, pce_exposure, services, traffic) -> HostBreakdown
  def classify_traffic(protection_state: str | None, port_status: str | None, recent_sources: int | None) -> RansomwareTrafficClass
  ```
  - `computed_percent` = Σ(weight × coverage) ÷ Σ weight × 100，只計 coverage 已知的服務。
  - `contradiction`：PCE 的值與計算值相差超過 5 個百分點。
  - PCE 值的刻度：`ransomware_protection_percent` 依名稱視為 0–100。Ruling：Task 16 用 PCE 主控台逐台核對，若其實是 0–1 就改這一處。
  - `classify_traffic` 的規則：
    - 未防護、listening、有近期來源 → PRIORITY（最優先：有人在用）；
    - 未防護、listening、沒有來源 → SAFE_TO_BLOCK（可直接封：零影響）；
    - 未防護、inactive、有來源 → SUSPICIOUS（服務沒在聽卻有連線嘗試）；
    - protected_* → PROTECTED；其他 → UNKNOWN。
- **flowsource**：`def service_traffic(ctx, targets: Collection[tuple[str, int, int]], *, since: datetime) -> dict[tuple[str, int, int], TrafficSummary(sources: int, last_seen: datetime | None, decisions: frozenset[str])]`
  - 讀 `connection_baseline`，走 `ix_baseline_port`，在 Python 篩 `dst_key`。
- **store**：`ransomware.services_by_host(conn) -> dict[str, list[sqlite3.Row]]`。
- **`services/analysis/ransomware.py`**：
  ```python
  def host_ransomware(ctx, href: str, *, now=None, explain_allows: bool = True) -> HostRansomware(breakdown: HostBreakdown, allow_rules: dict[str, list[RuleRef]])
  def ransomware_overlay(ctx, now: datetime) -> None     # 每小時步驟
  ```
  - `allow_rules` 只對 `active_policy` 為 `allowed` 或 `potentially_blocked` 的服務呼叫 `explain_service`。lab 的值都是 blocked_by_override_deny，所以不會呼叫。
  - 每小時步驟寫入 `analysis_results('ransomware')`：
    - 各主機的拆解，不含 allow rule；
    - priority、safe_to_block、suspicious 三個清單，依嚴重度權重與來源數排序，**不看 PCE 分數**；
    - `contradictions` 計數、能力狀態。
  - 能力 `ransomware_risk` 為 unsupported 時，結果寫 `{"unsupported": true}`，畫面會說此 PCE 版本不提供。
  - 疊加的流量期間：取 30 天與基準期保留天數中較小者。
  - `hourly.py` 附加步驟 `("ransomware", ransomware_overlay)`，排在 exposure 之後。

- [ ] **Step 1：失敗測試**：`test_weights_40_30_20_10`、`test_all_protected_vs_pce_zero_is_contradiction`（lab 的情形）、`test_contradiction_not_used_for_sorting`、`test_traffic_classes_five_cases`、`test_empty_recommendation_ok`、`test_unknown_protection_state_excluded_from_percent`、`test_unsupported_capability_reported`、`test_allow_attribution_only_for_allowed_services`、`test_overlay_written_by_hourly_step`。
- [ ] **Step 2：** `timeout 300 .venv/bin/python -m pytest tests_v6/domain/test_ransomware.py tests_v6/services/analysis -q` → FAIL
- [ ] **Step 3：實作。**
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/domain/ransomware.py illumio_ops/services/analysis illumio_ops/services/flowsource.py illumio_ops/store/flowdb/ransomware.py tests_v6/domain/test_ransomware.py tests_v6/services/analysis && git commit -m "feat(v6): ransomware protection breakdown with vendor-number contradictions and traffic overlay"`

---

### Task 12：竄改判讀、規律分類與已知原因

**Files:**
- Create: `illumio_ops/domain/tamper.py`、`illumio_ops/services/analysis/tamper.py`、`illumio_ops/store/migrations/0003_tamper_annotations.sql`、`illumio_ops/store/annotations.py`、`tests_v6/domain/test_tamper.py`、`tests_v6/services/analysis/test_tamper.py`、`tests_v6/fixtures/pce/tamper_60d.json`（從 `tmp/v6-p2-verification/p3-tamper_60d.json` 複製，Task 0 已去識別）
- Modify: `illumio_ops/store/ownership.py`、`illumio_ops/services/analysis/hourly.py`、`illumio_ops/i18n/` 兩個語系字典

**Interfaces:**
- **`domain/tamper.py`**：
  ```python
  @dataclass(frozen=True)
  class TamperReading:
      at: datetime; classification: str | None; process: str | None; pid: int | None
      actions: tuple[TamperAction | str, ...]; tamper_type: str | None; num_events: int | None
      revert_succeeded: bool | None; has_process_info: bool
  def interpret(raw: Mapping[str, Any]) -> list[TamperReading]
  @dataclass(frozen=True)
  class PatternResult:
      kind: TamperPattern; n: int; median_minutes: float | None; q1: float | None; q3: float | None
  def classify(times: Sequence[datetime]) -> PatternResult
  TIMELINE_EVENT_TYPES: tuple[str, ...]
  def timeline(events: Sequence[TimelineEvent], first_at: datetime, *, before=timedelta(hours=24), after=timedelta(hours=24)) -> list[TimelineEvent]
  @dataclass(frozen=True)
  class Command:
      platform: Literal["linux_nftables", "linux_iptables_legacy", "windows"]; purpose_key: str; text: str
  def guidance(os_id: str | None) -> tuple[Command, ...]
  @dataclass(frozen=True)
  class Annotation:
      id: int; host_href: str | None; pattern: TamperPattern | None; process: str | None; reason: str
  def explained_by(reading: TamperReading, host_href: str, pattern: TamperPattern, annotations: Sequence[Annotation]) -> int | None
  ```
  - **`interpret`**：
    - signal 型：每個 `info.events[]` 產生一筆；`kernel_functions` 每個元素以逗號拆開。
    - 對應：`nf_tables_newrule→add_rule`、`delrule→delete_rule`、`newchain→add_chain`、`delchain→delete_chain`、`newtable→add_table`、`deltable→delete_table`；`nfnetlink_rcv_batch` 略過；未知值照原字串保留。
    - confirmed 型：一筆，`has_process_info=False`；畫面據此說「這類事件不帶 process 資訊」。
  - **`classify`**，以 Task 0 的 lab 實測校準：
    ```
    n < 3                                    → too_few
    n >= 6 且 (q3 − q1) <= 0.25 × 中位間隔    → regular_cycle
    中位間隔 <= 2 分鐘                        → burst
    其他                                      → sporadic
    ```
  - **`TIMELINE_EVENT_TYPES`**：
    - 主機範圍：`workload.update`、`workloads.update`、`agent.request_policy`、`agent.upload_existing_ip_table_rules`、`agent.goodbye`、`agent.suspend`、`agent.unsuspend`、`workload.online`、`system_task.agent_offline_check`、`agent.update`。
    - 組織範圍：`sec_policy.create`、`firewall_settings.update`。
  - **`guidance`**：依 `os_id` 前綴分平台，`win-` 為 Windows，其他為 Linux 且兩種 Linux 都給。指令照抄，來源是 2026-10-02 dev 實測與 runbook：
    - nftables：
      - `nft -s list ruleset`
      - `nft monitor ruleset | while read -r l; do printf '%s %s\n' "$(date -Is)" "$l"; done`
      - `bpftrace -e 'kprobe:nf_tables_newrule { printf("%s pid=%d comm=%s\n", strftime("%H:%M:%S", nsecs), pid, comm); }'`
      - `ls -l /opt/illumio_ven_data/etc/firewall/workload/*/tampered/`
    - iptables-legacy：
      - `auditctl -a always,exit -F arch=b64 -S setsockopt -F a2=64 -k ilo_tamper`
      - `ausearch -k ilo_tamper -i`
    - Windows：platform.log 的位置先用 microseg-kb 查 Illumio 官方文件確認，查到才寫並附出處；查不到就不給這一項，在帳本記 Ruling。
  - **`explained_by`**：標註的非空欄位都相符時，回傳該標註 id。
- **app 庫遷移 0003**：
  - `tamper_annotations(id INTEGER PRIMARY KEY, pce_url TEXT NOT NULL, org_id TEXT NOT NULL, host_href TEXT, pattern TEXT, process TEXT, reason TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL)`。
  - 擁有者 `illumio_ops.store.annotations`；Task 2b 的遷移是 0002，所以這裡是 0003。
- **`services/analysis/tamper.py`**：
  ```python
  def host_tamper(ctx, href: str, *, now=None, days: int = 60) -> HostTamper(readings, pattern, timeline, guidance, annotations, explained: dict[int, int], signal_capability: CapabilityState)
  def tamper_summary(ctx, now: datetime) -> None        # 每小時步驟，寫 analysis_results('tamper')
  def add_annotation(ctx, *, host_href: str | None, pattern: TamperPattern | None, process: str | None, reason: str, by: str) -> int
  def remove_annotation(ctx, annotation_id: int) -> None
  def list_annotations(ctx) -> list[Annotation]         # 只列目前 PCE 的
  ```
  - `tamper_summary` 寫入的每台主機摘要：`href`、`hostname`、`n_7d`、`n_60d`、`pattern`、`last_at`、`unexplained_7d`、`has_signal`。
  - 標註的路由與畫面在 P6 主機側寫頁。Ruling：沒有畫面就不出貨路由（反目標 4）；P3 只交付服務與表。
- `hourly.py` 附加步驟 `("tamper", tamper_summary)`。
- i18n：`guidance` 的 `purpose_key` 與 `TamperAction` 的顯示文字，兩個語系都要有。

- [ ] **Step 1：失敗測試**：
  - 判讀：`test_signal_reading_actions_from_comma_joined_kernel_functions`、`test_confirmed_reading_has_no_process_info`、`test_unknown_kernel_function_kept_raw`。
  - 分類：
    - `test_classify_lab_fixture`：`tamper_60d.json` 中 host-01、04、05、07 為 regular_cycle，host-03 為 burst，host-02 為 sporadic，host-06 為 too_few。
    - `test_classify_threshold_edges`。
  - 時間線與指引：`test_timeline_window_and_types`、`test_guidance_by_os_family`。
  - 已知原因：`test_annotation_explains_matching_readings`、`test_annotations_scoped_to_current_pce`。
  - 摘要：`test_summary_written_by_hourly_step`、`test_every_guidance_key_in_both_languages`。
- [ ] **Step 2：** `timeout 300 .venv/bin/python -m pytest tests_v6/domain/test_tamper.py tests_v6/services/analysis/test_tamper.py tests_v6/store tests_v6/i18n tests_v6/gates -q` → FAIL
- [ ] **Step 3：實作。**
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/domain/tamper.py illumio_ops/services/analysis illumio_ops/store illumio_ops/i18n tests_v6/domain/test_tamper.py tests_v6/services/analysis tests_v6/fixtures/pce/tamper_60d.json && git commit -m "feat(v6): tamper readings, interval pattern classification, timeline, host guidance and known causes"`

---

### Task 13：關注清單

**Files:**
- Create: `illumio_ops/domain/focus.py`、`illumio_ops/services/analysis/focus.py`、`tests_v6/domain/test_focus.py`、`tests_v6/services/analysis/test_focus.py`
- Modify: `illumio_ops/services/analysis/hourly.py`、i18n 兩個語系

**Interfaces:**
- **`domain/focus.py`**：
  ```python
  @dataclass(frozen=True)
  class FocusAction:
      target: Literal["workbench", "lateral", "host", "settings_lateral", "settings_collection", "alerts",
                      "system_jobs", "system_pce"]
      segment: FlowSegment | EventSegment | None; host_key: str | None
  @dataclass(frozen=True)
  class FocusItem:
      kind: FocusKind; fingerprint: str; severity: Severity; critical_asset: bool; confidence: Confidence
      title_key: str; why_key: str; params: Mapping[str, Any]; action: FocusAction
  SEVERITY_POINTS = {low: 1, medium: 2, high: 4, critical: 8}
  CONFIDENCE_FACTOR = {high: 1.0, medium: 0.8, low: 0.6}
  def score(item: FocusItem, *, new_this_week: bool) -> float
  # SEVERITY_POINTS × (1.5 若涉及重要資產) × (1.3 若本週新出現) × CONFIDENCE_FACTOR
  @dataclass(frozen=True)
  class RankedItem:
      item: FocusItem; score: float; first_seen: datetime; new_this_week: bool; weeks_persisting: int
  def rank(items: Sequence[FocusItem], first_seen: Mapping[str, datetime], now: datetime) -> list[RankedItem]
  # 本週新出現 = first_seen 在 7 天內；持續週數 = (now − first_seen) // 7 天
  ```
  - 權重的理由寫在 docstring：spec §6.5.4 的排序因子是嚴重度、重要資產、本期新出現、可信度，權重由 builder 決定（§10）。
- **每種來源一個純函式 builder**，輸入是服務層讀好的資料。嚴重度規則如下：

  | 來源 | 項目與嚴重度 |
  |---|---|
  | 近 7 天的偵測 | 每筆一項，嚴重度取偵測本身 |
  | 重要資產可觸及 | 「現在」可觸及來源 ≥20 為 high、≥5 為 medium、其餘 low；標涉及重要資產 |
  | 樞紐主機 | 前 5 名，medium |
  | 跨環境邊 | 有 allowed 為 high，否則 medium |
  | 竄改 | 近 7 天有未解釋的竄改：burst 為 high；regular_cycle 為 medium，why 鍵說明「多半是另一套防火牆程式與 VEN 搶表」；sporadic 為 medium；含 signal 型時升一級 |
  | 勒索 priority 服務 | 嚴重度依服務：critical／high 照用，其餘 medium |
  | 原廠數字矛盾 | 有矛盾時一項，low，不排序其他項 |
  | 切換模式的阻礙 | visibility_only／selective 主機近 7 天有 potentially_blocked 的入向連線，以 `aggregate_flows` 取前 50；medium，參數帶主機數與連線數 |
  | 資料品質 | 近 7 天 process 或使用者覆蓋 < 20% 為 low（data_coverage）；有 `flow_drops`／`flow_off` 主機為 medium（visibility）；近 7 天有未解的收集缺口，failed 為 high、truncated 為 medium（collection_gap） |
  | 系統健康 | job 健康失敗或 PCE 探測失敗，high |
  | 設定 | 重要資產或管理群組未設定為 low（setup_required）；選擇的 label 已不存在為 medium（stale_selector） |
  | 僅事件模式 | 一項 setup_required，說明橫向移動分析需要完整或告警模式 |

- **`services/analysis/focus.py`**：`def build_focus(ctx, now: datetime) -> None`
  - 每小時最後一步，讀 exposure、ransomware、tamper 的結果與 detections。
  - `upsert_focus` 拿回 `first_seen`，`rank` 之後寫入 `analysis_results('focus')`：`items`、`computed_at`、`sources_status`（每個來源 ok／缺／錯誤）。
  - 某來源的結果不存在時，`sources_status` 寫明，不當成沒有項目。
- `hourly.py` 附加步驟 `("focus", build_focus)`，排在最後。

- [ ] **Step 1：失敗測試**：
  - 排序：`test_score_formula`、`test_new_this_week_and_persisting_weeks`。
  - 各來源：`test_detection_items_from_last_7_days`、`test_asset_exposure_severity_bands`、`test_tamper_regular_cycle_item_explains_firewall_conflict`、`test_ransomware_priority_items`、`test_contradiction_item_does_not_reorder`、`test_mode_switch_blocker_item`、`test_low_coverage_item`、`test_visibility_item`、`test_gap_item`、`test_system_health_item`。
  - 設定與模式：`test_setup_required_when_unset`、`test_stale_selector_item`、`test_events_only_mode_item`。
  - 狀態與文字：`test_missing_source_reported_in_status`、`test_first_seen_persists_across_runs`、`test_every_focus_key_in_both_languages`。
- [ ] **Step 2：** `timeout 300 .venv/bin/python -m pytest tests_v6/domain/test_focus.py tests_v6/services/analysis tests_v6/i18n -q` → FAIL
- [ ] **Step 3：實作。**
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/domain/focus.py illumio_ops/services/analysis illumio_ops/i18n tests_v6/domain/test_focus.py tests_v6/services/analysis && git commit -m "feat(v6): derived focus list ranked by severity, critical assets, novelty and confidence"`

---

### Task 14：設定 › 橫向移動（GUI）

**Files:**
- Create: `illumio_ops/web/routes/system_lateral.py`、`web/src/pages/system/Lateral.tsx`、`tests_v6/web/test_system_lateral.py`、`tests_v6/e2e/test_lateral_settings.py`
- Modify: `illumio_ops/web/app.py`（藍圖）、前端路由與導覽、i18n 兩個語系、`web/src/api/contracts.json`、`web/src/api/generated.ts`

**Interfaces:**
- `GET /api/system/lateral` 回傳 `LateralView`：
  - `revision`、`settings: LateralSettings`；
  - `effective_ports: list[AdminPortView(port, proto, name, source)]`；
  - `label_choices: list[LabelChoice(key, values: list[str], truncated: bool)]`：每個 key 最多 500 個值，超過就 `truncated=true`；
  - `status: LateralStatus`：`collected`、`baseline_days`、`baseline_required`、`detect_last_ok_at`、`detectors: list[DetectorStatusView]`、`exposure_last_ok_at`、`stale_selectors`。
- `PUT /api/system/lateral` 收 `LateralUpdate(revision, settings)`：
  - 驗證錯誤逐欄回傳，比照 P1／P2 的設定頁；
  - revision 不符回衝突；
  - 成功後下一輪偵測與每小時分析就用新設定，不需要重啟。
- **頁面**（Direction D、人話文案、一顆主要動作「儲存」）：
  - **頂部狀態**：
    - 基準期累積 N／30 天；
    - 最後一次偵測與每小時分析的時間；
    - 每個偵測器的狀態，例如 `disabled` 時寫「尚未設定管理群組」；
    - 僅事件模式時明說「橫向移動分析需要完整或告警收集模式」，並連到資料收集頁。
  - **主要區塊**：
    - 管理 port：列出內建、PCE 高風險、自行加入三種來源，可移除、可加入；
    - 重要資產與管理群組：label 選擇器，值超過上限時寫明「只列前 500 個」；
    - 環境 label 的 key；
    - 偵測門檻：每個偵測器一列，寫它判斷什麼；
    - 預期的發起 process：每個 port 一列；
    - 圖的跳數與觀察天數。

- [ ] **Step 1：失敗測試**：
  - 路由：`test_get_returns_effective_ports_with_sources`、`test_put_validates_and_bumps_revision`、`test_put_stale_revision_conflict`、`test_label_choices_truncation_flag`、`test_events_only_status_says_mode_required`。
  - e2e（Playwright 對本機測試伺服器，比照 P2 的資料收集頁 e2e）：
    - 加入一個重要資產、儲存、重新載入後仍在；
    - 觀察天數超過基準期時，欄位顯示錯誤；
    - 導覽列看得到「橫向移動」。
- [ ] **Step 2：** `timeout 600 .venv/bin/python -m pytest tests_v6/web/test_system_lateral.py tests_v6/e2e/test_lateral_settings.py tests_v6/gates -q` → FAIL
- [ ] **Step 3：實作；** 跑 `bash scripts/v6/gen_contracts.sh && npm --prefix web run typecheck && npm --prefix web run build`。
- [ ] **Step 4：PASS；閘門。**
- [ ] **Step 5：Commit** `git add illumio_ops/web web/src illumio_ops/i18n tests_v6/web/test_system_lateral.py tests_v6/e2e/test_lateral_settings.py && git commit -m "feat(v6): Settings › Lateral movement page"`

---

### Task 15：驗收（.106、lab、規模）、文件回寫與全分支審查

驗證腳本放 `tmp/v6-p3-verification/`（gitignored）；部署腳本從 P2 的 `tmp/v6-p2-verification/deploy106.sh` 複製並改路徑。

- [ ] **Step 1：打包並部署到 .106**：
  - `PYTHON=.venv/bin/python bash scripts/v6/build_bundle.sh`；
  - 部署腳本做套件交換：先停服務，備份 `illumio_ops/` 與 `python/`，換上新版，pip 離線安裝，啟動，檢查登入頁回 HTTP 200；
  - 確認 5.x 仍 active。
- [ ] **Step 2：0002 遷移與第一輪結果**（約 1 小時後）：
  - 0002 在 .106 的現有庫成功；
  - `analysis_runs` 的 detect、exposure、ransomware、tamper、focus 都是 ok；
  - `analysis_results` 五種結果都存在；
  - 偵測數量的量級與 Task 0 一致：扇出 34 天約 3 次、新的管理連線每天 1–9 組；
  - 關注清單含店內 30 天那台約 10 分鐘的規律竄改。
- [ ] **Step 3：預計阻擋與 deny rule 名稱**（spec §9）：
  - 腳本在 .106 以服務函式 `predict_blocks` 查目的為 visibility_only 主機、近 1 天的流量；
  - 斷言每筆 `blocked_by_boundary` 的列都對到 `RuleRef`，至少一筆的規則集名稱是 lab 當時存在的 deny rule 規則集（撰寫時是 `tedt`）。
- [ ] **Step 4：勒索拆解逐台核對**（spec §9）：
  - 腳本印出每台主機的計算值、PCE 值、矛盾旗標與逐服務貢獻；
  - 在 PCE 主控台的 Ransomware Protection 儀表板逐台核對 PCE 值，確認刻度是 0–100（Task 11 的 Ruling）；
  - lab 13 台 `fully_protected`、0% 的主機必須全部標成矛盾。
- [ ] **Step 5：竄改**：
  - Task 12 的 fixture 測試通過（7 台的分類）；
  - .106 店內的分類結果印出來核對。
- [ ] **Step 6：扇出的實機觸發**：
  - 從一台受管 Linux 主機在 60 分鐘內對 ≥ 10 台 lab 主機的 22 port 發起連線：`for ip in $(cat targets.txt); do nc -z -w2 "$ip" 22; done`。目標清單取自店內有 22 port 流量的目的。
  - 來源主機的 `enforcement_mode` 不得是 idle；dev.lab.local 若是 idle，就改用另一台可以 ssh 進去的 lab 主機。
  - 在 10–20 分鐘內 `detections` 出現該來源的扇出偵測。
  - 告警送達屬 P4 的驗收，這裡只驗偵測。
- [ ] **Step 7：規模**：
  - **寫入成本**：在 1,000 台合成庫的副本上（`/root/v6-p2-load/load1m35` 以 SQLite backup API 複製，先跑 0002），用 P2 Task 14 的量測腳本重量尖峰每輪持鎖（指令見 `tmp/v6-p2-verification/load-test.md`）。
    - 目標：不得超過 P2 量到的 4 GB 約 25 秒的 10%（≤ 27.5 秒）。
  - **每小時分析**：在同一副本上計時 `run_hourly_analysis` 的耗時與記憶體增量，目標 60 秒、500 MB（Global Constraints）。超過時：
    - 依瓶頸改成 `limits_hit` 加降級，例如只對受管主機算可觸及數，或延長間隔；
    - 在帳本記 Ruling，並回報使用者。
- [ ] **Step 8：最終全分支審查**：
  - Codex reviewer（`reviewer` profile、effort xhigh），範圍從開出 P3 的那個 commit 到 HEAD。
  - 每一項 finding 都對照原始碼查證；Critical／Important 的修正一次做完，每項都要有先變紅的測試；Minor 記入帳本延後。
- [ ] **Step 9：文件回寫**：
  - spec §6.5.1 偵測器表補上預設值與 Task 0 的量測依據；
  - §6.6 更正 F4（60 天錄製檔為 4 台規律循環），新增 draft `rules` 的形狀；
  - 路線圖 P3 標「完成」並附驗收結果；
  - 驗收報告 `tmp/v6-p3-verification/report.md`。
- [ ] **Step 10：Commit** `git add docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md docs/superpowers/plans/2026-10-24-v6-roadmap.md && git commit -m "docs(v6): record P3 acceptance and measured detector defaults"`，之後依使用者決定合併。
