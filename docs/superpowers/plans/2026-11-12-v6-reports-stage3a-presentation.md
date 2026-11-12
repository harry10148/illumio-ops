# v6 報表第 3a 段：呈現 Implementation Plan

**Goal:** 每份報表的第 1 頁給不看細節的人：一句結論、讀數字前先知道、3 個重點數字（上期變化與方向）、最該做的 3 件事；發現改成卡片，
相同行動合併；白話用語；「怎麼讀這份報表」移到最後；紙本每張表只印前 10 列；表格裡的主機連到主機頁；範本頁分常用／專題。版本 6.9.0。

**Architecture:** 報表仍是一份 `ReportDocument`，HTML、XLSX、郵件三個輸出各自讀它。本段在模型上加呈現用的欄位（發現的行動代號與事實／理由分欄、
`caveats`、表格的主機鍵），「最該做的 3 件事」是對 `doc.findings` 的純函式（`domain/actions.py`），三個輸出共用，所以不會各說各話。
重點數字的排序放在收尾步驟 `finish()`，不是每個 builder 各排一次。每個數字的算法不動。

**Tech Stack:** Python 3 / pydantic（`extra="forbid"`、frozen）；報表 HTML 是 `render_html.py` 的字串樣板加 `assets/report_shell.css`；
openpyxl；React 19＋TypeScript（範本頁、用語表）；pytest＋Playwright（列印用 print media）；i18n `illumio_ops/i18n/{en,zh_TW}.json`。

**Spec:** `docs/superpowers/specs/2026-11-11-v6-purpose-led-ui-design.md` §9.1、§9.3、§11（第 3 段的 3a 部分）。
示意圖：`docs/superpowers/specs/2026-11-11-v6-purpose-led-ui-samples/report-page1.html`（使用者 2026-11-12 同意方向）。
§9.2（3b：沒有判定的流量、每週總覽、合併 Rule Hit Count、安全風險瘦身）不在本計畫；3a 落地後另寫。

## Global Constraints

- **每個數字的算法不變。** 3a 不改任何 `Kpi.value`、任何規則的觸發條件與嚴重度、任何表的列。會變的可見輸出只有下面「3a 會變的輸出」列的那些。
- 文字規則（使用者 2026-11-03）：每一句是固定文字或「模板＋算出的值」，不寫推論。新文案 en 與 zh_TW 都要有；不留死鍵。
- 用語閘門 `tests/i18n/test_terminology.py` 必須照過：PCE 的原文保留在括號裡（「開始擋之後會被擋（Potentially Blocked）」），不得出現「可能被擋」。
- 長度規則（專案規則：不得無聲截斷）：本計畫每個新元素都寫了上限與超過時怎麼說，照做；新增上限時在 `domain/report.py` 開頭的長度說明補一行。
- 報表不發任何對外請求（`test_no_external_requests` 照過）；所有來自 PCE 或資料庫的值照舊跳脫。
- `ReportDocument` 不存檔，加欄位不需遷移；`reports` 表存的 `kpis` JSON 形狀（key／label／value／previous）不變。
- 改了 `CatalogEntry` 要 `bash scripts/gen_contracts.sh` 並提交 `web/src/api/contracts.json` 與 `generated.ts`。
- mypy strict、ruff 都要過。Task 1、2、6 先寫失敗測試再實作；其餘以渲染結果的測試與 e2e 驗證。
- 工作目錄 `/home/harry/rd/illumio-ops/.worktrees/v6-ui`，分支 `feat/v6-reports-stage3`，每個指令開頭 `cd` 到這裡；`git add` 只加明確路徑；
  英文 conventional commits；commit 不接在閘門後用 `;` 或管線串；不 push。
- 全套閘門：`bash .superpowers/sdd/2026-11-03-v6-ui-b-rule-scheduling/gates.sh`。
  單檔測試的寫法：`cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && timeout 600 .venv/bin/python -m pytest <檔案> -x -q -p no:logging`。

### 3a 會變的輸出（除了版式之外）

| 哪裡 | 現在 | 3a 之後 |
|---|---|---|
| `doc.findings`（流量、安全風險、應用摘要、網路盤點） | 前 5 個；安全風險只取嚴重與高 | 所有觸發的規則（最多 19） |
| 郵件主旨的「N 項」 | `len(doc.findings)`，最多 5 | 同式子，數字變大 |
| 封面頂線顏色 | 安全風險沒有嚴重／高時是灰色 | 取全部發現的最高嚴重度（可能變成中或低的顏色） |
| 報表末的「規則」章 | 列出摘要沒列的規則 | 只剩沒能評估的規則；都評估了就沒有這一章 |
| 郵件內文 | 結論、前 4 個數字、全部發現 | 結論、讀數字前先知道、3 個數字、最該做的 3 件事、連結 |
| 重點數字的順序 | builder 的順序 | 領頭 3 個在前（下表），其餘照原順序 |
| 安全風險的 `critical_high_findings` 數字 | `len(fired)` | **不變**（仍只數嚴重與高） |

## Review Focus

1. **一個數字都不能變**：兩層證據。Task 0 在動任何 builder 之前把每型 fixture 文件的 `{key: (value, previous)}` 釘成測試，之後每個 task 都跑；
   Task 8 在部署前一刻取 .106 的基準、部署後立刻重產比對。
2. **合併的三件事不得漏掉或重複發現**：每個發現恰好屬於一件事；第 1 頁沒列的件數寫得出來（Task 1）。
3. **主機連結對到正確的列**：`finish()` 會拿掉空欄、HTML 會把每列都一樣的欄拿掉、HTML 只印前 200 列；連結以欄的 key 對應，不以位置（Task 5、6）。
4. **沒有對外網址、沒有 XLSX、沒有發現、沒有重點數字（自訂報表）、沒有上期**：第 1 頁每一塊都有說法，不留空框（Task 6）。
5. **紙本**：超過 10 列的表只印 10 列並寫總數與去處；卡片不被切開；不因強制分頁出現空白頁（Task 6、Task 8 以 print media 量）。

---

**執行方式：** Task 0–7 依序，一次只有一個 implementer（Task 2–5 都改同一批 builder 與兩個 i18n 檔，不得平行）。每份 brief 明文要求先確認
`pwd` 是 `/home/harry/rd/illumio-ops/.worktrees/v6-ui`、分支是 `feat/v6-reports-stage3`。

### Task 0: 把現在的數字釘住

**Files:**
- Create: `tests/services/reports/test_numbers_pinned.py`

在動任何 builder 之前做，單獨提交。對 `tests/services/reports` 現有 fixture 能建出的每一型報表（目標是有 HTML 的 15 型全部；借用各型測試檔已有的
建構方式，不新造資料），把 `{k.key: (k.value, k.previous) for k in doc.kpis}` 以字面值寫進測試。之後的 task 不得修改這個檔案裡的期望值；
`finish()` 重排之後順序會變，所以比的是字典不是序列。哪幾型沒有現成 fixture、因此沒釘到，列在回報裡（那幾型只靠 Task 8 的實機比對）。

- [ ] **Step 1: 寫測試，跑過（它描述現況，本來就該綠）。**
- [ ] **Step 2: 把其中一個期望值改錯跑一次，確認會紅，再改回來。**
- [ ] **Step 3: commit** `test(v6-reports): the key numbers of every report type are pinned before the page is rearranged`

---

### Task 1: 模型欄位、「最該做的事」、領頭數字

**Files:**
- Create: `illumio_ops/domain/actions.py`
- Modify: `illumio_ops/domain/report.py`、`illumio_ops/domain/conclusion.py`（`LEAD_KPIS`）、`illumio_ops/services/reports/finish.py`、
  `illumio_ops/services/reports/generate.py`（填 `gui_base`）
- Test: `tests/domain/test_report.py`、`tests/domain/test_actions.py`（新）、`tests/services/reports/test_generate.py`（`finish` 的排序）

**Interfaces:**
- `Finding` 新欄位（都有預設值，既有呼叫不必改）：
  - `what: str = ""`：發生什麼（事實）。空的時候卡片的第一段只有標題。
  - `action_code: str | None = None`、`action_short: str = ""`（一句祈使句）、`action_focus: str = ""`（一句「最多的是誰」，可空）。
  - 驗證：有 `action_code` 就要有 `action_short`；`action_code` 符合 `^[a-z][a-z0-9_]*$`。
- `ReportDocument` 新欄位：
  - `caveats: tuple[str, ...] = Field(default=(), max_length=2)`：結論正下方的「讀數字前先知道」。
  - `gui_base: str | None = None`：主控台的對外網址（`settings.reports.gui_external_url`，去掉結尾的 `/`）；`generate` 在填 `gui_link` 的同一處填。
- `TableBlock` 新欄位：
  - `host_keys: dict[str, tuple[str | None, ...]] = {}`：欄 key → 每列的主機鍵（列序同 `rows`）。只需帶前 `HTML_ROW_CAP` 列
    （HTML 最多印這麼多，XLSX 不放連結）。驗證：每個 key 是某一欄的 key；每個 tuple 的長度 ≤ `len(rows)`。
  - `host_section: str | None = None`：連結落在主機頁哪一段；允許的值同前端 `HostSection`
    （`status／alerts／different／usual／connections／would-block／ransomware／tamper／quarantine`）。
- `domain/actions.py`：
  ```python
  ACTION_ORDER: tuple[str, ...]            # 登記順序：平手時的最後一個排序依據；新代號加在這裡
  TOP_ACTIONS = 3
  ACTION_TITLES_MAX = 4                    # 一件事列出的發現標題數；超過的以「另 N 項」表示
  ACTION_FOCUS_MAX = 2

  @dataclass(frozen=True)
  class TopAction:
      severity: Severity                   # 這件事裡最高的嚴重度
      short: str                           # 同代號中嚴重度最高那個發現的 action_short；沒有代號的發現用它的 title
      findings: tuple[int, ...]            # doc.findings 的索引，依嚴重度由高到低
      titles: tuple[str, ...]              # 前 ACTION_TITLES_MAX 個發現的標題
      titles_more: int
      focus: tuple[str, ...]               # 各發現非空的 action_focus，前 ACTION_FOCUS_MAX 句

  def group_actions(findings: Sequence[Finding]) -> tuple[TopAction, ...]: ...   # 全部的事，已排序
  def top_actions(findings: Sequence[Finding]) -> tuple[tuple[TopAction, ...], int]: ...  # 前 3 件、另有幾件
  def action_number(findings: Sequence[Finding]) -> dict[int, int]: ...  # 發現索引 → 它是第 1 頁的第幾件事（1 起算；不在前 3 的不在表裡）
  ```
  規則：相同 `action_code` 併成一件；`action_code is None` 的各自一件。排序：最高嚴重度 → 發現數多的在前 → `ACTION_ORDER` 的位置
  （不在表裡的代號與沒有代號的排最後，彼此依在 `findings` 中第一次出現的順序）。不看語言、不做翻譯。
- `LEAD_KPIS: Mapping[ReportType, tuple[str, ...]]`（`domain/conclusion.py`，放在 `CONCLUSION_KPIS` 旁）：

  | 報表 | 領頭 3 個（`Kpi.key`） |
  |---|---|
  | `security_risk` | `maturity`、`enforced_hosts_pct`、`pb_flows` |
  | `lateral_posture` | `assets_reachable`、`pivots`、`new_detections` |
  | `new_connections` | `new`、`admin`、`unmanaged_source` |
  | `unmanaged_endpoints` | `total`、`admin_sources`、`public` |
  | `traffic` | `flows`、`sources`、`destinations` |
  | `network_inventory` | `managed_hosts`、`hosts_missing_labels`、`apps` |
  | `app_summary` | `inbound_connections`、`outbound_connections`、`allowed_pct` |
  | `ven_status` | `managed`、`long_offline`、`sync_problems` |
  | `audit` | `high_risk`、`auth_failed`、`policy_provisions` |
  | `ransomware` | `rated_hosts`、`priority`、`safe_to_block` |
  | `readiness` | `apps`、`ready`、`predicted_blocked` |
  | `policy_usage` | `rules`、`unused`、`no_rule` |
  | `rule_hit_count`（3b 併入規則使用前仍獨立） | `rules`、`hit`、`zero` |
  | `policy_diff` | `total`、`rules`、`high` |

  `policy_resolver`、`custom` 不在表裡（沒有第 1 頁的數字列）。
- `finish(doc)` 多做一件事：重點數字重排——`LEAD_KPIS` 裡**報表實際有的**那幾個依表的順序在前，其餘照原本順序接在後面。
  某個領頭數字這份報表沒有（例：勒索報表只有一份清單時沒有 `priority`）就由後面的遞補，所以第 1 頁永遠是 `doc.kpis[:3]`。
  `rpt_quality_no_previous` 那一句的判斷不變。

- [ ] **Step 1: 寫失敗測試**
  - `tests/domain/test_report.py`：`caveats` 三句被拒；`action_code` 沒有 `action_short` 被拒；`host_keys` 的 key 不是欄 key 被拒、
    tuple 比 `rows` 長被拒；`host_section="nowhere"` 被拒；既有不帶新欄位的建構照過。
  - `tests/domain/test_actions.py`：
    - 六個發現（`enforce`×3：高、中、中；`narrow_rules`×1 嚴重；無代號×1 高；`unmanaged`×1 中）→ 順序是 `narrow_rules`、`enforce`、無代號那個、`unmanaged`；
      `top_actions` 回前 3 件與 `1`。
    - 同嚴重度同發現數時依 `ACTION_ORDER`。
    - 每個發現的索引在 `group_actions` 的結果裡恰好出現一次（對任意輸入：用 6–8 組手寫輸入，含空輸入、全部沒有代號、全部同一個代號）。
    - 一件事有 6 個發現：`titles` 4 個、`titles_more == 2`；`focus` 最多 2 句、跳過空字串。
    - `short` 取同代號中嚴重度最高那個發現的 `action_short`。
    - `action_number`：第 4 件事裡的發現不在回傳的表裡。
  - `tests/services/reports/test_generate.py`（或 `finish` 現有的測試檔）：`finish` 之後 `kpis[:3]` 的 key 符合表；缺一個領頭數字時由後面的遞補；
    其餘數字的相對順序不變；`LEAD_KPIS` 沒有的型別順序不動。
  - `LEAD_KPIS` 的每個 key 都是該型 builder 真的會產生的 key：對 `tests/services/reports` 現有 fixture 建出的每型文件斷言
    （找不到可用 fixture 的型別，改成斷言該 key 字面出現在 builder 原始碼，並在回報列出是哪幾型）。
- [ ] **Step 2: 跑測試確認失敗**（缺欄位、缺模組）。
- [ ] **Step 3: 實作**，並在 `domain/report.py` 開頭的長度說明補上：`caveats` 最多 2 句；一件事列 4 個發現標題、其餘以數量表示。
- [ ] **Step 4: 跑 `tests/domain` 與 `tests/services/reports`，全過。**
- [ ] **Step 5: commit** `feat(v6-reports): findings carry what to do as a code, a report has what to know before its numbers, the three lead numbers come first`

---

### Task 2: 19 條規則——行動代號、為什麼要緊、全部列出

**Files:**
- Modify: `illumio_ops/domain/findings_rules.py`、`illumio_ops/services/reports/findings.py`、
  `illumio_ops/services/reports/{security_risk,traffic,app_summary,network_inventory}.py`、`illumio_ops/i18n/{en,zh_TW}.json`
- Test: `tests/services/reports/test_findings.py`、`test_security_risk.py`、`test_traffic.py`、`test_app_summary.py`、`test_network_inventory.py`、
  `tests/services/reports/test_report_i18n.py`

**Interfaces:**
- `RuleInfo` 加 `why_key: str`（`rpt_rule_<id>_why`，字面寫出，i18n 閘門才算用到）。
- `ACTION_CODES: Mapping[tuple[str, str], str]`（`domain/findings_rules.py`）：`(rule_id, rec_key) → 代號`。

  | 代號 | `action_short`（zh） | (規則, 建議句的 key) |
  |---|---|---|
  | `enforce` | 把還在「只記錄、不擋」的主機切到開始擋。 | B001 `rec_pb`、B001 `rec_pb_cross_env`、B003、B006 `rec_pb`、L005 `rec_pb`、L008 |
  | `cross_env_rules` | 移除或收斂允許跨環境連線的規則。 | B001 `rec_critical_cross_env`、B009、L004、L010 |
  | `narrow_rules` | 把允許管理、資料庫、身分 port 的規則收斂到需要的來源。 | B001 `rec_allowed`、B002、B006 `rec_allowed`、L003、L005 `rec_allowed`、L006 |
  | `write_rules` | 替確認過的流量補上規則。 | B005 |
  | `unmanaged` | 查清非受管來源是誰；該納管的裝上 VEN。 | B004、L007 |
  | `accounts` | 向帳號擁有者確認連到很多台主機的帳號。 | B007 |
  | `transfers` | 查清傳輸量異常大的連線。 | B008、L009 |
  | `legacy_protocols` | 停用明文協定與網路探索協定。 | L001、L002 |

  `ACTION_ORDER`（Task 1）先依上表的順序。`action_short` 的 key：`rpt_act_<代號>`。
- `RuleOutcome` 加 `focus: str = ""`：這條規則「最多的那一個」，由規則函式取它已經在跑的那個排名查詢的第一列，**不是**把組好的字串用逗號切開
  （主機名稱可以有逗號）。哪條規則取什麼：

  | 規則 | focus 的值 |
  |---|---|
  | B001、B002、B003、L004 | 連線最多的目的端（`top_destinations` 的第一個） |
  | B004、B006、L007 | 第一個來源（`top_sources`） |
  | B007 | 第一個帳號 |
  | B008 | 傳輸量最大的那一組（來源 → 目的端 服務） |
  | B009、L010 | 第一組環境（A → B） |
  | L003 | 第一個目的端與服務 |
  | L006 | 可觸及最多主機的那一台 |
  | L008 | 第一個目的端 app |
  | L009 | 第一個目的端 |
  | B005、L001、L002、L005 | 空（沒有「誰」） |

  `Finding.action_focus` = `tr("rpt_act_focus", finding=<規則名稱>, top=<focus>)`，zh「{finding}：最多的是 {top}。」；focus 空就留空。
- `as_findings(outcomes, lang) -> tuple[Finding, ...]`：拿掉 `limit`；回所有觸發的規則（已依嚴重度排）。每個發現：
  `title`＝規則名稱、`what`＝`desc_key` 的句子（事實）、`why`＝`why_key` 的句子、`action`＝`rec_key` 的句子、`action_code／action_short／action_focus` 如上。
- `rest_sections(...)` 改成 `unevaluated_section(outcomes, lang, *, title, intro, table_title, evaluated=True) -> tuple[Section, ...]`：
  只列沒能評估的規則（`severity is None`）。都評估了回空；規則根本沒跑（沒有符合的流量，`evaluated=False`）時照舊留下這一章說明。
  `rpt_rules_rest_intro` 不再使用，從兩個語言檔刪掉。
- 四個 builder 拿掉 `KEY_FINDINGS`。安全風險：`findings=as_findings(outcomes 中觸發的全部, lang)`；`critical_high_findings` 的算法（`len(fired)`）不動。
- 19 句「為什麼要緊」（zh；en 依同一個意思寫，取材自現有的 `rpt_rule_<id>_how` 英文句，不得加入原句沒有的主張）：

  | 規則 | `rpt_rule_<id>_why`（zh） |
  |---|---|
  | B001 | 勒索軟體就是經由這幾個 port（SMB、RPC、RDP、WinRM）在網路裡一台傳一台。 |
  | B002 | 這些遠端存取 port 能讓人從外面持續控制一台主機。 |
  | B003 | 沒有規則允許這些連線；現在會通，只因為目的端還沒開始擋。 |
  | B004 | 非受管主機沒有 VEN，沒辦法對它套用任何分段規則。 |
  | B005 | 沒有規則允許的流量，在主機開始擋之後會被擋下；比例低表示分段還在初期。 |
  | B006 | 一台主機用管理 port 連到很多台，是蠕蟲擴散與入侵後跳板的典型樣子。 |
  | B007 | 同一個帳號連到很多台主機，是自動化偵察與撞庫常見的樣子；是否為預期作業要向帳號擁有者確認。 |
  | B008 | 突然出現的大量傳輸，是資料被集中或外傳時會出現的樣子；是否為預期作業要對照用途確認。 |
  | B009 | 環境之間的連線越多，一個環境出事時越容易波及另一個。 |
  | L001 | Telnet 與 FTP 以明文傳送帳號與密碼，網路上的任何人都能讀到。 |
  | L002 | 這些探索協定能被用來冒充主機名稱並取得帳號的雜湊，不需要任何認證。 |
  | L003 | 資料庫應該只讓自己的 app 連；連得到的 app 越多，一次橫向移動就越可能直接拿到資料。 |
  | L004 | 環境邊界一旦被跨過，低安全等級環境裡的人可以直接讀到 Production 的資料。 |
  | L005 | Active Directory 是網域的認證核心；能連到它的 app 越多，網域被列舉與接管的機會越大。 |
  | L006 | 拿下這台主機，就能經由已允許的管理 port 走到它連得到的所有主機。 |
  | L007 | 非受管主機不受 PCE 控制；它連得到關鍵服務，就是一個不受控的入口。 |
  | L008 | 這些路徑沒有規則允許；在主機開始擋之前，每一條都是現在就能用的橫向移動路徑。 |
  | L009 | 報表只看得到傳輸量與目的端；是否為資料外洩，要對照主機上的程式與用途確認。 |
  | L010 | 管理 port 能跨環境，一個環境被入侵就會打開其他環境。 |

- [ ] **Step 0: 先讀 `tests/services/reports/test_report_i18n.py` 與 `test_report_copy.py`**（它們對每型報表的輸出檢查沒有漏翻的 key、中文版沒有英文句子）；
  新文案要過這兩支，不是改它們。
- [ ] **Step 1: 寫失敗測試**（`test_findings.py`）
  - `findings.py` 裡每一個以字面出現的 `(規則, rec_key)` 都在 `ACTION_CODES`（以 AST 或正則掃 `RuleOutcome("B001", …, "rpt_rule_b001_rec_…"` 與 `_simple(...)` 的引數；
    測試本身先對一個少登記的假表確認會紅）。`ACTION_CODES` 的每個代號都在 `ACTION_ORDER`，都有 `rpt_act_<代號>` 兩個語言的句子。
  - 19 條規則都有 `why_key`，兩個語言都有值，且 zh 過用語閘門。
  - 用現有的 findings fixture 觸發超過 5 條規則：`as_findings` 回全部；每個發現的 `what`、`why`、`action`、`action_code`、`action_short` 都不空；
    B001 在「跨環境且已允許」「同環境已允許」「只有 Potentially Blocked」三種資料下分別得到 `cross_env_rules`、`narrow_rules`、`enforce`。
  - `focus` 來自查詢的第一列：造一台名稱含 `, ` 的主機當最大的目的端，B001 的 `action_focus` 含完整名稱。
  - `unevaluated_section`：全部評估過 → 空；L006 沒有暴露面分析（輕量模式）→ 一章、一列；沒有流量 → 一章，說規則沒有執行。
  - 四個 builder 的測試：發現數等於觸發的規則數；安全風險含中、低嚴重度的發現時 `critical_high_findings` 的值與改前相同。
- [ ] **Step 2: 跑測試確認失敗。**
- [ ] **Step 3: 實作。** `_Run.top` 可改成同時回傳第一列（或加一個 `first()`），但每條規則不得為了 focus 多跑一次全表查詢。
- [ ] **Step 4: 跑 `tests/services/reports tests/i18n`，全過；修掉因「前 5 個」而寫死的既有斷言（改成新行為，不是放寬）。**
- [ ] **Step 5: commit** `feat(v6-reports): every rule that fired is a finding with what it found, why it matters and the action it belongs to`

---

### Task 3: 其餘 builder 的發現——事實與理由分開、行動代號

**Files:**
- Modify: `illumio_ops/services/reports/{policy_usage,rule_hit_count,policy_diff,audit,readiness,lateral_posture,new_connections,unmanaged,ven_status,ransomware_report}.py`、
  `illumio_ops/domain/actions.py`（`ACTION_ORDER` 加新代號）、`illumio_ops/i18n/{en,zh_TW}.json`
- Test: 各 builder 現有的測試檔、`tests/domain/test_actions.py`

`policy_resolver` 只出 JSON／CSV，不動。`custom` 沒有發現。

**Interfaces:** 每個建 `Finding` 的地方依下表加 `action_code` 與 `action_short`（key：`rpt_act_<代號>`）。

| builder | 發現 | 代號 | `action_short`（zh） |
|---|---|---|---|
| policy_usage | 沒有流量使用的規則 | `unused_rules` | 確認沒有流量使用的規則是否還需要；不需要的停用。 |
| rule_hit_count | 命中 0 次的 Allow 規則 | `unused_rules` | （同上，共用） |
| policy_usage、rule_hit_count | 待 Provision 的規則 | `pending_policy` | 把待 Provision 的變更確認後 Provision，或捨棄。 |
| policy_diff | 其他待 Provision 的項目 | `pending_policy` | （同上，共用） |
| policy_diff | 放寬範圍／停用規則的變更（最多 `HIGH_FINDINGS` 個） | `risky_change` | Provision 前逐一確認會放寬範圍或停用規則的變更。 |
| audit | 需要注意的事件類型（最多 `ATTENTION_FINDINGS` 個） | `review_events` | 向做這些操作的人確認是不是預期的。 |
| audit | 登入失敗後隨即變更政策 | `failed_then_change` | 確認登入失敗後隨即變更政策的帳號是不是本人。 |
| readiness | 還不能切的 app | `write_rules` | （Task 2 的句子，共用） |
| lateral_posture | 偵測／可觸及的重要資產／跳板主機／跨環境（`FINDING_KINDS` 四種） | `lat_detection`、`lat_exposure_asset`、`lat_pivot_host`、`lat_cross_env` | 依序：查看橫向移動偵測到的異常。／收斂連得到重要資產的管理 port 規則。／收斂跳板主機的管理 port 連線。／確認跨環境的管理 port 連線是否需要。 |
| new_connections | 每種服務一個發現（最多 5 個） | `new_connections` | 確認新出現的連線是不是預期的；不是的補上規則或查來源。 |
| unmanaged | 使用管理 port 的非受管端點（最多 5 個） | `unmanaged` | （Task 2 的句子，共用） |
| ven_status | 失聯／無法解釋的竄改／同步問題／相容性 | `ven_offline`、`ven_tamper`、`ven_sync`、`ven_compat` | 逐台確認失聯的 VEN：主機關機、除役，或 VEN 連不到 PCE。／查清無法由政策變更解釋的防火牆竄改。／處理政策同步有問題的 VEN。／處理相容性檢查沒有通過的主機。 |
| ransomware | 優先處理／無法分類／可以直接擋 | `rw_priority`、`rw_unsorted`、`rw_safe` | 先收斂任何來源都連得到、而且有人在連的高風險服務。／補上流量資料，才能替高風險服務分類。／把近期沒有人連的高風險服務直接擋下。 |

- 規則（implementer 逐一讀每個發現現有的 `action` 句）：上表的一句話必須是那個 `action` 句所說的同一個行動的短版。若讀了之後發現不是
  （例如 `pending_policy` 在某份報表其實是「等待」而不是「去 Provision」），**改用自己的代號與句子，並在回報列出**，不要硬套。
- 事實與理由：現有 `why` 一欄有的裝事實、有的裝理由。逐一處理：
  - 整句是事實（例 `rpt_aud_finding_why`「相關使用者：{actors}。」）→ 移到 `what`；`why` 用一句新的固定理由（新 key）。
  - 事實＋理由連在一起（例 `rpt_ven_find_offline_why`：前半是三個數字、後半是「失聯的 VEN 收不到政策更新…」）→ 拆成兩個 key。
  - 整句是理由（例 `rpt_rw_finding_priority_why`）→ 不動，`what` 留空。
  - 拆完後不留死鍵；每個新句子過用語閘門與文字規則。把每個發現「原句 → what／why」的對照列在回報裡。
- `action_focus`：有明確「最多的那一個」而且 builder 手上已經有的才填（new_connections：第一組來源 → 目的；unmanaged：該端點位址；
  ven_status 失聯：失聯最久的那台）；其餘留空。

- [ ] **Step 1: 在各 builder 的測試加斷言**：每個發現有 `action_code` 與非空的 `action_short`；同一份報表中同代號的發現被 `group_actions` 併成一件
  （new_connections 造 3 種服務的新連線 → 第 1 頁是一件事、三個標題）。先跑確認失敗。
- [ ] **Step 2: 實作；`ACTION_ORDER` 依上表順序接在 Task 2 的八個之後。**
- [ ] **Step 3: 一支總測試**：`tests/services/reports` 現有每型的 fixture 文件中，凡 `action_code` 不是 `None` 的發現，代號都在 `ACTION_ORDER`。
- [ ] **Step 4: 跑 `tests/services/reports tests/i18n tests/domain`，全過。**
- [ ] **Step 5: commit** `feat(v6-reports): the other reports' findings say what happened apart from why, and name their action`

---

### Task 4: 讀數字前先知道（收集缺口）

**Files:**
- Modify: `illumio_ops/services/reports/generate.py`、呼叫 `coverage_note` 的每個 builder（`app_summary、security_risk、readiness、network_inventory、
  lateral_posture、new_connections、unmanaged、traffic、custom`）、`audit.py`、`illumio_ops/i18n/{en,zh_TW}.json`
- Test: `tests/services/reports/test_generate.py`、`test_audit.py`、`test_archive_reports.py`

**Interfaces:**
- `coverage_text(ctx, start, end, lang, *, now, tz, flows=False) -> CoverageText`，`CoverageText(lines: tuple[str, ...], caveats: tuple[str, ...])`。
  `lines` 就是現在 `coverage_note` 回的東西（`coverage_note` 留著、改成呼叫它）。`caveats`：期間內有缺口時一句
  `rpt_caveat_gaps`（zh「期間內有 {n} 段、共 {hours} 小時沒有收集到資料；明細在最後的「資料註記」。」），`n` 與 `hours` 算**全部**缺口
  （不是只算列出的前 `MAX_GAP_LINES` 段）；小時取到小數一位。沒有缺口是空 tuple。
- 每個 builder：`cov = coverage_text(...)`，`data_quality` 照舊用 `cov.lines`，`ReportDocument(caveats=cov.caveats, …)`。
- `audit`：事件的收集缺口（`counts.coverage.gaps`）用同一句。
- `_build`：從封存讀而且有缺日（`res.missing_days`）時，在還沒滿 2 句的前提下加一句 `rpt_caveat_archive_missing`
  （zh「期間內有 {n} 天的封存讀不到；明細在最後的「資料註記」。」）。
- 3a 只有這兩種。3b 才加「沒有判定的流量」那一句；到時超過 2 句的取捨在 3b 的計畫裡定。

- [ ] **Step 1: 寫失敗測試**：兩段缺口共 5.5 小時 → 一句、數字正確；12 段缺口 → `n=12`（`lines` 仍只列 10 段加「另有 2 段」）；
  沒有缺口 → 空；封存缺日 → 第二句；audit 的事件缺口 → 一句。
- [ ] **Step 2–4: 確認失敗、實作、跑 `tests/services/reports` 全過。**
- [ ] **Step 5: commit** `feat(v6-reports): a gap in what was collected is said under the conclusion, in one sentence`

---

### Task 5: 白話用語與表格裡的主機鍵

**Files:**
- Modify: `illumio_ops/i18n/{en,zh_TW}.json`、`illumio_ops/services/reports/common.py`、`illumio_ops/services/reports/{flowsections,new_connections,unmanaged,
  lateral_posture,app_summary,security_risk,readiness,ven_status,ransomware_report,network_inventory}.py`、`web/src/terms.ts`、
  `web/src/components/ConditionEditor.tsx`、`web/src/pages/siem/Siem.tsx`、`web/src/pages/workbench/Predicted.tsx`、`web/src/pages/alerts/ruleSummary.ts`、
  以及清查出來的其他位置
- Test: `tests/i18n/test_terminology.py`、`tests/services/reports/test_report_i18n.py`、`tests/services/reports/test_report_copy.py`、各 builder 測試、
  `tests/e2e`（畫面上判定字樣的既有斷言）

**用語（使用者 2026-11-12 同意三個中文說法；英文與套用範圍是我的決定）：**

| key | zh_TW | en |
|---|---|---|
| `term_decision_allowed` | 有規則允許（Allowed） | Allowed (a rule allows it) |
| `term_decision_potentially_blocked` | 開始擋之後會被擋（Potentially Blocked） | Potentially Blocked (blocked once enforcement starts) |
| `term_decision_blocked` | 已被擋下（Blocked） | Blocked |

- 固定規則，不是「第一次出現才帶」：**當作名稱的地方**用上表（表格裡的判定值、判定的篩選選項與勾選項、狀態標籤、欄名、數字名稱、章節與表格標題）；
  **句子裡**維持 PCE 的原文（現有二十多句 `rpt_*` 與畫面提示不改寫）。`decision_unknown` 不動（3b 處理）。
- 做法：四個報表模組的 `DECISION_KEYS`／`EDGE_STATE_KEYS` 與四個前端檔的對照表改指向 `term_decision_*`；`web/src/terms.ts` 加 `decisionWord(decision)`
  （同 `modeWord`），前端四處改用它。`decision_allowed／decision_potentially_blocked／decision_blocked` 三個舊鍵若不再有人用就刪掉。
- 名稱類的字串逐一改（清查方式：兩個語言檔裡不分大小寫找 `potentially blocked`、`allowed`、`blocked`，把「整個值就是名稱」的挑出來；句子不動）。
  名稱裡也帶 PCE 的原文。至少包含：`rpt_sec_kpi_pb_flows`（→「開始擋之後會被擋的流量（Potentially Blocked）」）、`rpt_sec_sec_pb`、`rpt_sec_tbl_pb`、`lat_state_potentially_blocked`、
  `wb_pred_pb_by_boundary`、`wb_pred_pb_by_override_deny`，以及 `rpt_sec_kpi_allowed_pct` 與 blocked 流量的數字名稱。完整清單（改了哪些、哪些因為是句子而不改）列在回報。
- `tests/i18n/test_terminology.py` 的 docstring 與「判定值寫 Allowed／Blocked」那一條的說明更新成現在的規則（名稱處是白話＋括號原文，句子裡是原文），
  規則本身（禁用的寫法）不放寬。
- 模式：`common.py` 加 `mode_word(lang, mode) -> str`，回 `term_mode_*` 的句子（不認得的模式照原樣）。報表表格裡印模式的地方全部改用它
  （`app_summary` 的主機表現在直接印 `visibility_only` 這種原始值；`ven_status` 的 `_MODE_KEYS`、`security_risk` 與 `readiness` 的模式分布表一併對齊）。
- 欄寬：這些說法比原文長。Task 6 的版面與 `tests/e2e/test_report_table_fit.py` 要用最長的說法量過（en 的 Potentially Blocked 那一句最長）。
- XLSX 的欄名與判定值跟著同一組 key 走（它讀同一份文件，不必另外處理）；JSON／CSV 的鍵與值不動（`RowsExport` 不經過這些 key，確認後寫進回報）。

**主機鍵：**
- 每張有主機欄的表填 `TableBlock.host_keys`（只帶前 `HTML_ROW_CAP` 列）與 `host_section`：

  | builder | 表 | `host_section` |
  |---|---|---|
  | lateral_posture | 現有 9 個 `kind="host"` 的欄（資產、主機、對象、來源、目的、伺服器） | `connections` |
  | new_connections | 來源、目的欄（3 處） | `connections` |
  | network_inventory | Label 衝突表的主機欄 | 不填 |
  | ven_status | 線上／失聯／同步／竄改各表的主機欄 | `status`（竄改表 `tamper`） |
  | ransomware | 主機清單各表 | `ransomware` |
  | unmanaged | 端點位址欄（鍵是 `ip:<位址>`） | `connections` |
  | app_summary | 主機表 | 不填 |
  | security_risk、readiness、traffic 中列出單一主機的表 | 有鍵的才填 | 不填 |

  欄若現在不是 `kind="host"` 而實際是主機名稱，改成 `kind="host"`。builder 手上只有名稱、沒有鍵的欄不填（照舊是文字），在回報列出是哪些。
- 只有主機頁打得開的鍵才會變成連結（workload href `/orgs/<n>/workloads/…` 或 `ip:`，同前端 `HostLink` 的 `OPENS`）；其他鍵（容器 workload 等）填了也不連。
  判斷放在 renderer（Task 6），builder 只管照實填鍵。

- [ ] **Step 1: 測試**：`mode_word` 兩個語言四個模式；每個 `term_decision_*` 過用語閘門；`lateral_posture`、`new_connections`、`ven_status`、`unmanaged`
  的 fixture 文件中指定的表有 `host_keys`，長度等於 `min(len(rows), HTML_ROW_CAP)`，而且第 n 個鍵解析出來的名稱等於那一格的文字（鍵與列對得上）。
  `finish()` 拿掉一個空欄之後 `host_keys` 仍通過模型驗證（被拿掉的欄若有鍵，一併拿掉：改 `finish._without_empty_columns`）。先跑確認失敗。
- [ ] **Step 2: 實作；`npm --prefix web run typecheck`；改掉 e2e 與單元測試中寫死舊字樣的斷言。**
- [ ] **Step 3: 跑 `tests/i18n tests/services/reports`，再跑 `tests/e2e/test_workbench_e2e.py tests/e2e/test_siem_e2e.py tests/e2e/test_predicted_e2e.py tests/e2e/test_lateral_e2e.py tests/e2e/test_ui_rules_e2e.py`
  （較長的說法不得讓標籤折行或溢出：第 1 段的十條規則照過）。**
- [ ] **Step 4: commit** `feat(v6): a policy decision is said in plain words beside the PCE's own, on the console and in reports; report tables know which host each row names`

---

### Task 6: HTML——第 1 頁、發現卡片、最後一部分、紙本、主機連結

**Files:**
- Modify: `illumio_ops/services/reports/render_html.py`、`illumio_ops/services/reports/assets/report_shell.css`（只在必要時；新樣式優先放 `EXTRA_CSS`）、
  `illumio_ops/domain/report.py`（保留的章節 id）、`illumio_ops/i18n/{en,zh_TW}.json`
- Test: `tests/services/reports/test_render_html.py`、`tests/e2e/test_report_table_fit.py`、`tests/e2e/test_reports_e2e.py`

**版面（由上到下；`data-role` 是測試與驗收的定位點）：**

1. 封面：標題、PCE／期間／產生時間。頂線顏色照舊（全部發現的最高嚴重度）。含中文的標籤不拉字距（`letter-spacing: 0`；現況「期 間」）。
2. `conclusion`（現有）。
3. `data-role="caveats"`：`doc.caveats` 每句一行，標題「讀數字前先知道」；沒有就整塊不出現。
4. `data-role="lead-kpis"`：`doc.kpis[:3]`，等高、排滿一列（窄螢幕與紙本直向時仍是一列三格；820px 以下改成一欄）。每格四行：
   名稱／數值（`None` → 現有的「無資料」，其 `note` 寫原因）／與上期的變化／方向。
   - 變化：`previous is None` → 這一行不寫；相同 → 現有 `rpt_kpi_flat`；不同 → 新句 `rpt_kpi_more`／`rpt_kpi_fewer`
     （zh「比上期多 {amount}」「比上期少 {amount}」；百分比的單位是「個百分點」）。現有的 `rpt_kpi_delta`（箭頭）若不再有人用就刪。
     XLSX 的「變化」欄用同一個函式。
   - 方向：`better == "higher"` →「越高越好」，`"lower"` →「越低越好」，`"neutral"` → 不寫。
   - `note` 放格子下方的註記列（`data-role="lead-notes"`，每句前帶數字名稱），不放在格子裡，三格才會等高。
   - 沒有任何重點數字（自訂報表、什麼都沒算出來）→ 整塊不出現。
5. `data-role="top-actions"`：標題「最該做的 {n} 件事」（n 是實際列出的件數，1–3）。每件：序號、嚴重度標籤、`short`、
   「解決 {n} 項發現：〈標題〉、〈標題〉…」（最多 4 個標題，其餘「另 {n} 項」；每個標題連到下方對應的卡片）、`focus` 的句子（最多 2 句）。
   - 超過 3 件：最後一行「另有 {n} 件，見下方的發現。」
   - 沒有發現、而且規則都評估過（或這份報表不跑規則）：現有的 `rpt_findings_none` 一句，沒有清單。
   - **不得把「沒評估」說成「沒事」**：文件有 `findings` 章（有規則沒能評估，或規則根本沒跑）時，這一塊的最後加一句
     `rpt_actions_unevaluated`「有 {n} 條規則沒能評估，見〈{section}〉。」並連到那一章；規則完全沒跑（沒有符合的流量）而且沒有任何發現時，
     只寫 `rpt_actions_not_run`「這段期間沒有流量可以評估規則，見〈{section}〉。」，**不寫**「本期沒有需要處理的項目」。
     判斷依據：`doc.sections` 裡有 id 為 `findings` 的章；`n` 是那張表的列數，表是空的（規則沒跑）就用第二句。
     輕量模式下 L006 一律沒能評估（沒有暴露面分析），所以 .135 的每份流量類報表都會走到這裡。
   - 自訂報表（`ReportType.CUSTOM`）：不出這一塊，也不出發現卡片；第 1 頁只有結論與目錄。
6. `data-role="findings"`：每個發現一張卡片（`data-role="finding"`、`id="finding-<n>"`、`data-severity`），依嚴重度排，全部列出（不設上限：最多 19＋builder 自己的）。
   卡片三段固定、各有小標：**發生什麼**（`title` 為卡片標題；`what` 非空才有內文）、**為什麼要緊**（`why`；空就不出現這一段）、
   **怎麼做**（它屬於第 1 頁的第 N 件事時，前面一句「見上方第 {n} 件事。」，再接 `action`）。MITRE 代號在卡片底部（現有的 chips）。
   紙本：卡片 `break-inside: avoid`。
7. `data-role="other-kpis"`：`doc.kpis[3:]`，沿用現有的小格（含 note）；變化那一行與領頭格、XLSX、郵件用同一個函式（`kpi_trend`，改成新句子），
   全份報表不再有箭頭版；沒有就不出現。
8. 目錄，再來是章節。**章節順序**：一般章節 → 「怎麼讀這份報表」這一部分。這一部分的內容依序是：
   - builder 的 `how` 章（有的才有；7 型有）。
   - `notes` 章「資料註記」：`doc.data_quality` 的清單（從摘要搬來；現在的「資料品質」標題改成這個）。
   - `nothing` 章「本期沒有內容的章節」（`finish` 產生的，有才有）。
   `notes` 是 renderer 產生的章，`ReportDocument._ids` 把 `notes` 也列為保留 id。目錄與章節編號照實際順序；這一部分在目錄與正文各有一個分隔標題「怎麼讀這份報表」。
   `findings` 章（沒能評估的規則）排在一般章節的最後、這一部分之前。

**紙本只印前 10 列：**
- 常數 `PRINT_ROW_CAP = 10`（`domain/report.py`，長度說明補一行）。螢幕上列出超過 10 列的表：`<table data-print-cap="10">`，
  `@media print { table[data-print-cap] tbody tr:nth-child(n+11) { display: none; } }`（以位置而不是以原始列號隱藏：讀者在螢幕上排序後列印，印的是排序後的前 10 列）。
- 表下一句只在紙本出現（`class="print-only"`，螢幕 `display:none`）：
  - 有 XLSX：`rpt_print_capped`「列印只列前 10 列，共 {total} 列；完整內容在 XLSX 的〈{sheet}〉分頁。」
  - 沒有 XLSX：`rpt_print_capped_no_xlsx`「列印只列前 10 列；螢幕上的這份報表列到前 {shown} 列，共 {total} 列。」
  `total` 是 `len(t.rows)`。螢幕上原有的截斷說明（`rpt_rows_capped` 等）螢幕與紙本都照舊顯示。
- `html_rows` 小於 10 的表、列數不超過 10 的表：不加這個屬性、不加這一句。
- 「怎麼讀這份報表」那一部分的表（`how` 章的評分因子、等級、名詞表）是說明，不是資料：不套這個上限，紙本全部印出。
- 紙本其他規則：封面、第 1 頁、發現接續排版，不強制分頁（拿掉 shell 裡對 `.exec`、`.toc` 的強制分頁，若有）；章節之間只用 `break-inside: avoid` 與
  `break-after: avoid`（標題不與內容分開）；表格跨頁重複表頭（現有）。

**主機連結：**
- `host_url(base, key, section) -> str | None`（`render_html.py` 或 `common.py`）：`key` 不符合 `^(/orgs/\d+/workloads/|ip:)` 或沒有 `base` → `None`；
  否則 `f"{base}/hosts?{urlencode({'key': key})}" + (f"#{section}" if section else "")`。與前端 `hostPath` 產生的網址一致
  （測試：三個鍵對照寫死的預期字串，其中一個含 `:` 與 `/`）。
- `_table`：某欄在 `host_keys` 裡、該列有鍵、`host_url` 不是 `None` → 該格是 `<a data-role="host-link" href="…">名稱</a>`；否則照舊是文字。
  拿掉「每列都一樣的欄」（`_said_once`）與只取前 N 列時，連結仍以欄的 key 與列號對應。
- 沒有對外網址時：全部是文字；`data_quality` 已有的那一句（`rpt_cust_no_links` 類）沿用到有主機表的報表——由 renderer 之外的 `finish()` 補：
  文件有任一 `host_keys` 而 `gui_base` 為空時加一句 `rpt_quality_no_host_links`「沒有設定主控台的對外網址，所以報表裡的主機名稱不是連結。」
  （`gui_base` 在 `finish` 之後才填的話，把這一步放在填完之後；順序由 implementer 依 `generate.py` 現況安排，測試釘住結果）。
- 收信開附件的人多半還沒登入主控台：確認未登入時點連結，登入後仍回到同一個網址（`?key=` 與 `#段落` 都在）。現況若會掉，在這個 task 修
  （登入頁保留原網址），並加 e2e。
- 報表不放隔離按鈕。

- [ ] **Step 1: 寫失敗測試**（`test_render_html.py`；斷言渲染出來的文字與結構，不是 class 名稱的存在）
  - 順序：conclusion → caveats → lead-kpis → top-actions → findings → other-kpis → toc → 章節；「怎麼讀這份報表」的三章在最後且依 how、notes、nothing 的順序；
    目錄的順序與章節相同。
  - 5 個數字的文件：lead 3 格、other 2 格；1 個數字：lead 1 格、沒有 other；0 個：兩塊都沒有。
  - 變化與方向：`previous=None` 的格子沒有變化那一行；相同 →「與上期持平」；多 2,823 →「比上期多 2,823」；`better="lower"` →「越低越好」；`neutral` 沒有方向。
  - 6 個發現、4 件事：top-actions 列 3 件與「另有 1 件」；每個發現卡片都在；屬於第 2 件事的卡片寫「見上方第 2 件事」；第 4 件事的卡片沒有這一句。
  - 一件事 6 個發現：4 個標題＋「另 2 項」。沒有發現：一句、沒有清單、沒有卡片。
  - 有 2 個發現、另有 1 條規則沒能評估：三件事之外多一句「有 1 條規則沒能評估」且連到 `#findings`。沒有發現、規則沒跑：只有「沒有流量可以評估規則」那一句，
    頁面上沒有「本期沒有需要處理的項目」。自訂報表：沒有 top-actions、沒有 findings 區塊。
  - `what` 與 `why` 為空的發現：卡片沒有空的小標。
  - 12 列的表：`data-print-cap`、有 print-only 的句子且 `total=12`；10 列的表沒有；`html_rows=5` 的表沒有；沒有 XLSX 時用另一句。
  - 主機連結：有 `gui_base` → 連結的 href 等於 `host_url` 的值、含 `#status`；沒有 → 沒有 `<a data-role="host-link">`；鍵是容器 workload → 文字；
    `_said_once` 拿掉一欄後，其餘欄的連結仍指向同一列的主機。
  - 跳脫：`what`、`action_focus`、`caveats`、主機名稱含 `<script>` 時都被跳脫。
  - `test_no_external_requests`、`test_html_is_self_contained` 照過。
- [ ] **Step 2: 跑測試確認失敗；實作。**
- [ ] **Step 3: e2e（`tests/e2e/test_report_table_fit.py`，print media）**：
  - 一張 30 列的表：`page.emulate_media(media="print")` 後可見的 `tbody tr` 是 10 列，print-only 的句子可見；`media="screen"` 是 30 列、句子不可見。
    先把 CSS 規則拿掉跑一次確認測試會紅，再放回去。
  - 19 張卡片、每張內文三行以上的文件：`page.pdf()` 產生的頁數與「內容高度 ÷ 頁高」相符（沒有只印標題的頁、沒有空白頁）；
    以 `getBoundingClientRect` 在 print media 下確認沒有卡片跨越分頁線（A4 直向）。
  - lead-kpis 三格在 1440、820、A4 print 三種寬度下等高（高度差 ≤ 1px）且沒有水平溢出；用最長的名稱（en 的 Potentially Blocked 那一句）量。
  - 產生一份 VEN 狀態報表（`tests/e2e/test_reports_e2e.py`），在報表頁面點第一個主機連結，落在主機頁、網址帶 `#status`、狀態段在畫面內。
- [ ] **Step 4: 跑 `tests/services/reports` 與上列 e2e，全過。**
- [ ] **Step 5: commit** `feat(v6-reports): the first page is for the reader who stops there; findings are cards; how to read it comes last; paper lists ten rows; a host leads to its page`

---

### Task 7: XLSX、郵件、範本頁

**Files:**
- Modify: `illumio_ops/services/reports/render_xlsx.py`、`illumio_ops/services/reports/render_email.py`、`illumio_ops/services/reports/views.py`、
  `web/src/pages/reports/Reports.tsx`、樣式檔、`illumio_ops/i18n/{en,zh_TW}.json`、`web/src/api/contracts.json`、`web/src/api/generated.ts`
- Test: `tests/services/reports/test_render_xlsx.py`、`test_render_email.py`、`tests/web`（catalog 路由）、`tests/e2e/test_reports_e2e.py`、`tests/e2e/ui_rules.py`

**XLSX**（版式不動）：摘要工作表在結論的位置之後多一段「讀數字前先知道」（有才有）；發現那幾列的欄位是
嚴重度／標題／發現（`what`，空的話留空）／為什麼要緊（`why`）／建議（`action`）／MITRE——比現在多一欄，表頭列照加（現在這一段沒有表頭：加上）。
「變化」欄用 Task 6 的新句子。其餘不動。

**郵件：** 內文依序：標題與期間、結論、讀數字前先知道（有才有）、3 個數字（`doc.kpis[:3]`；每個帶變化、方向、note）、
最該做的 3 件事（每件：嚴重度、`short`、「解決 N 項發現：…」；超過 3 件一句「另有 N 件」；沒有發現用 `rpt_findings_none`）、
`note`（附件因大小被拿掉的那一句，**保留**）、連結。
- 沒有對外網址時（沒有連結可以點）：現有的 `rpt_mail_no_link` 照舊，再加一句固定文字「完整的發現在附件的報表裡。」（有附件時）；
  附件也被拿掉時就是現有的 `note`。資料註記那一長串不再放進郵件（它在報表最後一章）；caveats 已經帶了最重要的那一句。
- 主旨的式子不動。純文字版與 HTML 版內容一致。

**範本頁**（使用者 2026-11-12 同意）：`CatalogEntry` 加 `tier: Literal["common", "topic"]`。3a 的常用：`security_risk`、`ven_status`、`new_connections`、`audit`
（每週總覽在 3b 加入並排第一）；其餘是專題。畫面由四欄改成上下兩段——「常用」「專題」各一個標題，卡片排成網格（1440 寬 3–4 欄、820 寬 1–2 欄）；
原本的四類（`ui_group`）變成每張卡片上的一個小標籤（`Tag tone="muted"`）。卡片內容與產生報表的流程不動；Rule Hit Count 卡片 3a 仍在（專題）。
- `data-role="report-catalog"` 保留；兩段各有 `data-tier`。第 1 段的十條呈現規則照過（`tests/e2e/test_ui_rules_e2e.py`）。

- [ ] **Step 1: 寫失敗測試**：XLSX 摘要頁的發現表頭與六欄、caveats 一段；郵件有三件事、沒有逐條發現與資料品質長串、`note` 仍在、沒有連結時的兩種說法；
  catalog 每個項目有 `tier`、常用恰好是那四型；e2e：範本頁兩段、常用四張卡片、每張卡片有類別標籤，1440 與 820 兩種寬度沒有溢出。
- [ ] **Step 2: 確認失敗、實作、`bash scripts/gen_contracts.sh`、`npm --prefix web run typecheck && npm --prefix web run build`。**
- [ ] **Step 3: 跑 `tests/services/reports tests/web tests/e2e/test_reports_e2e.py tests/e2e/test_ui_rules_e2e.py`，全過。**
- [ ] **Step 4: commit** `feat(v6-reports): the email is the first page; templates are the common ones, then the rest`

---

### Task 8: 版本、真資料驗收、部署

**Files:**
- Modify: `illumio_ops/__init__.py`（`6.9.0`）、版本號出現的其他位置（照 6.8.0 那次的 commit 找）、
  `docs/superpowers/specs/2026-11-11-v6-purpose-led-ui-design.md` §11（寫實際驗到什麼、沒驗到什麼）

這一個 task 由主對話（不是 subagent）執行，因為要碰兩台機器。

- [ ] **Step 0（Task 1 開始之前）: 留下改前的樣子。** 在 .106（6.8.0）產生有 HTML 的 15 型 × zh_TW，把 HTML 存到 scratchpad 當版面對照。不拿它比數字。
- [ ] **Step 1: 全套閘門**（`gates.sh`）全綠。
- [ ] **Step 2: 數字基準，然後部署 .106。** 部署前一刻，在 .106 以最近一段完整的 7 天（固定 `period_from`／`period_to`）產生 15 型，
  把每份的 `Kpi.key → value、previous`（`reports` 表存的 `kpis`）倒成 JSON 存到 scratchpad。接著打包（`scripts/build_bundle.sh`）並部署
  （`./install.sh --accept-report`）。
- [ ] **Step 3: 數字不變。** 部署後立刻以同一段期間再產 15 型，逐型比對 `key → value、previous`：除了順序之外必須完全相同。
  不同的每一個都逐一查明：是兩次產生之間資料真的變了（讀「現在」的數字，例如 VEN 在線台數；要拿得出是哪筆資料變了），還是程式改壞了。
  查不出資料原因的一律當缺陷，先修再往下。
- [ ] **Step 4: 逐份看**（專案報表規則）。15 型 × 2 語言，每份用 Playwright 開螢幕版（1440、820）與 print media（A4），逐份檢查並記錄：
  第 1 頁五塊是否齊全且沒有空框；三格等高；最長的中文與英文字串有沒有被切或溢出；超過 10 列的表在紙本是 10 列且有去處句；卡片沒有被切開；
  沒有只有標題的頁；主機連結點得進去且落在對的段；「怎麼讀這份報表」在最後。以程式量的項目（溢出、列數、等高、分頁）附數字，
  人眼看的項目寫明看了哪幾份。截斷與溢出的檢查結果附在回報裡。
- [ ] **Step 5: 郵件。** 在 .106 以一份有發現、一份沒有發現的報表各寄一次，確認收到的內容是 Task 7 的順序。
- [ ] **Step 6: 部署 .135**（輕量、英文）：產生它能產的型別，檢查英文版第 1 頁與較長的英文用語沒有撐破版面；1440／820 跑 `tools/ui_audit.py` 零違規。
- [ ] **Step 7: 更新規格 §11，commit；合入 main、推送、盯 CI**（長期授權；閘門全綠之後）。tag 等使用者同意。
