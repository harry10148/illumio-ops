# CLI 選單流程稿（Task 14）

UI/UX 全面重新設計 v2 Phase 1 — CLI 互動選單重組為六區心智模型的流程規格。

- 依據：`docs/superpowers/specs/2026-08-03-ui-ux-redesign-v2-design.md` §5（CLI）
- 依據：`docs/superpowers/specs/2026-08-03-ui-redesign-feature-inventory.md` §3.2（CLI 互動選單 checklist）
- 範圍：僅互動選單（`illumio-ops.py` 不帶旗標時的 `main_menu()` 樹）。click 子指令（`cache`/`config`/`monitor`/`monitor-gui`/`gui`/`report`/`rule`/`siem`/`status`/`workload`/`completion`）結構不動，本文件不涉及（spec §5：「click 子指令：結構不動（7/24 全審過），僅術語/輸出對齊」）。

## 0. 範圍與方法

### 0.1 轉錄覆蓋聲明

逐檔全讀（非抽樣、非 grep 摘要），依序：

| 檔案 | 行數 | 角色 |
|---|---|---|
| `src/cli/menus/_root.py` | 190 | `settings_menu` — Settings 樹入口 |
| `src/cli/menus/_helpers.py` | 76 | 共用：`_menu_hints`／`_wizard_step`／`_wizard_confirm`／`_empty_uses_default`／時區換算 |
| `src/cli/menus/alert.py` | 119 | `alert_settings_menu` — 告警管道連線設定＋語言 |
| `src/cli/menus/event.py` | 237 | `add_event_menu` — Event 規則精靈 |
| `src/cli/menus/traffic.py` | 261 | `add_traffic_menu` — Traffic 規則精靈 |
| `src/cli/menus/bandwidth.py` | 249 | `add_bandwidth_volume_menu` — Bandwidth/Volume 規則精靈 |
| `src/cli/menus/system_health.py` | 87 | `add_system_health_menu` — System Health 規則精靈 |
| `src/cli/menus/manage_rules.py` | 184 | `manage_rules_menu` — 規則清單/刪除/修改 |
| `src/cli/menus/report_schedule.py` | 292 | `manage_report_schedules_menu` + `_add_report_schedule_wizard` |
| `src/cli/menus/web_gui.py` | 306 | `web_gui_security_menu` + `_web_gui_tls_menu` |
| `src/cli/menus/__init__.py` | 15 | 純 re-export，無選單邏輯 |
| `src/main.py` | 994 | 主選單入口：`main_menu()`（**285行**，經 `main()` 於 **773行** 呼叫）；其上游 `rule_management_menu`（166）／`report_generation_menu`（255）；下游散出的三個外部模組見下 |

主選單有 3 個分支指向 `src/cli/menus/` 之外、本任務 brief 未列入逐檔讀取清單的既有模組：`src/rule_scheduler_cli.py`（697 行）、`src/pce_cache_cli.py`（233 行）、`src/siem_cli.py`（278 行）。這三者在下面的樹狀圖與對照表中**仍然列為節點**（一項不漏）；review 後追加展開了它們的**第一層選單結構**（每個頂層項目一列、file:line 齊全），但不再往下展開到精靈逐步稿的細節（那是 Phase 2 實作階段的工作）。此決策記為 **RS-1**／**SY-1**（見 §4.4 findings 清單）。

### 0.2 現況渲染基礎（新設計沿用，不換 renderer）

- `draw_panel()`（`src/cli/_render.py:390-424`）：rich `Panel`，`box=ROUNDED`、`border_style=cyan`、`title_align=left`；`'-'` 這個特殊行值畫分隔線。終端不支援 unicode 時 `safe_box=True` 自動退化為 ASCII。
- `safe_input()`（`src/cli/_render.py:178-224`）：TTY 用 questionary、非 TTY 用 `input()`；固定印出 shortcuts 行（`Enter=default, 0=back, -1=cancel, h=help`）；有 `hint` 時提示尾巴印 `(Default: <hint>)`；輸入錯誤**原地印紅字重問**、不離開當前欄位（spec 5「錯誤就地重問」——現況已如此，新設計沿用不改）。
- `_wizard_step()`（`_helpers.py:51-53`）：印 `[Step n/N] <title>`（粗體青色），不畫框、只是一行 plain print。
- 本文件的 ASCII 稿把「小標頭框（麵包屑+提示）＋其下 plain-text 步驟內容」收斂成單一 box 呈現，純為文件可讀性；實機兩者是分開的 `print()`／`draw_panel()` 呼叫，語意相同。此收斂不代表新設計要把 `_wizard_step` 也塞進框裡。

### 0.3 資料樣例來源

畫面中的具體數值一律取自測試機真快照或原始碼常數，禁止手寫假資料（spec §6.1）：

| 用途 | 來源 |
|---|---|
| 健康列 5 燈數值 | `design/v2/snapshots/status.json`（`pce_stats`、`timezone`）＋ `design/v2/snapshots/dashboard_overview.json`（`job_health`、`pipeline`、`alert_channels`、`as_of`）；燈號邏輯照抄 `design/v2/mockup/js/components/healthbar.mjs` 與 `design/v2/mockup/js/core/fmt.mjs` |
| 規則清單／刪除範例 | `design/v2/snapshots/rules.json`（19 條真規則） |
| Best Practices 影響摘要的規則數 | `src/config.py:751-843`（`_best_practice_rules`，16 條事件規則常數）＋ `src/config.py:845-885`（`apply_best_practices(mode="replace")` 的清空/寫入/備份邏輯） |
| Event 精靈的分類/事件範例 | `src/events/catalog.py`（`_CATEGORY_ORDER`、`FULL_EVENT_CATALOG["User Access"]`，共 22 個事件，源碼常數非快照） |
| 報表排程精靈範例 | `design/v2/snapshots/report_schedules.json`（真排程 "UI Redesign Snapshot Demo"） |
| PCE URL | `design/v2/snapshots/status.json` 的 `api_url`（`dashboard_overview.json.api_url` 該欄位是 `null`，非來源） |
| PCE Cache 狀態列數字 | `design/v2/snapshots/cache_settings.json`（`enabled`、`db_path`）＋ `cache_status.json`（`events`/`traffic_raw` 列數） |
| Rule Scheduler 狀態列數字 | `design/v2/snapshots/rs_status.json`（`schedule_count`、`check_interval_seconds`、`next_trigger_at`） |
| SIEM 狀態/目的地範例 | `design/v2/snapshots/siem_status.json`（`sent`/`success_1h`）＋ `siem_destinations.json`（真目的地 "graylog"）＋ `siem_dlq.json`（DLQ 現況為空） |
| 顯示字串（英文） | 實際呼叫 `src.i18n.engine.t()`（`set_language('en')`）取得的真實輸出，非憑印象手寫 |


## 1. 現況選單樹（Step 1）

根：`python illumio-ops.py`（無旗標）→ `main()`（`src/main.py:559`）→ 互動分支（`main.py:773`）→ `main_menu()`（`src/main.py:285`）。

```
main_menu()                                                         main.py:285
|- [1] Rule Mgmt & Alerts -> rule_management_menu()            main.py:347->166
|  |- [1] Add Event Rule -> add_event_menu()         main.py:190 -> event.py:18
|  |- [2] Add Traffic Rule -> add_traffic_menu()   main.py:192 -> traffic.py:48
|  |- [3] Add Bandwidth/Volume -> add_bandwidth_volume_menu()
      main.py:194 -> bandwidth.py:48
|  |- [4] Manage Rules -> manage_rules_menu() main.py:196 -> manage_rules.py:40
|  |  |- list (rich table)                               manage_rules.py:43-133
|  |  |- "d <i[,i...]>" delete (NO confirm today -- MR-1)
         manage_rules.py:153-158
|  |  `- "m <i>" modify -> dispatch to the 4 add_*_menu()
         manage_rules.py:159-180
|  |- [5] Load Official Best Practices (destructive)            main.py:197-209
|  |- [6] Send Test Alert                                       main.py:210-219
|  |- [7] Run Analysis & Send Alerts Now                        main.py:220-239
|  |- [8] Rule Simulation & Debug Mode                          main.py:240-251
|  `- [9] Add System Health Rule -> add_system_health_menu()
      main.py:252 -> system_health.py:13
|- [2] Report Generation -> report_generation_menu()           main.py:349->255
|  |- [1] Generate Traffic Flow Report                         main.py:274->387
|  |- [2] Generate Audit Log Report                            main.py:276->777
|  |- [3] Generate VEN Status Report                           main.py:278->845
|  |- [4] Generate Policy Usage Report                         main.py:280->888
|  `- [5] Report Schedules -> manage_report_schedules_menu()
      main.py:282 -> report_schedule.py:24
|     |- list (A/E/T/D/R/0 command line)              report_schedule.py:40-127
|     |- [A]/[E] Add/Edit -> _add_report_schedule_wizard()
         report_schedule.py:130
|     |- [T] Toggle enable/disable                   report_schedule.py:101-106
|     |- [D] Delete (confirm already present)        report_schedule.py:107-115
|     `- [R] Run now                                 report_schedule.py:116-127
|- [3] Rule Scheduler -> rule_scheduler_menu()
   main.py:351 -> rule_scheduler_cli.py:91
|  `- -> _RuleSchedulerCLI.run() (RS-1: 1st level only)
      rule_scheduler_cli.py:108->643
|     |- [1] Schedule Management -> schedule_management_ui()
         rule_scheduler_cli.py:175
|     |  |- list grouped rulesets/rules (star/dot markers)
            rule_scheduler_cli.py:458
|     |  |- a = Browse & Add                          rule_scheduler_cli.py:355
|     |  |- e <ID> = Edit by ID                       rule_scheduler_cli.py:583
|     |  `- d <ID,ID,...> = Delete by IDs             rule_scheduler_cli.py:612
|     |- [2] Check Now (engine.check(), inline)   rule_scheduler_cli.py:656-659
|     `- [3] Settings -> _settings_submenu()          rule_scheduler_cli.py:668
|        |- 1 Toggle Enable/Disable (dup of Settings #6 -- AU-2)
            rule_scheduler_cli.py:685-689
|        `- 2 Set Check Interval                  rule_scheduler_cli.py:690-696
|- [4] System Settings -> settings_menu()            main.py:354 -> _root.py:14
|  |- [1] Change API Settings (URL/OrgID/Key/Secret)             _root.py:72-94
|  |- [2] Change Alert Channels & Lang -> alert_settings_menu()
      _root.py:96 -> alert.py:11
|  |  |- [1] Change Language                                     alert.py:55-61
|  |  |- [2]/[3]/[4]/[8] Toggle Mail/LINE/Webhook/Teams          alert.py:63-75
|  |  |- [5] Edit LINE Channel Access Token                      alert.py:77-89
|  |  |- [6] Edit LINE Target ID                                 alert.py:91-99
|  |  |- [7] Edit Webhook URL                                  alert.py:101-109
|  |  `- [9] Edit Teams Workflow Webhook URL                   alert.py:111-119
|  |- [3] SSL Certificate Verification toggle                   _root.py:97-106
|  |- [4] SMTP Settings                                        _root.py:107-146
|  |- [5] Report Output (Dir/Retention)                        _root.py:147-163
|  |- [6] Rule Scheduler enable/interval (AU-2: dup of [3])    _root.py:164-188
|  `- [7] Web GUI Security -> web_gui_security_menu()
      _root.py:190 -> web_gui.py:16
|     |- [1] Change Username/Password                          web_gui.py:61-78
|     |- [2] Manage Allowed IPs (A/D/0 sub-loop)              web_gui.py:80-116
|     `- [3] Configure TLS/HTTPS -> _web_gui_tls_menu()   web_gui.py:119 -> 122
|        |- [1] Toggle HTTPS                                 web_gui.py:222-230
|        |- [2] Switch mode (self-signed/custom)             web_gui.py:232-246
|        |- [3] Edit cert/key paths                          web_gui.py:248-262
|        |- [4] Toggle auto-renew                            web_gui.py:264-272
|        |- [5] Set auto-renew threshold                     web_gui.py:274-283
|        `- [6] Renew self-signed certificate now            web_gui.py:285-306
|- [5] Launch Web GUI (prompts for port, launch_gui())          main.py:356-375
|- [6] View System Logs -> view_logs()                       main.py:376 -> 144
|- [7] Manage PCE Cache -> manage_pce_cache_menu()
   main.py:378 -> pce_cache_cli.py:10
|  |- [1] View status                                      pce_cache_cli.py:165
|  |- [2] Edit settings (basic/retention/polling/throughput)
      pce_cache_cli.py:63
|  |- [3] Edit traffic filter                               pce_cache_cli.py:91
|  |- [4] Edit traffic sampling                            pce_cache_cli.py:141
|  |- [5] Backfill (interactive)                           pce_cache_cli.py:185
|  `- [6] Run retention now                                pce_cache_cli.py:215
|- [8] Manage SIEM Forwarder -> manage_siem_menu() main.py:381 -> siem_cli.py:9
|  |- [1] View status                                            siem_cli.py:49
|  |- [2] Edit forwarder config                                  siem_cli.py:57
|  |- [3] List destinations                                      siem_cli.py:80
|  |- [4] Add destination                                       siem_cli.py:127
|  |- [5] Edit destination                                      siem_cli.py:139
|  |- [6] Delete destination                                    siem_cli.py:152
|  |- [7] Test destination                                      siem_cli.py:162
|  `- [8] DLQ management -> _dlq_submenu()                      siem_cli.py:176
|     |- a List entries (up to 50)                              siem_cli.py:203
|     |- b Replay selected                                      siem_cli.py:211
|     |- c Purge selected                                       siem_cli.py:211
|     |- d Purge ALL by destination                             siem_cli.py:244
|     `- e Export to CSV                                        siem_cli.py:258
`- [0] Exit
```

### 1.1 `_helpers.py`（`src/cli/menus/_helpers.py`）不是選單節點

它是純函式庫，被上面每一個精靈 import：`_tz_offset_info`／`_utc_to_local_hour`／`_local_to_utc_hour`（時區換算，report_schedule 精靈用）、`_menu_hints`（麵包屑+shortcuts 兩行）、`_wizard_step`（步驟標籤）、`_wizard_confirm`（審閱畫面的 Y/N）、`_empty_uses_default`（Enter=採用預設 vs 真正取消 的判斷）。轉錄樹裡不單獨列節點，但下面每個精靈畫面都會引用到它的輸出格式。

## 2. 舊項→新落點對照表

左欄涵蓋上面樹狀圖的**每一個節點**（含容器節點，以及 3 個外部選單模組的第一層展開），與功能盤點 §3.2 的 6 個大類逐一交叉核對（見 §4.1）。review 後追加了 report_schedule 的 Toggle/Run-now 兩列（原稿漏列，§1 樹狀圖有、對照表沒有），以及 `rule_scheduler_cli.py`／`pce_cache_cli.py`／`siem_cli.py` 三個外部模組的第一層功能逐列。

圖例：**M**=併入其他既有節點（合併，非刪除）／**R**=位置搬遷（畫面／功能不變，僅落在新六區的哪一格）／**K**=原地保留（不移動）。


| # | 現況節點（file:line） | 現況顯示文字 | 新落點（六區） | 動作 | 備註 |
|---|---|---|---|---|---|
| 1 | `main.py:285` | `main_menu()`（根） | 新主選單（六區＋`G`/`0`） | R | 見 §3.2 |
| 2 | `main.py:166` | Rule Mgmt & Alerts（容器） | — | R | 拆解，9 個子項各自見下（不再是獨立的 root 項） |
| 3 | `main.py:190→event.py:18` | 1. Add Event Rule | Alerting | R |  |
| 4 | `main.py:192→traffic.py:48` | 2. Add Traffic Rule | Alerting | R |  |
| 5 | `main.py:194→bandwidth.py:48` | 3. Add Bandwidth & Volume Rule | Alerting | R |  |
| 6 | `main.py:196→manage_rules.py:40` | 4. Manage Rules | Alerting | R |  |
| 7 | `manage_rules.py:153-158` | "d" 刪除 | Alerting > Manage Rules | R | **MR-1**：現況無確認，新設計依 spec 2.3 補「一般刪除=確認」 |
| 8 | `manage_rules.py:159-180` | "m" 修改（分派 4 型精靈） | Alerting > Manage Rules | R |  |
| 9 | `main.py:197-209` | 5. Load Official Best Practices | Alerting | R | 破壞性動作，新增確認＋影響摘要（見 §3.5） |
| 10 | `main.py:210-219` | 6. Send Test Alert | Alerting | R |  |
| 11 | `main.py:220-239` | 7. Run Analysis & Send Alerts Now | Alerting | R |  |
| 12 | `main.py:240-251` | 8. Rule Simulation & Debug Mode | Alerting | R |  |
| 13 | `main.py:252-253→system_health.py:13` | 9. Add System Health Rule | Alerting | R | 現況排最後（歷史遺留：晚加的規則型別），新設計移到與其他 3 型並列（第 4 項） |
| 14 | `main.py:255` | Report Generation（容器） | — | R | 拆解為 Reports（4 項生成）＋ Automation（排程） |
| 15 | `main.py:274→387` | 1. Generate Traffic Flow Report | Reports | R |  |
| 16 | `main.py:276→777` | 2. Generate Audit Log Report | Reports | R |  |
| 17 | `main.py:278→845` | 3. Generate VEN Status Report | Reports | R |  |
| 18 | `main.py:280→888` | 4. Generate Policy Usage Report | Reports | R |  |
| 19 | `main.py:282→report_schedule.py:24` | 5. Report Schedules | Automation | R | 排程＝「會動的東西」，依 spec 六區判準歸 Automation，不留在 Reports |
| 20 | `report_schedule.py:130` | [A]/[E] Add/Edit 排程精靈 | Automation > Report Schedules | R |  |
| 21 | `report_schedule.py:101-106` | [T] Toggle enable/disable | Automation > Report Schedules | R | review 補列：原稿 §1 樹狀圖有列、§2/§3 漏列；畫面見 §3.3.4 |
| 22 | `report_schedule.py:107-115` | [D] Delete 排程 | Automation > Report Schedules | K | 現況已有確認，僅統一措辭／chrome |
| 23 | `report_schedule.py:116-127` | [R] Run now | Automation > Report Schedules | R | review 補列：同上，原稿漏列；畫面見 §3.3.4 |
| 24 | `main.py:351→rule_scheduler_cli.py:91` | 3. Rule Scheduler | Automation | R | 容器，第一層子選單見下三列（**RS-1**：更深的精靈逐步稿留待 Phase 2） |
| 25 | `rule_scheduler_cli.py:175` | [1] Schedule Management（browse/add/edit/delete） | Automation > Rule Scheduler | R |  |
| 26 | `rule_scheduler_cli.py:656-659` | [2] Check Now | Automation > Rule Scheduler | R |  |
| 27 | `rule_scheduler_cli.py:668-697` | [3] Settings（enable/interval） | Automation > Rule Scheduler | R | 吸收下面 #34 的重複開關 |
| 28 | `main.py:354→_root.py:14` | 4. System Settings（容器） | — | R | 拆解為 System（多數）＋ Automation（1 項，見 #34）＋ Reports（1 項，見 #33） |
| 29 | `_root.py:72-94` | 1. Change API Settings | System | R | 與 SSL verify 併為「PCE Connection」一個畫面 |
| 30 | `_root.py:96→alert.py:11（9 個子項，語言/mail/line/webhook×3/teams×2）` | 2. Change Alert Channels & Language | System | R | 整個 `alert_settings_menu` 搬到 System；spec 2.3「連線設定在系統區」 |
| 31 | `_root.py:97-106` | 3. SSL Certificate Verification | System | M | 併入 #29 PCE Connection 畫面（現況已是同一 `settings_menu` 下的相鄰項，非新合併，僅明確標註同畫面） |
| 32 | `_root.py:107-146` | 4. SMTP Settings | System | R | 與 #30 同屬「告警管道連線設定」網域 |
| 33 | `_root.py:147-163` | 5. Report Output (Dir/Retention) | Reports | R | 報表網域設定，不留在 System（spec Reports 區含「產出清單管理」） |
| 34 | `_root.py:164-188` | 6. Rule Scheduler enable/interval | Automation | **M** | **AU-2**：與 #27 是同一顆開關的兩個入口，合併為一（新設計只保留 Automation > Rule Scheduler 一處） |
| 35 | `_root.py:190→web_gui.py:16` | 7. Web GUI Security | System | R |  |
| 36 | `web_gui.py:61-78` | Change Username/Password | System > Web GUI Security | R |  |
| 37 | `web_gui.py:80-116` | Manage Allowed IPs | System > Web GUI Security | R |  |
| 38 | `web_gui.py:119→122` | Configure TLS/HTTPS（容器） | System > Web GUI Security | R |  |
| 39 | `web_gui.py:222-306` | TLS 6 個子項（toggle/mode/paths/autorenew/threshold/renew） | System > Web GUI Security > TLS | R | 同一畫面欄位，不拆散 |
| 40 | `main.py:356-375` | 5. Launch Web GUI | 主選單快捷鍵 `G` | **DD-2** | 不落入六區任一格：這是應用程式模式切換（背景啟動 Web GUI 行程），不是某個內容網域；見 §3.0 設計決策 |
| 41 | `main.py:376→144` | 6. View System Logs | System | R |  |
| 42 | `main.py:378→pce_cache_cli.py:10` | 7. Manage PCE Cache | System | R | 容器，第一層 6 項見下（**SY-1**：更深細節留待 Phase 2） |
| 43 | `pce_cache_cli.py:165` | [1] View status | System > PCE Cache | R | **WZ-3**：此模組完全不用 `draw_panel`/rich 框線，只有 plain print/input |
| 44 | `pce_cache_cli.py:63` | [2] Edit settings (basic/retention/polling/throughput) | System > PCE Cache | R |  |
| 45 | `pce_cache_cli.py:91` | [3] Edit traffic filter | System > PCE Cache | R |  |
| 46 | `pce_cache_cli.py:141` | [4] Edit traffic sampling | System > PCE Cache | R |  |
| 47 | `pce_cache_cli.py:185` | [5] Backfill (interactive) | System > PCE Cache | R | 長時間執行動作，非立即破壞性但應有進度回饋（Phase 2 考量） |
| 48 | `pce_cache_cli.py:215` | [6] Run retention now | System > PCE Cache | R | 會即時刪資料，建議升級為確認＋影響摘要（同 MR-1 精神） |
| 49 | `main.py:381→siem_cli.py:9` | 8. Manage SIEM Forwarder | System | R | 容器，第一層 8 項＋DLQ 5 子項見下（**SY-1**：更深細節留待 Phase 2） |
| 50 | `siem_cli.py:49` | [1] View status | System > SIEM Forwarder | R | 同 WZ-3：無 `draw_panel` 框線 |
| 51 | `siem_cli.py:57` | [2] Edit forwarder config | System > SIEM Forwarder | R |  |
| 52 | `siem_cli.py:80` | [3] List destinations | System > SIEM Forwarder | R |  |
| 53 | `siem_cli.py:127` | [4] Add destination | System > SIEM Forwarder | R |  |
| 54 | `siem_cli.py:139` | [5] Edit destination | System > SIEM Forwarder | R |  |
| 55 | `siem_cli.py:152` | [6] Delete destination | System > SIEM Forwarder | R | 破壞性，建議依 spec 2.3 補確認 |
| 56 | `siem_cli.py:162` | [7] Test destination | System > SIEM Forwarder | R |  |
| 57 | `siem_cli.py:176` | [8] DLQ management（容器） | System > SIEM Forwarder | R |  |
| 58 | `siem_cli.py:203` | a. List entries（最多 50 筆） | System > SIEM Forwarder > DLQ | R |  |
| 59 | `siem_cli.py:211` | b. Replay selected | System > SIEM Forwarder > DLQ | R |  |
| 60 | `siem_cli.py:211` | c. Purge selected | System > SIEM Forwarder > DLQ | R | 破壞性，建議補確認 |
| 61 | `siem_cli.py:244` | d. Purge ALL by destination | System > SIEM Forwarder > DLQ | R | 破壞性、影響範圍最大，建議依 spec 2.3 補確認＋影響摘要（同 §3.5 精神） |
| 62 | `siem_cli.py:258` | e. Export to CSV | System > SIEM Forwarder > DLQ | R |  |
| 63 | `main.py（`sel==0`）` | 0. Exit | 主選單 `0` | K |  |

**Overview／Investigate 兩區：左欄查無來源。** CLI 現況完全沒有互動選單項目對應這兩區——Dashboard 式總覽、流量分析器、Workload 搜尋、隔離 apply/lift、事件檢視器等都只存在於 Web GUI（見 inventory §1.1-1.3）。這不是「移除」，是新六區骨架下暫時的空區（**OV-1**／**IV-1**，見 §4.4），Overview 區用主選單既有的狀態列（API/規則數/語言/主題/最後活動）升格成一個獨立唯讀畫面撐場，Investigate 區指向既有的 `workload` click 子指令與 Web GUI；兩區內容擴充留待後續實作階段。

**統計**：63 個節點，**0 個移除**、**2 個合併**（#34 併入 #27 是 **AU-2** 真正的重複開關去重；#31 併入 #29 只是同一 `settings_menu` 下相鄰項的展示整併，並非消除重複功能）、**1 個非六區特殊落點**（#40 `Launch Web GUI` → 主選單快捷鍵，DD-2）、其餘 60 個為單純位置搬遷（R）或原地保留（K）。3 個外部模組（Rule Scheduler／PCE Cache／SIEM Forwarder）review 後合計展開 22 個第一層節點（另加 report_schedule 的 Toggle/Run-now 2 列補漏）。

## 3. 新選單逐畫面 ASCII 稿（Step 2）

### 3.0 設計決策

- **DD-1（每步驟 redraw）**：現況多數精靈只在「選類別」等入口點清畫面+重繪 `draw_panel`，之後的步驟只是往下 `print()`、不清畫面，畫面會越印越長（例如 `add_event_menu` 選完分類後，事件表格／trigger／進階篩選／審閱全部疊在同一個終端捲動視窗）。新設計統一為「每一步都清畫面＋重繪一個小標頭框（麵包屑 + shortcuts）＋當步驟內容」，畫面高度固定、精簡，這是本文件所有精靈畫面採用的呈現方式，也是本次提出的實際行為變更（非僅文件呈現手法）。
- **DD-2（Launch Web GUI 不進六區）**：它是「切換到另一個應用程式介面」的動作，不屬於總覽/調查/告警/自動化/報表/系統任何一個內容網域；比照 GUI 的 Cmd/Ctrl+K 指令面板精神，在 CLI 主選單保留一個不佔六區編號的快捷鍵 `G`。
- **WZ-1（Current／Default 分開標示）**：現況所有精靈的提示尾巴一律印 `(Default: X)`（`_render.py:236,258` 的 `def_val_prefix` 固定字串），即使是在編輯既有規則、`X` 其實是「目前值」而非工廠預設值，也用同一個詞——這正是 spec 5「目前值＋預設值」要求要分清楚的落差。新設計依情境分開：新增流程顯示 `(Default: X)`，編輯流程顯示 `(Current: X)`。
- **健康列常駐**：spec 1.1「全域健康列（所有頁面常駐）」比照 GUI 頂欄，CLI 端在主選單與六區子選單的標頭都印一行健康列（不含精靈內部逐步畫面——精靈步驟畫面留給輸入內容，健康列只在精靈的入口/離開點可見，避免每步都重繪 5 個字外部 API 造成延遲）。

### 3.1 全域健康列圖例（5 燈，引用 `healthbar.mjs`）

5 燈定義照抄 `design/v2/mockup/js/components/healthbar.mjs`（其註解本身即逐行引用 shipping GUI 原始碼行號）：

| # | 燈 | 資料 | 計算依據（healthbar.mjs） |
|---|---|---|---|
| 1 | Jobs（Daemon/排程） | `dashboard_overview.json.job_health` | 1502-1539 之抄錄：`level!='ok'` 記為壞，`worst()` 取最壞 tone；顯示 `okCount/total` |
| 2 | PCE | `status.json.pce_stats` | `event_poll_status` 映射 ok/warn/crit；`consecutive_failures>0` 一律升級 crit；`last_error` 是 sticky 欄位不驅動 tone（只作說明） |
| 3 | Lag（Cache lag） | `dashboard_overview.json.pipeline.cache_lag` | `level` 為 error/warning 的列 worst 化；顯示 `dur(maxLag)` |
| 4 | SIEM | `dashboard_overview.json.pipeline` | `verdict` 映射 tone；`siem_success_1h<95` 或 `dlq>0` 皆升級為至少 warn |
| 5 | Chan（告警管道） | `status.json.alert_channels` | 已啟用且已設定＝live；有 `last_status!='success'` 的 live 管道 → crit；否則 live>0 → ok |

Tone 詞彙（`fmt.mjs:tone()`）：`ok` / `warn` / `crit` / `info` / `neutral`。ASCII 稿以單一圓點 `●` 代表所有燈，實機用 `Colors.GREEN`/`WARNING`/`FAIL`/`DARK_GRAY` 上色區分 tone（同一套 5-tone token，spec 2.3）；本文件截取的真快照全部是 `ok`，故全部顯示綠點，不代表其他 tone 不存在——非 ok 的顏色差異無法用純文字重現，色彩語意見上表。

真快照數值（`design/v2/snapshots/status.json` + `dashboard_overview.json`，擷取時全綠）：


```
● Jobs 14/14 │ ● PCE OK │ ● Lag 3m │ ● SIEM 100% │ ● Chan 2/5   06:27 UTC+8
```

- Jobs `14/14`：`job_health` 14 個 job 全部 `level=ok`
- PCE `OK`：`pce_stats.event_poll_status=ok`、`consecutive_failures=0`
- Lag `3m`：`cache_lag` 最大值 174s → `dur()` 四捨五入為 3 分鐘
- SIEM `100%`：`pipeline.siem_success_1h=100.0`、`dlq=0`
- Chan `2/5`：`alert_channels` 中 mail/line 為 `enabled&&configured`（webhook/telegram/teams 未設定）
- 時區 `UTC+8`：`status.json.timezone`

### 3.2 主選單（六區）


```
╭─ Illumio PCE Ops v3.x ──────────────────────────────────────────────────────╮
│ ● Jobs 14/14 │ ● PCE OK │ ● Lag 3m │ ● SIEM 100% │ ● Chan 2/5   06:27 UTC+8 │
│ API: https://pce.lab.local:8443  │  Lang: EN  │  Theme: Dark                │
│ Shortcuts: Enter=default | 0=back | -1=cancel | h/?=help                    │
├─────────────────────────────────────────────────────────────────────────────┤
│   1. Overview      status, posture, top actions                             │
│   2. Investigate    traffic, workloads, events, quarantine                  │
│   3. Alerting       rules, run/test/debug, output console                   │
│   4. Automation     rule scheduler, report schedules, job history           │
│   5. Reports        generate & manage the 11 report types                   │
│   6. System         PCE/cache/SIEM/TLS/security/display/logs                │
│   G. Launch Web GUI (background)                                            │
│   0. Exit                                                                   │
╰─────────────────────────────────────────────────────────────────────────────╯
```

### 3.3 六區子選單


#### 3.3.1 Overview（OV-1：現況無對應項，僅狀態列升格）

```
╭─ Overview ──────────────────────────────────────────────────────────────────╮
│ ● Jobs 14/14 │ ● PCE OK │ ● Lag 3m │ ● SIEM 100% │ ● Chan 2/5   06:27 UTC+8 │
├─────────────────────────────────────────────────────────────────────────────┤
│   API URL          : https://pce.lab.local:8443                             │
│   Rules configured  : 19   (16 event / 1 traffic / 1 system / 1 bw)         │
│   Language / Theme  : EN / Dark                                             │
│   Last activity     : 3m ago                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│   (Read-only. No further drill-down in this iteration -- see                │
│   design/v2/cli-flows.md ss2 note OV-1.)                                    │
│   0. Return                                                                 │
╰─────────────────────────────────────────────────────────────────────────────╯
```

#### 3.3.2 Investigate（IV-1：現況無對應項）

```
╭─ Investigate ───────────────────────────────────────────────────────────────╮
│   No interactive menu maps here yet (see note IV-1).                        │
│   Traffic analyzer, workload search and quarantine apply/lift are           │
│   Web GUI-only today; the closest CLI equivalent is the click               │
│   subcommand:                                                               │
│                                                                             │
│     illumio-ops workload --help                                             │
│                                                                             │
│   0. Return                                                                 │
╰─────────────────────────────────────────────────────────────────────────────╯
```

#### 3.3.3 Alerting（= 舊 root #1 全部 9 項，重新編號）

```
╭─ Alerting ──────────────────────────────────────────────────────────────────╮
│   1. Add Event Rule                                                         │
│   2. Add Traffic Rule                                                       │
│   3. Add Bandwidth & Volume Rule                                            │
│   4. Add System Health Rule                                                 │
│   5. Manage Rules (list / delete / modify)          -- 19 rules             │
├─────────────────────────────────────────────────────────────────────────────┤
│   6. Send Test Alert                                                        │
│   7. Run Analysis & Send Alerts Now                                         │
│   8. Rule Simulation & Debug Mode                                           │
│   9. Load Official Best Practices           [destructive, see ss3.4]        │
├─────────────────────────────────────────────────────────────────────────────┤
│   0. Return                                                                 │
╰─────────────────────────────────────────────────────────────────────────────╯
```

#### 3.3.4 Automation（= 舊 Rule Scheduler + Report Schedules + 去重後的排程開關）

```
╭─ Automation ────────────────────────────────────────────────────────────────╮
│   1. Rule Scheduler             ON  │ check every 300s                      │
│      -- ruleset/rule browser, schedules, check-now  -> see ss3.3.4b         │
├─────────────────────────────────────────────────────────────────────────────┤
│   2. Report Schedules                    1 schedule -> see ss3.3.4a         │
├─────────────────────────────────────────────────────────────────────────────┤
│   0. Return                                                                 │
╰─────────────────────────────────────────────────────────────────────────────╯
```

**3.3.4a Automation > Report Schedules（清單畫面，review 補：原稿沒有這張，導致 Toggle/Run-now 兩個動作無畫面可查）**


```
╭─ Automation > Report Schedules ─────────────────────────────────────────────╮
│ Name                  Type          Frequency    Last Run  Status           │
├─────────────────────────────────────────────────────────────────────────────┤
│ [1] UI Redesign Sn..  audit_summary Weekly (Mon) Never     Never            │
│                                                                             │
│ [A] Add  [E] Edit  [T] Enable/Disable  [D] Delete  [R] Run now              │
│ [0] Back                                                                    │
│ [?] Select action [A/E/T/D/R/0] >                                           │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

**3.3.4b Automation > Rule Scheduler（第一層選單，`rule_scheduler_cli.py:643-650`，review 補）**

真數字取自 `design/v2/snapshots/rs_status.json`：`schedule_count=3`、`check_interval_seconds=300`、`next_trigger_at="2026-08-04T08:00:00"`。第 3 項「Settings」正是 **AU-2** 提到、與舊 System Settings #6 重複的那顆開關——新設計裡這裡是唯一保留的入口。


```
╭─ Automation > Rule Scheduler ───────────────────────────────────────────────╮
│ 1. Schedule Management               3 schedules (ruleset/rule)             │
│ 2. Check Now                  next auto-check: 2026-08-04 08:00             │
│ 3. Settings                       ON  |  check every 300s                   │
│ 0. Back                                                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ [?] >                                                                       │
╰─────────────────────────────────────────────────────────────────────────────╯
```

#### 3.3.5 Reports（= 舊 4 種報表生成 + Report Output 設定）

```
╭─ Reports ───────────────────────────────────────────────────────────────────╮
│   1. Generate Traffic Flow Report                                           │
│   2. Generate Audit Log Report                                              │
│   3. Generate VEN Status Report                                             │
│   4. Generate Policy Usage Report                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│   5. Report Schedules                    -- see Automation area             │
│   6. Report Output Settings   (Dir: reports/ | Retention: 30d)              │
├─────────────────────────────────────────────────────────────────────────────┤
│   0. Return                                                                 │
╰─────────────────────────────────────────────────────────────────────────────╯
```

#### 3.3.6 System（= 舊 Settings 大部分 + View Logs + PCE Cache + SIEM）

```
╭─ System ────────────────────────────────────────────────────────────────────╮
│   1. PCE Connection (API URL / Org ID / Key / Secret / SSL verify)          │
│   2. Alert Channel Connections (Mail/LINE/Webhook/Teams + Language)         │
│   3. SMTP Settings                                                          │
│   4. Web GUI Security (username / password / allowed IPs / TLS)             │
├─────────────────────────────────────────────────────────────────────────────┤
│   5. PCE Cache                              6 functions -> ss3.3.6a         │
│   6. SIEM Forwarder            8 + DLQ 5 actions -> ss3.3.6b/6c             │
│   7. View System Logs                                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│   0. Return                                                                 │
╰─────────────────────────────────────────────────────────────────────────────╯
```

**3.3.6a System > PCE Cache（第一層選單 + View status 代表畫面，`pce_cache_cli.py:10-40`，review 補）**

真數字取自 `design/v2/snapshots/cache_settings.json`（`enabled`、`db_path`）與 `cache_status.json`（`events`=146567、`traffic_raw`=135394 列）。**WZ-3**（新 finding）：此模組完全不用 `draw_panel`/rich 框線，只有 `print(t("pcc_menu"))` + `input("> ")` 的純文字選單，與 `cli/menus/` 下所有精靈的 chrome 不一致——新設計統一套用同一個小標頭框（呼應 DD-1）。


```
╭─ System > PCE Cache ────────────────────────────────────────────────────────╮
│ 1. View status                                                              │
│ 2. Edit settings (basic / retention / polling / throughput)                 │
│ 3. Edit traffic filter                                                      │
│ 4. Edit traffic sampling                                                    │
│ 5. Backfill (interactive)                                                   │
│ 6. Run retention now                                                        │
│ 0. Back                                                                     │
│ > 1                                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Enabled: True                                                               │
│ DB path: data/pce_cache.sqlite                                              │
│ Events rows: 146567                                                         │
│ Traffic (raw) rows: 135394                                                  │
╰─────────────────────────────────────────────────────────────────────────────╯
```

**3.3.6b System > SIEM Forwarder（第一層選單 + 真目的地，`siem_cli.py:9-32`，review 補）**

真資料取自 `design/v2/snapshots/siem_destinations.json`（唯一目的地 "graylog"，`172.16.15.105:5514`，`tcp`/`cef`）與 `siem_status.json`（`sent=128334`、`success_1h=100.0`）。同 WZ-3，此模組也沒有 `draw_panel` 框線。


```
╭─ System > SIEM Forwarder ───────────────────────────────────────────────────╮
│ SIEM Forwarder Menu:                                                        │
│   1. View status                                                            │
│   2. Edit forwarder config                                                  │
│   3. List destinations                                                      │
│   4. Add destination                                                        │
│   5. Edit destination                                                       │
│   6. Delete destination                                                     │
│   7. Test destination                                                       │
│   8. DLQ management                                                         │
│   0. Back                                                                   │
│ > 1                                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ graylog  172.16.15.105:5514  tcp/cef  sent=128334  success_1h=100%          │
╰─────────────────────────────────────────────────────────────────────────────╯
```

**3.3.6c System > SIEM Forwarder > DLQ Management（`siem_cli.py:176-191`，5 個動作，review 補）**

真資料：`design/v2/snapshots/siem_dlq.json` 顯示 DLQ 目前是空的（`entries: []`），畫面如實呈現「0 筆」而非虛構待處理項目。


```
╭─ System > SIEM Forwarder > DLQ Management ──────────────────────────────────╮
│ DLQ Management:                                                             │
│   a. List entries                                                           │
│   b. Replay selected                                                        │
│   c. Purge selected                                                         │
│   d. Purge ALL by destination                                               │
│   e. Export to CSV                                                          │
│   0. Back                                                                   │
│   > a                                                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│ (0 entries -- destination "graylog" DLQ is currently empty)                 │
╰─────────────────────────────────────────────────────────────────────────────╯
```

### 3.4 精靈逐步畫面

每個精靈以一個**具體、來自真資料的完整走過一遍**呈現全部 n/N 步（而非窮舉每個條件分支；分支在旁註說明）。四個規則精靈的走過範例用 `design/v2/snapshots/rules.json` 裡的既有規則以**編輯模式**示範（能同時展示「目前值」的用法）；Event 精靈用**新增模式**示範（能展示無「目前值」時的畫面）。

#### 3.4.1 Alerting > Add Event Rule（新增，5 步；現況 4 步 + 1 個無標籤畫面，見 EV-1）

現況 `add_event_menu`（`event.py:18-237`）的「選分類」畫面（`event.py:31-56`）是全案唯一一個**沒有**呼叫 `_wizard_step()` 的互動點——用類別清單但不印 `[Step n/N]`。新設計依 spec 5「精靈統一：第 n/N 步」把它補上正式步驟編號，原本的 4 步（`event.py` 內 `_wizard_step(1..4, 4, ...)`）順延為 2-5：


```
╭─ Alerting > Add Event Rule ─────────────────────────────────────────────────╮
│ [Step 1/5] Select Category  [NEW step label -- see EV-1]                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  1. General                    2. Agent Health                              │
│  3. Agent Operations           4. Agent Security                            │
│  5. User Access                6. Auth & API                                │
│  7. Policy                     8. Containers & Workloads                    │
│  9. Network & Integrations    10. Platform & System                         │
│ 11. Inventory & Identity                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ [?] Select category [1-11] >                                                │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Alerting > Add Event Rule ─────────────────────────────────────────────────╮
│ [Step 2/5] Select Event Type                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ No Type                          Description                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1  user.accept_invitation       User Accept Invitation                      │
│ 2  user.authenticate            User Authenticated                          │
│ 3  user.create                  User Create                                 │
│ ...                             (22 events in User Access)                  │
│ 12 user.sign_in                 User Sign-In / Login                        │
│ 13 user.sign_out                User Sign-Out / Logout                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ [?] Select Event [0-22] >                                                   │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Alerting > Add Event Rule ─────────────────────────────────────────────────╮
│ [Step 3/5] Set Trigger                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ Selected: user.sign_in                                                      │
│                                                                             │
│ 1. Immediate Alert                                                          │
│ 2. Cumulative Count                                                         │
│ [?] please select [0-2] (Default: 1) > 2                                    │
│                                                                             │
│ [?] Cumulative Count (Default: 5) >                                         │
│ [?] Time Window (mins) (Default: 10) >                                      │
│ [?] Cooldown Time (mins) (Default: 10) >                                    │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Alerting > Add Event Rule ─────────────────────────────────────────────────╮
│ [Step 4/5] Advanced Filters                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ --- Advanced Filters ---                                                    │
│ (Enter 0 to go back)                                                        │
│                                                                             │
│ [?] Status Filter [0-2] (Default: 0)          [NEW: inline legend,          │
│     1=Success  2=Failure  0=All                see EV-2]           >        │
│                                                                             │
│ [?] Severity Filter [0-3] (Default: 0)                                      │
│     1=Error  2=Warning  3=Info  0=All          >                            │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Alerting > Add Event Rule ─────────────────────────────────────────────────╮
│ [Step 5/5] Review & Save                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ Type:              event                                                    │
│ Event:             user.sign_in                                             │
│ Trigger:           count                                                    │
│ Threshold:         5                                                        │
│ Window / Cooldown: 10m / 10m                                                │
│ Status / Severity: all / all                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ [?] Save this rule? (Y/n) >                                                 │
╰─────────────────────────────────────────────────────────────────────────────╯
```

#### 3.4.2 Alerting > Modify Traffic Rule（編輯 `rules.json` 第 16 條「高 Blocked 流量」，5 步）


```
╭─ Alerting > Modify Traffic Rule ────────────────────────────────────────────╮
│ [Step 1/5] Basic Setup                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ [?] Rule Name (Current: 高 Blocked 流量) >                                  │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Alerting > Modify Traffic Rule ────────────────────────────────────────────╮
│ [Step 2/5] Traffic Filters                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│ Policy Decision                                                             │
│ 1. Blocked   2. Potentially Blocked   3. Allowed   4. All                   │
│ [?] Select (Current: 1 -- Blocked) >                                        │
│                                                                             │
│ --- Service / Port (include) ---   [object-picker, see note WZ-2]           │
│   1. Label  2. IP List  3. Workload  4. IP/CIDR (manual)                    │
│   -- Done --                                                                │
│ [?] Select object category for 'Service / Port criteria (include)': >       │
│                                                                             │
│ Source / Destination: (none set)                                            │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Alerting > Modify Traffic Rule ────────────────────────────────────────────╮
│ [Step 3/5] Trigger Threshold                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ [?] Time Window (mins) (Current: 10) >                                      │
│ [?] Trigger Threshold (count) (Current: 25) >                               │
│ [?] Cooldown Time (mins) (Current: 30) >                                    │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Alerting > Modify Traffic Rule ────────────────────────────────────────────╮
│ [Step 4/5] Exclusions                                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│ --- Excludes (Optional) ---                                                 │
│ [?] Exclude Source Label/IP/CIDR: (none set) >                              │
│ [?] Exclude Destination Label/IP/CIDR: (none set) >                         │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Alerting > Modify Traffic Rule ────────────────────────────────────────────╮
│ [Step 5/5] Review & Save                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ Type:              traffic                                                  │
│ Name:              高 Blocked 流量                                          │
│ Policy:            Blocked                                                  │
│ Port/Proto:        -                                                        │
│ Source/Dest:       -  ->  -                                                 │
│ Threshold:         25 in 10m (cooldown 30m)                                 │
│ Excludes:          -                                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ [?] Save this rule? (Y/n) >                                                 │
╰─────────────────────────────────────────────────────────────────────────────╯
```

#### 3.4.3 Alerting > Modify Bandwidth Rule（編輯 `rules.json` 第 18 條「Design-v2 sample: bandwidth」，5 步；物件挑選器沿用 3.4.2 已完整示範過的 `object_picker.py`，此處不重複展開，見 WZ-2）


```
╭─ Alerting > Modify Bandwidth Rule ──────────────────────────────────────────╮
│ [Step 1/5] Basic Setup                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ [?] Rule Name (Current: Design-v2 sample: bandwidth) >                      │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Alerting > Modify Bandwidth Rule ──────────────────────────────────────────╮
│ [Step 2/5] Select Metric                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ --- 1. Select Metric ---                                                    │
│ 1. Bandwidth                                                                │
│ 2. Total Volume                                                             │
│ [?] please select [0-2] (Current: 1 -- Bandwidth) >                         │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Alerting > Modify Bandwidth Rule ──────────────────────────────────────────╮
│ [Step 3/5] Filters                                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│ --- 2. Filters ---   (Enter 0 to go back)                                   │
│ Service/Port (include), Service/Port (exclude), Source, Destination:        │
│   each opens the same object-picker as the Traffic wizard (WZ-2).           │
│   Current selections for this rule: none set (pd=All, no label/IP           │
│   criteria saved).                                                          │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Alerting > Modify Bandwidth Rule ──────────────────────────────────────────╮
│ [Step 4/5] Threshold                                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ --- 3. Threshold ---                                                        │
│ [?] Trigger Threshold (Mbps) (Current: 999999.0) >                          │
│ [?] Time Window (mins) (Current: 60) >                                      │
│ [?] Cooldown Time (mins) (Current: 30) >                                    │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Alerting > Modify Bandwidth Rule ──────────────────────────────────────────╮
│ [Step 5/5] Review & Save                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ Type:              bandwidth                                                │
│ Name:              Design-v2 sample: bandwidth                              │
│ Metric/Threshold:  Mbps / 999999.0                                          │
│ Port/Proto:        -                                                        │
│ Source/Dest:       -  ->  -                                                 │
│ Window/Cooldown:   60m / 30m                                                │
│ Excludes:          -                                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ [?] Save this rule? (Y/n) >                                                 │
╰─────────────────────────────────────────────────────────────────────────────╯
```

#### 3.4.4 Alerting > Modify System Health Rule（編輯 `rules.json` 第 17 條「Design-v2 sample: PCE health」，3 步）


```
╭─ Alerting > Modify System Health Rule ──────────────────────────────────────╮
│ [Step 1/3] Basic Setup                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ [?] Rule Name (Current: Design-v2 sample: PCE health) >                     │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Alerting > Modify System Health Rule ──────────────────────────────────────╮
│ [Step 2/3] Set Trigger                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ When the PCE health check fails, send an alert so you can verify            │
│ PCE service status and network reachability.                                │
│ This rule triggers immediately when the health check fails. Only            │
│ cooldown is configurable.                                                   │
│                                                                             │
│ [?] Cooldown Time (mins) (Current: 30) >                                    │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Alerting > Modify System Health Rule ──────────────────────────────────────╮
│ [Step 3/3] Review & Save                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ Type:              system                                                   │
│ Name:              Design-v2 sample: PCE health                             │
│ Event:             pce_health                                               │
│ Trigger:           immediate                                                │
│ Threshold:         1                                                        │
│ Window/Cooldown:   10m / 30m                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ [?] Save this rule? (Y/n) >                                                 │
╰─────────────────────────────────────────────────────────────────────────────╯
```

#### 3.4.5 Automation > Edit Report Schedule（編輯真排程「UI Redesign Snapshot Demo」，7 步）

**RS-2（真實資料落差，非本任務修復範圍）**：`report_schedule.py:163-170` 的 `type_map`/`default_type_k` 只認識 `traffic`/`audit`/`ven_status` 三種 `report_type`。真快照 `design/v2/snapshots/report_schedules.json` 裡這條排程的 `report_type` 是 `"audit_summary"`（GUI 新報表分類，非 CLI 精靈認識的舊三型之一）。`default_type_k` 用 dict `.get(edit_sched.get("report_type","traffic"), "1")` 查表，`"audit_summary"` 查無此鍵，**靜默 fallback 成 `"1"`（Traffic）**——操作者編輯這條排程時，Step 2 預設值錯誤地顯示成 Traffic；若直接按 Enter 通過，儲存後 `report_type` 會被**靜默改寫**成 `traffic`，原本的 `audit_summary` 遺失。下面畫面如實呈現這個現況行為（含錯誤的預設值），並標註 `[BUG, see RS-2]`；修復不在本次 IA 重組範圍內，記錄供 Phase 2 report-schedule 精靈擴充報表型別時一併處理。


```
╭─ Automation > Edit Report Schedule ─────────────────────────────────────────╮
│ [Step 1/7] Schedule name                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ [?] Schedule name (Current: UI Redesign Snapshot Demo) >                    │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Automation > Edit Report Schedule ─────────────────────────────────────────╮
│ [Step 2/7] Report type                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Traffic Flow Report                                                      │
│ 2. Audit Report                                                             │
│ 3. VEN Status Report                                                        │
│ [?] Report type (Default: 1 -- Traffic)  [BUG, see RS-2] >                  │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Automation > Edit Report Schedule ─────────────────────────────────────────╮
│ [Step 3/7] Schedule type                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Daily                                                                    │
│ 2. Weekly                                                                   │
│ 3. Monthly                                                                  │
│ [?] Schedule type (Current: 2 -- Weekly) >                                  │
│ [?] Day of week (Current: mon) >                                            │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Automation > Edit Report Schedule ─────────────────────────────────────────╮
│ [Step 4/7] Execution time (UTC+8)                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│ [?] Hour (UTC+8) (Current: 16) >                                            │
│ [?] Minute (Current: 0) >                                                   │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Automation > Edit Report Schedule ─────────────────────────────────────────╮
│ [Step 5/7] Lookback days                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ [?] Lookback days (Current: 7) >                                            │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Automation > Edit Report Schedule ─────────────────────────────────────────╮
│ [Step 6/7] Format                                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. HTML                                                                     │
│ 2. CSV + ZIP                                                                │
│ 3. HTML + CSV                                                               │
│ [?] Format (Current: 1 -- HTML) >                                           │
│     Enter=default | 0=back | -1=cancel | h/?=help                           │
╰─────────────────────────────────────────────────────────────────────────────╯
```

```
╭─ Automation > Edit Report Schedule ─────────────────────────────────────────╮
│ [Step 7/7] Email Options + Review                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│ [?] Email report (Current: N) >                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ Name:       UI Redesign Snapshot Demo                                       │
│ Type:       traffic     [was audit_summary -- see RS-2]                     │
│ Frequency:  weekly (mon)                                                    │
│ Time:       16:00 UTC+8  (= 08:00 UTC)                                      │
│ Lookback:   7 days                                                          │
│ Format:     html                                                            │
│ Email:      No                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ [?] Save this schedule? (Y/n) >                                             │
╰─────────────────────────────────────────────────────────────────────────────╯
```

### 3.5 破壞性動作影響摘要畫面

比照 GUI `modal.confirm({title, impact, onOk})`（`design/v2/mockup/js/components/modal.mjs:10-16`：`impact` 是**具體後果字串陣列，不是散文**）語意，CLI 端用小 box 呈現同樣的結構：標題 + 條列後果 + 二選一（`[N] Cancel` / `[Y] <動作>`）。分級依 spec 2.3：「一般刪除=確認；批次隔離/重啟=確認＋影響摘要」。

#### 3.5.1 Alerting > Manage Rules — 清單畫面（供對照，含刪除/修改指令列）


```
╭─ Alerting > Manage Rules ───────────────────────────────────────────────────╮
│ No Name             Type      Condition           Filters                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ 0  Agent 遭竄改     Event     > 1 (w10m)                                    │
│ 1  Agent 已暫停     Event     > 1 (w10m)                                    │
│ 3  Agent 心跳遺失   Event     > 3 (w30m)                                    │
│ 16 高 Blocked 流量  Traffic   > 25 (w10m)         [Blocked]                 │
│ 17 Design-v2 samp.. System    > 1 (w10m)                                    │
│ 18 Design-v2 samp.. Bandwidth > 999999 (w60m)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│   ... 13 more rows (19 total)                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│ [?] Enter command (m 3 to modify, d 3 or d 1,2 to delete)                   │
│     0=back  -1=cancel  h=help                                               │
╰─────────────────────────────────────────────────────────────────────────────╯
```

#### 3.5.2 一般刪除（單一規則）— 確認，無需完整影響摘要

**MR-1**：現況 `manage_rules.py:153-158` 的 `d <i>` 指令完全沒有確認步驟，`cm.remove_rules_by_index(target)` 直接執行。新設計依 spec 2.3「一般刪除=確認」補上：


```
╭─ Confirm ───────────────────────────────────────────────────────────────────╮
│   Delete rule?                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│   - #3  Agent 心跳遺失  (event, 3-in-30m)                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│   [N] Cancel      [Y] Delete                                                │
╰─────────────────────────────────────────────────────────────────────────────╯
```

#### 3.5.3 批次刪除（多筆規則）— 確認＋影響摘要

`d 1,2,16` 這種多索引刪除，依 spec 2.3「批次…=確認＋影響摘要」列出每一條要刪的規則：


```
╭─ Confirm -- Delete 3 Rules ─────────────────────────────────────────────────╮
│   This will permanently delete:                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│   - #1  Agent 已暫停            (event, immediate)                          │
│   - #2  偵測到 Agent 複製        (event, immediate)                         │
│   - #16 高 Blocked 流量          (traffic, 25-in-10m)                       │
├─────────────────────────────────────────────────────────────────────────────┤
│   No undo. Re-create manually if needed.                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│   [N] Cancel      [Y] Delete 3 rules                                        │
╰─────────────────────────────────────────────────────────────────────────────╯
```

#### 3.5.4 Load Official Best Practices — 全量替換，最大影響範圍

真實數字取自 `src/config.py`：`_best_practice_rules()`（751-843 行）目前定義 **16** 條官方事件規則常數；`apply_best_practices(mode="replace")`（845-885 行）把 `cm.config["rules"]` 整批替換——`replaced_count = len(current_rules)`（現況快照 19 條）、`added_count = len(bp_rules)`（16 條）。同一函式（856-864 行）會先把舊規則寫進 `cm.config["rule_backups"]`（保留最近 10 份）才覆寫，這是唯一目前存在的「軟安全網」，值得在影響摘要裡明講給操作者安心：


```
╭─ Confirm -- Load Official Best Practices ───────────────────────────────────╮
│   This replaces ALL 19 current rules with 16 official rules:                │
├─────────────────────────────────────────────────────────────────────────────┤
│   - 16 official event rules will be loaded (agent tampering,                │
│     login failures, policy/ruleset changes, ...)                            │
│   - 19 current rules will be removed, incl. 3 custom rules not              │
│     part of the official set:                                               │
│       #16 高 Blocked 流量 (traffic)                                         │
│       #17 Design-v2 sample: PCE health (system)                             │
│       #18 Design-v2 sample: bandwidth (bandwidth)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│   The removed 19 rules are backed up (config.rule_backups, last             │
│   10 kept) and can be restored by an operator with file access.             │
├─────────────────────────────────────────────────────────────────────────────┤
│   [N] Cancel      [Y] Replace all rules                                     │
╰─────────────────────────────────────────────────────────────────────────────╯
```
## 4. 自查（Step 3/4）

### 4.1 對照表覆蓋度 — 盤點 §3.2 六大類逐一核對

盤點文件 §3.2「互動選單（cli/menus/）」原文列出 6 個大類；下表核對每一類在 §2 對照表左欄都能找到對應節點（右欄皆非空格）：

| §3.2 原文 | 對照表節點 # | 核對結果 |
|---|---|---|
| 主選單（main.py 入口）→ settings_menu（_root.py） | #1（根）、#28、#35 | 覆蓋：根選單 + settings_menu 容器 + Web GUI Security 入口 |
| 規則管理（manage_rules） | #6、#7、#8 | 覆蓋：Manage Rules 選單本體 + 刪除 + 修改指令 |
| 四型規則新增/編輯精靈（event/traffic/bandwidth/system_health） | #3、#4、#5、#13（新增）；#8 分派回同 4 支（編輯） | 覆蓋：4 型新增各一列，編輯共用同一分派點 |
| 告警設定（alert） | #30（9 個子項） | 覆蓋：`alert_settings_menu` 全部子項 |
| 報表排程管理（report_schedule） | #19、#20、#21、#22、#23 | 覆蓋：入口 + 新增/編輯精靈 + Toggle + 刪除 + Run now（Toggle/Run now 為 review 後補列） |
| Web GUI 安全/TLS 選單（web_gui） | #35、#36、#37、#38、#39 | 覆蓋：入口 + 帳密 + IP + TLS 容器 + TLS 6 子項 |

§3.2 未逐項點名、但本次逐檔轉錄 `main.py` 全文＋review 後追加逐檔展開 3 個外部模組所發現的節點（Best Practices/Test Alert/Run Analysis/Debug Mode、Report Generation 其餘 3 型、Rule Scheduler／PCE Cache／SIEM Forwarder 全部第一層項目、Web GUI Security 細項等，共 43 個非 §3.2 逐項點名的節點）——多數對應到更廣的 inventory §1.4 Alerts（Best Practices/Run once/Debug/Test alert 皆已在 GUI 盤點列出，CLI 是同一批後端動作的另一入口）與 §1.6/1.7/1.8（Rule Scheduler／PCE Cache／SIEM／Web GUI Security／模組日誌），無一項是盤點文件完全沒有概念對應的全新功能；已在 §2 逐列標注新落點。

### 4.2 行號抽驗

**Round 1（5 個，逐一開檔核對）**：

| 引用 | 核對方式 | 結果 |
|---|---|---|
| `src/main.py:285` = `def main_menu():` | `sed -n '285p' src/main.py` | 一致 |
| `src/main.py:773` = `main_menu()` 呼叫本身 | `sed -n '765,776p' src/main.py` | 一致，但**原稿註解有誤已修正**：773 行是 `main()` 頂層 `else: try: main_menu()` 分支（無旗標時的互動入口），不是 `main_menu()` 內部的 `elif sel == 3`；`sel==3` 是 `main_menu()` 自己選單裡「啟動 Rule Scheduler」那個分支（main.py:351），跟 773 行是兩件事，原稿誤植 |
| `src/cli/menus/manage_rules.py:153` = `if action == "d":` 區塊起點 | `sed -n '153,158p' src/cli/menus/manage_rules.py` | 一致，確認無確認提示（MR-1 屬實） |
| `src/cli/menus/event.py:18` = `def add_event_menu(cm: ConfigManager, edit_rule=None):` | `sed -n '18p' src/cli/menus/event.py` | 一致 |
| `src/config.py:845` = `def apply_best_practices(self, mode: str = "append_missing") -> dict:` | `sed -n '845p' src/config.py` | 一致 |

**Round 2（review 修復新增內容抽驗 3 個）**：

| 引用 | 核對方式 | 結果 |
|---|---|---|
| `src/rule_scheduler_cli.py:643` = `def run(self):`（3 項頂層選單） | `sed -n '643,650p' src/rule_scheduler_cli.py` | 一致 |
| `src/pce_cache_cli.py:10` = `def manage_pce_cache_menu(cm) -> None:`（6 項選單，無 draw_panel） | `sed -n '10,30p' src/pce_cache_cli.py` | 一致，確認純 `print`/`input`，無 rich 框線（WZ-3 屬實） |
| `src/siem_cli.py:176` = `def _dlq_submenu(cm):`（5 動作 a/b/c/d/e） | `sed -n '176,192p' src/siem_cli.py` | 一致 |

### 4.3 ASCII 寬度驗證

全部 41 張 ASCII 畫面（主選單 1、六區子選單 6、規則清單 1、report schedule 清單 1、Rule Scheduler/PCE Cache/SIEM 代表畫面 4、破壞性動作 3、精靈步驟 25＝event 5＋traffic 5＋bandwidth 5＋system_health 3＋report_schedule 7）以程式化方式產生並逐一驗證（含 review 新增的 5 張）：以 `unicodedata.east_asian_width()` 只把真正的中日韓全形字元（`W`/`F`）計為 2 欄寬、box-drawing／項目符號等「Ambiguous」字元計為 1 欄（多數等寬終端字型的實際渲染寬度——這與 `src/cli/_render.py:get_visible_width()` 為了 CJK 表格對齊刻意保守地把 Ambiguous 也算 2 欄的內部慣例不同，本檢查要驗的是「是否撞到 80 欄真終端」，取一般終端的實際渲染寬度更準確）。全部畫面最大寬度 ≤ 79 欄，符合「≤ 80 字元」要求；生成與驗證腳本見 worktree 外的 scratchpad（不隨文件提交，因為畫面內容已固定內嵌於本文件）。

### 4.4 Findings 索引（本文件內文引用代號一覽）

| 代號 | 內容 |
|---|---|
| OV-1 | Overview 區現況無對應選單項，僅狀態列升格為獨立唯讀畫面 |
| IV-1 | Investigate 區現況無對應選單項，指向 `workload` click 子指令與 Web GUI |
| RS-1 | `rule_scheduler_cli.py` 只展開到第一層（`run()` 的 3 個頂層項目＋各自的直接子項），精靈內部逐步稿（如 `_browse_and_add`/`_collect_schedule_params` 的多輪問答）留待 Phase 2 |
| SY-1 | 同 RS-1，適用於 `pce_cache_cli.py`／`siem_cli.py`：第一層全部功能已列出，更深的表單欄位級細節留待 Phase 2 |
| AU-2 | Settings 選單「Rule Scheduler enable/interval」（`_root.py:164-188`）與 Rule Scheduler 選單自己的 Settings（`rule_scheduler_cli.py:668-697`）是同一顆開關的兩個入口，新設計合併去重、只保留後者 |
| RP-1 | Report Output Dir/Retention 從 System 搬到 Reports（報表網域設定） |
| MR-1 | 現況 `manage_rules.py` 刪除規則指令沒有任何確認，新設計依 spec 2.3 補上 |
| EV-1 | 現況 Event 精靈「選分類」畫面沒有 `[Step n/N]` 標籤，新設計補上（4 步→5 步） |
| EV-2 | 現況 Status/Severity Filter 提示不印選項對照，只有按 `h` 才看得到，新設計改為提示旁直接印出 |
| WZ-1 | 現況所有精靈提示尾巴一律印 `(Default: X)`，編輯模式下其實是「目前值」，新設計依情境分別標示 `(Current: X)` / `(Default: Y)` |
| WZ-2 | `object_picker.py`（label/iplist/workload/ip 兩段式挑選器）為 Traffic/Bandwidth 精靈共用元件，僅在 Traffic 精靈完整示範一次 |
| WZ-3 | `pce_cache_cli.py`／`siem_cli.py` 完全不用 `draw_panel`/rich 框線，只有純文字 `print`/`input`，與 `cli/menus/` 下所有精靈的 chrome 不一致；新設計統一套用同一個小標頭框（呼應 DD-1） |
| RS-2 | `report_schedule.py` 的 `type_map` 不認識新版 GUI 報表型別（如 `audit_summary`），編輯此類排程若不留意會被靜默改寫成 `traffic`；真實資料落差，記錄供 Phase 2 參考 |
| DD-1 | 新設計統一精靈為「每步驟 redraw」，取代現況「累加往下印」的行為 |
| DD-2 | `Launch Web GUI` 保留為主選單快捷鍵，不落入六區任一格 |

