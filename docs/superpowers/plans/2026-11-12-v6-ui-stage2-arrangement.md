# v6 介面第 2 段：依功能目的編排 Implementation Plan

**Goal:** 告警是入口、設備是樞紐：導覽依目的分組，每則告警列出涉及的設備並可點進去，主機頁成為目的地（空白時有清單、帶錨點的段落），
新增隔離頁；版本 6.8.0。

**Architecture:** 後端先補資料（告警涉及的設備存成自己的表、「上次查看」的時間戳、兩個清單端點），前端再用第 1 段的元件重排。
設備鍵沿用現有的主機鍵（workload href 或 `ip:<address>`，`services/hosts.parse_key`）。名稱在讀取時解析（`display_names`），資料表只存鍵與角色。

**Tech Stack:** Python 3 / Flask / SQLite（app 庫的遷移在 `illumio_ops/store/migrations/`，流量庫另一個檔）；React 19＋TypeScript；
pytest＋Playwright；API 契約由 `scripts/gen_contracts.sh` 產生 `web/src/api/contracts.json` 與 `generated.ts`（改了路由或模型一定要重產並提交）。

**Spec:** `docs/superpowers/specs/2026-11-11-v6-purpose-led-ui-design.md` §4、§5.6、§6、§7、§8、§11（第 2 段）。
第 1 段的元件與差異見 `docs/superpowers/plans/2026-11-11-v6-ui-stage1-shared-rules.md` 末段。

## Global Constraints

- 不改偵測、收集、告警評估（何時觸發、嚴重度、冷卻）的語意；本段只增加「告警記下涉及哪些設備」與呈現。
- 舊網址全部可用：現有路徑不改；新路徑只有 `/quarantine`。
- 隔離只對清冊中的受管 workload；非受管與不在清冊的不出現隔離按鈕、寫明原因（`services/quarantine.eligibility` 的判定不動）。
- 基本模式下新元素不消失、不顯示成空白像一切正常（規格 §7 的表逐列照做）。
- 文字規則：每一句是固定文字或「模板＋算出的值」。白話用語只用規格 §5.6 的對照表，寫進 i18n，不逐頁自由發揮。
- 第 1 段的十條呈現規則必須維持：`tests/e2e/test_ui_rules_e2e.py` 的 `PATHS`（`tests/e2e/ui_rules.py`）加入 `/quarantine`，
  新的互動狀態加入 `STATES`；每個前端 task 結束前 build 並跑這支測試。
- 新 i18n 鍵 en 與 zh_TW 都要有；中文用「VEN 總覽」；不留死鍵。
- 單一寫入者守門：SQL 的表名要明寫（不得用 f-string 組表名）。mypy strict、ruff 都要過。
- 嚴格先寫失敗測試再實作的範圍：Task 1–3（資料正確性與 API 契約）。Task 4–8 是介面，以 e2e 驗證行為。
- 工作目錄 `/home/harry/rd/illumio-ops/.worktrees/v6-ui`，每個指令開頭 `cd` 到這裡；`git add` 只加明確路徑；英文 conventional commits；
  commit 不接在閘門後用 `;` 或管線串；不 push。
- 全套閘門：`bash .superpowers/sdd/2026-11-03-v6-ui-b-rule-scheduling/gates.sh`。

## Review Focus

1. **升級前就存在的告警**沒有設備資料：清單與詳情照舊顯示文字、不可點、不報錯；回填得出來的要回填（Task 1）。
2. **設備已不在清冊**（主機被移除、IP 不再出現）：連結仍可點，主機頁說明它不在清冊，不是空白或 500（Task 6）。
3. **一則告警涉及很多設備**（次數門檻規則、流量規則的前幾名）：清單列最多 3 台加「另有 N 台」，詳情最多 20 台加「另有 N 台」，版面不被撐破（Task 5）。
4. **兩個分頁同時開著告警頁**：一邊打開把「新的」歸零，另一邊留在頁面上的清單不能因此在換頁時把還沒看的告警變成舊的（Task 2）。
5. **沒有寫入用 API key**：隔離頁清單照常顯示，解除按鈕不出現並寫明原因；告警上的隔離按鈕同（Task 7、Task 5）。

---

### Task 1: 告警記下涉及的設備

**Files:**
- Create: `illumio_ops/domain/alert_devices.py`、`illumio_ops/store/migrations/0018_alert_devices.sql`
- Modify: `illumio_ops/domain/alerting.py`（`Trigger`、事件與流量規則的評估）、`illumio_ops/store/alerts.py`、
  `illumio_ops/services/alerts/views.py`、`illumio_ops/services/alerts/evaluate.py`、`illumio_ops/web/routes/alerts.py`、
  `illumio_ops/services/flowsource.py`（流量規則前幾名的來源與目的鍵）
- Test: `tests/domain/test_alert_devices.py`（新）、`tests/store/test_alert_store.py`、`tests/services/alerts/test_alert_console.py`、`tests/web/test_alerts_routes.py`

**Interfaces:**
- Produces（`domain/alert_devices.py`）:
  - `Role = Literal["source", "destination", "subject"]`
  - `@dataclass(frozen=True) class Device: key: str; role: Role`
  - `MAX_DEVICES = 20`
  - `devices_of_detection(fingerprint: str) -> tuple[Device, ...]`：由偵測指紋取設備。指紋格式（`domain/detectors.py`、`domain/anomaly.py`）：
    第一段是偵測器代號。來源在第二段、目的在第三段的：`xenv`、`nag`、`new`、`authdst`、`reverse`、`pairport`。只有來源（第二段）的：`fanout`、
    `blocked`、`dcclient`、`newproc`、`tool`、`proc`、`peer`，以及 `{prefix}|{src}` 這種兩段的。三台都是設備的：`chain|{a}|{b}|{c}`（a 來源、b 與 c 目的）。
    只有目的的：`staging|{dst}`。對象是帳號、沒有設備的：`acct`、`acctsrc`（第三段是來源主機：`acctsrc|{account}|{src}` 回一台來源）。
    一段不是主機鍵（`parse_key` 丟 `ValueError`）就略過那一段，不猜。不認得的代號回空。
  - `devices_of_events(hosts: Iterable[str | None]) -> tuple[Device, ...]`：去掉 `None`、去重、保序，角色 `subject`，最多 `MAX_DEVICES`。
- Produces（`domain/alerting.py`）: `Trigger` 新增欄位 `devices: tuple[Device, ...] = ()` 與 `devices_more: int = 0`（超過上限沒列的台數）。
  - 偵測類（`evaluate_lateral_rule`）：`devices_of_detection(d.fingerprint)`。
  - 事件類逐台評估：該台（`host`）一台，角色 `subject`。次數門檻（`ThresholdType.COUNT`）：**本輪新命中事件**（`matched`）的主機。
  - 流量、頻寬、傳輸量規則：`IncrementTopFact` 新增 `src_key: str | None`、`dst_key: str | None`（`flowsource` 產生前幾名時一併帶出；
    現在只帶顯示字串），告警列出前幾名的兩端（去重，上限同上）。
  - 系統規則：空。
- Produces（資料表，`0018_alert_devices.sql`）:
  ```sql
  CREATE TABLE alert_devices (
      alert_id INTEGER NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
      key      TEXT NOT NULL,
      role     TEXT NOT NULL CHECK (role IN ('source', 'destination', 'subject')),
      PRIMARY KEY (alert_id, key, role)
  );
  CREATE INDEX ix_alert_devices_key ON alert_devices (key);
  ALTER TABLE alerts ADD COLUMN devices_more INTEGER NOT NULL DEFAULT 0;
  ```
  同一個遷移回填舊告警（純 SQL 做得到的部分）：`rule_type = 'event'` 且 `subject_key` 是 workload href（`LIKE '/orgs/%/workloads/%'`）的，
  寫一列 `subject`。偵測類的回填要解析指紋，放在啟動時的一次性步驟：`store.alerts.backfill_devices(conn) -> int`，對沒有任何 `alert_devices`
  列的 `lateral` 告警以 `devices_of_detection(subject_key)` 補寫，回補了幾則；由現有的啟動流程在套用遷移後呼叫一次（冪等：有列的不再處理）。
  確認 `alerts` 的刪除（`delete_alerts_before`）在這個連線上有開外鍵；沒有就在該函式裡明寫一條 `DELETE FROM alert_devices WHERE alert_id IN (…)`。
- Produces（`store/alerts.py`）: `insert_alert` 寫入 `trigger.devices` 與 `devices_more`；`devices(conn, alert_ids) -> dict[int, list[Device]]`；
  `list_alerts(..., device: str | None = None)`（只回涉及這個鍵的告警）；`period_counts`、`count_*` 不變。
- Produces（API）:
  - `AlertItem` 新增 `devices: list[AlertDevice]`、`devices_more: int`；`AlertDevice = {key: str, name: str, role: Role, managed: bool}`
    （`name` 由 `display_names` 解析，解析不到用鍵去掉 `ip:` 前綴；`managed` ＝鍵是 workload href）。既有的 `src`、`dst` 欄位保留（舊告警靠它顯示）。
  - `alerts.list` 多一個查詢參數 `device`。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/domain/test_alert_devices.py
W = "/orgs/1/workloads/"
@pytest.mark.parametrize("fingerprint, expected", [
    (f"xenv|{W}a|{W}b|22|6", [(W + "a", "source"), (W + "b", "destination")]),
    (f"pairport|{W}a|ip:10.0.0.9|many", [(W + "a", "source"), ("ip:10.0.0.9", "destination")]),
    (f"fanout|{W}a", [(W + "a", "source")]),
    (f"chain|{W}a|{W}b|{W}c", [(W + "a", "source"), (W + "b", "destination"), (W + "c", "destination")]),
    (f"staging|{W}d", [(W + "d", "destination")]),
    ("acct|CORP\\\\svc", []),
    (f"acctsrc|CORP\\\\svc|{W}a", [(W + "a", "source")]),
    (f"peer|{W}a|sig123|445|6", [(W + "a", "source")]),      # the signature is not a host
    ("something_new|x|y", []),                                 # an unknown detector names nothing
])
def test_devices_of_a_detection(fingerprint, expected): ...

def test_event_hosts_are_deduplicated_in_order_and_capped():
    hosts = [W + "a", None, W + "b", W + "a"] + [f"{W}h{i}" for i in range(40)]
    out = devices_of_events(hosts)
    assert [d.key for d in out[:2]] == [W + "a", W + "b"] and len(out) == MAX_DEVICES and {d.role for d in out} == {"subject"}
```

儲存與 API（各寫在對應的現有測試檔，沿用它們的 fixture）：

- `test_an_alert_is_stored_with_its_devices_and_found_by_one`：插入一則帶兩台設備的告警與一則不帶的；`devices(conn, [id])` 回那兩台；
  `list_alerts(device=鍵)` 只回第一則。
- `test_a_count_threshold_event_alert_names_the_hosts_of_the_events_that_fired_it`：`ThresholdType.COUNT` 的規則、三筆來自兩台主機的新事件，
  觸發的 `Trigger.devices` 是那兩台、角色 `subject`。
- `test_a_per_host_event_alert_names_its_host`、`test_a_system_alert_names_no_device`。
- `test_a_traffic_alert_names_both_ends_of_its_top_connections`。
- `test_old_alerts_are_backfilled`：直接寫入一則沒有設備列的 `lateral` 告警（指紋 `xenv|…`）與一則 `event` 告警（subject 是 href）；
  套用遷移並呼叫 `backfill_devices` 後兩則都有設備；再呼叫一次回 0。
- `test_deleting_an_alert_removes_its_devices`。
- 路由：`GET /api/alerts` 的每個項目有 `devices`（含 `name`、`managed`）；`?device=<鍵>` 只回涉及它的；一則舊告警（沒有設備列）`devices == []` 且 `src`／`dst` 仍在。

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && timeout 600 .venv/bin/python -m pytest tests/domain/test_alert_devices.py tests/services/alerts tests/web/test_alerts_routes.py -x -q -p no:logging`
Expected: FAIL

- [ ] **Step 3: 實作**（上面的介面）
- [ ] **Step 4: 重產契約**：`bash scripts/gen_contracts.sh`，提交 `web/src/api/contracts.json`、`generated.ts`。
- [ ] **Step 5: 跑測試確認通過**（同 Step 2，另加 `tests/store tests/gates`）
- [ ] **Step 6: Commit** `feat(v6-alerts): an alert records the hosts it is about`

---

### Task 2: 「新的」取代「未處理」

**Files:**
- Create: `illumio_ops/store/migrations/0019_alerts_seen.sql`
- Modify: `illumio_ops/store/alerts.py`、`illumio_ops/services/alerts/views.py`、`illumio_ops/services/shell.py`、`illumio_ops/web/routes/alerts.py`、
  `web/src/shell/nav.ts`、`web/src/shell/Shell.tsx`、`web/src/pages/alerts/AlertsHome.tsx`、i18n 兩檔
- Test: `tests/services/alerts/test_alert_console.py`、`tests/web/test_shell_status.py`、`tests/web/test_alerts_routes.py`、`tests/e2e/test_alerts_e2e.py`

**Interfaces:**
- Produces（資料表）: `CREATE TABLE alerts_seen (id INTEGER PRIMARY KEY CHECK (id = 1), seen_at TEXT NOT NULL);`
  遷移時寫入一列，`seen_at` ＝遷移當下（升級後整份歷史不算新的）。全站一份（產品只有一個帳號）。
- Produces（`store/alerts.py`）: `seen_at(conn) -> datetime`、`mark_seen(conn, at: datetime) -> datetime`（回更新前的值）、
  `count_new(conn, *, pce_url, org_id, after: datetime) -> int`。
- Produces（API）:
  - `POST /api/alerts/seen`（`alerts.mark_seen`）→ `{previous: datetime}`。告警頁進頁時呼叫一次。
  - `alerts.list` 多一個查詢參數 `new_after`（ISO 時間）：有給時每個項目的 `is_new` ＝ `fired_at > new_after`，並可搭配 `only_new=true` 只回新的；
    沒給時 `is_new` 一律 false。`AlertList` 新增 `new: int`（期間內 `fired_at > new_after` 的數量；沒給 `new_after` 為 0）。
    既有的 `unprocessed` 參數與「已歸組」的標示保留（API 不移除，介面不再用它當篩選）。
  - `ShellStatus.unprocessed_alerts` 改名 `new_alerts`＝`count_new(after=seen_at)`，不限 7 天。
- 前端:
  - 進告警頁：先 `alerts.mark_seen` 取得 `previous`，之後這個頁面存活期間的每次 `alerts.list` 都帶 `new_after=previous`（換頁、換天數、切篩選都一樣）。
    只有 `/` 這頁會呼叫；`/alerts/:id` 不呼叫。
  - 篩選：「全部／只看新的」（`Segmented`，`data-role="alert-seen"`），預設「全部」。取代第 1 段的「全部／只看未處理」。
  - 清單時間欄前，新的告警有一個點（`data-new="true"`，另有文字替代 `aria-label`＝鍵 `alerts_new_mark`）。
  - 結論句（頁首用途句下方，`data-role="page-conclusion"`）：模板
    zh「近 {days} 天共 {n} 則：{各等級}。上次查看之後新增 {k} 則。」／en 對應句；各等級只列大於 0 的（「嚴重 1、高 12、中 13」）；
    `n = 0` 時改用「近 {days} 天沒有告警。」；`k = 0` 時省略第二句。
  - 導覽徽章：`new_alerts > 0` 才顯示，文字「新 {n}」（鍵 `nav_alerts_new`）。`nav.ts` 的 `badge: "unprocessed"` 改名 `"new"`。
  - 「系統 › 安全」帳號說明加一句（鍵 `security_shared_seen`）：這個帳號由多人共用時，一個人看過告警，其他人的「新的」也會歸零。
  - KPI 列的「已歸組（已知）」保留。

- [ ] **Step 1: 寫失敗測試**
  - 服務：`mark_seen` 回更新前的值且第二次回第一次的時間；`count_new` 只算之後觸發的；遷移後 `seen_at` 存在。
  - 路由：`new_after` 讓 `is_new` 正確、`only_new` 只回新的、`new` 計數正確；`shell.status` 回 `new_alerts`。
  - e2e（`tests/e2e/test_alerts_e2e.py`）：
    ```python
    def test_new_alerts_are_marked_until_the_page_is_left(context, live_app):
        # 兩則舊告警（先 mark_seen），再插入一則新的；開首頁：徽章「New 1」、清單一列 data-new、結論句含 "1 new"
        # 切到 [data-role=alert-seen] 的 only-new：仍是那一列（不是空的）
        # 換到別頁再回來：徽章消失、沒有 data-new 的列
    def test_two_tabs_do_not_age_each_others_list(context, live_app):
        # 分頁 A 開首頁（看到 1 則新的）；分頁 B 開首頁；回分頁 A 切「只看新的」：那一則還在
    def test_opening_one_alert_from_a_link_does_not_mark_the_rest_seen(context, live_app):
        # 直接開 /alerts/<id>；之後 shell.status 的 new_alerts 不變
    ```
- [ ] **Step 2: 跑測試確認失敗**

Run: `cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && timeout 600 .venv/bin/python -m pytest tests/services/alerts tests/web/test_shell_status.py tests/web/test_alerts_routes.py -x -q -p no:logging`

- [ ] **Step 3: 實作後端，重產契約；實作前端**
- [ ] **Step 4: build，跑上面的測試加 e2e**

Run: `cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && npm --prefix web run --silent typecheck && npm --prefix web run --silent build > /dev/null && timeout 900 .venv/bin/python -m pytest tests/e2e/test_alerts_e2e.py tests/e2e/test_shell_e2e.py tests/e2e/test_ui_rules_e2e.py tests/i18n -q -p no:logging`

- [ ] **Step 5: Commit** `feat(v6-alerts): alerts are new until the alerts page has been opened`

---

### Task 3: 兩份清單：近期有告警的設備、隔離中的主機

**Files:**
- Modify: `illumio_ops/services/hosts.py`、`illumio_ops/web/routes/hosts.py`、`illumio_ops/services/quarantine.py`、`illumio_ops/web/routes/quarantine.py`、`illumio_ops/store/alerts.py`
- Test: `tests/web/test_hosts_routes.py`、`tests/web/test_quarantine_routes.py`、對應的 services 測試

**Interfaces:**
- Produces: `GET /api/hosts/alerted?days=7`（`hosts.alerted`）→ `{items: [{key, name, managed, alerts: int, highest: Severity, last_at: datetime}], more: int}`：
  期間內 `alert_devices` 依鍵彙總，依 `alerts` 多到少、同數依 `last_at` 新到舊，最多 20 筆，其餘的台數放 `more`。
  `store.alerts.alerted_devices(conn, *, pce_url, org_id, since, limit) -> list[Row]`。
- Produces: `GET /api/quarantine/current`（`quarantine.current`）→
  `{items: [{key, name, level, enforcement_mode, no_enforcement: bool, applied_at: datetime | None, applied_by: str | None}], write_key: bool}`：
  清冊中受管且標籤集含隔離鍵（`services/quarantine.py` 的 `KEY`）的 workload；`applied_*` 取自 `quarantine_actions` 該主機最近一次 `action='apply'` 且
  `result='ok'` 的列，沒有就都是 `None`（介面寫「不是由本工具套上」）。只讀清冊與動作紀錄，**不連 PCE**，沒有寫入 key 也能回。
  PCE 切換後尚未清除的清冊照 `require_same_pce` 的既有行為回錯。

- [ ] **Step 1: 寫失敗測試**
  - `hosts.alerted`：三台設備各 3、1、1 則（後兩台時間不同）→ 順序與 `highest` 正確；限 20 筆時 `more` 正確；期間外的不算；沒有任何設備列時 `items == []`。
  - `quarantine.current`：清冊三台（一台帶隔離標籤且有成功的 apply 紀錄、一台帶標籤但沒有紀錄、一台沒標籤）→ 回前兩台，
    第二台 `applied_at is None`；Idle 的那台 `no_enforcement` 為真；沒有寫入 key 時 `write_key` 為假、`items` 照回。
- [ ] **Step 2: 跑測試確認失敗**

Run: `cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && timeout 600 .venv/bin/python -m pytest tests/web/test_hosts_routes.py tests/web/test_quarantine_routes.py -x -q -p no:logging`

- [ ] **Step 3: 實作，重產契約**
- [ ] **Step 4: 跑測試確認通過**（同上加 `tests/gates tests/web/test_contract.py`）
- [ ] **Step 5: Commit** `feat(v6): the hosts recent alerts are about, and the hosts in quarantine now`

---

### Task 4: 導覽分組、名稱統一、白話用語

**Files:**
- Modify: `web/src/shell/nav.ts`、`web/src/shell/Shell.tsx`、每個 `registerNav` 呼叫（`section` 與 `order`）、i18n 兩檔、
  用到被改名字串的頁面
- Test: `tests/e2e/test_shell_e2e.py`、`tests/e2e/test_basic_mode_e2e.py`、`tests/i18n`

**Interfaces:**
- Produces: `NavSection = "watch" | "devices" | "analyse" | "automate" | "settings" | "system"`。分組標題鍵 `nav_section_watch` 等：
  監看 Watch／設備 Hosts／分析 Analyse／自動 Automation／設定 Settings。
  項目與順序（規格 §4.1）：監看＝告警 `/`、告警規則與通知 `/alert-rules`、報表 `/reports`（標籤改短為「報表」／"Reports"）；
  設備＝主機 `/hosts`、VEN 總覽 `/fleet`、隔離 `/quarantine`（Task 7 註冊）；分析＝偵測 `/detect`（`needs: "advanced"`）、調查 `/investigate`；
  自動＝規則排程 `/rule-schedules`；設定＝SIEM 轉送 `/siem`、系統（連到第一個系統頁，現有做法）。`Shell.tsx` 依這個順序渲染五組，每組有標題；
  `nav-spacer` 取消。
- 名稱統一（規格 §4.2；改 i18n 的值，鍵不改名，兩種語言）：
  「在工作台開啟」→「在調查頁開啟」／"Open in Investigate"；「橫向移動頁」→「偵測頁」／"Detection page"；「派送」→「通知」／"Notification"
  （欄名、段落名、`alert_delivery_title` 等）；「原廠查不到的」→「PCE 主控台看不到的」／"What the PCE console does not show"；
  背景工作頁的 `rule_schedules_tick` 補上名稱「規則排程切換」／"Rule schedule switching"。
- 白話用語（規格 §5.6）：新增一個前端小工具 `web/src/terms.ts`：`modeWord(mode: string): string` 回「白話（原文）」
  （`idle`→「還沒開始擋（Idle）」、`visibility_only`→「只記錄、不擋（Visibility Only）」、`selective`→「只擋部分（Selective）」、`full`→「全部都擋（Full）」；
  en：「Not blocking yet (Idle)」「Recording only (Visibility Only)」「Blocking some (Selective)」「Blocking everything (Full)」），
  鍵 `term_mode_idle` 等。主機頁身分段、VEN 總覽清單的模式欄、告警詳情的設備列（Task 5）用它；VEN 總覽的分布表與篩選下拉維持原文（那是對照 PCE 用的）。
  `Potentially Blocked` 的白話「開始擋之後會被擋」用在偵測頁與主機頁第一次出現處（鍵 `term_potentially_blocked`）。

- [ ] **Step 1: 更新／新增 e2e 測試**
  - `test_nav_order_and_sections`：改成斷言五個分組標題與各組項目的順序（en）。**先確認現有斷言在改之前是綠的、改名後會紅**，再改斷言。
  - `test_old_addresses_still_open`：逐一開現有的每個路徑（`ui_rules.PATHS` 加 `/alerts`、`/lateral`、`/alerts/rules`、`/system/reports`、`/system/channels`），都到得了頁面（有 `h1`），沒有被導回首頁（除了本來就轉址的那幾個，斷言它們轉到的位置與現在相同）。
  - `test_basic_mode_marks_advanced_items`：偵測仍淡化並標 ◆，調查不淡化。
  - `test_the_enforcement_mode_is_said_in_plain_words_with_the_term`：主機頁 Visibility Only 的主機顯示「Recording only (Visibility Only)」。
- [ ] **Step 2: build，跑測試確認失敗**
- [ ] **Step 3: 實作**
- [ ] **Step 4: build，跑測試**

Run: `cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && npm --prefix web run --silent typecheck && npm --prefix web run --silent build > /dev/null && timeout 900 .venv/bin/python -m pytest tests/e2e tests/i18n -q -p no:logging -n auto --dist loadfile`

- [ ] **Step 5: Commit** `feat(v6-ui): the navigation in five groups by purpose; one name for each place; enforcement modes in plain words`

---

### Task 5: 告警頁：涉及設備、同一份詳情、從告警隔離

**Files:**
- Create: `web/src/pages/alerts/AlertBody.tsx`、`web/src/components/HostLink.tsx`
- Modify: `web/src/pages/alerts/AlertsHome.tsx`、`web/src/pages/alerts/AlertDetail.tsx`、i18n 兩檔
- Test: `tests/e2e/test_alerts_e2e.py`、`tests/e2e/test_quarantine_e2e.py`

**Interfaces:**
- Produces（`HostLink.tsx`）: `HostLink({ hostKey, name, section }: { hostKey: string; name: string; section?: HostSection })`：
  連到 `/hosts?key=<鍵>#<section>`；位址用等寬字（第 1 段的 `HostName`）；`data-role="host-link"`。
  `HostSection = "status" | "alerts" | "different" | "usual" | "connections" | "would-block" | "ransomware" | "tamper" | "quarantine"`。
  `sectionForAlert(a: { rule_type: string; pack_key?: string | null; category: string }): HostSection | undefined`（規格 §6.3 的落點表）：
  事件類且事件是 VEN 離線、心跳遺失、暫停（`pack_key` 為 `rule_agent_offline`、`rule_agent_heartbeat`、`rule_agent_suspend`，
  或自訂規則的事件類型含這三種）→ `status`；竄改（`rule_agent_tampering`）→ `tamper`；偵測類與流量類 → `connections`；其餘不帶錨點。
  （`AlertItem` 若沒有 `pack_key`，在 Task 1 的 API 一併加上。）
- Produces（`AlertBody.tsx`）: `AlertBody({ alert, full }: { alert: AlertDetail; full: boolean })`：側欄與 `/alerts/:id` 共用的同一份內容。
  區塊順序固定（規格 §6.1）：
  1. 等級、類型、時間、標題（現有的 `summary`）。
  2. 建議怎麼做：`next_steps` 第一段，其餘在 `Disclosure`（摘要鍵 `alert_steps_all`「看全部」）。沒有就整段不出現。
  3. 涉及設備（`data-role="alert-devices"`）：每台一列——角色（來源／目的／對象）、`HostLink`、受管主機另列環境標籤與 `modeWord`；
     最多 20 台，`devices_more > 0` 時加一列「另有 {n} 台」。沒有設備的告警寫對象是什麼：系統類寫「這則告警是關於這個工具或 PCE 本身」
     （鍵 `alert_about_system`）；舊告警（沒有設備資料但有 `src`／`dst`）顯示那兩個文字、不可點。
     設備的標籤與模式來自詳情 API：`AlertDetail` 新增 `device_facts: {key: {env: str | None, mode: str | None, in_inventory: bool}}`（Task 5 內加，
     讀清冊，不連 PCE）。
  4. 經過：現有時間軸。
  5. PCE 主控台看不到的：`beyond_vendor` 非空才出現。
  6. `full` 才有：證據、通知紀錄、備註。
  7. 動作（底部，`side-actions`）：主要「調查這條連線」（有 `evidence_kind`；連到 `/investigate?alert=<id>`）；次要「隔離 {name}…」
     （`quarantine.eligible` 時；直接開 `QuarantineDialog`，`/alerts/:id` 上也一樣，不再是「在主機頁隔離」的連結）；
     Idle／Visibility Only 時按鈕可按、下方 `ActionNote`；不符合資格時不出現按鈕、寫原因（現有三句）；
     文字「這類以後不要再告警」（只在偵測類且未歸組；`full` 時捲到同頁的表單，否則連到 `/alerts/:id#mark-known`）、
     「在 PCE 主控台開啟」（有 `console_link`）、非 `full` 時「完整詳情」。
- 清單（`AlertsHome.tsx`）:「來源 → 目的」欄改名「涉及設備」（鍵 `alerts_col_devices`／"Hosts involved"）：有 `devices` 時，
  有來源與目的就排成「來源 → 目的」，否則逐台列出，最多 3 台，其餘「另有 {n} 台」；每台是 `HostLink`（帶 `sectionForAlert`）。
  點連結不觸發列的選取（`stopPropagation`）。沒有 `devices` 時照舊顯示 `src → dst` 文字；兩者都沒有顯示「—」，系統類顯示「PCE 或本工具」（鍵 `alerts_about_system_short`）。
- 「標為已知」的按鈕與表單標題改成「這類以後不要再告警」／"Stop alerting on this"（規格 §6.1）；表單說明文字不變。

- [ ] **Step 1: 寫失敗 e2e 測試**
  ```python
  def test_an_alert_lists_its_hosts_and_each_opens_that_host(context, live_app):
      # 用 Task 1 的寫入路徑插入一則 xenv 偵測告警（來源是清冊中的受管主機、目的是 ip: 位址）
      # 清單該列的 [data-role=host-link] 有兩個；第一個的 href 以 /hosts?key= 開頭並以 #connections 結尾
      # 點它：到主機頁、h1 是那台的名稱、清單頁的選取沒有因此改變（回上一頁後側欄仍是原本那則）
  def test_the_side_panel_and_the_full_page_show_the_same_alert(context, live_app):
      # 同一則告警：側欄 [data-role=alert-devices] 的文字 == 完整頁 [data-role=alert-devices] 的文字；
      # 兩邊的動作按鈕標籤集合相同（完整頁沒有「完整詳情」）
  def test_many_hosts_are_cut_to_three_in_the_list_and_twenty_in_the_detail(context, live_app):
      # 25 台主機的事件告警：存 20 台、devices_more=5。清單顯示 3 台與「另有 22 台」；詳情顯示 20 台與「另有 5 台」
  def test_an_old_alert_without_host_data_still_reads(context, live_app):
      # 直接寫一則沒有 alert_devices 的偵測告警（params 有 host、target）：清單顯示文字、沒有 host-link、詳情頁不報錯
  def test_quarantine_opens_from_the_alert_itself(context, live_app, fake_pce):
      # 沿用 test_quarantine_e2e.py 的 _setup；側欄與完整頁的隔離按鈕都直接開 [data-role=quarantine] 對話框
  def test_no_quarantine_button_for_unmanaged  # 現有測試維持綠
  ```
- [ ] **Step 2: build，跑測試確認失敗**
- [ ] **Step 3: 實作**
- [ ] **Step 4: build，跑測試**（`tests/e2e/test_alerts_e2e.py tests/e2e/test_quarantine_e2e.py tests/e2e/test_ui_rules_e2e.py tests/e2e/test_ui_controls_e2e.py`）
- [ ] **Step 5: Commit** `feat(v6-alerts): every alert lists the hosts it is about; one body for the side panel and the full page`

---

### Task 6: 主機頁成為目的地；全站的主機都可點

**Files:**
- Modify: `web/src/pages/hosts/HostProfile.tsx`、`illumio_ops/services/hosts.py`（`HostProfile` 多帶告警數）、
  用到主機名稱的頁面：`web/src/pages/lateral/LateralMovement.tsx`、`detect/Attention.tsx`、`workbench/Workbench.tsx`（結果表與左欄）、
  `fleet/Fleet.tsx`、`schedules/RuleSchedules.tsx`（紀錄的目標是規則不是主機，確認後略過）、`alerts/AlertDetail.tsx` 的證據表
- Test: `tests/e2e/test_hosts_e2e.py`、`tests/e2e/test_detect_attention_e2e.py`、`tests/e2e/test_workbench_e2e.py`

**Interfaces:**
- 帶 `key` 的主機頁：
  - 段落固定順序並各有 `id`（規格 §6.2）：`status`、`alerts`、`different`、`usual`、`connections`（誰連它／它連到哪／常用 port 這一組的容器）、
    `would-block`、`ransomware`、`tamper`、`quarantine`。進頁或 `location.hash` 改變時捲到該段並加 `data-arrived` 1.5 秒（樣式：左側一條強調線）。
    內容晚到的段落（要等 API）在資料到了之後再捲一次。
  - 新段 `#alerts`「這台的告警」：`alerts.list?device=<key>&days=7`，列時間、等級、標題（連到 `/alerts/<id>`），最多 10 則，其餘「另有 {n} 則」連到
    `/?device=<key>`（告警頁支援 `device` 查詢參數並在篩選列顯示可移除的條件「設備：{name}」）。沒有時寫「近 7 天沒有關於這台的告警。」
  - 結論句（`data-role="page-conclusion"`）：「{name}：{modeWord}；VEN {在線｜失聯 {n} 小時｜未回報心跳}；近 7 天告警 {n} 則；{隔離中（{level}）｜未隔離}。」
    非受管位址：「{address}：非受管位址，只有它的連線紀錄；近 7 天告警 {n} 則。」不在清冊的受管鍵：「{key}：不在目前的清冊中（可能已從 PCE 移除）；近 7 天告警 {n} 則。」
    告警數只算列得出這台的告警；`alert_devices` 最早一列的時間晚於 7 天前時，在數字後加註「（{日期} 起才記錄告警涉及的設備）」
    （`HostProfile` API 新增 `alerts_7d: int`、`alerts_counted_since: datetime | None`）。
- 不帶 `key` 的主機頁（搜尋框下）：三張清單卡，各最多 10 列、每列是 `HostLink`：
  - 「近 7 天有告警的設備」（`hosts.alerted`）：名稱、告警數、最高等級、最近一次時間。空：「近 7 天沒有告警涉及任何設備。」
  - 「失聯的受管主機」（`fleet.hosts` 依在線狀態篩選失聯三種）：名稱、失聯多久。空：「所有受管主機都在線。」只在清冊讀取過之後才這樣寫，
    清冊還沒讀過寫「清冊尚未讀取。」
  - 「隔離中的主機」（`quarantine.current`）：名稱、等級、何時套上。空：「目前沒有隔離中的主機。」
  - 進階模式另有第四張「需要注意」＝現有的關注清單元件（`detect/Attention.tsx`，同一份資料）；基本模式在這個位置顯示 `NeedsAdvanced`。
- 全站主機連結（規格 §6.3）：凡是把主機或位址當文字印出來的地方改用 `HostLink`（偵測頁各表、關注清單、調查頁結果表的主機欄與左欄主機項、
  告警證據表的來源與目的）。已經是連結的（VEN 總覽、偵測頁部分）改用同一個元件。調查頁左欄每列的「↗」連結併入名稱本身。
  **盤點法**：`grep -rn "hostname\|src_hostname\|dst_hostname\|\.name}" web/src/pages` 逐筆看，列出每一處改或不改的理由放進回報。

- [ ] **Step 1: 寫失敗 e2e 測試**
  ```python
  def test_arriving_with_an_anchor_lands_on_that_section(context, live_app):
      # /hosts?key=<DB>#tamper：[id=tamper] 在視窗內（boundingBox.y 在 0..視窗高之間）且有 data-arrived
  def test_the_host_page_lists_the_alerts_about_this_host(context, live_app): ...
  def test_the_host_page_without_a_host_offers_where_to_start(context, live_app, fake_pce):
      # 三張卡各有預期的主機；每個 host-link 點得進去
  def test_basic_mode_shows_the_three_lists_and_says_what_attention_needs(context, live_app): ...
  def test_a_host_no_longer_in_the_inventory_still_opens(context, live_app):
      # 一則告警涉及一台之後從清冊移除的主機：連結可點、頁面有結論句說它不在清冊、沒有錯誤
  def test_hosts_on_the_detection_and_investigate_pages_are_links(context, live_app): ...
  ```
- [ ] **Step 2: build，跑測試確認失敗**
- [ ] **Step 3: 實作（後端欄位先、重產契約，再前端）**
- [ ] **Step 4: build，跑整個 e2e**

Run: `cd /home/harry/rd/illumio-ops/.worktrees/v6-ui && npm --prefix web run --silent typecheck && npm --prefix web run --silent build > /dev/null && timeout 900 .venv/bin/python -m pytest tests/e2e tests/web tests/i18n -q -p no:logging -n auto --dist loadfile`

- [ ] **Step 5: Commit** `feat(v6-hosts): the host page is where every host name leads: its sections can be landed on, and without a host it says where to start`

---

### Task 7: 隔離頁

**Files:**
- Create: `web/src/pages/quarantine/Quarantine.tsx`
- Modify: `web/src/main.tsx`（頁面靠匯入時 `registerNav`：加一行 `import "./pages/quarantine/Quarantine";`）、`tests/e2e/ui_rules.py`（`PATHS` 加 `/quarantine`）、i18n
- Test: `tests/e2e/test_quarantine_e2e.py`

**Interfaces:**
- Consumes: `quarantine.current`（Task 3）、`quarantine.history`（不帶 `key`）、`quarantine.remove`、`QuarantineDialog` 的解除確認流程（主機頁現有的）。
- 頁面（規格 §6.4）：`registerNav({ section: "devices", path: "/quarantine", labelKey: "nav_quarantine", order: … })`。
  用途句：「現在有哪些主機被隔離、誰在什麼時候做的，以及怎麼解除。」／"Which hosts are quarantined now, who did it and when, and how to release them."
  結論句：「隔離中 {n} 台；其中 {m} 台的隔離不會生效（還沒開始擋或只記錄）。」`n = 0` 時不放結論句，清單位置是 `EmptyState`：
  「目前沒有隔離中的主機。要隔離一台主機，從告警或主機頁發動。」（連到 `/`）。
  清單欄：主機（`HostLink` 落 `#quarantine`）、等級、強制模式（`modeWord`；不會生效的加一行 `ActionNote` 樣式的說明）、何時由誰套上
  （沒有紀錄：「不是由本工具套上」）、「解除…」（危險按鈕，按下出現確認，確認後呼叫 `quarantine.remove`，結果照實顯示成功／失敗／未知）。
  `write_key` 為假時整欄不出現，清單上方一行說明並連到「系統 › PCE 連線」。
  下方「最近的隔離與解除」：`quarantine.history` 最近 50 筆（時間、主機、動作、等級、由誰、結果）。
  基本模式可用。

- [ ] **Step 1: 寫失敗 e2e 測試**（沿用 `test_quarantine_e2e.py` 的 `_setup` 與 `fake_pce`）
  - 兩台隔離中（一台 Idle）：清單兩列、結論句數字正確、Idle 那列有不會生效的說明。
  - 解除：確認後 `fake_pce` 收到那一台的標籤寫入、清單更新、紀錄多一筆。
  - PCE 拒絕（403）：該列顯示失敗與 PCE 的回應，主機仍在清單。
  - 沒有寫入 key：清單在、沒有解除按鈕、有說明。
  - 空狀態；基本模式可用；導覽「設備」組有「隔離」。
- [ ] **Step 2: build，跑測試確認失敗**
- [ ] **Step 3: 實作**
- [ ] **Step 4: build，跑測試**（`tests/e2e/test_quarantine_e2e.py tests/e2e/test_ui_rules_e2e.py tests/e2e/test_ui_skeleton_e2e.py tests/e2e/test_shell_e2e.py`）
- [ ] **Step 5: Commit** `feat(v6-quarantine): a page for what is quarantined now, by whom, and how to release it`

---

### Task 8: 偵測頁與調查頁整理

**Files:**
- Modify: `web/src/pages/lateral/LateralMovement.tsx`、`web/src/pages/workbench/Workbench.tsx`、`web/src/styles/base.css`、i18n
- Test: `tests/e2e/test_lateral_e2e.py`、`tests/e2e/test_workbench_e2e.py`

**Interfaces:**
- 偵測頁（規格 §6.5；不拆頁、不改內容與計算）：
  - 用途句下方加頁內目錄（`nav`，`data-role="page-toc"`）：每個區塊一個連結，點了捲到該區塊（區塊加 `id`）。
  - 區塊順序：結論（KPI 列、現在與全部強制後的比較、需要注意）在前；其餘在後。
  - 預設收合的細節區塊（用 `Disclosure`，摘要是區塊標題加一句由資料算出的摘要）：可觸及排名、依 Label 彙總、可落腳點、誰發起管理 port 連線。
    預設展開：重要資產與路徑、樞紐主機、跨環境管理 port、正在發生。**交付時把這份清單列給使用者確認**（規格 §13）。
  - 從目錄或外部連結帶 `#id` 進來時，該區塊若是收合的就展開。
- 調查頁：左欄每列的排除鈕（⊘）只在滑鼠停留或鍵盤焦點在該列時出現（`opacity`，仍可用 Tab 到達）；從告警進來時頁首有一行
  「條件來自告警 #{id}」與返回連結（已有，確認樣式用 `ActionNote` 類的次要文字）；結果表主機欄用 `HostLink`（Task 6 已做，這裡只確認）。

- [ ] **Step 1: 寫失敗 e2e 測試**
  - 目錄每個連結對得到一個存在的 `id`；點「可觸及排名」後該區塊展開且在視窗內。
  - 既有的偵測頁測試（讀收合區塊內容的）改成先展開再斷言。**先確認哪些現有斷言會因收合而讀不到**，逐一處理，不刪斷言。
  - 調查頁排除鈕：未停留時 `opacity` 為 0、`focus` 後為 1、按 Enter 有作用。
- [ ] **Step 2–4: build、失敗、實作、通過**（`tests/e2e/test_lateral_e2e.py tests/e2e/test_workbench_e2e.py tests/e2e/test_detect_attention_e2e.py tests/e2e/test_ui_rules_e2e.py`）
- [ ] **Step 5: Commit** `feat(v6-ui): the detection page has a table of contents and folds its details; the investigate page's exclude buttons appear on the row in hand`

---

### Task 9: 實機驗收與發版

**Files:**
- Modify: `CHANGELOG.md`、`illumio_ops/__init__.py`（6.8.0）、`README.md` 徽章、規格 §11 第 2 段（寫實際驗了什麼）

- [ ] **Step 1: 全套閘門**（`gates.sh`，最後一行 `ALL GATES GREEN`）
- [ ] **Step 2: 版本與變更紀錄**，Commit `chore(v6): version 6.8.0`
- [ ] **Step 3: 合併、push、盯 CI**（主持人）
- [ ] **Step 4: 打包、升級 .106 與 .135**（`PATH="$PWD/.venv/bin:$PATH" PYTHON="$PWD/.venv/bin/python" bash scripts/build_bundle.sh`；
  各台解開後 `./install.sh --accept-report`）。升級後確認回填：.106 的舊告警有設備（唯讀查 `alert_devices` 的列數與涵蓋的告警數）。
- [ ] **Step 5: 規則稽核**：`tools/ui_audit.py` 兩台 × 1440 與 820，四次都是 `every rule holds on every page`。
- [ ] **Step 6: 主線走查（.106，真資料）**：每一種有樣本的告警類型各取一則（`rule_type`／`pack_key` 分組取最新一則），逐則確認：
  清單列出設備 → 點進主機頁 → 落在對的段落 → 該段有內容。把每一類的結果列成表放進回報（類型、涉及設備、落點、是否正確）。
- [ ] **Step 7: lab 上製造沒有樣本的類型**（lab PCE 可寫入測試；NFR 不寫）：停一台 lab VEN 的服務，等 PCE 產生離線與心跳遺失事件，
  確認兩種告警（逐台評估的 Agent 離線、次數門檻的 VEN 心跳遺失）都列出那台主機並落在 `#status`；做完把 VEN 服務啟回並確認恢復在線。
  這一步動到 lab 主機的服務，**執行前向使用者確認要停哪一台**。
- [ ] **Step 8: 兩種模式各走一遍主線**（.135 是基本模式）；舊網址逐一開過；「新的」：看過歸零、換瀏覽器數字相同。
- [ ] **Step 9: 逐張看截圖**：告警頁、一則偵測類告警的完整頁、帶與不帶 key 的主機頁、隔離頁、偵測頁（兩台、1440）；回報列出看了哪幾張。
- [ ] **Step 10: 更新規格 §11，Commit**

## 不在這份計畫裡

報表樣式、列印與報表到主機的連結（規格 §9）是第 3 段；告警規則表單（§10）是第 4 段。
