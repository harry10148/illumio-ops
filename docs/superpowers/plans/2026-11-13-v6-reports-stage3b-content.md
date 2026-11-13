# v6 報表第 3b 段：內容 Implementation Plan

**Goal:** 報表的比例只算「有判定」的流量，沒有判定的另列「只能監看的流量」；新增「每週總覽」；Rule Hit Count 併進「規則使用」；
安全風險瘦身；安全風險的成熟度與已強制主機比例有上期值。版本 6.10.0。

**Architecture:** 「有判定／沒有判定」在讀取層（`services/flowsource.py` 的 `FlowTotals` 與規則用的彙總表）定一次，報表各自取用，不在每個 builder 各寫條件。
「只能監看的流量」「使用者與程式」是共用的章節產生函式（`services/reports/flowsections.py`），誰需要誰放。每週總覽是新型別，自己決定要不要向 PCE 取流量，
取不到時只有流量那幾段寫原因。Rule Hit Count 的讀取留在 `services/rhc.py`，改由規則使用的 builder 呼叫並接住失敗。

**Tech Stack:** 同 3a（`docs/superpowers/plans/2026-11-12-v6-reports-stage3a-presentation.md`）。流量庫遷移在 `illumio_ops/store/flowdb/migrations/`；
設定檔升級在 `illumio_ops/settings/upgrade.py`（`SCHEMA_VERSION` 現在是 13）。

**Spec:** `docs/superpowers/specs/2026-11-11-v6-purpose-led-ui-design.md` §9.2、§9.3、§11（第 3 段的 3b 部分）。使用者 2026-11-12 同意：
沒有判定流量造成的數字變動（§9.2 的表）、每週總覽、合併 Rule Hit Count、安全風險移走三章。

## Global Constraints

- **會變的數字只有下表列的；其餘一個都不能變。** `tests/services/reports/test_numbers_pinned.py` 的期望值只准改下表列到的 key，而且每一處改動都要在回報列出
  「型別、key、改前、改後、為什麼」。

  | 報表 | 會變的 `Kpi.key` | 原因 |
  |---|---|---|
  | 安全風險 | `maturity`、`allowed_pct`、`unmanaged_connections`、`admin_open_connections`、`critical_high_findings` | 分母與計數只算有判定的；規則 B001、B006、L005、L007 的嚴重度可能跟著變 |
  | 安全風險 | 拿掉 `lateral_detections`；`ransomware_protected_pct` 留著 | 橫向移動章移走 |
  | 應用摘要 | `allowed_pct` | 分母只算有判定的 |
  | 規則使用 | 多三個：`rhc_hit`、`rhc_zero`、`rhc_no_record` | 併入 Rule Hit Count |
  | 每週總覽 | 全新 | 新型別 |
  | 安全風險 | `maturity`、`enforced_hosts_pct` 的 `previous` 由 `None` 變成有值（條件見 Task 4） | Task 4 |

  `pb_flows`、`blocked_flows` 本來就只數有判定的，不變。
  查過的事實（2026-11-13）：`flow_totals`、`maturity()`、`run_rules`、`readiness_rows` 的呼叫者全部在 `services/reports/` 底下，畫面沒有用到，
  所以不會有「畫面與報表對同一個數字說兩個值」。安全風險的上期值是用同一個算法現算的（不是取舊報表存的數字），升級後第一份的比較兩邊是同一個基準。
  準備度的 `policy`、`staged` 已經除以有判定的連線；`ringfence`（同一個 app 內的連線比例）分子分母都是全部連線，它量的是連線往哪裡去、不是判定，**不改**，
  在準備度「怎麼算」的說明表補一句寫明這一點。
  **2026-11-13 修正（Task 1 的 implementer 讀到的）**：準備度的 `remote` 因子（遠端管理連線中有規則允許的比例）分母含沒有判定的連線。它是判定的比例，
  照使用者同意的規則改成只算有判定的（`readiness_rows` 的 `remote` 加 `d != 'unknown'`；`remote_allowed` 本來就只數 allowed）。
  準備度的 `overall`、`ready`、`held_back` 因此列入會變的數字；Task 7 驗收時附 .106 的改前改後。這一項併在 Task 3 的開頭做。流量報表的 `flows`、`connections`、`sources`、`destinations` 是「看到多少」，照舊含沒有判定的。
- 19 條規則的觸發條件除了「只算有判定的」之外不變（§9.3）；不加新規則。
- 定義只有一個：有判定＝`policy_decision IN ('allowed','potentially_blocked','blocked')`；沒有判定＝`'unknown'`。不看 `state`。
  沒有判定的再分兩種，只看隨那筆流量存下的 `src_managed／dst_managed`：兩端都是 0＝「兩端都沒有 VEN」；其餘＝「至少一端有 VEN」。
- 報表不寫「這台當時是 Idle」。流量庫的 `src_mode／dst_mode` 不用；列主機時模式取清冊**現在**的值，並標明是現在的。
- 文字規則、用語閘門、長度規則、不發對外請求、跳脫：同 3a。3a 的版面規則全部維持：新章節的表照樣有 `host_keys`、紙本 10 列上限、空表的說法。
  「最該做的事」與「沒評估不得說成沒事」的判斷只用 `render_html.to_do`，不另寫。
- XLSX 版式、JSON／CSV 結構不改（欄名與新章節的工作表會跟著文件多出來）。
- 改了路由回傳的模型或 `ReportType` 要 `bash scripts/gen_contracts.sh` 並提交 `web/src/api/contracts.json`、`generated.ts`。
- mypy strict、ruff；每個 task 先寫失敗測試、確認是斷言失敗、再實作。
- 工作目錄 `/home/harry/rd/illumio-ops/.worktrees/v6-ui`，分支 `feat/v6-reports-stage3b`，每個指令開頭 `cd` 到這裡；`git add` 只加明確路徑；
  英文 conventional commits；commit 不接在閘門後用 `;` 或管線串；不 push；不 amend。
- Task 1–7 依序，一次一個 implementer（它們改同一批 builder 與兩個 i18n 檔）。
- 單檔測試：`cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && timeout 600 .venv/bin/python -m pytest <檔案> -x -q -p no:logging`；
  全套閘門：`bash .superpowers/sdd/2026-11-03-v6-ui-b-rule-scheduling/gates.sh`。

## Review Focus

1. **分母換了，分子有沒有跟著換**：每個比例的分子與分母來自同一群流量（都只算有判定的）；不得出現超過 100% 或分母為 0 時印 0%（沒有有判定的流量時是「無資料」加原因）。
2. **沒有判定的流量沒有消失**：它從比例裡拿掉，但「只能監看的流量」一章與第 1 頁那一句要說它有多少（筆數與連線數兩個比例都寫）。
3. **每週總覽在輕量模式**：向 PCE 取流量失敗時，只有流量、新連線兩段與規則部分寫原因；告警、VEN、政策三段照出；整份不失敗；第 1 頁不說「沒有需要處理的項目」。
4. **既有的 Rule Hit Count 排程升級後不能消失、不能重複、不能超過 30 天**；升級步驟跑兩次結果相同；RHC 沒開或 403 時規則使用報表照常產出且那一章寫了原因。
5. **安全風險移走的三章各有去處**：勒索一個數字一句、橫向移動一句、使用者與程式在流量報表出現；沒有任何一張表或一個數字是「搬了但沒落地」。

---

### Task 1: 讀取層分出有判定與沒有判定

**Files:**
- Modify: `illumio_ops/services/flowsource.py`（`FlowTotals`、`flow_totals`、`group_for_findings`）、`illumio_ops/domain/maturity.py`、
  `illumio_ops/services/reports/{security_risk,app_summary,traffic}.py`、`illumio_ops/services/reports/findings.py`、`illumio_ops/i18n/{en,zh_TW}.json`
- Test: `tests/services/test_flowsource*.py`（現有 `flow_totals` 的測試檔）、`tests/domain/test_maturity.py`、`tests/services/reports/test_findings.py`、
  `test_security_risk.py`、`test_app_summary.py`、`test_traffic.py`、`test_numbers_pinned.py`

**Interfaces:**
- `flowsource.DECIDED = ("allowed", "potentially_blocked", "blocked")`。
- `FlowTotals` 新欄位（既有欄位的意思不變，除了註明的兩個）：
  - `decided_flows: int`、`decided_connections: int`
  - `undecided: Undecided`，`Undecided(flows, connections, unmanaged_flows, unmanaged_connections, managed_flows, managed_connections)`：
    `unmanaged_*`＝兩端都沒有 VEN；`managed_*`＝至少一端有 VEN；兩者相加等於 `flows／connections`。
  - **改意思**：`from_unmanaged_connections`、`admin_open_connections` 只算有判定的（SQL 加 `f.policy_decision != 'unknown'`）。
    安全風險的 `unmanaged_connections` 這個數字因此會比〈非受管端點〉報表看到的少很多（.106：77,664 → 420 筆的量級）：數字名稱改成寫明
    「有判定的非受管來源連線」（en 對應），note 固定一句指向〈只能監看的流量〉。
    `from_unmanaged`、`to_unmanaged`（筆數，流量報表「非受管」章用）不動。
- `maturity()`：`lateral` 與 `managed` 兩部分的分母改成 `connections - undecided_connections`（與 `policy` 同一個分母；為 0 時三部分都是 `None`）。
  `MaturityInputs` 的欄位不必改名；docstring 寫明三部分都只算有判定的連線。
- `_flow_kpis.allowed_pct`、`app_summary` 的 `allowed_pct`：分母改成有判定的連線；沒有有判定的連線時值是 `None`，`note` 用新句
  `rpt_no_decided_flows`（zh「期間內沒有帶判定的流量，所以算不出比例。」）。
  應用摘要的結論句用到 `allowed_pct`：它是 `None` 時不得落到「不完整」的句式——在 `CONCLUSIONS[APP_SUMMARY]` 補一個不含它的短句式
  （三個連線數），並確認 `conclusion.incomplete()` 的其他使用者（grep）不會因此把報表當成沒算出來。
- 判定表（流量 `decisions`、應用摘要 `impact`、安全風險 `coverage`）：只列有判定的三列，比例的分母是有判定的合計；表下一句
  `rpt_decided_note`（zh「比例只算有判定的流量；沒有判定的 {flows} 筆（{connections} 次連線）見〈只能監看的流量〉。」），沒有就不寫。
  `rpt_trf_unknown_note` 由這一句取代（刪掉舊鍵）。應用摘要的 `impact_text`、安全風險的 `direction` 句同樣只算有判定的。
- 規則（`findings.py`）：
  - B001、B006、L002、L005、L007：`decision != 'blocked'` 改成 `decision IN ('allowed','potentially_blocked')`。
  - B004：條件加 `decision != 'unknown'`。B005：分母 `r.sum("decision != 'unknown'")`；分母為 0 時不觸發。
  - B007、B008、B009、L001、L006 與已指定判定的規則不動。
  - `rpt_rule_b004_desc`、`rpt_rule_b005_desc` 與兩條的 `_how` 句補上「只算有判定的流量」（en、zh）。
- 安全風險「分段成熟度怎麼算」的說明表（`parts_table`）加一句固定文字：三個以連線比例計分的部分只算有判定的連線，沒有判定的不計入；自 6.10.0 起如此，與更早產出的報表的分數不能直接相比（`rpt_sec_how_decided`）。

- [ ] **Step 1: 寫失敗測試**
  - `flow_totals`：造 allowed 10 連線、potentially_blocked 30、blocked 0、unknown（兩端非受管）50、unknown（來源受管）10，其中非受管來源的有判定流量 4 連線、
    沒有判定的 50；斷言 `decided_connections == 40`、`undecided.unmanaged_connections == 50`、`undecided.managed_connections == 10`、
    `from_unmanaged_connections == 4`（不是 54）；管理 port 上一筆 unknown 不進 `admin_open_connections`。
  - `maturity`：同樣的輸入下 `policy == 10/40`、`managed` 用 4/40 而不是 54/100；沒有有判定的連線時三部分都是 `None`、分數只由其餘部分算。
  - 報表：`allowed_pct == 25.0`（不是 10.0）；判定表三列、比例相加 100%、有那一句且數字正確；全部都是 unknown 時 `allowed_pct` 是 `None` 且有原因，表是空的並說原因。
  - 規則：只有 unknown 流量在高風險 port 上時 B001 不觸發；B004 的 `n_flows` 不含 unknown；B005 的覆蓋率用有判定的分母；
    B007、B008、L001 在只有 unknown 流量時照樣觸發（它們看的是有沒有發生）。
- [ ] **Step 2: 確認失敗；實作。**
- [ ] **Step 3: 更新 `test_numbers_pinned.py`**——只改 Global Constraints 表列到的 key，逐一記下改前改後。
- [ ] **Step 4: 跑 `tests/domain tests/services tests/i18n tests/gates`，全過。**
- [ ] **Step 5: commit** `feat(v6-reports): a share counts only the flows the PCE gave a decision for`

---

### Task 2: 「只能監看的流量」一章與第 1 頁那一句

**Files:**
- Modify: `illumio_ops/services/flowsource.py`（一個新讀取）、`illumio_ops/services/reports/flowsections.py`、
  `illumio_ops/services/reports/{security_risk,traffic,app_summary,readiness}.py`、`illumio_ops/i18n/{en,zh_TW}.json`
- Test: `tests/services/reports/test_flowsections.py`、三個 builder 的測試、`test_readiness.py`、`test_render_html.py`（caveats 取捨）

**Interfaces:**
- `flowsource.undecided_breakdown(ctx, spec, *, top=10) -> UndecidedBreakdown`：
  `sources`、`destinations`（各前 `top` 名：key、flows、connections，分兩種）、`managed_hosts`（出現在「至少一端有 VEN」那一種裡的受管端主機：key、flows、connections、
  它是來源端還是目的端；最多 200 台，總數另回）。
- `flowsections.monitor_only_section(inp, spec, totals, *, names, hosts) -> tuple[Section, ...]`：沒有沒有判定的流量時回空 tuple。章 id `monitor_only`，
  標題 zh「只能監看的流量」。內容依序：
  1. 一段固定說明（`rpt_mon_intro`）：這些流量 PCE 沒有回報判定，所以報表的比例不算它們；它們照樣是發生過的連線。
  2. 兩種各多少（一張兩列的表：種類、筆數、連線數、佔全部流量的比例〔筆數〕、〔連線數〕）。種類的名稱與說明：
     「兩端都沒有 VEN」——PCE 沒有 VEN 可以回報或控制這些連線，只能看；「至少一端有 VEN」——VEN 記下了這筆連線但沒有回報判定。
  3. 兩種各自最多的來源與目的（前 10；主機欄有 `host_keys`，`host_section="connections"`）。
  4. 「出現在裡面、有 VEN 的主機」表：主機、它**現在**的模式（`mode_word`；欄名寫「現在的模式」）、筆數、連線數、在哪一端。
     現在是 Idle 的列，備註欄寫固定一句「Idle 的 VEN 只記快照，不回報判定。」；其餘主機備註留空——報表不對它們下原因。
     不在清冊的主機模式寫「不在清冊」。超過 200 台照 `limit_note` 的既有寫法說明。
- 放在哪：安全風險、流量、應用摘要的一般章節最後（`findings` 章之前）。準備度不放這一章，但它現有的 `rpt_rdy_quality_unknown` 改用與其他報表同一句 caveat。
- caveat（3a 留下的第二種）：`rpt_caveat_undecided`（zh「期間內有 {pct_flows}% 的流量（依連線數是 {pct_connections}%）沒有判定；報表的比例只算有判定的，
  其餘見〈只能監看的流量〉。」）。適用安全風險、流量、應用摘要、準備度（準備度的句尾不指向那一章，用 `rpt_caveat_undecided_plain`）。
  `caveats` 最多 2 句的取捨順序：收集缺口 → 沒有判定 → 封存缺日；第三句放不下時它已經在資料註記裡（3a 的 `_archive_lines`），不另補。
  這個取捨寫成一個函式（`generate.py` 或 `finish.py`），不讓每個 builder 各自判斷；`_build` 現在「未滿 2 句才加封存缺日」的邏輯併進來。

- [ ] **Step 1: 寫失敗測試**：兩種的筆數與連線數相加等於 `totals.undecided`；主機表的模式取自清冊而不是流量列（造一台流量列 `src_mode='idle'`、清冊現在是 `selective` 的主機，
  表裡寫的是 Selective 的說法、備註空白）；現在是 Idle 的主機有那一句；沒有 unknown 流量時沒有這一章也沒有 caveat；
  三句都成立時 caveats 是缺口與沒有判定兩句、封存缺日仍在資料註記；兩個百分比用的分母是全部流量（筆數與連線數各自）。
  `host_keys` 的不變量測試（3a 的 `test_every_host_column_knows_which_host_each_row_names`）涵蓋新表。
- [ ] **Step 2: 確認失敗；實作。**
- [ ] **Step 3: 實際輸出檢查**：用 rich fixture 產安全風險、流量、應用摘要的 HTML（en、zh），以 3a 的量測腳本
  （`/tmp/claude-1000/-home-harry-rd-illumio-ops/40e21a2b-5668-4a7f-bdb5-688edf9e405b/scratchpad/t6/measure.py <目錄>`）在 1440、820、print 量過；新章的表有沒有溢出、紙本 10 列上限有沒有套到。結果寫進回報。
- [ ] **Step 4: 跑 `tests/domain tests/services tests/i18n tests/gates`，全過。**
- [ ] **Step 5: commit** `feat(v6-reports): flows without a decision have their own chapter, and the first page says how many there are`

---

### Task 3: 安全風險瘦身；使用者與程式搬到流量報表

**Files:**
- Modify: `illumio_ops/services/reports/security_risk.py`、`flowsections.py`、`traffic.py`、`illumio_ops/domain/conclusion.py`（若結論句用到被拿掉的數字）、
  `illumio_ops/i18n/{en,zh_TW}.json`
- Test: `tests/services/reports/test_security_risk.py`、`test_traffic.py`、`test_numbers_pinned.py`、`test_report_i18n.py`

**Interfaces:**
- 安全風險的章節（依序）：`coverage`（政策覆蓋）、`uncovered`（沒有規則涵蓋的流量；原 `ports` 章的「有缺口的 port」表搬進這一章當第二張表，`ports` 章取消）、
  `enforcement`（模式推進）、`pb`（開始擋之後會被擋的）、`monitor_only`（Task 2）、`findings`（沒評估的規則）、`how`。
- 拿掉三章：
  - `ransomware` → `enforcement` 章之後不留章；`ransomware_protected_pct` 這個數字留著，它的 `note` 是固定一句
    `rpt_sec_see_ransomware`（zh「各主機與服務的明細見〈勒索防護〉報表。」）。成熟度的勒索部分照算。
  - `lateral` → 取消；`lateral_detections` 這個數字拿掉；`coverage` 章的 intro 之後加固定一句 `rpt_sec_see_lateral`
    （zh「橫向移動的偵測與可觸及範圍見〈橫向移動態勢〉報表。」）。
  - `users` → 抽成 `flowsections.users_section(inp, spec) -> tuple[Section, ...]`（原樣搬：兩張排名、欄位覆蓋的判斷、工作台連結），
    改由流量報表呼叫，放在流量報表 `unmanaged` 章之後。安全風險不再呼叫。
- 搬章與改章名之後，grep 兩個語言檔裡以字面章名指路的句子（3a 抓過兩句同類的），指到不存在的章就改。
- 被拿掉的章用到、之後沒有人用的 i18n 鍵刪掉；`CONCLUSION_KPIS[SECURITY_RISK]`（`maturity`、`enforced_hosts_pct`、`critical_high_findings`）不受影響，確認即可。

- [ ] **Step 1: 寫失敗測試**：安全風險的章 id 序列等於上面的清單（有資料時）；沒有 `ransomware／lateral／users／ports` 這四個 id；
  「有缺口的 port」表在 `uncovered` 章裡而且列與搬之前相同（同一個 fixture 比對列內容）；流量報表有 `users` 章而且兩張表的列與原本安全風險的相同；
  `ransomware_protected_pct` 的值不變、note 是那一句；`lateral_detections` 不在數字裡。
- [ ] **Step 2: 確認失敗；實作；更新 `test_numbers_pinned.py`（只有 `lateral_detections` 被拿掉）。**
- [ ] **Step 3: 跑 `tests/domain tests/services tests/i18n tests/gates`，全過。**
- [ ] **Step 4: commit** `feat(v6-reports): the security risk report keeps what is its own; users and processes move to the traffic report`

---

### Task 4: 成熟度與已強制主機比例的上期值

**Files:**
- Create: `illumio_ops/store/flowdb/migrations/00NN_snapshot_managed.sql`（接現有最大編號）
- Modify: `illumio_ops/store/flowdb/workloads.py`（`snapshot_day`、新讀取）、`illumio_ops/services/reports/security_risk.py`、`app_summary.py`、
  `illumio_ops/i18n/{en,zh_TW}.json`
- Test: `tests/store`（流量庫遷移與 `snapshot_day` 的測試檔）、`tests/services/reports/test_security_risk.py`、`test_app_summary.py`

**Interfaces:**
- 遷移：`ALTER TABLE workload_snapshot_daily ADD COLUMN managed INTEGER;`（可為 NULL：升級前的快照沒有這欄，讀到 NULL 就是「那天不能比」）。
  `snapshot_day` 一併寫入 `managed`。若有把快照複製到別處的函式（`copy_from`），一併帶上新欄。
- `workloads.mode_counts_on(conn, day) -> ModeCounts | None`：那一天的快照裡 `managed = 1` 的主機各模式幾台；那天沒有快照或有任何一列 `managed IS NULL` 回 `None`。
- 安全風險：上期結束那一天（顯示時區的日曆日，與每日快照的 `day` 同一種算法——確認 `snapshot_day` 的 `day` 是哪個時區的日期並照它）取 `mode_counts_on`。
  有的話：`enforced_hosts_pct.previous` 用它算。
  `maturity.previous`：用「上期那天的主機模式＋上期的流量數字（現有的 `before`）」重算。勒索部分沒有歷史，所以**只有本期也沒有勒索部分時**
  （PCE 不給勒索評等、或分析沒跑）兩期計分的部分才相同，才給 `previous`；本期有勒索部分時 `previous=None`，`maturity` 的 note 補固定一句
  `rpt_sec_no_previous_parts`（zh「上期沒有勒索防護那一部分的紀錄，計分的部分不同，所以不比較。」）。不得拿兩個不同基準的分數相減。
  另外兩個前提，缺一就是 `None`：上期流量有完整收集（現有的 `traffic_covered`）；本期值取的是**現在**的清冊，所以期間必須結束在今天或昨天
  （顯示時區）——指定較早期間的手動報表這兩個數字不比。
- 不變量測試：以同一時刻的清冊寫一份快照，`mode_counts_on` 算出的已強制比例等於報表本期的 `enforced_hosts_pct`（「受管」的認定兩邊一致）。
- 有篩選條件的報表（`inp.params.filter` 不是 `None`）：快照沒有 Label，這兩個數字的 `previous` 一律 `None`。應用摘要的 `enforced_hosts_pct` 因此不比（它一定有篩選）。
- 升級後第一個週期：上期結束那天的快照沒有 `managed` → `None`，報表照 3a 的規則不寫變化。

- [ ] **Step 1: 寫失敗測試**：遷移後舊列 `managed` 是 NULL、`mode_counts_on` 回 `None`；新快照寫入後回正確的台數（含一台非受管的不計）；
  安全風險在上期那天有快照且上期流量完整時兩個數字有 `previous`，值等於手算；沒有快照、快照有 NULL、有篩選、上期流量不完整——四種各一個測試都是 `None`；
  本期有勒索部分時 `maturity.previous` 是 `None` 且有那一句 note、沒有勒索部分時有值；期間結束在三天前的報表兩個數字都不比；上面的不變量測試。
- [ ] **Step 2: 確認失敗；實作。**
- [ ] **Step 3: 跑 `tests/store tests/domain tests/services tests/gates`（含單一寫入者與遷移的閘門），全過。**
- [ ] **Step 4: commit** `feat(v6-reports): the maturity score and the enforced share are compared with the previous period once a snapshot knows which hosts were managed`

---

### Task 5: Rule Hit Count 併進規則使用

**Files:**
- Modify: `illumio_ops/services/reports/policy_usage.py`、`rule_hit_count.py`（留下可重用的部分，builder 取消）、`registry.py`、`generate.py`（`availability`）、
  `views.py`、`illumio_ops/domain/conclusion.py`、`illumio_ops/settings/schema.py`（`SCHEMA_VERSION` 14）、`illumio_ops/settings/upgrade.py`、
  `illumio_ops/migrate/v5_reports.py`、`illumio_ops/web/routes/report_schedules.py`（如需）、`web/src/pages/reports/{Reports,Schedules}.tsx`、`common.ts`、
  `illumio_ops/i18n/{en,zh_TW}.json`
- Test: `tests/services/reports/test_policy_usage.py`、`test_rule_hit_count.py`、`tests/settings`（升級）、`tests/migrate`、`tests/services/reports/test_schedules.py`、
  `test_conclusion.py`、`test_generate.py`、`test_numbers_pinned.py`、`tests/e2e/test_rhc_e2e.py`、`test_reports_e2e.py`

**Interfaces:**
- 規則使用多一章 `rhc`（zh「已生效規則的實際命中」），放在 `unused` 章之後：原 Rule Hit Count 報表的 `hit`、`zero`、`no_record` 三張表（表的產生邏輯從
  `rule_hit_count.py` 抽成函式重用，列內容不變）。原 RHC 報表的 `pending` 章不搬（規則使用自己已有 `pending` 章）；原 `how` 的名詞說明併進規則使用的 `how` 章。
- 取不到命中資料時這一章只有一段文字、沒有表，其餘章節照出，報表不失敗：
  - `rhc_status` 不是 ENABLED → 該狀態的原因句（沿用 `RHC_UNAVAILABLE` 的 key）加「怎麼開」一句（沿用現有說明開啟步驟的句子；沒有就寫固定一句指向報表頁的 Rule Hit Count 設定）。
  - `RhcPullError`（含 403 `rhc_err_pull_refused`）、PCE 連不上 → 該錯誤的現有句子。
  - 同時在 `data_quality` 加一句說這一章沒有資料與原因。
- 數字：現有六個不動；多 `rhc_hit`、`rhc_zero`、`rhc_no_record`（沒有命中資料時 `value=None`、`note` 是原因）。
  `LEAD_KPIS[POLICY_USAGE]` 不變。`CONCLUSIONS[POLICY_USAGE]` 兩種句式：有命中資料時在現有句子後多半句（命中幾條、零命中幾條），沒有時用現在的句子。
- 期間：沿用規則使用的 30 天（`POLICY_USAGE_MAX_DAYS`）。
- `ReportType.RULE_HIT_COUNT` 留在列舉；從 `_builtin()` 的登記拿掉，所以範本頁沒有它、排入時被拒（`rpt_unavailable_not_built` 改成專用的
  `rpt_err_rhc_merged`：「Rule Hit Count 已併入〈規則使用〉報表。」）。已產出的舊 RHC 報表在清單上照常顯示標題、可開可刪（`TYPE_KEYS` 留著）。
  `CONCLUSION_KEYS／CONCLUSION_KPIS／LEAD_KPIS` 與各「列舉全部型別」的測試：RHC 從「可產生的型別」那一邊拿掉，測試的集合跟著改（不是放寬成子集）。
- 設定升級 `_v13_to_v14`：`reports.schedules` 裡 `report_type == "rule_hit_count"` 的每一個 → `report_type = "policy_usage"`、`lookback_days = min(原值, 30)`；
  改完後若與另一個排程除了 `id` 與 `name` 之外完全相同，留 id 較小的那個。步驟是純函式、可重跑（跑兩次結果相同）。
  改了哪幾個：升級函式回傳之外，用 `logger.info` 記一行（排程名稱、原回溯天數 → 新值、是否因重複被拿掉）；設定檔升級沒有別的紀錄管道，這是我的決定。
- 升級步驟必須是純函式；`upgrade()` 每次載入設定都在記憶體跑一次，所以**紀錄不寫在升級函式裡**。先查升級後的設定何時寫回磁碟
  （`settings/store.py`），把那一行 `logger.info` 放在「讀到舊版、寫回新版」的那一處，只印一次；若現況從不主動寫回，就在啟動時偵測到 RHC 排程被轉換時寫回並記錄。
- 被去重拿掉的排程：它名下已產出的報表留著（清單照常顯示、照各自的保留規則清理），不轉給留下的那個；在那一行紀錄裡寫明。
- **按概念掃**：型別不在 `specs()` 之後，凡是拿「已存的報表或排程的型別」去查 `specs()` 的路徑都要容得下 `rule_hit_count`：報表清單與單筆、下載與開啟、刪除、
  保留份數清理（`retention.py`）、catalog 的排程數與份數統計、重寄、排程清單與「立即執行」、5.x 遷移器的 `specs()[kind]`。逐一 grep `specs()`、`REGISTRY`、
  `report_type` 的使用處，回報列出查了哪些。測試：資料庫裡有一份舊 RHC 報表與（升級前的）RHC 排程時，上述每條路徑都不丟例外。
- 儲存排程的路由現在靠 `availability()` 拒絕不能產的型別；型別不在 `specs()` 後可能變成不拒。測試：存 `rule_hit_count` 的排程被拒，原因是 `rpt_err_rhc_merged`。
- 狀態不是 ENABLED 時不得呼叫 `pull_rhc`（它會在 PCE 上產一份報表，是寫入；NFR 不寫）：用 spy 測「沒開時 `pull_rhc` 被呼叫 0 次」。
- 5.x 遷移器：`TYPES["rule_hit_count"]` → `ReportType.POLICY_USAGE`（回溯天數照現有的 `spec.max_lookback` 上限）。
- 前端：拿掉範本頁對 `rule_hit_count` 的特殊連結（`Reports.tsx`）；RHC 的開關與狀態畫面留在原處不動，確認它不依賴那張卡片存在。
  `tests/e2e/test_reports_e2e.py` 的卡片數由 16 改 15。

- [ ] **Step 1: 寫失敗測試**
  - RHC 開著：規則使用有 `rhc` 章、三張表的列與原 RHC 報表對同一份假資料產出的相同；三個新數字等於三張表的列數；結論用長句式。
  - RHC 關著／不支援／狀態未知／拉取 403／PCE 連不上——五種各一個測試：報表產得出來、`rhc` 章是一段原因、三個數字是 `None` 有 note、結論用短句式、其他六個數字與沒有 RHC 時相同。
  - 排入 `rule_hit_count`：被拒，原因是新 key。舊的 RHC 報表列在清單上仍顯示。
  - 升級：一個 90 天的 RHC 排程 → `policy_usage` 30 天；一個 7 天的 → 7 天；升級後與既有的規則使用排程完全相同 → 只剩一個；沒有 RHC 排程的設定檔原樣；
    對輸出再跑一次升級結果不變；升級後整份設定通過驗證。
  - 遷移器：5.x 的 RHC 排程變成 `policy_usage`。
- [ ] **Step 2: 確認失敗；實作；`bash scripts/gen_contracts.sh`；前端 typecheck 與 build。**
- [ ] **Step 3: 更新 `test_numbers_pinned.py`**（規則使用多三個 key；RHC 那一型的項目拿掉）。
- [ ] **Step 4: 實際輸出檢查**：規則使用在「有命中資料」「RHC 沒開」兩種情況各產 en、zh 的 HTML，用量測腳本量過並自己看過 `rhc` 章。
- [ ] **Step 5: 跑 `tests/domain tests/services tests/settings tests/migrate tests/web tests/i18n tests/gates` 與
  `tests/e2e/test_rhc_e2e.py tests/e2e/test_reports_e2e.py tests/e2e/test_rule_schedules_e2e.py tests/e2e/test_ui_rules_e2e.py`，全過。**
- [ ] **Step 6: commit** `feat(v6-reports): rule hits are a chapter of the rule usage report; a schedule for the old report becomes one for this`

---

### Task 6: 每週總覽

**Files:**
- Create: `illumio_ops/services/reports/weekly_overview.py`、`tests/services/reports/test_weekly_overview.py`
- Modify: `illumio_ops/domain/values.py`（`ReportType.WEEKLY_OVERVIEW`）、`illumio_ops/domain/conclusion.py`、`illumio_ops/services/reports/registry.py`、
  `views.py`（`COMMON`）、`illumio_ops/store/alerts.py`、`illumio_ops/services/reports/{ven_status,new_connections,audit}.py`（把要重用的計算抽成可呼叫的函式，行為不變）、
  `web/src/pages/reports/{common.ts,Reports.tsx}`、`illumio_ops/i18n/{en,zh_TW}.json`、contracts
- Test: 上列各檔對應的測試、所有「列舉全部型別」的測試（`test_conclusion.py`、`test_generate.py`、`test_reads_without_optional_settings.py`、`test_numbers_pinned.py`、
  `test_report_i18n.py`、`test_formats.py`、`tests/e2e/test_reports_e2e.py`）

**Interfaces:**
- 型別 `weekly_overview`，預設回溯 7 天，格式 HTML＋XLSX，`needs_traffic=False`（它自己決定要不要取流量，見下），不接受篩選。`tier` 是常用，而且排第一
  （`views.COMMON` 與前端 `COMMON_ORDER`）。標題 zh「每週總覽」。
- 告警讀取補上界：`store/alerts.py` 的 `period_counts`、`count_alerts`、`alerted_devices` 加 `until: datetime | None = None`（`fired_at < until`）；既有呼叫不帶、行為不變。
  另加 `counts_by_category(conn, *, pce_url, org_id, since, until) -> dict[str, int]`（類別照 `domain/alertcategory.CATEGORIES`，用同一個 `category_filter`）。
- 章節（每章結尾一句指向對應的專題報表，固定文字）：
  1. `alerts` 告警：本期幾則、依嚴重度、依類別；與上期比（上期＝前一個等長期間，同一個讀取帶不同上下界）。告警最多的 5 台主機
     （表：主機、則數、最近一則；`host_keys`、`host_section="alerts"`）。→ 指向告警頁（沒有對應的報表；句子指向主控台的告警頁）。
  2. `vens` VEN：在線／失聯未滿 24 小時／24–48 小時／超過 48 小時／狀態不明各幾台（重用 `ven_status.bucket`）；**本期內失聯的**＝現在不是在線、
     而且最後一次心跳落在本期內的（表：主機、最後心跳、失聯多久；`host_section="status"`）；模式分布，與上期比（Task 4 的 `mode_counts_on`，沒有就不比）。
     在線台數沒有歷史，只寫本期。→〈VEN 狀態〉。
  3. `flows` 流量：有判定的三種各多少連線，與上期比；只能監看的有多少（Task 1 的 `FlowTotals`）。→〈流量〉與〈安全風險〉。
  4. `new_connections` 新出現的連線：幾條、其中管理 port 幾條，與上期比（把 `new_connections._count` 開成可重用的函式）。→〈新出現的連線〉。
  5. `policy` 政策：Provision 幾次、誰做的（`eventsource.audit_counts` 的 `PROVISION` 與 `type_users`）。→〈稽核〉與〈待 Provision 的政策變更〉。
- 發現＝19 條規則的結果（`findings.run_rules` → `as_findings`）＋VEN 狀態的發現（把 `ven_status.py` 建發現的那一段抽成
  `ven_findings(...) -> list[Finding]`，兩邊共用，不複製）。「最該做的事」照 3a 自動產生。沒評估的規則照 3a 有 `findings` 章。
- 數字（依序；領頭 3 個）：`new_alerts`（lower）、`vens_not_online`（lower；失聯三種相加）、`pb_connections`（lower；開始擋之後會被擋的連線）、
  `critical_high_alerts`、`new_connections`、`provisions`（neutral）。`CONCLUSION_KPIS`：`new_alerts`、`vens_not_online`、`pb_connections`、`provisions`；
  第二種句式（沒有流量數字時）：`new_alerts`、`vens_not_online`、`provisions`。
- **流量從哪來、取不到怎麼辦**：
  - 安裝有留流量（`pulls_on_demand` 對這段期間回 False 的情況：以一個 `needs_traffic=True` 的假 spec 問，或抽出它的判斷式）→ 直接讀 `inp.ctx`。
  - 否則 builder 自己開 `ondemand.pull_period(inp.ctx, start=上期開始, end=inp.end, now=inp.now)`（lead 涵蓋上期與新連線的基準需要的範圍：
    新連線的基準沿用〈新出現的連線〉的 `ondemand_lead` 與 `ondemand_prepare`），在 `with` 裡面算流量、新連線兩章與規則。
  - `OnDemandFailed`、PCE 連不上：`flows`、`new_connections` 兩章各剩一段文字（`rpt_wk_no_flows`：「這段期間的流量向 PCE 取不到：{reason}。」）；
    `pb_connections`、`new_connections` 兩個數字 `None` 並帶原因；規則沒有執行 → 照 3a 產生「規則沒有執行」的 `findings` 章（空表、說明原因），
    第 1 頁因此不說「沒有需要處理的項目」；`data_quality` 一句；結論用第二種句式。告警、VEN、政策三章照出。整份報表是「完成」。
  - 取流量的保留期限：期間早於 PCE 還留著的範圍時，同上處理（寫原因），不讓整份失敗。
  - 這種情況下第 1 頁與 `findings` 章不得寫 3a 的「這段期間沒有流量可以評估規則」（原因不對）：用自己的句子 `rpt_wk_rules_no_flows`
    （zh「流量向 PCE 取不到，所以規則沒有評估。」）。`render_html.to_do` 要能分辨這兩種「規則沒跑」——由 `findings` 章的空表說法帶出，不在 renderer 裡判斷型別。
- 告警的上期值：上期整段都在「這個安裝已經在評估告警、而且告警還留著」的範圍內才給（最早一則告警的時間、告警的保留天數、安裝時間，取實際有的依據；
  implementer 讀 `store/alerts.py` 的清理與設定後定，寫進回報），否則 `previous=None`——不得把「沒有紀錄」印成 0 則。
- `needs_traffic=False` 的副作用逐項處理：catalog 的 `mode` 要標成 on_demand（它在輕量模式會向 PCE 取流量；`views.py` 的判斷加上這個型別或給 spec 一個旗標）；
  `refusal` 對回溯上限與「期間早於保留範圍」的檢查不會自動套用——給這個型別 `max_lookback`（同流量報表）並確認超過時被拒；它讀事件（政策那一章），`reads_events=True`
  以便較早的期間讀封存。自己 pull 時補上 `_build` 原本替流量報表做的事：`require_same_pce`／generation 檢查（PCE 中途換了要失敗，不是產一份混的）、
  `_ondemand_lines` 的資料註記、新連線基準的 `ondemand_prepare`。
- 一次 pull 涵蓋上期與新連線基準需要的 lead，不要 pull 兩次。Task 7 在 .135 記下它實際花多久（它是常用第一張）。
- caveat：收集缺口與「沒有判定的流量」兩句同其他流量類報表（Task 2 的同一個函式）。
- 郵件、XLSX 不必特別處理（讀同一份文件）。

- [ ] **Step 1: 寫失敗測試**
  - 進階模式的 fixture：五章都在、順序正確；每個數字等於對應專題報表 builder 對同一份資料算出的數字（告警數對 `count_alerts`、失聯對 VEN 狀態報表的三個數字相加、
    `pb_connections` 對 `FlowTotals`、新連線對 `new_connections` 報表、Provision 對稽核報表）——每一項都是「兩邊各算一次再比」，不是寫死數字。
  - 上期：告警的 `previous` 只數上期區間內的（造一則剛好在邊界上的告警確認歸屬）。
  - 本期內失聯：一台三天前失聯（在 7 天期間內）列出；一台二十天前失聯不列；一台在線不列。
  - 輕量模式、PCE 取流量失敗：頁面上沒有「沒有流量可以評估規則」而有「流量向 PCE 取不到」；報表狀態完成；`flows`、`new_connections` 兩章是原因；另外三章有內容；兩個流量數字是 `None`；有 `findings` 章；
    渲染出的第 1 頁沒有「沒有需要處理的項目」；結論是第二種句式。
  - 輕量模式、取得到：五章都有內容。
  - 型別登記齊全：所有「列舉全部型別」的測試加上新型別後通過；範本頁常用第一張是每週總覽；en、zh 沒有漏翻的 key。
- [ ] **Step 2: 確認失敗；實作；`bash scripts/gen_contracts.sh`；前端 typecheck 與 build。**
- [ ] **Step 3: 實際輸出檢查**：進階與「取不到流量」兩種各產 en、zh 的 HTML，量測腳本三種寬度量過；自己看第 1 頁的 PDF；郵件 HTML 在 600px 看過一份。
- [ ] **Step 4: 跑 `tests/domain tests/services tests/store tests/web tests/i18n tests/gates` 與 `tests/e2e/test_reports_e2e.py tests/e2e/test_ui_rules_e2e.py`，全過。**
- [ ] **Step 5: commit** `feat(v6-reports): a weekly overview: alerts, VENs, traffic, new connections and policy on one page, and what to do first`

---

### Task 7: 版本、真資料驗收、部署

由主對話執行。

- [ ] **Step 0（Task 5 部署之前要準備）**：在 .106 建一個回溯 90 天的 Rule Hit Count 排程（停用狀態即可），用來驗升級。
- [ ] **Step 1**: `illumio_ops/__init__.py`、README 徽章改 `6.10.0`；CHANGELOG 寫一節，**列出哪些數字的算法變了與為什麼**（這是使用者會在報表上看到的變動）。全套閘門全綠。
- [ ] **Step 2: 改前基準。** 用規格 §9.2 那張表的同一段期間 2026-11-05–11-11（.106 的流量保留 35 天，夠；6.9.0 在這段期間的數字已在 scratchpad `t8/after-6.9.0.json`）。
  部署前一刻再產一次 14 型 zh_TW 當基準（讀「現在」的數字會動）。
- [ ] **Step 3: 部署 .106，同一期間重產全部型別 × 兩種語言**，逐型比對：
  - Global Constraints 表**沒列**的 key：必須與基準完全相同。
  - 表列的 key：把改前改後列成表，與規格 §9.2 的表**逐項對照**（同一段期間：`allowed_pct` 2.7 → 3.9、B004 77,664 → 420 筆、B005 0.2% → 2.6%、成熟度各部分）；
    不符的逐項查明是資料在這幾天變了（讀現在的清冊）還是算錯。
    以唯讀 SQL 在 .106 的流量庫直接算一次「有判定的連線數、其中 allowed 的」驗證 `allowed_pct`，兩邊各算一次再比。
  - 規則的發現：改前改後哪幾條的嚴重度或筆數變了，逐條列出（B001、B004、B005、B006、L002、L005、L007 之外的不該變）。
- [ ] **Step 4: 逐份看。** 全部型別 × 兩種語言用量測腳本在 1440、820、print 量過；人眼看：每週總覽、安全風險、流量、規則使用的 PDF 第 1 頁與新章節。
  結果（含截斷與溢出）附在回報。
- [ ] **Step 5: 升級驗證。** .106 的 RHC 排程升級後變成規則使用、回溯 30 天、沒有重複，按「立即執行」產得出報表；服務日誌有那一行紀錄。
- [ ] **Step 6: 部署 .135（輕量、英文、RHC 沒開）**：每週總覽產得出來（取得到流量時五章齊全；若 NFR 取流量失敗則照 Review Focus 3）；
  規則使用產得出來且 `rhc` 章寫了原因；1440／820 介面稽核零違規。
- [ ] **Step 7: 更新規格 §11（驗到什麼、沒驗到什麼），commit；合入 main、推送、盯 CI。** tag 等使用者同意。
