# v6 P6b 首頁關注清單＋主機側寫 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 首頁顯示每小時算好的關注清單；新增主機側寫頁（身分、誰連它、常用 port、切換模式會被擋的流量、事件、竄改調查、勒索防護拆解），輕量模式也能用。

**Architecture:** 關注清單已由 P3 每小時算好存在 `analysis_results`（kind `focus`），首頁只讀不算。主機側寫的後端只回傳「store 已有的東西」（清冊列、暴露結果中此主機那一段、`host_tamper`、`host_ransomware(explain_allows=False)`）；所有流量／事件的數字由頁面呼叫既有的 `workbench.dimension`／`workbench.run`（條件＝此主機），沿用輕量模式按需讀取、單一讀取者閘門與 `run_segment`。允許規則的說明（PCE Rule Search，每個服務一次呼叫）放在按鈕後面。

**Tech Stack:** Python 3.12、Flask、pydantic 2、SQLite、React/TS/Vite、Playwright。

**Spec:** `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md` §6.5.3（主機側寫）、§6.5.4（關注清單、竄改調查）、§6.5.6（勒索防護）。

## Global Constraints

- 每個 operation 要有前端呼叫者，API 與 GUI 同一個 commit。
- 流量表只能經 `services/flowsource.py` 讀（`test_single_reader`）；本計畫不新增流量讀取。
- 中文用字照 PCE 主控台：Label、VEN、Full／Selective／Visibility Only／Idle、Allowed／Potentially Blocked／Blocked；zh 不可出現小寫 label／service／workloads／allow（`tests_v6/i18n/test_terminology.py`）。
- 新 gui 鍵 en／zh_TW 兩語系都要有。
- 主機的鍵沿用 `endpoint_key`：受管主機是 workload href，非受管是 `ip:<位址>`。

## Review Focus

1. 關注清單還沒算過（新安裝、hourly 尚未跑）或某來源失敗／過期——頁面要說「還沒算」或「哪個來源有問題」，不可顯示成「沒有要關注的事」。
2. `ip:` 主機（非受管位址）進主機頁——只顯示流量段落與「非受管位址」說明，不可 500。
3. 不存在於清冊的 href（已刪除的主機）——顯示「清冊沒有此主機」，流量段落照常。
4. 輕量模式——流量段落經按需讀取，頁面寫明讀了哪段；竄改／事件照常（事件有收）。
5. 告警的證據期間超過 30 天或格式不符——關注項目的「在工作台開啟」不給連結，而不是讓工作台 400。

---

### Task 1: 首頁關注清單

**Files:**
- Modify: `illumio_ops/services/workbench.py`（抽出 `request_for(kind, raw) -> FlowRequest | EventRequest | None`，`from_alert` 改用它；驗證失敗回 None）
- Create: `illumio_ops/services/home.py`（`focus_view(ctx, now) -> FocusView`）
- Modify: `illumio_ops/web/routes/system_jobs.py`（`OP_FOCUS = operation("home.focus", "GET", "/api/home/focus", None, FocusView)`）
- Modify: `web/src/pages/Home.tsx`、i18n en/zh_TW、`base.css`
- Test: `tests_v6/services/test_home.py`、`tests_v6/web/test_home_routes.py`、`tests_v6/e2e/test_home_e2e.py`

**Interfaces:**
- Produces: `FocusView{computed_at: datetime|None, items: list[FocusEntry], sources_status: dict[str,str], stale: bool}`；`FocusEntry` = 存的 item 欄位＋`link: FocusLink|None`，`FocusLink{route: str, query: dict[str,str]}`。
- 目標對應：`workbench`→`/investigate`＋`q`（`request_for` 的 JSON）；`host`、以及帶 `host_key` 的 `lateral`→`/hosts`＋`key`；沒有 `host_key` 的 `lateral`→無連結（P6c 補）；`settings_lateral`→`/system/lateral`；`settings_collection`→`/system/collection`；`system_jobs`→`/system/jobs`；`system_pce`→`/system/pce`；`alerts`→`/alerts`。

- [ ] 測試：`test_focus_not_computed`（無 focus 列→`computed_at is None`、items 空）、`test_focus_stale`（computed_at 超過 2 小時→`stale`）、`test_focus_links`（每種 target 的 link；超過 30 天的 segment→None；lateral 無 host_key→None）、`test_from_alert_unchanged`（既有 from_alert 測試照過）。
- [ ] 實作、路由、Home 頁：每項顯示嚴重度、`t(title_key, params)`、`t(why_key, params)`、「本週新出現」或「持續 N 週」、連結；`sources_status` 非 ok 的來源列在清單上方；未計算時寫「關注清單每小時計算一次，尚未算過」。
- [ ] e2e：種一列 focus 結果，首頁看到項目與連結。
- [ ] 閘門全綠後 commit。

### Task 2: 主機側寫後端

**Files:**
- Create: `illumio_ops/services/hosts.py`
- Create: `illumio_ops/web/routes/hosts.py`（註冊 blueprint）
- Test: `tests_v6/services/test_hosts.py`、`tests_v6/web/test_hosts_routes.py`

**Interfaces:**
- `profile(ctx, key, now) -> HostProfile{key, managed: bool, in_inventory: bool, identity: HostIdentity|None, labels: dict[str,str], exposure: HostExposureView|None, tamper: HostTamper|None, ransomware: HostRansomware|None, flow_mode: str}`
- `ransomware_allows(ctx, key) -> HostRansomware`（`explain_allows=True`）
- `add_tamper_note(ctx, key, pattern, process, reason) -> Annotation`、`remove_tamper_note(ctx, id)`
- Operations：`hosts.profile` GET `/api/hosts/profile?key=`、`hosts.ransomware_allows` POST、`hosts.tamper_note_add` POST、`hosts.tamper_note_remove` POST。

- [ ] 測試：受管主機完整欄位、`ip:` 主機（managed False、tamper/ransomware None）、清冊沒有的 href（in_inventory False）、暴露段落取自存的 exposure 結果、`explain_allows=False` 時不呼叫 Rule Search、註記增刪後 `host_tamper` 的 explained 計數改變、key 格式錯誤→400。
- [ ] 實作；路由錯誤對應同 workbench（ValueError→400）。
- [ ] 前端呼叫者在 Task 3 同一個 commit（本 task 不單獨 commit）。

### Task 3: 主機側寫頁與入口

**Files:**
- Create: `web/src/pages/hosts/HostProfile.tsx`（`/hosts?key=`，hidden nav）
- Modify: `web/src/pages/workbench/Workbench.tsx`（主機維度列旁「主機側寫」連結）、`web/src/pages/alerts/AlertDetail.tsx`（主體為主機時連到主機頁，若有）
- Test: `tests_v6/e2e/test_hosts_e2e.py`

- [ ] 段落：身分（名稱、模式、可見度、VEN 版本與狀態、心跳、政策同步、Label）；誰連它（`workbench.dimension` src_host，條件 dst＝此主機，7 天）；常用 port（service）；往外連到哪（dst_host，條件 src＝此主機）；切換模式後會被擋（decisions＝Potentially Blocked，src_host 與 service）；事件（`workbench.run` 事件模式 host_hrefs，明細）；每段附「在工作台開啟」。輕量模式時以 `Pulled` 顯示讀取資訊。
- [ ] 竄改調查：判讀（signal 型的 process／PID／動作；confirmed 型寫「這類事件不帶 process 資訊」）、規律分類與中位數間隔、時間線、依 OS 可複製指令、註記（新增／移除，說明被解釋的筆數）。
- [ ] 勒索防護：PCE 分數與計算分數、矛盾標示、逐服務表（服務、嚴重度、覆蓋、貢獻、流量分類）；「查允許規則」按鈕呼叫 `hosts.ransomware_allows`，顯示每個服務的允許規則或錯誤／部分。
- [ ] e2e：受管主機頁各段出現；`ip:` 主機頁只有流量段落；新增註記後列表出現。
- [ ] 閘門全綠後與 Task 2 一起 commit。

### Task 4: lab 驗收與收尾

- [ ] .106 lab（經通道）：先確認 lab 根目錄 `analysis_results` 有 `focus` 列；首頁清單、從清單點進主機頁；NetBird 竄改主機分類為規律循環、加註記「NetBird，已知」後歸組；輕量根目錄的主機頁流量段落按需讀取。
- [ ] Codex 最終審查（prompt 開頭「TASK: code review only…」），Important 以上一次修完。
- [ ] 合併 main、push、盯 CI。

**不在本計畫**：關注清單放進每封報表信件第一段（目前只有 lateral_posture 讀它）留給 P6e／P7；`/lateral` 頁是 P6c。
