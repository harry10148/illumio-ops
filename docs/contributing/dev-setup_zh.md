---
title: Developer Setup
audience: [developer]
last_verified: 2026-05-15
verified_against:
  - requirements.txt
  - requirements-dev.txt
  - pytest.ini
  - mypy.ini
  - AGENTS.md
  - .github/workflows/ci.yml
  - commit 926ea42
related_docs:
  - i18n-workflow.md
  - release-process.md
  - ../architecture/overview.md
  - ../INDEX.md
---

> **[English](dev-setup.md)** | **[繁體中文](dev-setup_zh.md)**
> 📍 [INDEX](../INDEX.md) › 貢獻指引 › 開發者設定
> 🔍 最後驗證日期 **2026-05-15**，對應 commit `926ea42`，參見 frontmatter 中的來源清單

# 開發者設定

本指引帶你從零開始完成 clone、建立開發環境，並讓測試與型別檢查正常運作。

---

## 取得原始碼與建立 venv

```bash
git clone <repo-url>
cd illumio-ops

python3 -m venv venv
source venv/bin/activate          # bash / zsh
# source venv/bin/activate.fish   # fish
```

> **Ubuntu 22.04+ / Debian 12+：** PEP 668 封鎖了直接執行 `pip install`。
> 若尚未安裝 venv 支援，請先執行：`sudo apt install python3-venv`

每次開啟新終端機前須重新啟動 venv：

```bash
source venv/bin/activate
```

---

## 安裝開發相依套件

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

`requirements.txt` — 正式執行環境相依套件（Flask、pandas、click、loguru 等）  
`requirements-dev.txt` — 測試框架 + Linter + 型別檢查工具（不打包進正式 RPM）：

| 群組 | 套件 |
|---|---|
| 測試框架 | `pytest`、`pytest-cov`、`responses`、`freezegun`、`cryptography`、`beautifulsoup4` |
| Lint / 型別 | `ruff`、`mypy` |
| 建置 / 封裝 | 離線套件工具（參見 `scripts/build_offline_bundle.sh`） |

---

## 本機執行

進入點為專案根目錄的 `illumio-ops.py`。

| 目的 | 指令 |
|---|---|
| 互動式 CLI 選單 | `python3 illumio-ops.py shell` |
| 僅啟動 Web GUI | `python3 illumio-ops.py gui` |
| 無頭監控 Daemon | `python3 illumio-ops.py monitor` |
| 監控 + GUI 一併啟動 | `python3 illumio-ops.py monitor-gui` |
| 顯示所有子指令 | `python3 illumio-ops.py --help` |

啟動 GUI 或 monitor 前，需先準備有效的設定檔：

```bash
cp config/config.json.example config/config.json
# 編輯 config/config.json，填入 api.url、api.org_id、api.key、api.secret
```

---

## 實驗室測試機（選用）

團隊有一台共用的實驗室測試機，可針對真實 Illumio PCE 執行端對端測試。
**請勿**在本文件中存放任何憑證 — 主機名稱、帳號與 API Key 詳情請參閱
`AGENTS.md` 或當前的 session-handoff 文件。

標記為 `requires_pce` 的測試在 CI 中預設略過，僅供實驗室環境執行。

---

## 測試

```bash
pytest              # 執行所有測試（簡短追蹤輸出）
pytest --tb=long    # 詳細追蹤輸出
pytest -m "not slow"            # 略過慢速測試，加快迭代
pytest -m "not slow and not integration"  # 僅執行單元測試
pytest tests/test_i18n_audit.py tests/test_i18n_quality.py  # i18n 閘門
```

測試檔案平鋪於 `tests/` 目錄下：

| 分類 | 檔案模式 | 說明 |
|---|---|---|
| API 用戶端 | `test_api_client*.py` | PCE HTTP 層、重試、執行緒安全 |
| 分析器 | `test_analyzer*.py` | 流量分析邏輯 |
| CLI | `test_cli_*.py` | Click 指令、退出碼、向下相容 |
| GUI / Web | `test_gui_*.py` | Flask 路由、設定分頁、認證 |
| i18n | `test_i18n_*.py`、`test_*_i18n.py` | Key 對稱性、品質、審計 |
| 快取 | `test_cache_*.py` | PCE 快取讀寫與接線 |
| 報表 | `test_report*.py`、`test_html_*.py` | HTML/XLSX/PDF 報表結構 |
| 排程器 | `test_cron_*.py` | APScheduler 時間 / 時區 |
| 整合 | `test_integrations_e2e.py`、`test_phase_*_e2e.py` | 跨子系統 |

**Pytest 標記**（定義於 `pytest.ini`）：

| 標記 | 說明 |
|---|---|
| `slow` | 執行時間 > ~1 秒；可用 `-m "not slow"` 略過 |
| `integration` | 橫跨多個子系統 |
| `requires_pce` | 需要連線至真實 PCE — CI 中略過 |

覆蓋率報告：

```bash
pytest --cov=src --cov-report=term-missing
```

---

## 型別檢查

mypy 設定於 `mypy.ini`，目標 Python 版本為 3.10。  
CI 硬閘門僅檢查三個已完整型別標注的進入點模組：

```bash
mypy --follow-imports=silent src/api_client.py src/analyzer.py src/reporter.py
```

若要在本機檢查其他模組：

```bash
mypy src/<module>.py
```

`src/api_client.py`、`src/analyzer.py`、`src/reporter.py` 已啟用嚴格的
`disallow_untyped_defs`；其餘模組以 `ignore_missing_imports = True` 為基準。

---

## Lint / 格式化

**Ruff** 是已設定的 Linter 與格式化工具（`requirements-dev.txt` 中為
`ruff>=0.4,<1.0`）。目前尚無 `ruff.toml` 或 `pyproject.toml` 中的 ruff 區段，
以預設值執行。

```bash
ruff check .          # lint 檢查
ruff format .         # 格式化（取代 black）
ruff check --fix .    # 自動修正 lint 問題
```

> **TODO：** 將 `[tool.ruff]` 設定（select、line-length、target-version）加入
> `pyproject.toml`。截至 2026-05-15 尚未設定。

---

## CI 檢查

工作流程：`.github/workflows/ci.yml` — **CI**

觸發條件：推送或 PR 目標為 `main`。相同 ref 的並行執行會自動取消。

矩陣：`ubuntu-22.04` 上的 Python **3.10** 與 **3.11**。

步驟（依序）：

1. **安裝相依套件** — `pip install -r requirements.txt -r requirements-dev.txt`
2. **文件連結檢查** — `python scripts/check_doc_links.py`
3. **i18n 審計**（硬閘門）— `python scripts/audit_i18n_usage.py`
4. **型別檢查（嚴格子集）** — `mypy --follow-imports=silent src/api_client.py src/analyzer.py src/reporter.py`
5. **執行測試** — `pytest --tb=short`

以上五個步驟全部通過後，PR 才可合併。

---

## 分支與 PR 慣例

**分支命名**（由近期分支名稱推導）：

| 類型 | 模式 | 範例 |
|---|---|---|
| 功能 | `feat/<short-name>` | `feat/phase-3.1-dashboard-story` |
| 修正 | `fix/<short-name>` | `fix/alert-i18n-and-delivery` |
| 文件 | `docs/<short-name>` | `docs/contributing-guide` |

**Commit 訊息格式**（由近期提交推導）：

```
<type>(<scope>): <subject>

<body — 選用，每行不超過 72 字元>

Co-Authored-By: ...
```

類型：`feat`、`fix`、`docs`、`test`、`refactor`、`chore`。

近期提交範例：
- `docs(ux-review): session wrap-up — all 9 plans + ADR completed`
- `fix(settings): use explicit i18n key lookup for dirty-section label`
- `test(dashboard): e2e Playwright coverage for story-mode redesign`

**`.github/` 中尚無 PR 模板** — 請在 PR 說明中手動加入清單：

```markdown
## Checklist
- [ ] 測試通過（`pytest`）
- [ ] i18n 審計通過（`python scripts/audit_i18n_usage.py`）
- [ ] 型別檢查通過（`mypy --follow-imports=silent src/api_client.py src/analyzer.py src/reporter.py`）
- [ ] 若更動了 UI / 報表 / 警示文字，已同步更新 `src/i18n_en.json` 和 `src/i18n_zh_TW.json`
```

---

## 相關文件

- [i18n 工作流程](i18n-workflow.md) — 新增翻譯 Key（下一份文件）
- [發布流程](release-process.md) — 建置與發佈版本
- [架構概覽](../_archive/architecture/overview.md) — 了解你正在開發的系統
- [INDEX](../INDEX.md) — 完整文件地圖
