# VEN Fleet Manager 設計（子專案 1／4，借鑒 illumio-plugger ven-fleet-manager）

日期：2026-09-09　狀態：**已實作**（2026-09-15 合入 main）　分支：feat/ven-fleet-manager（已合併）

> 實作與本文的偏離逐條記在文末「實作偏離」一節。§2.1 的七項決定**全部照做**；
> 偏離集中在計畫（plan）寫錯的錨點與兩個本文沒查證的假設。

## 0. 背景與範圍

illumio-plugger（alexgoller）的 ven-fleet-manager 提供 VEN 車隊層級視角：版本分布、compat 檢查、
enforcement 進程管線、coverage gaps、fleet health score，以及唯一的寫入功能 batch_progress（批次
推進 enforcement_mode）。本專案已有 VEN 狀態報表（`src/report/ven_status_generator.py`）與儀表板
`ven_summary`（`src/scheduler/jobs.py:run_ven_summary`），缺 compat 四態、管線、score、gaps、批次推進。

使用者決定：
- 呈現面：GUI 工作台新頁 ＋ 擴充 VEN 狀態報表。
- 批次推進：要做，含 dry-run 預覽；允許 idle→{visibility_only,selective,full}、visibility_only→
  {selective,full}、selective→{full}。

不在範圍：`/vens` 端點、time_in_mode、trend_store 每 tick 存快照、VEN 升級觸發。

## 1. 架構

```
scheduler run_ven_summary (dashboard.ven_summary_interval_seconds，預設 300s)
   └─ api.fetch_managed_workloads(raise_on_error=True)  ── 一次抓取
        ├─ ven_summary（現況，不動）
        └─ analyze_fleet(workloads, now, target_version) ──> dashboard_summary.json["fleet"]
                                                                   │
GUI #/investigate/fleet ── GET /api/fleet ─────────────────────────┘（讀快照，不打 PCE）
   ├─ GET  /api/fleet/list?bucket=<name>          完整名單（快照內過濾，分頁）
   ├─ POST /api/fleet/progress/preview            不寫 PCE
   └─ POST /api/fleet/progress/apply ──> PUT /workloads/bulk_update（1000/批）
                                          └─> config/fleet_progressions.json（可還原紀錄）
VEN 狀態報表 ── 同一個 analyze_fleet ── 新增四段落
```

原則：同一份分析函式餵 job、GUI、報表；PCE 只在排程 job 與 apply 兩處被打。

## 2. 分析層 `src/report/analysis/fleet.py`

純函式，無 I/O：

```
analyze_fleet(workloads: list[dict], now: datetime, target_version: str | None,
              *, top_n: int = 50) -> dict
```

輸入為 `/workloads?managed=true` 原始物件。每筆擷取：hostname（`hostname||name||"(unnamed)"`）、
href、online、enforcement_mode（缺→"idle"）、os_id/os_detail、
agent_version（`agent.status.agent_version || ven.version || agent.config.agent_version`）、
`agent.status.agent_health[]`、`last_heartbeat_on`、`hours_since_last_heartbeat`（PCE 算的優先）、
`security_policy_received_at/applied_at`、labels（key/value 直接讀，缺 value 時回 href）。

### 2.1 對 plugger 缺陷的決定（逐項）

| plugger 行為 | 本案決定 |
|---|---|
| target 未設則取 `max()` 字典序 | 版本用數字 tuple 排序（`26.2.20-2063` → (26,2,20,2063)，無法解析者排最後並標 unparsable）。target 未設定是明確狀態 `target: null`，前端顯示「未設定目標版本」，`needs_upgrade` 為 null 不為 0 |
| compat warning 併入 fail | 四態 `pass / warn / fail / unknown`：無 compat 項→unknown；任一 error→fail；否則任一 warning→warn；否則 pass |
| health score 缺資料分量給 100 | 缺資料分量剔除、其餘權重重新正規化；回傳 `score`, `components{name:{value,weight,present}}`, `partial: bool` |
| time_in_mode = now-updated_at | 不做 |
| OFFLINE_THRESHOLD_HOURS 死碼、`/vens` 沒用 | 不引入；online 判定沿用 `run_ven_summary` 的規則（status∈{active,online} 且 hslh≤1h）；stale 沿用既有 24h/48h 分桶 |
| `idle_compat_unknown` 篩選暗含 pass | 篩選名與內容一一對應：`idle_compat_pass`、`idle_compat_warn`、`idle_compat_fail`、`idle_compat_unknown`、`idle_all`、`visibility_ready`、`visibility_all` |
| 清單全量放記憶體 | 快照內每個 bucket 只存前 `top_n` 筆（依 hours_since_heartbeat 或 hostname 排序），並存 `count`；完整名單由 `/api/fleet/list` 從快照的 `workloads_index` 過濾 |

### 2.2 輸出結構

```
{
  generated_at, total, managed_online, managed_offline,
  versions: {distribution: {ver: {count, os_breakdown{os_detail:count}}},
             ordered: [ver...]（新→舊）, target, on_target, needs_upgrade|null,
             oldest, newest, unparsable: [ver...]},
  compat: {pass, warn, fail, unknown},                     # idle 工作負載的 compat 計數
  pipeline: {idle_compat_pass, idle_compat_warn, idle_compat_fail, idle_compat_unknown,
             visibility_ready, visibility_not_ready, selective, full}   # 各 {count, sample[:top_n]}
  heartbeat: {fresh, stale_24h, stale_48h, no_heartbeat},   # 對齊 ven_status_generator 分桶
  coverage_gaps: {by_app{app:{mode:count}}, by_env{env:{mode:count}}, unlabeled{count,sample}},
  agent_health: {errors{count,sample}, warnings{count,sample}}, # 每筆 {hostname,href,type,severity,audit_event}
  health_score: {score, partial, components{online,enforcement,version,heartbeat,compat}},
  workloads_index: [{href, hostname, mode, online, version, compat, hslh, app, env, os}]  # 供 list/preview
}
```

`visibility_ready` = `security_policy_received_at` 非空。health score 權重同 plugger
（online .30、enforcement(非 idle) .25、version(on_target) .20、heartbeat(fresh/(fresh+stale)) .15、
compat(pass/(pass+warn+fail)) .10），缺分量重正規化。

`workloads_index` 大小：每筆約 200 bytes，1 萬台約 2 MB，可接受；若超過 `fleet.index_cap`
（預設 20000）則不寫 index、`index_truncated: true`，list/preview 改為即時抓取。

## 3. 排程與儲存

- `run_ven_summary` 在既有抓取後多呼叫 `analyze_fleet`，用 `write_dashboard_summary` 寫 `fleet` 鍵。
  PCE 失敗時保留上次 `fleet` 並寫 `fleet.last_error`（與 ven_summary 同語意，不得寫 0）。
- target 版本設定：`config.json` 新鍵 `fleet.target_ven_version`（字串，空＝未設定），走既有
  settings 登錄（`src/settings/`）與 GUI 系統設定頁；`fleet.index_cap`、`fleet.max_batch`（預設 200）同處。

## 4. GUI `#/investigate/fleet`

- v3.1 路由表新增一列（工具頁），`design/v3/coverage.yaml` 新增 IV-16..IV-20：
  IV-16 fleet 摘要卡（score、版本、管線計數）、IV-17 管線 bucket 清單（可切 bucket、分頁）、
  IV-18 版本分布表、IV-19 coverage gaps 表、IV-20 推進預覽→套用抽屜。
- `pageHead` 一顆主按鈕「推進」，開抽屜：選 bucket 或勾選名單、選 to_mode、按「預覽」列
  eligible/skipped，再按「套用 N 台」。抽屜用 `data-field` 綁資料（3E 教訓）。
- 頁面只讀 `GET /api/fleet`（回快照 `fleet` 去掉 `workloads_index`）與 `GET /api/fleet/list`。
- 新 gui 鍵釘 `zh_explicit`；managed/unmanaged/idle/visibility_only/selective/full 等 PCE 字面按
  glossary 保留英文。

## 5. 批次推進 API（兩段式合約，子專案 4 重用）

新 blueprint `src/gui/routes/fleet.py`，`make_fleet_blueprint(cm, csrf, limiter, login_required)`。

`POST /api/fleet/progress/preview`
```
in : {to_mode, hrefs?: [...], bucket?: <pipeline name>}   # 二擇一；bucket 從快照 index 展開
out: {ok, to_mode, eligible: [{href, hostname, from, to}], deferred: [{href, hostname, from, to}],
      skipped: [{href, hostname, reason}], cap: max_batch, truncated: bool}
```
`deferred` = 合法轉換但 VEN 離線（PCE 立即接受，VEN 重連後才套用）；預設不勾選，操作者可加回。
skipped reason 列舉：`not_managed`、`invalid_transition`、`already_target`、`over_cap`、`unknown_href`。
eligible＋deferred 依 hostname 排序後合計截到 `max_batch`（預設 200，上限 1000），被截者進 skipped(over_cap)。

`POST /api/fleet/progress/apply`
```
in : {to_mode, hrefs: [...]}          # 只收 preview 回的 href 清單，不收 bucket/filter
out: {ok, applied: [{href, hostname, from, to, deferred: bool}], failed: [{href, hostname, http, error}],
      record_id}
```
- 伺服端重跑同一套 eligibility（不信任前端），任何 href 落在 skipped→整批 400 回 skipped，不部分套用；
  落在 deferred 的允許，回應逐筆標 `deferred: true`。
- 寫入：`ApiClient.bulk_update_workloads(items: list[{href, enforcement_mode}]) -> list[{href, status, errors}]`
  走 `PUT /orgs/{org}/workloads/bulk_update`，1000 筆一批，`rate_limit=True`；解析 PCE 回傳的逐筆狀態。
  官方 guide 查證：bulk_update 接受 `enforcement_mode`、每次 1000、不需 provision、下次 heartbeat 生效。
- 紀錄：`config/fleet_progressions.json`，沿用 `ScheduleDB` 的鎖內重讀單筆寫入模式：
  `{record_id: {at, user, to_mode, items: [{href, hostname, previous_mode, new_mode, status, errors}]}}`。
  `_audit_action("fleet_progress", user, to_mode, applied, failed, record_id)` 照寫。
- `@limiter.limit("10 per minute")`；CSRF app-wide 生效。
- `GET /api/fleet/progress/records?limit=` 回最近紀錄（GUI 抽屜底部「最近推進」）。還原功能不在本案，
  但紀錄格式保證可還原（previous_mode 必填）。

## 6. VEN 狀態報表擴充

`ven_status_generator.generate` 呼叫 `analyze_fleet` 後新增四段：進程管線、compat 分布、
fleet health score（含 partial 註記與缺分量）、coverage gaps。表格欄位走 `COL_I18N`；長 hostname
與 audit_event 欄位設定截斷規則（換行，不省略）。xlsx 輸出同步加 sheet。

## 7. 錯誤處理

- 快照缺 `fleet` 鍵（job 尚未跑）：GUI 顯示「尚無車隊快照，下次排程時間 T」，不顯示 0。
- `fleet.last_error` 存在：頁首 tone=warn 條顯示上次成功時間與錯誤。
- apply 部分失敗：回 200 含 failed 清單，紀錄逐筆狀態；GUI 列出失敗原因。
- bulk_update 非 2xx：整批 failed，紀錄 http 與 body 前 500 字。

## 8. 測試

- `tests/test_fleet_analysis.py`（TDD）：fixture 涵蓋 compat 四態、版本 tuple 排序與 unparsable、
  target null、score 重正規化（缺 compat／缺 heartbeat）、top_n 截斷與 count 一致、visibility_ready。
- `tests/test_fleet_progress.py`：fake ApiClient 驗 preview 六種 reason、apply 拒收非 preview 集合、
  over_cap、bulk 分批、逐筆狀態解析、紀錄落檔含 previous_mode。
- `tests/test_gui_fleet_e2e.py`：route mount（`[data-route="#/investigate/fleet"]`）、主按鈕、
  抽屜預覽→套用走 stub、無快照文案。
- i18n 閘門全套；coverage.yaml 守門；report 真機重產雙語逐頁看截斷（專案規則）。

## 9. 已知限制與風險

- lab（21 台）`agent_health` 全空，compat 四態只能靠 fixture 驗證；真環境驗證待有 idle VEN 的環境。
- 離線 VEN 的模式變更在 PCE 立即生效、VEN 重連後才套用；preview 把它列 `deferred`，操作者勾選後
  apply 允許並逐筆標 `deferred: true`。
- `fetch_managed_workloads` 走 500 上限＋截斷偵測；>500 集合的 fallback 行為依 api-layer-hardening。

---

## 實作偏離（2026-09-15 收尾時逐條對照）

§2.1 的七項決定全部照做，逐項驗證都有守門測試（`tests/test_fleet_analysis.py`）。
以下是**與本文或計畫不符**之處，都是實作時查原始碼才發現的。

### 本文（spec）層面

1. **`visibility_only` 不是 glossary 詞。** 本文與計畫都要求它「依 glossary
   保留英文」，實查 `src/i18n/data/glossary.json` 並沒有這一條，而 reviewer-copy
   閘門會正確地把 snake_case 形式判成內部欄位名。操作者文案改用 PCE 主控台自己
   的顯示形式 **Visibility only**；API 值域、bucket 名與紀錄欄位仍是
   `visibility_only`。

2. **`visibility_ready` / `visibility_not_ready` 在逐台清單上分不出來。**
   兩者的差別是 `security_policy_received_at`，而它沒有進 `workloads_index`
   （§2.2 定義的欄位裡沒有）。摘要的 `count` 仍精確；`/api/fleet/list` 對這兩個
   bucket 都列出整個 `visibility_only`。要分開就得擴充 index 的欄位。

3. **bulk_update 的 response schema 未經證實。** Illumio KB（REST_APIs_25_2／
   26_1）有批次上限 1000、一次只能跑一個 bulk operation（並行回 429）、政策在
   VEN 下次 heartbeat 才套用——但**沒有** response 的結構。逐筆
   `{href, status, errors}` 的解析是假設；PCE 沒有回應到的 href 會被賦予整批的
   結果，而不是猜它成功或失敗。**真 PCE 驗證仍未做。**

### 計畫（plan）層面

4. **`next_run_at` 的來源不存在。** 計畫要求從 `logs/job_health.json` 的
   `ven_summary` 條目取，該檔只有 `last_run` / `last_status` /
   `interval_seconds` / `registered_at`——APScheduler 的 `next_run_time` 活在
   排程行程的記憶體裡。改為由 `last_run + interval_seconds` 推導；job 卡住時
   推導值會落在過去，那本身就是訊號。兩個輸入缺一即 `null`。

5. **`components.weight` 沒有實作。** §2.1 寫回傳
   `components{name:{value,weight,present}}`，實作只給 `{value, present}`。
   權重是模組級常數 `_SCORE_WEIGHTS`，逐分量重複一次只是讓兩份數字有機會分岔。

6. **`crumbsFor` / `labelForRoute` 不需要改。** 計畫要求改
   `components/page.mjs`，但那兩支是從 `NAV` 讀的，在 `shell.mjs` 加一筆導覽項
   就夠了。

7. **端點是 5 個不是 6 個。** 計畫的 Task 6 寫「fleet 六個端點」，實際是
   `/api/fleet`、`/api/fleet/list`、`progress/preview`、`progress/apply`、
   `progress/records`。

### 真機驗收（2026-09-19 完成）

- **Task 5 的真機視覺驗收已補做。** 測試機開機後部署 `91383d77`，用 lab 真資料
  （21 台 managed workload）產 en／zh_TW 兩份 VEN 報表，Chromium 800／1280 兩種
  寬度逐章截圖並量測：**四章在兩語系兩寬度都沒有截斷或溢出，計畫的驗收條件通過。**
  逐頁親看另外發現六項非阻斷的版面／文案問題（F1–F6）。

- **F1–F6 已於同日全數修復並複驗**（使用者裁示先修再發版）。F1 的根因是 v2 report
  shell 移植時漏掉 `.report-table-panel` 的 `width: max-content`，影響五處
  `--compact` 呼叫端、非 fleet 專屬；修它又帶出一個 `--compact` 上限不收斂到欄寬的
  回歸，靠重產全報表抓到。複驗涵蓋全部 11 種 HTML 報表 × 2 語系 × 2 寬度，
  共 2,440 個面板、0 項問題。逐項紀錄在
  `docs/superpowers/plans/2026-09-09-ven-fleet-manager.md` 文末。

### 未完成

- **`bulk_update` 的 response schema 仍未經真 PCE 驗證**（見上方第 3 條）。
  這是整個功能唯一沒有事實基礎的地方，且推進動作是唯一會寫 PCE 的一段。
