# v6 告警規則表單（第 4 段）Implementation Plan

**Goal:** 「新增規則」先挑情境、再填一張只有必要欄位的短表單；完整表單收在「進階」，隨時可展開。編輯既有規則的畫面不變。
規則的資料模型、評估、內建規則包都不改。版本 6.11.0。

**Architecture:** 仍是同一個 `RuleEditor`（路由 `/alerts/rules/:id`）。`/alerts/rules/new` 不帶參數時顯示情境清單；帶 `?scenario=<組>:<id>`
時顯示短表單＋收合的「進階」；帶 `?form=full` 時是現在的完整表單。短表單與進階是**同一個已掛載的表單**（進階用 `<details>` 收合），
送出的 payload 就是現在的 `RuleWrite`。後端只加一個唯讀路由，把內建規則包的規則值交給前端預填。

**Tech Stack:** React 19＋TypeScript＋Vite（`web/src/pages/alerts/`）；Flask＋pydantic（`illumio_ops/web/routes/alert_rules.py`）；
pytest＋Playwright（`tests/e2e`，前端沒有單元測試框架）；i18n `illumio_ops/i18n/{en,zh_TW}.json`。

**Spec:** `docs/superpowers/specs/2026-11-11-v6-purpose-led-ui-design.md` §10、§11「第 4 段」。

## 規格 §10 與程式不符之處，以及這份計畫的處理（寫計畫時定下，交付時回報使用者）

| 規格寫的 | 程式實際 | 這份計畫怎麼做 |
|---|---|---|
| 編輯器是抽屜 | 是整頁路由 `/alerts/rules/:id` | 維持整頁 |
| 事件分類例：VEN 與主機、登入與帳號、政策變更 | 事件目錄有 11 個分類（`evcat_*`） | 用目錄的 11 個 |
| 短表單有「通知與通道」 | 規則只有 `notify`；通道是全域設定 | 「發通知」勾選＋唯讀列出目前啟用的通道＋連到通道頁；不加每條規則選通道 |
| 門檻預填內建規則包同一事件的值 | 規則包沒有送到前端；有些規則還靠 `status`、頻率限制、冷卻、固定嚴重度才成立（只帶門檻的話，登入失敗會把成功登入也算進去） | 後端加唯讀路由；勾選的事件**剛好等於**某條內建規則的事件時，整條規則的值一起帶入並寫明帶了什麼，否則一律「每次發生」 |
| 情境的說明取自現有偵測器文字 | 偵測器與系統檢查只有名稱，沒有說明 | 新寫說明（21＋6＋3 句），每句對得到該偵測器／檢查的觸發條件，交付時列成清單給使用者審 |
| 流量門檻是連線數或位元組 | 單位是連線數、Mbps、MB | 用現有單位 |
| 「以最近 24 小時試算」是主要確認方式 | 系統類試算回 `not_applicable` | 系統類短表單不放試算按鈕，寫現有的「不適用」說明 |
| 「已有規則」＝事件類型落在分類裡 | 規則可以寫 `*`、`a|b`、正規表示式或目錄沒有的類型 | 另列「以樣式比對的規則」一區，不歸到任何分類；任何地方都不寫「沒有規則涵蓋」 |
| 抽屜的 `data-field` 是資料遺失防線 | 那是 5.x 的事；v6 只有七支來回測試 | 七支測試保留並繼續走完整表單；另加「進階區有值就展開」的逐欄測試 |

## Global Constraints

- 不改：`illumio_ops/domain/alertrules.py`、`domain/alertpack.py`、`domain/alerting.py`、`services/alerts/evaluate.py`；既有 API 的請求與回應。
- 送出的規則 JSON 必須與用完整表單填同樣值的**逐欄相同**（`id` 除外）。
- 文字規則（使用者 2026-11-03）：每句話對得到資料或固定規則。不寫推論、不寫「可能」。用語閘門 `tests/i18n/test_terminology.py`。
- i18n 閘門只認 `t("key")`、`labelKey: "key"`、`message_key: "key"` 三種寫法；`t(` 裡不可用樣板字串。新鍵兩種語言都要有、佔位符一致。
- 契約有變就跑 `bash scripts/gen_contracts.sh` 並提交 `web/src/api/contracts.json`、`generated.ts`。
- mypy strict、ruff、`npm run typecheck` 全過。
- `ConditionEditor` 的輸入是非受控（`defaultValue`＋`onBlur`）：短表單與進階之間**不可重新掛載**；`blank()` 只在挑情境的那一刻呼叫。
- 介面稽核 `tests/e2e/ui_rules.py` 十條規則對三個畫面（情境清單、短表單、完整表單）都要零違規，特別是每區一顆主要按鈕。
- 工作目錄 `/home/harry/rd/illumio-ops/.worktrees/v6-ui`，分支 `feat/v6-rule-form-stage4`。每個指令先 `cd` 到這裡並確認 `pwd` 與分支。
- commit：英文 conventional commits；只 `git add` 明確路徑；不接在別的指令後面用 `;`；不 push；結尾兩行
  `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`、`Claude-Session: https://claude.ai/code/session_01V7rXuiroWZKXLffJeydNsX`。
- 單支測試：`cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && timeout 600 .venv/bin/python -m pytest <檔案> -x -q -p no:logging`。
  全套：`bash .superpowers/sdd/2026-11-03-v6-ui-b-rule-scheduling/gates.sh`（讀它最後的 `ALL GATES GREEN`）。
- e2e 需要先 build 前端：照 `tests/e2e/conftest.py` 的作法（implementer 先讀它）。

## Review Focus

1. 短表單存出來的規則與完整表單不同（Task 3、4 的相等測試）。
2. 預填帶進了看不到的值：進階區有任何欄位不同於 `blank(type)` 就必須展開（Task 4）。
3. 既有七支來回測試被改弱（Task 2 只改它們的網址）。
4. 情境清單暗示「這個情境沒有規則」（Task 2）。
5. 新寫的 30 句說明對不到觸發條件（Task 2 的清單、Task 6 的審閱）。

---

**執行方式：** Task 1–5 依序交給一個 implementer（每個 brief 開頭驗證 `pwd` 與分支）；Task 6 由主對話執行。

---

### Task 1: 後端唯讀路由：內建規則包的規則值

**Files:**
- Modify: `illumio_ops/web/routes/alert_rules.py`
- Regenerate: `web/src/api/contracts.json`、`web/src/api/generated.ts`
- Test: `tests/web/test_alert_rules_routes.py`

**Interfaces:**
```python
class PackRule(BaseModel):
    rule: AlertRule          # as best_practice_rules(notify_new_defaults=True) builds it
    name_key: str            # the pack key: the i18n key of its name

class PackRules(BaseModel):
    rules: list[PackRule]

OP_PACK_RULES = operation("alert_rules.pack_rules", "GET", "/api/alert-rules/pack-rules", None, PackRules)
```
權限與 `alert_rules.event_catalog` 相同（讀）。不讀設定、不寫任何東西。

- [ ] **Step 1: 寫失敗測試**：回 200；筆數等於 `len(best_practice_rules(notify_new_defaults=True))`；`rule_login_failed` 那筆的
  `status == "failure"`、`throttle == {"count": 1, "period_minutes": 15}`、`threshold_count == 5`；每筆 `name_key == rule.pack_key`；
  未登入 401；呼叫前後設定檔 revision 不變。
- [ ] **Step 2: 跑測試確認失敗。**
- [ ] **Step 3: 實作**，跑 `bash scripts/gen_contracts.sh`。
- [ ] **Step 4: 跑 `tests/web/test_alert_rules_routes.py` 與契約測試，全過。**
- [ ] **Step 5: commit** `feat(v6-alerts): the built-in pack's rule values, read-only, for the rule form`

---

### Task 2: 情境定義、情境清單頁、既有測試改走完整表單

**Files:**
- Create: `web/src/pages/alerts/scenarios.ts`、`web/src/pages/alerts/ScenarioList.tsx`
- Modify: `web/src/pages/alerts/RuleEditor.tsx`、`web/src/pages/alerts/common.ts`、`web/src/pages/alerts/ruleSummary.ts`、
  `web/src/pages/system/Lateral.tsx`（偵測器與檢查的鍵對照表搬到 `common.ts`，三處改成匯入，不留複本）、
  `illumio_ops/i18n/en.json`、`illumio_ops/i18n/zh_TW.json`
- Test: `tests/e2e/test_rule_scenarios_e2e.py`（新）、`tests/e2e/test_alerts_e2e.py`、`tests/e2e/test_decision_words_e2e.py`、
  `tests/e2e/test_ui_controls_e2e.py`、`tests/e2e/ui_rules.py`

**Interfaces:**
```ts
// scenarios.ts
export type ScenarioGroup = "event" | "flow" | "detector" | "system";
export type Scenario = { group: ScenarioGroup; id: string; labelKey: string; descKey: string | null };
// event: id = the catalog category id, labelKey = its label_key, descKey = null (the line under it is computed:
//        how many event types the category holds — "scn_event_count" with {n})
// flow: "traffic" | "bandwidth" | "volume";  detector: a DetectorKind;  system: a SystemCheck
export function scenarioOf(search: URLSearchParams): Scenario | null     // "?scenario=detector:fanout"
export function covering(rule: Rule, catalog: EventCatalog): { scenarios: string[]; byPattern: boolean }
```
- `covering`：事件規則的每個 `event_types` 項目，若是目錄裡的確切類型，歸到該類型的分類；`*`、含 `|`、不在目錄裡的字串都算樣式
  （`byPattern: true`，不歸任何分類）。流量三型歸自己那一型；系統規則歸它的檢查；橫向規則歸它列的每個偵測器。
- 網址：`/alerts/rules/new` → 情境清單；`/alerts/rules/new?scenario=<group>:<id>` → 短表單（Task 3）；`/alerts/rules/new?form=full`
  → 現在的完整表單（這個 Task 先讓 `?scenario=` 也落到完整表單並預選類型，Task 3 再換成短表單）。
- 情境清單頁（`data-role="scenario-list"`）：四組各一區，區標題用組名；每個情境一列：名稱、一句說明、其下
  「已有規則：{名稱}」每條一個連結（`data-role="covered-by"`，連到 `/alerts/rules/<id>`），以及「新增」連結（不是主要按鈕樣式；整頁沒有主要按鈕）。
  已有規則的情境排在該組前面，其餘依定義順序。最下面一區「以樣式比對的規則」（`data-role="pattern-rules"`）列出 `byPattern` 的規則與它的條件摘要
  （`conditionSummary`），沒有這種規則時不顯示這一區。頁尾一個連結「不挑情境，直接開完整表單」→ `?form=full`。
  沒有任何規則涵蓋的情境**不寫任何「沒有規則」的字**，就只是沒有那一行。
- 新文字（`scn_*`）：四個組名；三個流量情境各一句；21 個偵測器各一句；6 個系統檢查各一句；`scn_event_count`；`scn_covered_by`；
  `scn_new`；`scn_pattern_title`、`scn_pattern_hint`；`scn_full_form`；頁面目的句 `purpose_scenario_list`。
  偵測器的句子由 implementer 讀 `illumio_ops/domain/detectors.py`、`domain/anomaly.py` 各偵測函式的觸發條件後寫，只寫「什麼情況會觸發」；
  系統檢查的句子依 `services/alerts/` 裡該檢查的判斷條件寫。**把 30 句連同各自依據的函式名列在 implementer 的回報裡。**

- [ ] **Step 1: 改既有測試的網址**：`test_alerts_e2e.py` 七支、`test_decision_words_e2e.py`、`test_ui_controls_e2e.py` 裡的
  `/alerts/rules/new` 改成 `/alerts/rules/new?form=full`，**其他一個字都不改**。`ui_rules.py` 的 `PATHS` 把 `/alerts/rules/new` 保留（現在是情境清單），
  另加 `/alerts/rules/new?form=full`。
- [ ] **Step 2: 寫失敗測試** `tests/e2e/test_rule_scenarios_e2e.py`：
  - `/alerts/rules/new` 有 `[data-role=scenario-list]`，四組都在；事件組有 11 列；偵測組 21 列；系統組 6 列；流量組 3 列。
  - 套用內建規則包後：`agent_security` 那列有「已有規則：VEN tampered」的連結，點了到該規則的編輯頁；
    `rule_bulk_unpair` 同時出現在 `containers_workloads` 與 `agent_operations` 兩列；`rule_anomaly_directory` 出現在三個偵測器列。
  - 建一條 `event_types=["*"]` 的規則：它出現在 `[data-role=pattern-rules]`，不出現在任何分類列。
  - 沒有樣式規則時 `[data-role=pattern-rules]` 不存在。
  - 頁面文字不含 "no rule"／「沒有規則」。
  - 兩種語言各跑一次列數；`ui_rules.violations(page) == {}`。
  - 從規則列表頁按「新增規則」到的是情境清單。
- [ ] **Step 3: 跑測試確認失敗。**
- [ ] **Step 4: 實作。**
- [ ] **Step 5: 跑 `tests/e2e/test_rule_scenarios_e2e.py tests/e2e/test_alerts_e2e.py tests/e2e/test_decision_words_e2e.py
  tests/e2e/test_ui_controls_e2e.py tests/e2e/test_ui_rules_e2e.py tests/i18n`，全過；`npm run typecheck`。**
- [ ] **Step 6: commit** `feat(v6-alerts): a new rule starts from a list of scenarios, each naming the rules that cover it`

---

### Task 3: 短表單與「進階」

**Files:**
- Modify: `web/src/pages/alerts/RuleEditor.tsx`（必要時拆出 `web/src/pages/alerts/ShortForm.tsx`，但表單狀態只有一份）、
  `illumio_ops/i18n/{en,zh_TW}.json`
- Test: `tests/e2e/test_rule_short_form_e2e.py`（新）

**Interfaces:**
- 進入 `?scenario=<group>:<id>` 時呼叫一次 `blank(type)` 並套上情境：流量三型 → 該型；`detector:<kind>` → `lateral`、`detectors: [kind]`；
  `system:<check>` → `system`、`check`；`event:<category>` → `event`、`event_types: []`（待勾選）。
- 短表單看得到的欄位（`data-role="short-form"`）：
  - 事件：名稱（預填分類名）；該分類的事件勾選清單（`data-role="event-checklist"`，每項 `input[type=checkbox][data-event-type]`，
    顯示目錄的說明、不顯示類型字串）；門檻（「每次發生」＝`immediate`＋`threshold_count: 1`；「{分鐘} 分鐘內 {次} 次」＝`count`）；發通知。
  - 流量三型：名稱；流量條件（現有 `ConditionEditor`，預設空）；門檻與視窗（現有單位）；發通知。
  - 偵測：名稱（預填偵測器名）；最低嚴重度；發通知。
  - 系統：名稱（預填檢查名）；發通知。
- 「進階」（`<details data-role="advanced">`）：該類型在完整表單裡、短表單沒列的**所有**欄位，原樣。至少一項不同於 `blank(type)`（套上情境之後的值）
  時 `open`；否則收合。`open` 只會由程式打開、不會由程式關上（使用者自己可以關）。
- 事件未勾任何項目時存檔鈕停用，並有一句「至少勾一種事件」（`data-role="need-event"`）。
- 短表單頂端一行連回情境清單；主要按鈕只有「儲存」。

- [ ] **Step 1: 寫失敗測試** `tests/e2e/test_rule_short_form_e2e.py`：
  - 四組各挑一個情境：短表單只看得到上列欄位，`[data-role=advanced]` 存在且未展開；展開後完整表單的每個 `name` 都在。
  - **相等**：四種各存一條，再用 `?form=full` 填同樣的值存一條；從 API 讀回兩條，除 `id` 與 `name` 外逐欄相同。
  - 事件：勾兩項後 `event_types` 就是那兩個類型（依目錄順序）；一項都不勾時存檔鈕停用。
  - 在流量短表單的條件裡填了 port、**還沒離開輸入框**就展開進階再收合：值還在，存出來的規則有那個 port（不重新掛載）。
  - 兩種語言都沒有未翻譯鍵（頁面文字不含 `scn_`、`rule_` 開頭的原始鍵）與殘留的 `{`。
  - `ui_rules.violations(page) == {}`（短表單、進階展開後各一次）。
- [ ] **Step 2: 跑測試確認失敗。**
- [ ] **Step 3: 實作。**
- [ ] **Step 4: 跑這支、Task 2 列的幾支與 `tests/i18n`，全過；`npm run typecheck`。**
- [ ] **Step 5: commit** `feat(v6-alerts): a short form for a new rule; every other field under Advanced`

---

### Task 4: 內建規則包的值整條帶入；進階有值就展開；通道與試算

**Files:**
- Modify: `web/src/pages/alerts/RuleEditor.tsx`（或 `ShortForm.tsx`）、`illumio_ops/i18n/{en,zh_TW}.json`
- Test: `tests/e2e/test_rule_short_form_e2e.py`

**Interfaces:**
- 事件短表單：勾選的事件集合**剛好等於**某條內建事件規則的 `event_types` 集合時，把那條規則的 `status`、`event_severity`、`match_fields`、
  `threshold`、`threshold_count`、`window_minutes`、`severity`、`cooldown_minutes`、`throttle` 整組帶入，並顯示一行
  （`data-role="pack-prefill"`）：「沿用內建規則「{name}」的設定」；因為有值不同於 `blank`，「進階」隨之展開。集合不再相等時，
  這些欄位回到 `blank` 的值、那一行消失——**但使用者親手改過的欄位不覆寫**（改過＝該欄位的值不等於剛才帶入的值）。
  不相等時一律「每次發生」。`name`、`enabled`、`notify`、`pack_key` 不帶。
- 偵測與流量情境不預填（規則包的橫向規則值與 `blank` 相同；`rule_high_blocked` 是帶條件的規則，不是「連線數」情境的預設）。
- 發通知：勾選框旁唯讀列出目前啟用的通道（`system.channels.get` 的 `enabled`，用 `CHANNEL_KEYS` 的名稱），一個都沒啟用時寫
  「目前沒有啟用任何通道」；連結到 `/alert-rules?tab=channels`。沒有讀通道權限時不顯示這一行。
- 試算：事件、流量、偵測的短表單在儲存鈕旁有「以最近 24 小時試算」（現有行為）；系統類不放按鈕，顯示現有的 `rule_preview_na` 句。
- 編輯既有規則（`/alerts/rules/<id>`）：畫面與現在相同，一個欄位都不收。

- [ ] **Step 1: 寫失敗測試**：
  - 在 `user_access` 勾 `user.sign_in` 與 `user.login`：出現 `[data-role=pack-prefill]`，進階展開，`status` 是 `failure`，
    存出來的規則除 `id`、`name`、`pack_key` 外與 `rule_login_failed` 逐欄相同。
  - 只勾 `user.sign_in`：沒有那一行，門檻是每次發生，`status` 是 `all`，進階收合。
  - 先勾成相等、把冷卻改成 45、再取消一項：冷卻仍是 45（改過的不覆寫），`status` 回到 `all`。
  - **逐欄**：對每個類型的每個進階欄位，用 `?form=full` 存一條只有那一欄不同於 `blank` 的規則，開它的編輯頁：那一欄的值看得到
    （編輯頁不收合任何東西）。再對事件類做一次「短表單帶入後該欄可見」。欄位清單從 `generated.ts` 的型別對照寫死在測試裡，
    並有一個斷言：清單涵蓋 `contracts.json` 裡六種規則的每個屬性（少一個就紅）。
  - 啟用 smtp 後短表單列出它；全部停用時寫沒有啟用；系統情境沒有試算按鈕。
  - 編輯頁：`test_alerts_e2e.py` 的七支來回測試不動、全過。
- [ ] **Step 2–4: 確認失敗、實作、全過**（同 Task 3 的範圍）。
- [ ] **Step 5: commit** `feat(v6-alerts): a built-in rule's settings come whole or not at all; Advanced opens on any value`

---

### Task 5: 驗收用的三條規則與既有規則原樣存回

**Files:**
- Test: `tests/e2e/test_rule_form_acceptance_e2e.py`（新）

- [ ] **Step 1: 寫測試**（規格 §11 第 4 段）：
  - 只用畫面操作，從規則列表按「新增規則」起：建一條事件類（挑分類、勾事件、存）、一條流量類（挑「連線數」、填門檻、存）、
    一條從「已有規則：…」連結開啟後改冷卻再存。前兩條與用完整表單填同樣值的規則逐欄相同；第三條只有冷卻不同。
  - 套用整個內建規則包後，逐條開編輯頁、不改任何東西按儲存：API 讀回的每條規則與存之前逐欄相同。
  - 另加幾條規則包沒有的形狀：`event_types=["a|b"]`、正規表示式、`*`、目錄沒有的類型、帶 `match_fields`、帶各種排除條件的流量規則、
    `exclude: null` 的橫向規則——同樣開了存回不變。
- [ ] **Step 2: 跑，全過；全套閘門 `gates.sh` 綠。**
- [ ] **Step 3: commit** `test(v6-alerts): three rules made without the manual; every rule opens and saves unchanged`

---

### Task 6: 版本、真資料驗收、部署（主對話執行）

- [ ] **Step 0:** 審 implementer 列的 30 句說明：逐句對照它引用的函式，不符的改掉。
- [ ] **Step 1:** `illumio_ops/__init__.py`、`README.md` 升 6.11.0；`CHANGELOG.md` 加 6.11.0 節；`gates.sh` 全綠。
- [ ] **Step 2:** `PATH="$PWD/.venv/bin:$PATH" PYTHON="$PWD/.venv/bin/python" bash scripts/build_bundle.sh`；部署 .106（進階、中文）與 .135（輕量、英文）。
- [ ] **Step 3:** .106：把現有每一條真規則（含從 5.x 遷移來的）在介面上開了、不改、存回，比對設定檔裡 `alerts.rules` 前後相同
  （先備份設定檔；不同就還原並查）。用畫面建驗收的三條規則、比對後刪掉。
- [ ] **Step 4:** 兩台情境清單、短表單、完整表單在 1440 與 820 截圖逐張看；`tools/ui_audit.py` 兩種寬度零違規。
- [ ] **Step 5:** 規格 §10 依上面的對照表更正；§11 寫第 4 段驗到什麼、沒驗到什麼。commit，合入 main，push，盯 CI。tag 等使用者同意。
- [ ] **Step 6:** 回報使用者：規格更正的九項、30 句新文字清單、沒驗到的事。
