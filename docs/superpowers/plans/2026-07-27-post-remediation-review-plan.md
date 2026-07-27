# 修復後複審計畫（Post-Remediation Review）

> **給執行者**：這份計畫是為「全新 session」寫的，假設你沒有先前對話的任何 context。所有需要的事實都寫在裡面。
> 本專案規則：**全程繁體中文**、**任何輸出都不得有 emoji**（包含 commit message、程式碼註解、報表）；commit message 用英文 conventional-commits。

**目標**：對 2026-07-24～27 這波大規模修復所產生、但**從未被任何人 review 過**的程式碼做獨立審查，並補完三塊已知的審查缺口。

**為什麼要做**：測試綠與 CI 綠只證明「沒破壞既有行為」，不證明「新程式碼本身沒問題」。這波修復由 15 個 agent 在兩天內寫成，過程中已知**自己引入過 4 個問題**（見下方背景），其中 3 個是靠 CI 或其他 agent 事後撞到才發現的，不是設計時避免的。

---

## 背景：已經做過什麼（不要重做）

2026-07 已完成的逐子系統 review（**這些區塊不需要重審，避免重複回報**）：

| 已審 | 範圍 |
|---|---|
| 前端 | `src/gui/static/**`、templates |
| CLI | `src/main.py`、`src/cli/**`、三支 standalone CLI |
| Report 輸出正確性 | 全 11 型報表的截斷／欄寬／i18n／版面 |
| Alert | `src/alerts/**`、告警文案 |
| 流量調閱 | `src/api/traffic_query.py` 的 query_flows 鏈 |
| 排程 | `src/scheduler/**` 的 job 註冊／間隔／cron／job_health |
| 後端 | GUI Flask、`src/pce_cache/**`、`src/siem/**`、`src/config.py`、`src/events/**`、i18n engine |
| analyzer 規則引擎 | dispatch／threshold-window／bandwidth-volume／watchdog／save_state |
| 併發／共享狀態模型 | state.json、JSON config、SQLite、行程拓撲 vs 鎖覆蓋 |
| api_client 其餘＋report 程式結構 | payload 組裝、快取生命週期、exporters、generator pipeline |
| 品質債 | 測試品質、打包/CI、文件 vs 程式一致性 |

累計 **205 個 confirmed findings 已全數修復並合入 main**。

### 這波修復自己引入過的問題（說明風險為何真實）

| 問題 | 由誰發現 |
|---|---|
| `threshold_count < 1` 擋掉合法的 0.5 Mbps（bandwidth 是浮點） | 寫的 agent 自己誠實標出 |
| `.gitignore` 的 `*.lock` 差點吞掉 `requirements-offline.lock` | 另一個 agent 撞到 |
| 「pip-audit 帶 hash 就不做相依解析」的錯誤假設 | **CI**（本機 py3.12 驗不到） |
| 用 `--no-deps` 修上一項，仍然錯 | **CI 第二次** |

---

## 待審對象：commit 範圍 `f152eea..HEAD`

```bash
cd /home/harry/rd/illumio-ops
git log --oneline f152eea..HEAD          # 8 個 commit
git diff --shortstat f152eea..HEAD       # 127 files, +11094 / -674
git diff --shortstat f152eea..HEAD -- src scripts   # 68 files, +3707 / -556
```

`f152eea` 是後端 review 修復的 merge，之後的每一個 commit 都是「修 finding 產生的程式碼」，沒有一行被獨立審過。

### 三個全新模組（風險最高，因為沒有既有行為可對照）

| 模組 | 行數 | 錯了會怎樣 |
|---|---|---|
| `src/file_lock.py` | 192 | 跨行程鎖失效 → **靜默丟失設定／排程資料**。Windows 的 `msvcrt` 分支從未在 Windows 上執行過 |
| `src/pce_cache/flow_deltas.py` | 183 | 差分算錯 → **產生看似合理但錯誤的告警數字**，比不告警更危險 |
| `src/report/exporters/_output_paths.py` | 66 | 檔名保留／原子寫入錯誤 → 報表覆蓋或 0 byte 檔 |

### src/ 改動熱點（供切批用）

```
+881 -106  src/analyzer.py                       <- 最大宗，跨兩批修復
+192   -0  src/file_lock.py                      <- 新模組
+183   -0  src/pce_cache/flow_deltas.py          <- 新模組
+118   -6  scripts/install.ps1                   <- Windows ACL，從未執行過
+103  -27  src/rule_scheduler.py
 +94  -60  src/pce_cache/schema.py               <- schema 遷移
 +88   -5  scripts/build_offline_bundle.sh
 +83  -25  src/api/traffic_query.py
 +83  -13  src/api/labels.py
 +82  -12  src/cli/_runtime.py
 +69  -10  src/main.py
 +68   -4  src/pce_cache/ingestor_traffic.py
 +66  -17  src/scheduler/jobs.py
 +66   -5  src/report/exporters/policy_usage_html_exporter.py
 +66   -0  src/report/exporters/_output_paths.py
 +65   -6  src/api_client.py
 +64   -8  src/report/analysis/policy_diff/diff_engine.py
 +64  -25  src/gui/routes/actions.py
 +64  -10  src/report/exporters/csv_exporter.py
 +59  -16  src/reporter.py
 +58  -17  src/report/analysis/policy_usage/pu_mod01_overview.py
 +57  -11  src/gui/routes/reports.py
```

---

## 階段 1（最高優先）：修復程式碼複審

**這一階段和一般 review 不同**：除了找新 bug，還要**驗證原本的 finding 是否真的被關掉**。目前「已修復」只有寫它的 agent 自己說了算。

### 建議切批（不相交檔案集，可平行）

| 批 | 檔案 | 重點 |
|---|---|---|
| R1 | `src/analyzer.py` 的 diff | 最大宗。規則選取白名單、save_state 白名單反轉、跨桶守門、視窗差分整合 |
| R2 | `src/file_lock.py`＋`src/config.py`＋`src/rule_scheduler.py`＋`src/cli/_runtime.py`＋`src/main.py` | 跨行程鎖與內容雜湊防護。**特別查鎖順序、可重入性、Windows 分支、失敗模式** |
| R3 | `src/pce_cache/**`（flow_deltas / schema / ingestor_traffic / retention） | 差分正確性、遷移可回溯性、觀測表無限成長風險 |
| R4 | `src/api/**`＋`src/api_client.py`＋`src/gui/routes/**` | 契約變更（`RuleTrafficQueryError`、`get_labels(raise_on_error)`）是否所有呼叫端都處理 |
| R5 | `src/report/**`＋`src/reporter.py` | exporters 原子寫入、失敗訊號、數字計算 |
| R6 | `scripts/**`＋`.github/workflows/ci.yml`＋`.gitignore` | 打包安全、Windows ACL、CI 閘門是否真的會擋 |

### 每批的審查提示（寫進 agent prompt）

1. **先讀 finding 再讀 fix**：原始 findings 在 `git log` 的 commit message 裡有摘要；每個 fix 都應該能對應到一個具體的失敗情境。**fix 沒有真的關掉 finding，本身就是一個 finding。**
2. **專找「fix 引入的新 bug」**：過度限制（如上面的 0.5 Mbps）、契約變更沒同步呼叫端、新增的 fail-closed 路徑在合法情況下誤擋、新加的鎖造成死鎖或饑餓。
3. **守門測試是否真的守門**：這波加了大量測試。抽驗其中的 AST 不變量與 subprocess 測試 —— 把對應的 fix 還原掉，測試是否真的轉紅？（這叫變異測試，本專案已用它抓過假守門。）
4. **註解是否與程式一致**：這波寫了大量繁中解釋性註解，其中至少一則被證實是錯的（pip-audit 那則）。**註解裡的技術宣稱要當作待驗證的斷言，不是事實。**

---

## 階段 2：`src/report/analysis/` 其餘模組

45 個檔、7081 行，其中 **40 個檔、5712 行**只驗過輸出正確性，從未做過四軸程式碼審查。

已審過的 5 個（跳過）：`mod15_lateral_movement.py`、`policy_diff/diff_engine.py`、`policy_resolver.py`、`policy_usage/pu_mod03_unused_detail.py`、`policy_usage/pu_mod00_executive.py`。

```bash
find src/report/analysis -name '*.py' | grep -vE 'mod15_lateral|policy_diff/diff_engine|policy_resolver\.py|pu_mod03_unused_detail|pu_mod00_executive'
```

**審查重點**：這些是報表數字的**計算來源**。失敗模式是「產生一個看起來權威的錯誤數字，操作者拿去做決策」—— 跟先前抓到的「policy-diff 完全沒 diff deny_rules」同一類。特別看：聚合與去重、資料集之間的 join、除零與空輸入、以及**有沒有把「算不出來」呈現成 0**。

建議依報表家族切批（audit mod00-15 / policy_usage / 其餘），約 4-6 批。

---

## 階段 3：整體安全威脅建模（從未做過）

到目前為止的安全發現**全部是逐檔抓點**：config show 明文憑證、hec_token 明文、bundle 內嵌私鑰、Windows 無 ACL。從來沒有一次 holistic 的審查。

**這一階段不能用逐檔掃的方式做**，要換審查方法：

1. **畫出信任邊界**：誰可以呼叫什麼？GUI 未登入 / 已登入 / CLI 本機 / 排程器 / PCE 對外呼叫，各自的權限邊界在哪。
2. **secret 全生命週期**：1Password → config.json → 記憶體 → 日誌／報表／API 回應／錯誤訊息／備份／offline bundle。每一段都問「這裡會不會漏」。
3. **機制之間的交互**：IP allowlist 的 RST-drop 匿蹤設計、CSRF、CSP、rate limiter、session 生命週期 —— **兩個各自正確的機制組合起來有沒有洞**。這是逐檔審查結構上抓不到的。
4. **這波新增的攻擊面**：跨行程鎖檔（可否被本機非特權使用者干擾？）、新的觀測表（是否含敏感資料、是否進備份）、新的錯誤訊息（是否洩漏內部路徑或狀態）。

---

## 階段 4：真環境驗證（**建議另外排，不要混進 review 批次**）

這幾項卡在環境而非人力，硬排進 review 只會變成「已知未驗」清單再抄一次：

| 項目 | 現況 | 需要什麼 |
|---|---|---|
| Windows 安裝（ACL、NSSM 回傳值檢查） | **只有手讀，從未執行**。這是唯一一條完全沒被執行過的 High 修復 | 一台 Windows 機器 |
| Offline bundle 端到端 | 只驗了 staging 排除與 wheel 下載，完整 build→安裝→啟動沒跑過 | 時間＋磁碟（bundle 約 1 GB） |
| 午夜 bucket 翻轉 | `counter_reset` 路徑在真機走到了，但真正的午夜翻轉沒觀察過 | 等到午夜前後看日誌 |
| 告警投遞 | SMTP／LINE／Telegram／SIEM 對真端點 | 真實收件端 |

---

## 執行方式

本專案已驗證可行的做法（沿用即可）：

1. **平行多 agent review**：每個審查單元一個 agent（四軸：安全／正確性與資料完整性／錯誤處理與資源洩漏／效能與容量），每條 finding 再派一個**對抗式 verify agent**，預設 REFUTED，只有確認可達性才給 CONFIRMED。
2. **修復用平行 fix-agent**：切成**不相交檔案集**，全部在同一個 git worktree。prompt 必須硬性規定：
   - 進 worktree 後用 `git rev-parse --abbrev-ref HEAD` 驗證分支（否則會改到主 checkout）
   - 一律用 worktree 前綴的絕對路徑
   - **禁止 `git stash`**（共用 worktree 會吞掉別人未 commit 的工作，發生過）
   - **不准碰 `src/i18n_en.json` / `src/i18n_zh_TW.json`**，需要新 key 就回報，由 orchestrator 單執行緒補
   - 不 commit／不 push，由 orchestrator 統一整合
3. **plausible 類 finding 要求先查證再決定修不修**，不照單全收。

### 閘門（合併前必須全綠，且要親自跑、不採信 agent 回報）

```bash
cd /home/harry/rd/illumio-ops
venv/bin/python -m pytest tests/ -q -p no:randomly     # 固定順序
venv/bin/python -m pytest --tb=short -q                # 隨機順序（CI 的跑法）
venv/bin/python scripts/audit_i18n_usage.py            # A-J 必須全 0
venv/bin/python scripts/docs_check.py
venv/bin/python scripts/check_doc_links.py
venv/bin/python scripts/check_no_naive_datetime.py
venv/bin/python -m mypy --follow-imports=silent src/api_client.py src/analyzer.py src/reporter.py
```

推送後 `gh run watch <id> --exit-status`，並確認**三個 job 都綠**（`test (py3.10)`、`test (py3.11)`、`Security audit (offline bundle lock)`）。

部署測試機：`172.16.15.106:/root/illumio-ops`，`git pull --ff-only && systemctl restart illumio-ops`。GUI 在 **https://127.0.0.1:5001**（自簽憑證，需 `curl -sk`）。憑證見 1Password，**不要寫進任何檔案或對話**。

---

## 執行時必須知道的坑

- **本機驗證可能驗不到 CI 的失敗模式**：本機 venv 是 py3.12，CI matrix 跑 3.10/3.11。跨版本假設一定要讓 CI 裁決。
- **`pip-compile` 沒有 `--upgrade` 會保留輸出檔的既有釘版** —— 改了來源卻沒升版，很容易誤判「已修好」。
- **`git checkout <file>` 會連同你剛做的正式修改一起還原** —— 變異測試後用它復原，會把同檔案的其他編輯清掉。
- **`ConfigManager.load()` 會依 `config/config.json` 呼叫 `set_language()`**，且路徑以套件根解析、不是 cwd。所以測試裡寫死英文字面會相依開發者本機語言設定（CI 綠只是因為那裡沒有 config.json）。
- **`src/reporter.py` 帶 UTF-8 BOM**：任何用 `utf-8` 讀它做 AST 分析的工具都會炸，要用 `utf-8-sig`。
- **`scripts/install.ps1`、`scripts/preflight.ps1`、`deploy/install_service.ps1` 是 UTF-8 with BOM、LF 行尾**，改動前後都要驗 BOM 未被破壞（此 repo 出過事）。
- **驗證腳本本身要照生產路徑的型別契約寫**：曾因傳 `iter(...)` 而非 list 給 `_run_rule_engine`，讓增量路徑靜默停用，一度誤判為產品 bug。

## 現存的已知設定約束

- **`traffic_poll_interval_seconds` 預設 3600 秒，在此預設下視窗差分（phase 2）完全惰性** —— 短視窗規則永遠拿不到可用基線。約束是「輪詢間隔須 ≲ 最短流量規則視窗的 25%」。測試機目前已改為 **120 秒**（原值備份於 `/root/config.json.bak`）。

---

## 建議順序與理由

1. **階段 1**（修復程式碼複審）—— 唯一能對「這兩天的工作品質」給出獨立判斷的動作，且同時驗證 205 條 finding 是否真的關掉。
2. **階段 2**（analysis 模組）—— 量大但單純，可高度平行。
3. **階段 3**（安全威脅建模）—— 需要不同的審查方式，不適合和逐檔審查混在同一批。
4. **階段 4**（真環境驗證）—— 依環境可得性另外排。
