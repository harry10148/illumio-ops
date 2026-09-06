# CLI 互動選單 v3 流程規格（五區）

> Phase 3C Task 3。`design/v2/cli-flows.md` 是 Phase 2C 六區的完整規格（63 節點
> 對照表、41 張畫面稿）；**本檔只寫 v2 → v3 的差異**，沒有提到的部分一律以 v2
> 那份為準。這是刻意的：把 95KB 重抄一遍，兩份就會開始各說各話，而真正會被讀的
> 是「哪裡不一樣」。

## 1. 為什麼從六區變五區

Web GUI 在 v3 spec §1 已經是五區（首頁／調查／規則／報表／系統）。CLI 停在
Phase 2C 的六區，於是同一套產品的兩個介面對「東西放在哪裡」給了兩個答案——
操作者在 GUI 學到的心智模型，換到 CLI 就得重學一次。

使用者裁決（2026-09-06）：**告警＋自動化併為「規則」**，其餘四區一對一。

| CLI v2（六區） | CLI v3（五區） | GUI v3 |
|---|---|---|
| 1. Overview 總覽 | 1. Home 首頁 | `#/home` |
| 2. Investigate 調查 | 2. Investigate 調查 | `#/investigate/*` |
| 3. Alerting 告警 | 3. Policy 規則 | `#/policy/*` |
| 4. Automation 自動化 | ↑ 併入 | ↑ |
| 5. Reports 報表 | 4. Reports 報表 | `#/reports/*` |
| 6. System 系統 | 5. System 系統 | `#/system/*` |

「總覽→首頁」不只是換字：GUI 的首頁本來就是唯讀的狀態總覽，CLI 的 Overview 也是，
兩邊名字對齊之後，「首頁看狀態」這句話在兩個介面都成立。

## 2. 合併後的「規則」區

### 2.1 為什麼合併是對的

告警區在做「定義規則、測試規則、手動跑一次」，自動化區在做「讓規則自己跑」。
兩者是同一件事的兩半，v2 把它們拆成兩區的理由是「排程＝會動的東西」——那是一個
關於**實作性質**的分類，不是操作者找東西時用的分類。GUI v3 已經改用後者。

### 2.2 畫面

編號**刻意沿用**：告警區原本的 1-9 一個都沒動，自動化區的 1、2 變成 10、11。
操作者原本記得的按鍵全部還能用，只有兩項要重學。中間那條空白列把「手動做」與
「自己跑」分開。

```
┌─ 規則 ─────────────────────────────────────────────────────────────────────┐
│ [健康列]                                                                   │
│                                                                            │
│  1. 新增 Event 規則                                                        │
│  2. 新增 Traffic 規則                                                      │
│  3. 新增 Bandwidth & Volume 規則                                           │
│  4. 新增 System Health 規則                                                │
│  5. 管理規則                            -- {n} 條規則                      │
│  6. 發送測試告警                                                           │
│  7. 立即執行分析並發送告警                                                 │
│  8. 規則模擬與除錯                                                         │
│  9. 載入官方最佳實務                    [破壞性]                           │
│                                                                            │
│ 10. 規則排程器                          -- ON | 每 300s 檢查               │
│ 11. 報表排程                            -- {n} 筆排程                      │
│                                                                            │
│  0. 返回                                                                   │
└────────────────────────────────────────────────────────────────────────────┘
```

§3.3.3 的 **System Health 排在 4**（四個「新增規則」精靈相鄰）與 **AU-2**
（規則排程器的開關只有一個家，在 `rule_scheduler_cli` 自己的 Settings；這裡是
入口不是第二個切換點）兩條約束原封不動。

### 2.3 精靈麵包屑

所有精靈的路徑字串從 `Alerting > …` / `Automation > …` 改成 `規則 > …`
（`cli_area_alerting`／`cli_area_automation` 兩個 key 合併為 `cli_area_policy`，
25 處引用一起改）。麵包屑指向一個不存在的區名，是「畫面上印路由字串」的同一類
缺陷。

## 3. 節點對照表的差異（相對 v2 §2 的 63 項）

v2 的 63 節點**沒有任何一項被移除或再合併**，只有落點欄改名：

| v2 落點 | v3 落點 | 影響節點 |
|---|---|---|
| Overview | Home | #1 的主選單第 1 項 |
| Alerting | Policy | #2-#13（含容器節點 #2） |
| Automation | Policy | #19、#27、#34 及排程相關子節點 |
| Reports / System | 不變 | — |

`tests/test_cli_flows_parity.py` 的 63 項檢查表同步改名，**不減項**：node 1 改指
`test_main_menu_dispatches_five_areas`，node 2 的 area 由 `alerting` 改為
`policy`，其餘引用改指改名後的測試。檢查表本來就會驗「它指的測試還存在」，
所以改名漏一個就會紅——這次就是它抓出來的。

## 4. 沒有改變的東西

- 精靈流程、`safe_input` 的行為、破壞性動作確認框、雙語、`draw_panel` chrome。
- click 子指令與參數介面零變動（`illumio-ops report …` 等）。
- `G` 快捷鍵（啟動 Web GUI）仍然不佔區域編號（DD-2）。
- 各子選單內部的項次，除了上述 automation 兩項。

## 5. i18n 異動

| 動作 | key |
|---|---|
| 改值 | `main_menu_area_1`（總覽→首頁）、`main_menu_area_3`（告警→規則，說明合併排程）、`main_menu_area_4`（原第 5 區報表）、`main_menu_area_5`（原第 6 區系統） |
| 刪除 | `main_menu_area_6`、`cli_area_alerting`、`cli_area_automation`、`cli_area_overview` |
| 新增 | `cli_area_policy`、`cli_area_home` |
| 改編號 | `cli_auto_rule_scheduler`（1→10）、`cli_auto_report_schedules`（2→11） |

`cli_area_policy` 與 `main_menu_area_3` 的 zh_TW 把 Policy 譯成「規則」，與
`gui_nav_policy` 同一個裁決，所以走 `glossary.json` 的 `exempt_keys`——**repo 有
三個 glossary 檢查器**，`exempt_keys` 是三者共用的那一個欄位。
