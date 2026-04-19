# illumio_ops 套件升級路線圖

> **For agentic workers:** 這是 master roadmap，不直接執行。每個 Phase 都會展開成獨立的 implementation plan（同目錄、相同日期前綴）後再透過 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 執行。

**Goal:** 在維持現有功能與 i18n 完整性的前提下，引入精選 pip 套件提升 CLI 體驗、報表品質、安全性與可維護性，為 RPM 離線部署鋪路（RPM 打包本身為後續獨立計畫）。

**Architecture:** 漸進式單一子系統替換。每個 Phase 自成一個可上線、可回滾的單元；先做使用者可見的小改善累積信心，再做結構性重構，最後動到全域風險最高的 logging。Python 啟動方式（`python illumio_ops.py`）保留為**僅供開發**，生產線一律走未來 RPM bundle。

**Tech Stack 變化總覽:**

| 子系統 | 現況 (stdlib only) | 升級後 | 套件大小 |
|---|---|---|---|
| CLI | print + ANSI Colors + custom draw_panel + safe_input | rich + questionary | ~6 MB |
| HTTP | urllib.request 手寫 retry/backoff | requests + urllib3 retry + **orjson** + **cachetools** | ~1.6 MB |
| 報表 | HTML + CSV ZIP | + xlsx (openpyxl) + PDF (weasyprint) + 靜態圖表 (matplotlib) + **互動圖表 (plotly)** + **語法高亮 (pygments)** | ~85 MB |
| 排程 | report_scheduler.py + rule_scheduler.py 自製 | APScheduler | ~2 MB |
| Web 安全 | 自製 CSRF 同步權杖 + 自製 rate limiter + PBKDF2 | flask-wtf + flask-limiter + flask-talisman + flask-login + argon2-cffi | ~5 MB |
| 設定 | dict + 手寫驗證 | pydantic v2 BaseSettings | ~8 MB |
| Logging | logging + 自製 module_log | loguru | ~1 MB |
| 通用工具 | （無） | **humanize**（人類可讀時間/位元/數字） | ~0.5 MB |

預估打包後增量：約 **+109 MB**（純功能），加上現有 flask + pandas 後，最終 RPM bundle 預估約 **180–210 MB**。

---

## 子計畫總覽

| # | Phase | 子計畫檔名 | 風險 | 大小 | 核心套件 |
|---|---|---|---|---|---|
| 0 | 相依性基線 | `2026-04-18-phase-0-deps.md` | 低 | XS (~1 day) | requirements.txt 全部 pin + dev/prod 分離 |
| 1 | CLI UX 升級 | `2026-04-18-phase-1-cli-rich.md` | 中（i18n + 互動流程） | L (~5 days) | rich + questionary + click + humanize |
| 2 | HTTP client 重構 | `2026-04-18-phase-2-http-requests.md` | 中（核心模組） | L (~5 days) | requests + orjson + cachetools |
| 3 | 設定驗證 | `2026-04-18-phase-3-settings-pydantic.md` | 中（向後相容） | M (~3 days) | pydantic v2 |
| 4 | Web GUI 安全 | `2026-04-18-phase-4-web-security.md` | 高（session、登入、CSRF） | XL (~7 days) | flask-wtf + flask-limiter + flask-talisman + flask-login + argon2-cffi |
| 5 | 報表 Excel/PDF/互動圖表 | `2026-04-18-phase-5-reports-rich.md` | 中（新增 + 不破壞舊輸出） | XL (~7 days) | openpyxl + weasyprint + matplotlib + plotly + pygments + humanize |
| 6 | 排程器統一 | `2026-04-18-phase-6-scheduler-aps.md` | 中（既有 jobs 遷移） | L (~5 days) | APScheduler |
| 7 | Logging 統一 | `2026-04-18-phase-7-logging-loguru.md` | 低-中（觸及全部檔案，但機械式） | M (~3 days) | loguru（**完整替換**） |
| 9 | 架構重構（god-class 拆分） | `2026-04-18-phase-9-architecture.md` | 高（核心模組分割） | XL (~10 days) | （無新套件，純重構） |
| 10 | **Wave D — UX Quick Wins + Report Parity** ✅ Done? | `2026-04-19-phase-10-ux-quickwins.md` | 低-中 | M (~3-4 days) | 既有套件活化（CSV 預設關、audit/ven/policy_usage 接 pdf/xlsx、7 新 chart、rule/workload CLI、progress bar） |
| 11 | **Wave D — Chart & Dashboard Expansion** | `2026-04-19-phase-11-charts-dashboard.md` | 中 | L (~5-6 days) | 10 traffic module chart、GUI plotly 即時 dashboard、rule edit（questionary+pygments）、cron 排程 |
| 12 | **Wave D — Polish & Advanced** | `2026-04-19-phase-12-polish.md` | 中 | M (~3-5 days) | humanize sweep、SIEM docs+configs、GUI pygments、SQLAlchemyJobStore 持久化、shell completions |
| 8 | (後續獨立計畫) RPM 打包 | TBD | 高（部署面） | XL | PyInstaller + fpm/rpmbuild |

**總工期估算**：~45 個工作天（單人、含 Phase 9、不含測試補強）。**已確認採平行執行**：
- **Wave A (Phase 0 後並行)**：Phase 1 (CLI) ‖ Phase 2 (HTTP) ‖ Phase 3 (Settings) — 3 條 branch 同時推進
- **Wave B (依賴 Wave A)**：Phase 4 (Web 安全，依賴 Phase 3) ‖ Phase 5 (報表) ‖ Phase 6 (排程，依賴 Phase 3)
- **Wave C (序列)**：Phase 7 (Logging) → Phase 9 (架構重構) — 序列因 Phase 9 須在乾淨 logging 基礎上重構
- **Wave D (序列, Phase 10 → 11 → 12)**：升級套件的價值實體化 — 讓使用者從「沒差」變成「感受到差」。每 Phase 為獨立 branch、依序 merge 以避免 rebase 衝突。

**平行執行下總工期壓縮至 ~28 天**（Wave A ~5 天，Wave B ~7 天，Wave C ~13 天，Wave D ~12 天）。

---

## 為何採用此順序

### 設計原則

1. **使用者可見改善優先**：Phase 1 (CLI) 立即帶來體驗提升，建立升級動能與信心
2. **核心穩定性次之**：Phase 2 (HTTP)、Phase 3 (Settings) 為後續所有功能奠基
3. **安全敏感放中段**：Phase 4 在已有穩固基礎上做，且能借用 Phase 3 的 pydantic 驗證
4. **大型新功能放後段**：Phase 5、6 影響範圍大但獨立性高，做完前面再做更安心
5. **全域改動放最後**：Phase 7 (Logging) 觸及所有檔案，等其他改動穩定後一次到位
6. **打包獨立**：RPM 打包（Phase 8）與套件升級解耦，任何時點都可開工，但建議所有升級完成後再做

### 相依性圖（已確認平行執行）

```
Phase 0 (deps)
    │
    ├─── Wave A (並行) ────────────────────────────────
    │       Phase 1 (CLI)        ─┐
    │       Phase 2 (HTTP)       ─┼─ 三條同時開 branch、同時推進、互不干擾
    │       Phase 3 (Settings)   ─┘
    │
    ├─── Wave B (Wave A 完成後並行) ──────────────────
    │       Phase 4 (Web 安全)   ─┐  ← 依賴 Phase 3 (pydantic form)
    │       Phase 5 (Reports)    ─┼─ 三條同時推進
    │       Phase 6 (Scheduler)  ─┘  ← 依賴 Phase 3 (schedule schema)
    │
    └─── Wave C (序列、依賴 Wave B 全部完成) ─────────
            Phase 7 (Logging)     ← 全換 loguru，77 檔機械式替換
              ↓
            Phase 9 (架構重構)    ← 在乾淨 logging 基礎上拆 god-class
```

**Branch 命名**：每 Phase 一條 `upgrade/phase-N-<name>`；同 Wave 平行 branch 互不 rebase，merge 順序由完成時間決定，後 merge 者自行解 conflict（預期衝突極小，因檔案影響面分離良好）。

---

## 各 Phase 詳細範圍

### Phase 0：相依性基線（XS · 1 day）

**目標**：把所有要引入的套件 pin 到 [requirements.txt](../../../requirements.txt)，確認 dev 環境可正常 install 與 import，不更動任何業務程式碼。

**新增套件**（完整清單）：
```
# Production runtime (bundled into RPM)
flask>=3.0,<4.0
flask-wtf>=1.2,<2.0
flask-limiter>=3.5,<4.0
flask-talisman>=1.1,<2.0
flask-login>=0.6,<0.7
argon2-cffi>=23.1,<25.0
requests>=2.31,<3.0
rich>=13.7,<14.0
questionary>=2.0,<3.0
click>=8.1,<9.0
pydantic>=2.6,<3.0
pydantic-settings>=2.2,<3.0
APScheduler>=3.10,<4.0
loguru>=0.7,<0.8
openpyxl>=3.1,<4.0
weasyprint>=61.0,<62.0
matplotlib>=3.8,<4.0
plotly>=5.20,<6.0         # 互動式圖表（HTML 自包含、離線可用）
pygments>=2.17,<3.0       # 報表 JSON/YAML 語法高亮
humanize>=4.9,<5.0        # 「2 小時前」「3.5 GB」可讀格式（zh_TW locale）
orjson>=3.9,<4.0          # 快 2-3x 的 JSON 解析（async traffic 大型回應）
cachetools>=5.3,<6.0      # TTL/LRU cache（解 Status.md Q5 label cache 無 TTL）
pandas>=2.0,<3.0          # MANDATORY — used by 41 files, 338 DataFrame ops in mod01-15/audit/policy_usage
pyyaml>=6.0,<7.0          # MANDATORY — report_config.yaml
```

**Dev-only**：
```
# requirements-dev.txt
pytest
pytest-cov
ruff
mypy
build
pyinstaller
```

**驗收**：`pip install -r requirements.txt` 在乾淨 venv 成功；現有 127 測試全部通過；`python illumio_ops.py` 可進入主選單。

---

### Phase 1：CLI UX 升級 — rich + questionary + click + humanize（L · 5 days）

**目標**：用 `rich` 取代 [src/utils.py](../../../src/utils.py) 的 `Colors` / `draw_panel` / `Spinner`，用 `questionary` 取代 `safe_input`，引入 `click` 實作 subcommand 結構（舊 flag 向後相容），並用 `humanize` 處理時間/位元/數字的可讀格式（「上次掃描 5 分鐘前」「報表大小 12.3 MB」）。

**humanize 接入點**：CLI 主選單頂端狀態列（最後掃描時間、daemon 啟動時長）、`illumio-ops status` 子命令、所有報表大小/檔案大小顯示。`humanize.i18n.activate('zh_TW')` 隨 `t()` 語言切換。

**Subcommand 設計（v3.4）**：
```
illumio-ops                       # 進入互動選單（rich-based）
illumio-ops monitor [-i 5]        # = 舊 --monitor
illumio-ops gui [--port 5001]     # = 舊 --gui
illumio-ops monitor-gui           # = 舊 --monitor-gui
illumio-ops report traffic ...    # 新：直接觸發傳輸報表
illumio-ops report audit ...      # 新：直接觸發稽核報表
illumio-ops report ven            # 新：直接觸發 VEN 狀態
illumio-ops report policy-usage   # 新：直接觸發 policy usage
illumio-ops status                # 新：daemon 狀態 + 健康檢查
illumio-ops version               # 版本資訊（含套件版本表）
```

**i18n 注意事項**：所有 rich Panel/Table 標題與 questionary prompt 都必須走 `t()`，不能硬寫 EN/ZH。新增的 i18n key 須加入 `tests/test_i18n_audit.py` 的 CI gate。

**檔案影響範圍**：
- 改：[src/utils.py](../../../src/utils.py)（Colors → 留作 deprecated wrapper；draw_panel → rich.Panel）
- 改：[src/main.py](../../../src/main.py)（argparse → click，所有選單改用 questionary）
- 改：[src/settings.py](../../../src/settings.py) 1938 LOC、[src/rule_scheduler_cli.py](../../../src/rule_scheduler_cli.py) 676 LOC（input → questionary）
- 新：`src/cli/` 子套件（subcommand 模組化）
- 新：`scripts/illumio-ops-completion.bash`（給 RPM 後續使用）

**驗收**：
- 所有舊 flag 仍可用（向後相容測試）
- 新 subcommand 完整可用
- i18n audit script 仍 0 findings
- 互動流程在 Windows + Linux + macOS 上 emoji/box-drawing 正確顯示
- `pytest` 通過全部 127+ 測試

---

### Phase 2：HTTP client 重構 — requests + orjson + cachetools（L · 5 days）

**目標**：把 [src/api_client.py](../../../src/api_client.py) 2542 LOC 內所有 `urllib.request.*` 呼叫換成 `requests.Session`，啟用連線池與 `urllib3.util.Retry`，移除手寫的 `MAX_RETRIES` / `RETRY_BACKOFF_BASE` 邏輯。順便導入 `orjson` 加速大型 traffic 回應解析，並用 `cachetools.TTLCache` 解決 [Status.md Q5](../../../Status.md) 的 label cache 無 TTL 問題。

**重要**：本 Phase **不**重構 god-class 結構（那是 Phase 9 的工作），只做傳輸層替換。SSL 行為（含 `verify_ssl=False`）必須與舊版完全一致，避免 S6 的延伸風險。

**orjson 接入點**：所有 `json.loads(response.content)` 改用 `orjson.loads()`；async job 結果解析（常 100MB+）效能提升最顯著。回應序列化（write 路徑少，影響小）維持 stdlib `json` 即可。

**cachetools 接入點**：[src/api_client.py:118-122](../../../src/api_client.py) 的 `_label_cache` 改用 `TTLCache(maxsize=10000, ttl=900)`（15 分鐘）；新增 `invalidate_labels()` 方法供 settings 變更時手動清除。

**檔案影響範圍**：
- 改：[src/api_client.py](../../../src/api_client.py) 全檔
- 改：[src/state_store.py](../../../src/state_store.py)（state 寫入也可用 orjson 加速 + 保證 datetime/UUID 序列化一致）
- 改：[tests/test_api_client*.py](../../../tests)（mock 對象從 urllib 換為 `responses` 或 `requests-mock`）
- 新增測試：連線池 reuse、retry adapter 行為、timeout 邊界、label cache TTL 過期、orjson/json 相容性

**驗收**：所有 api_client 測試通過；對 PCE 實機煙霧測試（list workloads、async traffic query）成功；label cache 在 15 分鐘後自動 refetch。

---

### Phase 3：設定驗證 — pydantic v2 + pydantic-settings（M · 3 days）

**目標**：把 [src/config.py](../../../src/config.py) 的 `_DEFAULT_CONFIG` dict 與隱含驗證重寫為 `BaseSettings` model，所有設定欄位有型別、有 validator、有 default。`pce_profiles` / `web_gui` / `report` 全部 typed。

**向後相容策略**：保留 `cm.config["api"]["url"]` dict-style 存取（Pydantic model 加 `__getitem__` proxy 或 `model_dump()` 後快取），避免 70+ 處 caller 全改。

**新增**：`illumio-ops config validate` subcommand（呼叫 model.validate，回報具體錯誤行）。

**檔案影響範圍**：
- 改：[src/config.py](../../../src/config.py) 全檔（重寫，保留 ConfigManager facade）
- 新：`src/config_models.py`（BaseSettings 定義）
- 影響全 caller，但只在 `cm.config[...]` 介面層動

**驗收**：載入損壞 config.json 給出清楚錯誤；既有 valid config 無感升級；測試通過。

---

### Phase 4：Web GUI 安全強化（XL · 7 days）

**目標**：把 [src/gui.py](../../../src/gui.py) 2662 LOC 內所有自製安全機制換成 Flask 生態標準套件，並把密碼雜湊從 PBKDF2 升級到 argon2id（保留 PBKDF2 verify 路徑做自動升級）。

**子任務**：
1. **flask-login**：取代自製 session 機制（`session["user"]` → `current_user`）
2. **flask-wtf**：取代 [Task.md S4](../../../Task.md) 的 synchronizer token 自製實作；所有表單需附 `<form>{{ form.csrf_token }}</form>` 或 SPA 走 `/api/csrf-token` endpoint
3. **flask-limiter**：取代 [Task.md S5](../../../Task.md) 的自製 rate limiter；引入 Redis-or-memory storage（記憶體即可、單節點）
4. **flask-talisman**：強制 HTTPS（已有 TLS 設定）+ HSTS + CSP + X-Frame-Options
5. **argon2-cffi**：新 hash 用 argon2id（`argon2:` prefix）；舊 PBKDF2 hash 仍可 verify，登入成功後 silent upgrade（沿用 S1 既有模式）

**i18n 注意**：flask-wtf 的錯誤訊息需透過 `lazy_gettext` 走 i18n。

**檔案影響範圍**：
- 改：[src/gui.py](../../../src/gui.py)、[src/config.py](../../../src/config.py)（密碼欄位）
- 改：[src/templates/](../../../src/templates)、[src/static/js/utils.js](../../../src/static/js/utils.js)（CSRF token 取得方式）
- 改：[tests/test_gui_security.py](../../../tests/test_gui_security.py)
- 新增測試：argon2 hash/verify、PBKDF2→argon2 自動升級、CSP header 存在、限流回應

**驗收**：[Task.md](../../../Task.md) S1/S4/S5 完整通過 OWASP 對應檢查；既有使用者帳密無痛登入後密碼自動升級。

---

### Phase 5：報表 Excel/PDF/互動圖表（XL · 7 days）

**目標**：在 [src/report/exporters/](../../../src/report/exporters) 下新增四個 exporter/renderer（不取代 HTML/CSV，新增為可選輸出格式），引入 plotly **互動式圖表**（HTML 內嵌可縮放、hover 顯示明細）+ matplotlib **靜態圖表**（給 PDF/Excel 用），加上 pygments 對報表中的 PCE rule JSON / YAML 做語法高亮，humanize 統一時間/位元/數字呈現。

**圖表雙軌策略**：
- **HTML 報表** → plotly（互動，企業 demo 級體驗）
- **PDF 報表** → matplotlib（靜態 PNG 內嵌）
- **Excel 報表** → openpyxl 內嵌 matplotlib PNG，或用 openpyxl native chart API（取較易維護者）

**子任務**：
1. **chart_renderer.py**：雙引擎 — `render_plotly(fig_spec) -> str (HTML div)` 與 `render_matplotlib(fig_spec) -> bytes (PNG)`；統一輸入 spec（dict）以便兩邊吃同一份資料；matplotlib 字型需設定 CJK fallback (Noto Sans CJK)
2. **xlsx_exporter.py**：openpyxl 寫多 sheet（每個 mod 一張）、表頭凍結、條件格式（red flag 標紅）、嵌入 matplotlib PNG
3. **pdf_exporter.py**：weasyprint 把現有 HTML 轉 PDF（CSS 已存在於 [report_css.py](../../../src/report/exporters/report_css.py)），plotly 圖表自動 fallback 到 matplotlib PNG（plotly HTML 在 PDF 不互動）
4. **新增圖表的模組**：mod02 traffic top-N（bar）、mod05 protocol breakdown（pie）、mod10 timeline（line）、mod07 cross-label matrix（heatmap）、mod15 lateral movement（network graph，plotly 強項）
5. **pygments 高亮**：在 HTML/PDF 報表內所有 PCE rule JSON、YAML 範例、API payload 範例都加上 `pygments.highlight()`；GUI 端 dashboard 顯示 raw rule 也用上
6. **humanize 統一格式**：報表頁尾「Generated 5 minutes ago」「Total traffic 3.5 GB」「12,345 flows」全走 humanize；CSV/xlsx **不**用 humanize（保留機器可讀格式）
7. **CLI/GUI 新格式**：`--format pdf` / `--format xlsx` / `--format all`；GUI 報表頁新增格式選項

**i18n 注意**：
- 圖表標題、軸標籤、legend 全走 `t()`
- matplotlib 字型需內建 CJK fallback（避免缺字）
- plotly locale 設定為當前語言（內建 zh-TW）
- pygments style 不需 i18n（純色彩主題）
- humanize 切語言用 `humanize.i18n.activate('zh_TW')`

**檔案影響範圍**：
- 新：`src/report/exporters/chart_renderer.py`（plotly + matplotlib 雙引擎）
- 新：`src/report/exporters/xlsx_exporter.py`
- 新：`src/report/exporters/pdf_exporter.py`
- 新：`src/report/exporters/code_highlighter.py`（pygments wrapper）
- 改：所有 `src/report/exporters/*_html_exporter.py`（內嵌 chart 與高亮）
- 改：所有 `src/report/analysis/mod*.py` 有圖表需求的（提供 chart spec）
- 改：[src/main.py](../../../src/main.py) CLI、[src/gui.py](../../../src/gui.py) 報表 endpoint
- 影響：[Status.md](../../../Status.md) T3（HTML/CSV exporter 測試），這次一併補

**驗收**：
- 4 種報表 × 3 種格式（HTML / PDF / Xlsx）共 12 組合產出無誤
- plotly 互動圖在離線 HTML（無網路）下完整可用（縮放、hover、legend toggle）
- CJK 字型在 zh_TW 下無 □□□（matplotlib + plotly 雙邊驗證）
- pygments 高亮的 JSON 在 PDF 列印仍可讀（避免色彩太淡）
- humanize zh_TW locale 切換正確

---

### Phase 6：排程器統一 — APScheduler（L · 5 days）

**目標**：用 `BackgroundScheduler` 取代 [src/main.py](../../../src/main.py) 內的 daemon loop 自製 tick 邏輯，以及 [src/report_scheduler.py](../../../src/report_scheduler.py) 496 LOC + [src/rule_scheduler.py](../../../src/rule_scheduler.py) 246 LOC 內的時間判斷。Job 設定持久化沿用既有 JSON state（自製 jobstore wrapper）。

**子任務**：
1. 定義 3 種 job：`monitor_cycle` (interval)、`report_schedules` (cron, dynamic)、`rule_schedules` (cron, dynamic)
2. 自製 `JsonJobStore` 對接既有 `config/rule_schedules.json` 與 `config/report_schedules.json`
3. 移除 `_shutdown_event.wait(timeout=60)` 的 busy loop，改用 scheduler 自身 lifecycle
4. 順便處理 [Status.md A3](../../../Status.md)（單執行緒阻塞）— APScheduler 的 ThreadPoolExecutor 解決

**檔案影響範圍**：
- 改：[src/main.py](../../../src/main.py)（`run_daemon_loop` 重寫）
- 改：[src/report_scheduler.py](../../../src/report_scheduler.py)、[src/rule_scheduler.py](../../../src/rule_scheduler.py)（時間邏輯外包，業務邏輯保留）
- 改：[src/rule_scheduler_cli.py](../../../src/rule_scheduler_cli.py)（job 列表查詢介面）
- 新：`src/scheduler/jsonstore.py`、`src/scheduler/__init__.py`
- 新增測試：scheduler 啟停、job 觸發、跳過、misfire grace time

**驗收**：所有現有排程在升級後維持原行為；daemon shutdown 在 < 5s 內乾淨退出。

---

### Phase 7：Logging 統一 — loguru（**完整替換**, M · 3 days）

**目標**：把所有 `logger = logging.getLogger(__name__)` 換成 `from loguru import logger`，**完全移除 stdlib logging 介面**，統一 sink 設定，啟用 JSON 結構化輸出選項供 SIEM 收集。保留 [src/module_log.py](../../../src/module_log.py) 的 ring-buffer 給 GUI 即時 log 視圖（這是業務邏輯，不是 logging 系統）。

**為何全換而非只當 sink**：保留 stdlib logging 介面雖然影響面小，但會留下兩套配置、兩種 format 字串語法的混亂；既然要做就一次到位，未來新加程式碼也不會再混用。

**遷移策略**：
1. 寫一個 codemod script（`scripts/migrate_to_loguru.py`）批次替換 import
2. `setup_logger` 改為 loguru `logger.add()` config
3. CRITICAL: loguru 用 `{}` 而非 `%s` 格式化；script 自動偵測並轉換 `logger.info("x %s", v)` → `logger.info("x {}", v)`
4. JSON sink 為 opt-in（透過設定 `logging.json_sink: true` 啟用）

**檔案影響範圍**：
- 改：77 個 `src/**/*.py` 檔的 logger import（codemod 自動處理）
- 改：[src/utils.py](../../../src/utils.py) 的 `setup_logger`
- 改：[src/main.py](../../../src/main.py) 的 logging 初始化
- 不動：[src/module_log.py](../../../src/module_log.py)

**驗收**：日誌外觀一致；JSON sink 可被 jq parse；既有 LOG_FILE 路徑/輪轉行為不變。

---

### Phase 9：架構重構（god-class 拆分, XL · 10 days）

**目標**：解決 [Status.md](../../../Status.md) 列出的所有 MEDIUM 級架構債，包括 [Task.md](../../../Task.md) Phase 2 的 A1-A5 + Q1-Q2。**不引入新套件**，純重構，建立在 Phase 7 完成後的 loguru 乾淨日誌基礎上（避免 logger import 替換與業務重構交雜）。**無 mem0 中標示「Phase 2-A1: split api_client.py」即為本 Phase 起點**。

**子任務**（依風險由低到高）：

1. **A5 — 移除 `events/shadow.py`**（D, ~0.5 天）
   - 確認 [src/events/shadow.py](../../../src/events/shadow.py) 與 [src/events/matcher.py](../../../src/events/matcher.py) 邏輯重複
   - 移除 shadow.py 與所有 import；補測試確認 matcher.py 涵蓋原 shadow 行為

2. **Q3 — 統一重複的 `extract_id()`**（XS, ~0.5 天）
   - [src/analyzer.py](../../../src/analyzer.py) + [src/rule_scheduler.py](../../../src/rule_scheduler.py) 兩處重複
   - 抽到 `src/utils/href_utils.py`，兩邊改 import

3. **Q1 — 拆解 `Analyzer.run_analysis()` 196 行**（M, ~1.5 天）
   - 拆為：`_fetch_traffic()`、`_run_event_analysis()`、`_run_rule_engine()`、`_dispatch_alerts()`
   - 公開介面 `run_analysis()` 維持不變；內部組合
   - 每個內部方法都要有單元測試

4. **A4 — 統一例外處理**（M, ~1.5 天）
   - 新增 `src/exceptions.py`：`IllumioOpsError` → `APIError`、`ConfigError`、`ReportError`、`AlertError`、`SchedulerError`
   - 替換所有 `except: pass` 與裸 `except Exception`，要嘛 log + reraise，要嘛 log + 明確默認值
   - 既有 silent fallback 鏈（如 [analyzer.py 的 format fallback](../../../src/analyzer.py)）保留但加註解 + log debug

5. **A3 + T1 — Daemon loop 解阻塞**（M, ~1 天）
   - 已由 Phase 6 (APScheduler) 解決大部分；本步驟確認 `_rs_log_history` 與 `module_log` 在多執行緒下安全
   - 加 `threading.Lock` 或改用 `collections.deque(maxlen=N)`（thread-safe）

6. **A2 — 拆 `api_client.py` 2542 LOC god-class**（XL, ~3 天）
   - 抽出三個 domain class，`ApiClient` 變 facade：
     - `TrafficQueryBuilder`（async traffic query 組裝、native filter 解析）
     - `AsyncJobManager`（job 提交、輪詢、結果下載、cache 管理）
     - `LabelResolver`（label cache、label_group 解析、href 對應）
   - facade 用 composition：`self._traffic = TrafficQueryBuilder(self)` 等
   - **不破壞既有 caller**：所有 public method 保留在 `ApiClient` 上，內部 delegate

7. **A1/Q2 — 模組依賴解耦**（L, ~2 天）
   - 既有：Analyzer→ApiClient→Reporter→Events（緊耦合）
   - 抽 `src/interfaces.py`：`IApiClient`、`IReporter`、`IEventStore` Protocol
   - Analyzer 依賴 Protocol 而非具體 class，方便測試 mock

8. **A2 全域可變狀態收斂**（M, ~1 天）
   - [src/utils.py:21](../../../src/utils.py) `_LAST_INPUT_ACTION`：包成 `InputState` singleton
   - [src/i18n.py:8,14](../../../src/i18n.py) `_current_lang`：包成 `I18nState` + thread-local
   - [src/gui.py:184](../../../src/gui.py) `_rs_log_history`：包成 `RSLogStore` + Lock

**檔案影響範圍**：
- 改：[src/analyzer.py](../../../src/analyzer.py)（拆方法）
- 改：[src/api_client.py](../../../src/api_client.py)（facade 化）
- 新：`src/api/traffic_query.py`、`src/api/async_jobs.py`、`src/api/labels.py`
- 新：`src/exceptions.py`、`src/interfaces.py`、`src/utils/href_utils.py`
- 改：[src/events/](../../../src/events) 移除 shadow.py
- 改：[src/utils.py](../../../src/utils.py)、[src/i18n.py](../../../src/i18n.py)、[src/gui.py](../../../src/gui.py) 全域狀態包裝
- 新增測試：每個拆出的 class、每個新例外類型、Protocol 對 Analyzer 的 mock 測試

**驗收**：
- [Status.md](../../../Status.md) A1/A2/A3/A4/A5 + Q1/Q2/Q3 全部標 ✅
- [src/api_client.py](../../../src/api_client.py) 從 2542 LOC 降到 < 800 LOC（facade only）
- 既有 127+ 測試 + 新增 ~30 測試全通過
- 無 public API 變更（caller 無感）

---

## 跨 Phase 共通規範

### Git 與 commit 策略
- 每個 Phase 一條 feature branch：`upgrade/phase-N-<name>`
- 每個 Task 一個 commit，commit message 走現有 conventional 風格
- 完成 Phase 後 squash merge 到 main，標 tag `v3.{N+3}.0`（例：Phase 1 後 v3.4.0）

### 測試門檻
- Phase 結束時：所有既有測試 + 新增測試通過
- i18n audit script `tests/test_i18n_audit.py` 持續 0 findings
- 新增的 logging 系列測試 `tests/test_log_layer_english.py` 持續通過

### 文件門檻
- Phase 結束時更新 [Status.md](../../../Status.md)（版本、新增依賴、架構變化）
- Phase 結束時更新 [Task.md](../../../Task.md)（標記完成）
- 影響 user-facing 行為時更新 [docs/User_Manual.md](../../../docs/User_Manual.md) + zh

### i18n 門檻
- 任何 user-visible 字串都必須走 `t()`
- 新增 i18n key 必須同時更新 `i18n_en.json` + `_ZH_EXPLICIT`
- 不可破壞既有 1400+ key 的 EN/ZH 對應

### 回滾策略
- 每個 Phase 在 merge 後保留 branch 一個 release cycle
- 若發現重大 regression，revert merge commit 即可（由於是 squash merge，回滾乾淨）

---

## 後續（不在本路線圖內）

完成 Phase 0–9 後，啟動獨立計畫：

- **Phase 8**：PyInstaller spec + RPM 打包 (`fpm` PoC → `.spec` 正式) → 另一份 plan
- **Phase 10**：[Status.md T1-T5](../../../Status.md) 測試覆蓋率補強（mod01-15、alerts、exporters） → 另一份 plan
- **Phase 11**：[Status.md DOC1-DOC4](../../../Status.md) 文件擴充（API_Cookbook、threshold tuning、rule scheduler 狀態機、報表模組） → 另一份 plan

---

## 套件選用最終清單（供 Phase 0 一次裝齊）

**核心新增**（生產 + bundle）：
| 套件 | Phase | 用途 |
|---|---|---|
| flask-wtf | 4 | CSRF 表單保護 |
| flask-limiter | 4 | rate limiting |
| flask-talisman | 4 | 安全 headers + HSTS + CSP |
| flask-login | 4 | session 管理 |
| argon2-cffi | 4 | 密碼雜湊（取代 PBKDF2） |
| requests | 2 | HTTP client |
| rich | 1 | CLI 美化 |
| questionary | 1 | 互動 prompt |
| click | 1 | CLI subcommand |
| pydantic + pydantic-settings | 3 | 設定驗證 |
| APScheduler | 6 | 統一排程 |
| loguru | 7 | 結構化 logging |
| openpyxl | 5 | Excel 輸出 |
| weasyprint | 5 | PDF 輸出 |
| matplotlib | 5 | 靜態圖表 (PDF/Excel) |
| plotly | 5 | **互動圖表** (HTML 自包含、離線可用) |
| pygments | 5 | 報表 JSON/YAML 語法高亮 |
| humanize | 1, 5 | 「2 小時前」「3.5 GB」可讀格式 |
| orjson | 2 | 快速 JSON 解析（async traffic 大型回應） |
| cachetools | 2 | TTL/LRU cache（解 Q5） |
| pandas | 既有 | **MANDATORY** — 41 檔/338 處運算 |
| pyyaml | 既有 | **MANDATORY** — report_config.yaml |
| flask | 既有 | Web GUI |

**Dev-only**：pytest, pytest-cov, ruff, mypy, build, pyinstaller, responses（Phase 2 mock）, freezegun（Phase 6 時間 mock）

---

## 待你確認

1. **順序是否同意**？我建議的順序是 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7。如果你想優先做某個 Phase（例如 5 報表優先給客戶 demo），可調整。
2. **是否平行**？若你願意自己同時開兩條 branch，Phase 1+2、Phase 5+6 可平行；但若是我獨立執行則建議序列以保持上下文清晰。
3. **Logging 是否真的要全換**？loguru 雖好但會碰 77 個檔。如果想保守可在 Phase 7 改為「保留 `logging` 標準介面、只加 loguru 作為 sink 之一」，影響面降到 [src/utils.py](../../../src/utils.py) 一個檔。
4. **要不要補做架構重構（Phase 9）**？god-class 與 `run_analysis()` 196 行可以在 Phase 7 後一起做。
5. **第一個要展開的詳細計畫是哪個**？建議從 **Phase 0** 開始（最低風險、可立即驗證所有套件相容性）。

確認後我會立刻寫 **Phase 0 詳細計畫**（具體 Task、TDD 測試碼、commit 命令），可在你看完直接 `superpowers:executing-plans` 跑起來。
