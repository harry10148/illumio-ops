# v6 告警規則頁改版（一個表單、內建規則當範本）Implementation Plan

**Goal:** `/alert-rules` 的「規則」分頁改成三張表（事件、流量、偵測與系統）＋頁面上方的一個規則表單；事件與流量規則的新增、編輯、
從內建範本帶入都用這個表單。偵測與系統檢查原樣保留。規則的資料模型、評估、內建規則包都不改。版本 6.13.0。

**Architecture:** 新元件放在 `web/src/pages/alerts/rules/`：`RulesPage.tsx`（頁面、三張表、搜尋、頁首）、`RuleForm.tsx`（四步表單）、
`EventCondition.tsx`（事件條件與挑選區）、`FlowCondition.tsx`（流量條件，包 `ConditionEditor`）、`model.ts`（不碰 DOM 的純函式：
編碼解碼、分組、比對、文字）。`RulesAndChannels.tsx` 的規則分頁改掛 `RulesPage`。舊 `Rules.tsx` 刪除；舊 `RuleEditor.tsx` 只留偵測與系統。
後端不改（`alert_rules.pack_rules`、`event_catalog`、`list`、`update`、`create`、`delete`、`preview`、`condition_choices` 都已存在）。

**Tech Stack:** React 19＋TypeScript＋Vite；pytest＋Playwright（`tests/e2e`；前端沒有單元測試框架，規格 §6 定為不加）；
i18n `illumio_ops/i18n/{en,zh_TW}.json`。

**Spec:** `docs/superpowers/specs/2026-11-18-v6-alert-rules-page-design.md`（`b8488bdf`）。§ 編號以下都指這份。
**樣張:** https://claude.ai/artifact/St3pKVr16tY1LuTVLdXomL（第 4 版）。

## Global Constraints

- 不改：`illumio_ops/domain/*`、`services/alerts/*`、既有 API 的請求與回應。若發現非改不可，停下回報。
- **存回不變**是第一優先：任何既有規則用新表單打開、不動、存回，送出的 JSON 與原本逐欄相同（§6）。不確定一個值能不能被控制項表示時，
  就原樣保留並顯示原文，不要正規化。
- 文字規則：每句話對得到資料或固定規則（[[ui-text-must-be-computable]]）；`Potentially Blocked` 不加解釋；不寫「已強制」。
  用語閘門 `tests/i18n/test_terminology.py` 與另外兩個詞彙檢查器。
- i18n 閘門只認 `t("key")`、`labelKey: "key"`、`message_key: "key"`；`t(` 裡不可用樣板字串；新鍵兩種語言都要有、佔位符一致；
  新的中文鍵若英文相同要釘 `zh_explicit`（照現有作法）。刪鍵時同時刪兩種語言。
- `ConditionEditor` 有非受控輸入（`defaultValue`＋`onBlur`）：範本帶入、還原預設、切換規則時用 `key` 讓它重新掛載；同一條規則編輯中不可重新掛載。
- 介面稽核 `tests/e2e/ui_rules.py` 對新頁（表單關、新增事件、新增流量、編輯內建）零違規，特別是每區一顆主要按鈕。
- 工作目錄 `/home/harry/rd/illumio-ops/.worktrees/v6-ui`，分支 `feat/v6-alert-rules-page`。每個指令先 `cd` 到這裡；每個 brief 開頭驗證
  `pwd` 與 `git branch --show-current`（[[subagent-worktree-pwd-pinning]]）。
- commit：英文 conventional commits；只 `git add` 明確路徑；不在閘門後用 `;` 或管線接 commit；不 push；結尾兩行
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`、`Claude-Session: https://claude.ai/code/session_01V7rXuiroWZKXLffJeydNsX`。
- 單支測試：`cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && timeout 900 .venv/bin/python -m pytest <檔案> -x -q -p no:logging`。
  e2e 前先 build：`npm --prefix web run --silent build`（`tests/e2e/conftest.py` 讀 build 產物，implementer 先讀它）。
  全套：`bash .superpowers/sdd/2026-11-03-v6-ui-b-rule-scheduling/gates.sh`，讀最後一行 `ALL GATES GREEN`。
- **每個 task 結束時全套閘門要綠**：它改到的舊測試在同一個 task 裡改寫或退役，回報逐支列出。
- 前端測試讀渲染後的 DOM 文字或送出的 JSON，不讀 class 名稱或原始碼字面（[[gate-checks-shape-not-rule]]）。

## Review Focus

1. 存回不變（Task 9 的測試；Task 2、5、6 的編碼解碼）。
2. 舊頁的資訊或動作消失（§2 反目標清單逐項對）。
3. 舊測試被改弱：改寫後斷言的範圍不可比原本小（[[gate-measurement-validity]]）。
4. 文字對不到程式（Task 7 的 17 句、Task 3 的條件欄與門檻欄）。

---

**執行方式：** Task 1–9 依序交給 implementer（一次一個，每個做完由主對話驗證後才開下一個）；Task 10 由主對話執行。

---

### Task 1: `model.ts`：純函式

**Files:** Create `web/src/pages/alerts/rules/model.ts`。這個 task 不接到畫面，只要 `npm run typecheck` 過；行為在之後的 task 用頁面測。

**Interfaces（全部 export）:**
```ts
type Rule = RuleWrite["rule"];  type Item = RuleListItem;
type Table = "event" | "flow" | "special";
tableOf(rule: Rule): Table                     // event → event；traffic/bandwidth/volume → flow；lateral/system → special（§4.2）
order(items: Item[], pack: PackRule[]): Item[]  // 內建照 pack 順序在前，其他照原順序在後（§4.2）
type State = "off" | "rec" | "on";
stateOf(rule): State; withState(rule, s: State): Rule   // off 只改 enabled=false，不動 notify（§4.2）

// 事件等級與結果（§4.4）
type Picks<T> = { kind: "set"; values: T[] } | { kind: "raw"; text: string };
readSeverity(s: string): Picks<"info"|"warning"|"err">   // _ANY（"", "*", "any", "all"，不分大小寫）→ 三個都勾；
                                                       // info/warning/err/error 以 | 串成 → 對應；其他 → raw
writeSeverity(p): string                               // 三個都勾 → "all"；部分 → 依 info|warning|err 順序以 | 串；空 → throw
readStatus(s: string): Picks<"success"|"failure">     // _ANY → 兩個；"success"/"failure" → 一個；其他 → raw
writeStatus(p): string                                 // 兩個 → "all"
// 「沒動就送回原字串」由表單負責：只有使用者改了控制項才呼叫 write*。

// 事件目錄（§4.4）
type Verb = "create" | "update" | "delete" | "other";
verbOf(eventType: string): Verb        // 最後一個 "." 之後的那段
resourceOf(eventType: string): string  // 第一個 "." 之前
splitTypes(types: string[], catalog: ReadonlySet<string>): { listed: string[]; other: string[] }
  // 依目錄分：確切類型在 catalog 裡的 vs 其他（a|b、樣式、目錄外）；兩邊都保持原順序
isPattern(p: string): boolean          // 搬 RuleEditor.tsx:524 的判斷（與 domain/alertrules._looks_like_regex 一致）
owners(items: Item[], exceptId: string | null): Map<string, Item[]>  // 確切類型 → 列出它的規則；a|b 拆開；* 與樣式不算；不論啟用
showSeverity(scopeAll: boolean, picked: CatalogEventView[], value: string): boolean // §4.4 何時顯示；showStatus 同理
// 範本與預設（§4.3）
PACK_SKIP = ["id", "pack_key", "enabled", "notify", "name"] as const
differsFromPack(rule: Rule, pack: PackRule[]): boolean   // 內建規則任何非 PACK_SKIP 欄位與 pack 不同（JSON 比較，鍵順序無關）
fromTemplate(p: PackRule, name: string): Rule           // pack 的值，pack_key=null，id=NEW_ID，name，enabled=true，notify=true
restored(rule: Rule, p: PackRule): Rule                  // PACK_SKIP 以外換成 pack 的值；name 換成 ""
switchMetric(rule: FlowRule, to: "traffic"|"bandwidth"|"volume", touched: {window: boolean; threshold: boolean}): FlowRule
  // type 換掉；舊門檻欄位刪掉；新門檻欄位與 window 用 blank(to)，除非 touched（§4.3）
blank(type): Rule   // 從 RuleEditor.tsx 搬來，RuleEditor 改成 import 這個
// 文字（§4.2）：conditionText(rule, choices): {main: string; excluded: string}；thresholdText(rule): string
```
- `conditionText`／`thresholdText` 放這裡或 `ruleSummary.ts` 皆可，但要重用 `ruleSummary.ts` 現有的 `ports`、`side`、`included`、`excluded`
  （必要時改成 export）。IP 清單與標籤群組改寫名稱：`side()` 加一個可選的 `choices` 參數，查得到寫名稱、查不到才寫數量（舊呼叫者不傳，行為不變）。
- `thresholdText` 的三種事件寫法照 §4.2（含 `immediate` 且 `threshold_count>1`）。

- [ ] Step 1：寫 `model.ts`，`blank` 從 `RuleEditor.tsx` 搬過來並改 import。
- [ ] Step 2：`npm --prefix web run --silent typecheck` 過；全套閘門綠。
- [ ] Step 3：commit `refactor(v6-alerts): pure helpers for the rules page`。

### Task 2: `ConditionEditor` 補齊並修埠

**Files:** Modify `web/src/components/ConditionEditor.tsx`；Test：新增 `tests/e2e/test_condition_editor_fields_e2e.py`（告警規則的完整表單與報表篩選各一組）。

- 埠（§4.5）：**輸入的意思不變**——只打數字（`445`、`135-139`）仍是 TCP（現有測試 `test_alerts_e2e.py:78` 等靠這個）。
  新增可解析的寫法讓每種已存的形狀都寫得出來、讀得回去：`445/any`＝沒有協定（`proto: null`）、`445/udp`、`445/proto:47`（其他協定號）、
  `proto:1`（只有協定沒有埠）、`-1/proto:1`（`port=-1`）。`portsText` 依這套寫出，`parsePorts` 依這套讀回；placeholder 與 hint 寫出新寫法。
  以前存成 `proto: null` 的埠，現在打開時顯示成 `445`、一 blur 就變 TCP——這就是要修的缺陷。
- 補編輯器（§4.5）：`service_process`、`service_user`、`text`（文字框，空字串存 `null`）；`initiator_processes`、`initiator_users`、
  `service_processes`、`service_users`（每行一筆的 textarea，空存 `[]`）；`Side` 的 `hrefs` 以 chip 顯示可移除——`condition_choices` 沒有 Workload，
  chip 一律顯示 href 本身，**不要為此加後端呼叫**；`match`（any／all）只在同一端同時有標籤和主機時出現。全部用受控或 `onBlur`，與既有欄位一致。
- 這些新控制項**只在告警規則表單出現**：`ConditionEditor` 加一個 opt-in prop（例 `full`），報表篩選不傳，版面與行為不變（埠的修正例外，兩邊都受惠，寫進 CHANGELOG）。
- 新欄位放在「排除」以外的進階區（實作者決定版面），任一有值時該區預設展開。

- [ ] Step 1：失敗測試（**不可只做「打開不動存回」——那在現在的程式也會過**，因為埠只在 blur 時重新解析、沒有編輯器的欄位本來就原封帶過）：
      - 埠：用 settings 寫入一條 traffic 規則，`ports` 含無協定、TCP、UDP、協定 47、只有協定、`-1`、範圍；在表單裡**對埠欄 focus 再 blur**
        （另一個情況：在尾端加一個 `, 8080`），存回後原有的每一筆協定都不變、新加的是 TCP。報表篩選做同樣兩個情況。
      - 新欄位：每個欄位先斷言**畫面上有控制項顯示存著的值**，再改它、存，斷言送出的 JSON 是改後的值；`hrefs` 移除一個 chip 後存回少了那一個。
      - 報表篩選：斷言新控制項**不**出現。
- [ ] Step 2：實作；Step 3：測試過、全套綠；Step 4：commit `fix(v6-ui): the condition editor keeps every field and port as it is`。

### Task 3: 規則頁：三張表、狀態、搜尋、頁首

**Files:** Create `web/src/pages/alerts/rules/RulesPage.tsx`；Modify `RulesAndChannels.tsx`（規則分頁掛 `RulesPage`）；Delete `Rules.tsx`
（`RulesRedirect` 與 `registerNav` 搬到新檔）；i18n；改寫受影響的 e2e。

- 版面照 §4.1、§4.2。三張表的 `data-role`：`rules-event`、`rules-flow`、`rules-special`；每列 `data-rule-id`、`data-rule-type`；
  條件格 `data-role=rule-condition`，排除第二行 `data-role=rule-exclusion`；門檻格 `data-role=rule-threshold`。
- 三段狀態：`role=radiogroup`，三個選項；存檔中／存好／失敗沿用現在 `Switch` 的 `data-state` 慣例，失敗切回並寫原因。
- 活動行、暫緩與重設、`last_status`、評估一次、內建規則選單（補上缺的／全部重設）、保留天數全部搬過來，行為不變。
- 偵測與系統表：§4.6（說明展開 `scn_det_*`／`scn_det_*_notes`／`scn_sys_*`；這個 task 先只做列與說明，新增連結在 Task 8）。
- 「編輯」：這個 task 先連到舊的 `/alerts/rules/:id`（表單在 Task 4 才接上）。「＋新增規則」先連到舊的 `/alerts/rules/new`。
- 搜尋：§4.7，比對渲染後的文字。
- 頁首計數：§4.1。
- 窄螢幕版面：§4.2 最後一段（照樣張的 CSS 斷點 860px；樣式寫進現有樣式表，用 tokens）。
- 改寫的舊測試（逐支回報）：`test_ui_controls_e2e.py:65-95`（改測三段）、`test_ui_layout_e2e.py:80-91`、`test_decision_words_e2e.py:96`
  （條件欄的判定寫法不變，選擇器改）、`test_alerts_e2e.py` 中讀列表的部分、所有等 `[data-role=rule-list]` 的地方（改等新表）。

- [ ] Step 1：失敗測試（新檔 `tests/e2e/test_rules_page_e2e.py`）：
      每條規則剛好出現在一張表一次（用 settings 放入內建 35 條＋`OTHER_SHAPES`）；三段切換三種狀態送出的 `enabled`/`notify` 正確且其他欄位不變；
      停用再切回「通知」時 `notify` 正確；存檔失敗切回；條件欄寫出每筆 `path = pattern`、排除第二行、IP 清單名稱；
      門檻欄三種事件寫法與三種流量寫法；搜尋用事件類型、IP、IP 清單名稱各找得到；頁首計數；`last_fired_at` 空時寫「沒有觸發紀錄」。
- [ ] Step 2：實作；Step 3：舊測試改寫；全套綠；Step 4：commit `feat(v6-alerts): rules page with event, traffic and special tables`。

### Task 4: 規則表單外殼

**Files:** Create `rules/RuleForm.tsx`；Modify `RulesPage.tsx`、`RulesAndChannels.tsx`、`RuleEditor.tsx`（路由轉址）；i18n；測試。

- 開關：`?rule=new`、`?rule=<id>`（§4.3）；「編輯」與「＋新增規則」改成設這個參數；表單打開時「＋新增規則」變次要按鈕。
  切分頁或關閉時表單有改動先確認。`/alerts/rules/:id` 對事件與流量規則 `Navigate` 到 `/alert-rules?rule=<id>`，偵測與系統照舊。
- 四步：盯什麼（編輯時不可改）、條件（這個 task 先放現有 `EventFields`／`ConditionEditor` 佔位，Task 5、6 換掉）、門檻、告警方式（§4.3 全部）。
- 門檻：事件含「每次發生」下的「同一次檢查裡，同一台主機達 N 筆」；切回每次發生時 `threshold_count=1`；`immediate` 時不顯示 `window_minutes`
  但保留原值。流量用 `switchMetric`。提示文字照 §4.3。
- 狀態一份：表單與列上共用（提升到 `RulesPage` 的 state）。
- 儲存：§4.3 的衝突判斷（重新 `alert_rules.list`，比對除 `enabled`/`notify` 外是否與打開時相同）；新增用 id 差找新規則、捲動並標示；
  欄位錯誤時展開對應的摺疊區（§4.3）；刪除兩段確認；試算；通知管道那一行。
- 失敗測試先寫（`tests/e2e/test_rule_form_e2e.py`）：新增一條事件規則與三種流量規則，存出的 JSON 與預期逐欄相同；
  `threshold_count=3` 的 immediate 規則打開看得到 3、存回不變；切算法後送出的規則沒有舊門檻欄位；衝突：打開表單後用 settings 改那條規則，
  按儲存不送出並出現提示；列上切狀態後表單的狀態跟著變、儲存不算衝突；刪除；舊 `/alerts/rules/<id>` 轉址。
- 改寫：`test_rule_form_acceptance_e2e.py` 的 `_save`／開表單 helper 改走新頁（三條規則的那支這時候先讓事件與流量走新表單）。
- commit `feat(v6-alerts): one rule form on the rules page`。

### Task 5: 事件條件

**Files:** Create `rules/EventCondition.tsx`；Modify `RuleForm.tsx`；i18n；測試。

- 全部依 §4.4 與樣張：全部事件／挑選事件；chip 列（目錄外與樣式的 chip 標「樣式」或「目錄外」）；分類欄（11 類＋全部＋已勾選，已勾數／總數，
  ≤720px 下拉）；搜尋（不限分類）；動作篩選；同資源分組（兩種以上才有標題與「這組全勾」，全勾存當下列出的確切類型）；
  「已有規則」提示（`owners`，排除正在編輯的那條；結果不是全部時加說明；停用的加「停用中」）；隱藏已有規則（已勾的不藏）；
  點已有規則的名稱：確認後打開那條。
- 「更多條件」：`EventTypesBox` 只顯示與編輯 `splitTypes().other`；`match_fields` 沿用現有那塊。
- `event_types` 陣列**只有在使用者改動時才重寫**；改動時的規則只有一條：既有項目留在原位置，取消勾選或在手動框刪掉的項目拿掉，新勾或新打的接在最後。
  不排序、不依「目錄＋其他」重組（`OTHER_SHAPES` 有樣式或目錄外類型排在第一個的規則）。
- 事件等級與結果：`readSeverity`／`readStatus`；raw 時換文字框；**沒動控制項就送回原字串**；何時顯示用 `showSeverity`／`showStatus`，
  不顯示時那一行說明。都不勾不能存（欄位錯誤）。
- 失敗測試：`OTHER_SHAPES` 的每條事件規則打開不動存回不變（含 `err|warning`、`!admin`、逗號樣式、`a|b`、目錄外）；`event_severity` 為
  `error`、`*`、`""`、`!info` 的規則存回不變且畫面分別顯示三勾或文字框；勾一組全勾存出確切類型；動作篩選「刪除」只列 delete；
  搜尋跨分類；已有規則的提示與可勾；只勾 `rule_set.create` 時結果欄不出現並有那一行說明，勾 `user.sign_in` 時出現。
- 改寫：`test_rule_form_acceptance_e2e.py` 兩支逗號測試（:183、:207）走新表單。
- commit `feat(v6-alerts): event conditions with categories, actions and groups`。

### Task 6: 流量條件

**Files:** Create `rules/FlowCondition.tsx`；Modify `RuleForm.tsx`；測試。

- 第一層：來源、目的（`Side`）、埠、四個判定（含 `Unknown`）；「更多條件」放 `ConditionEditor` 其餘的全部（含 Task 2 補的）。
  實作者可以把 `ConditionEditor` 拆成兩塊（常用／其餘），但報表篩選的行為與版面不可變（Task 2 的報表測試要照過；Task 2 的新控制項只在 opt-in 時出現）。
- 任一「更多條件」欄位有值時預設展開。
- 失敗測試：`OTHER_SHAPES` 的三條流量規則與 Task 2 那條全欄位規則打開不動存回不變；勾 `unknown` 存出 `["unknown"]`。
- 改寫：`test_decision_words_e2e.py:41`（改走新表單選流量）、`test_alerts_e2e.py` 的 `test_rule_traffic_exclusions_round_trip`（:88）、
  `test_rule_traffic_parity_conditions_round_trip`（:402）。
- commit `feat(v6-alerts): traffic conditions in the rule form`。

### Task 7: 範本、還原預設、17 句說明

**Files:** Modify `RuleForm.tsx`、`RulesPage.tsx`；i18n；測試。

- 範本選單（只在新增時）、`?rule=new&template=<pack_key>`、`fromTemplate`、名稱加「（複本）」、表單有改動時確認、帶入後重新掛載。
- 範本說明：17 個新鍵 `rule_why_<pack_key 去掉 rule_ 前綴>`，中英。程式裡用**字面對照表**（`{ rule_login_failed: "rule_why_login_failed", … }`），
  不可用字串拼出鍵名（i18n 閘門只認字面 `t("key")`）。**寫之前**用 microseg-kb（Illumio）查 §5 列的六件事，查到什麼寫進
  `tmp/alert-rules-page/why-sources.md`（每句一行：鍵、句子、出處）。不確定的寫保守的、只描述事件本身。
- 編輯內建規則時同一句顯示在表單標題下。
- 「和預設不同」小標（列上）與「還原成內建預設」按鈕用同一個 `differsFromPack`；還原後重新掛載、要按儲存才存。
- 失敗測試：選每個範本，存出的規則等於 `pack_rules` 的值（`id`、`pack_key`、`name`、`enabled`、`notify` 除外）；網址帶 template 直接打開；
  改內建規則一個欄位後列上出現「和預設不同」、按還原再存後與 `pack_rules` 相同且小標消失；從 5.x 形狀的內建規則（cooldown 不同）也出現小標。
- commit `feat(v6-alerts): built-in rules as templates, restore to default`。

### Task 8: 偵測與系統、舊網址、情境清單瘦身

**Files:** Modify `RulesPage.tsx`、`RuleEditor.tsx`、`ScenarioList.tsx`、`scenarios.ts`、i18n、`tests/e2e/ui_rules.py`；測試。

- §4.6 的新增連結；情境清單只留偵測與系統兩組（`?only=special` 或實作者定的參數）。
- §4.8 的轉址表逐列實作；`?form=full` 類型選單只剩 `lateral`、`system`，預設 `lateral`。`RuleEditor.tsx` 刪掉事件與流量的分支與只給它們用的元件
  （`EventChecklist`、`ShortThreshold`、`EventPicker`、`PACK_FIELDS`…，若 Task 5 沒有搬走就刪）。
- 刪除不再被用到的 i18n 鍵（`scn_group_event`、`scn_group_flow`、`scn_flow_traffic` 等；**保留** `scn_det_*`、`scn_sys_*`、`scn_flow_*_notes`、
  `rule_traffic_hint`、`rule_bytes_hint`）。用 i18n 閘門確認沒有懸空鍵。
- 全 repo grep `alerts/rules` 與 `rule-list`，連結改新網址。
- 改寫或退役：`test_rule_short_form_e2e.py`、`test_rule_scenarios_e2e.py` 的事件與流量部分（偵測與系統部分照舊）；`ui_rules.py:15-17` 頁面清單。
- 失敗測試：§4.8 每一列轉到對的地方；`?form=full` 沒有事件與流量選項；情境清單沒有事件與流量組。
- commit `feat(v6-alerts): detection and system rules keep their own forms; old links redirect`。

### Task 9: 存回不變與欄位涵蓋守門

**Files:** Modify `tests/e2e/test_rule_form_acceptance_e2e.py`、`tests/e2e/test_alerts_e2e.py`；新增守門測試。

- `test_every_built_in_rule_opens_and_saves_unchanged`、`test_rules_of_other_shapes_open_and_save_unchanged`：事件與流量走新表單，偵測與系統走完整表單；
  `OTHER_SHAPES` 加入 Task 2、5 的難例（每個 `FlowCondition` 欄位、各種埠、`event_severity` 的四種非標準值、非標準 `status`）。
- `test_alerts_e2e.py` 的 :149（事件欄位比對來回）走新表單；:109（lateral）照舊。逐支確認 71、181、328、448、473、522、548 行的測試已在前面的 task 改好或在這裡改好。
- 欄位涵蓋守門（取代 `test_rule_short_form_e2e.py:343`；先讀它：它比對 contracts 的屬性集合等於幾份手寫清單的聯集）。新的寫法兩半：
  1. 靜態：從 `contracts.json`（`operations["alert_rules.create"]["request_schema"]["$defs"]`）讀 `EventRule`、`TrafficRule`、`BandwidthRule`、
     `VolumeRule`、`FlowCondition`、`EndpointFilter`、`PortProto`、`Throttle` 的屬性集合，必須等於測試裡一份手寫對照表的鍵：
     每個屬性對應「表單上的控制項選擇器」或明列在「原樣保留」清單（只有 `id`、`pack_key` 這類不給編輯的）。模型多一個屬性就紅。
  2. 動態：對照表裡每個有控制項的屬性，用一條該屬性有非預設值的規則打開表單，斷言那個選擇器**看得到且顯示存著的值**。
  **先注入缺陷確認會紅**：暫時拿掉 `service_user` 的控制項（不是讓它丟值），動態那半要紅；暫時在對照表刪一個鍵，靜態那半要紅。
  結果寫在 commit 訊息（[[gate-measurement-validity]]）。
- commit `test(v6-alerts): every rule shape saves back unchanged through the new form`。

### Task 10: 文字審閱、版本、真機驗收（主對話執行）

- [ ] 新句子表：列出這次新增與改寫的每個 i18n 鍵（中英），連同 Task 7 的出處，給使用者審；使用者改的照改。
- [ ] `illumio_ops/__init__.py` 版本 6.13.0；CHANGELOG 6.13.0（Changed：規則頁；Fixed：條件編輯器的埠與漏掉的欄位、報表篩選也受惠）。
- [ ] 全套閘門綠（親跑，看最後一行）。
- [ ] 合入 main、push、盯 CI（長期授權，[[v6-push-main-authorized]]）；push 單獨一行。
- [ ] 部署 .106；1440、820、400 各截：表單關、新增事件（挑選區＋選分類＋動作篩選）、新增流量、編輯內建（看得到還原）。逐張看溢出與截斷。
- [ ] .106 實測：從範本建一條事件規則、建一條流量規則、切一次三段狀態、評估一次不出錯；刪掉測試規則。
- [ ] 回報分「驗到」「沒驗到」；更新記憶 [[v6-purpose-led-ui-delivered]]。tag 要問使用者。
