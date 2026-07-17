---
title: 開發流程與慣習
audience: [developer]
version: 4.1.0
last_verified: 2026-07-17
verified_against:
  - requirements.txt
  - requirements-dev.txt
  - requirements.lock
  - pytest.ini
  - mypy.ini
  - .github/workflows/ci.yml
  - scripts/docs_check.py
  - scripts/check_doc_links.py
  - scripts/bump_version.sh
  - scripts/resolve_version.sh
  - scripts/build_offline_bundle.sh
  - scripts/setup.sh
  - scripts/audit_i18n_usage.py
  - scripts/check_no_naive_datetime.py
  - AGENTS.md
  - src/i18n/engine.py
  - src/i18n/__init__.py
  - src/i18n/data/zh_explicit.json
  - src/i18n/data/dashboard_approved.json
  - src/gui/routes/dashboard.py
  - src/config.py
  - src/gui/routes/actions.py
  - src/analyzer.py
  - src/api/traffic_query.py
  - src/report/report_generator.py
  - src/static/js/dashboard.js
  - src/report_scheduler.py
  - tests/test_i18n_audit.py
---

# 開發流程與慣習

本文件的讀者是**要對這個 codebase 送 PR 的開發者**。涵蓋開發環境建置、測試與 CI 守門、i18n 鍵值合約（取代已刪除的 `docs/reference/i18n-contract.md`）、幾個重複發生過的斷鏈坑，以及發版流程。架構全貌見 [architecture.md](architecture.md)，PCE vendor 知識見 [pce-domain-notes.md](pce-domain-notes.md)。

---

## 1. 開發環境建置

```bash
git clone <repo-url>
cd illumio-ops

python3 -m venv venv
source venv/bin/activate          # bash / zsh

pip install -r requirements.txt -r requirements-dev.txt
```

`requirements.txt` 是正式執行環境相依套件的**來源規格**（版本區間，未鎖 hash）；`requirements-dev.txt` 是測試框架＋Linter＋型別檢查工具，不打包進正式安裝。日常開發用上面兩行即可。

`requirements.lock` 是用 `pip-compile --generate-hashes --strip-extras requirements.txt` 從 `requirements.txt` 編譯出的**逐版本 hash 鎖定檔**，CI 與 `scripts/setup.sh`（正式環境安裝）都用它以 `pip install --require-hashes -r requirements.lock` 安裝，確保供應鏈可重現。三者關係：`requirements.txt`（人寫的規格）→ `requirements.lock`（機器編譯出的鎖定＋hash，逐套件 `--hash=sha256:...`）→ CI/正式環境用鎖定檔安裝，開發機通常用規格檔即可，只有要精確重現 CI 環境時才需要 `pip install --require-hashes -r requirements.lock -r requirements-dev.txt`。

啟動 GUI／monitor 前需準備設定檔：

```bash
cp config/config.json.example config/config.json
# 編輯 config/config.json，填入 api.url、api.org_id、api.key、api.secret
```

本機執行入口為專案根目錄的 `illumio-ops.py`：`python3 illumio-ops.py shell|gui|monitor|monitor-gui`，`--help` 看完整子指令。

---

## 2. 測試與守門

### 2.1 CI 實際跑的順序（`.github/workflows/ci.yml`）

矩陣：`ubuntu-22.04` 上的 Python `3.10` 與 `3.11`，push/PR 到 `main` 觸發，同 ref 並行執行自動取消。步驟依序：

1. **安裝相依套件（鎖定＋hash 驗證）** — `pip install --require-hashes -r requirements.lock`
2. **安裝開發相依套件** — `pip install -r requirements-dev.txt`
3. **安全稽核（pip-audit）** — `pip-audit -r requirements.lock --strict`，`continue-on-error: false`。**這一步在 pytest 之前**，CVE 掃描直接擋 CI，不是事後才發現。
4. **禁止 naive datetime lint** — `python3 scripts/check_no_naive_datetime.py`：擋 `src/` 下新增的 naive `datetime.now()`（`src/report/` 與 `src/humanize_ext.py` 在允許清單內，是既有技術債，非新代碼豁免）。
5. **文件連結檢查** — `python scripts/check_doc_links.py`
6. **i18n 審計（硬閘門）** — `python scripts/audit_i18n_usage.py`
7. **型別檢查（嚴格子集）** — `mypy --follow-imports=silent src/api_client.py src/analyzer.py src/reporter.py`
8. **執行測試** — `pytest --tb=short`

八步全過 PR 才可合併。

### 2.2 本機測試

```bash
pytest                                      # 全套（簡短追蹤）
pytest --tb=long                            # 詳細追蹤
pytest -m "not slow"                        # 略過慢速測試
pytest -m "not slow and not integration"    # 僅單元測試
pytest --cov=src --cov-report=term-missing  # 覆蓋率
```

`pytest.ini` 定義的三個標記：`slow`（>~1 秒）、`integration`（跨子系統）、`requires_pce`（需連線真實 PCE，CI 中預設略過，僅供實驗室測試機執行；主機/帳密資訊見 `AGENTS.md` 或當下的 session-handoff 文件，切勿寫進本文件）。

### 2.3 型別檢查與 Lint

`mypy.ini`：目標 Python 3.10，`src/api_client.py`、`src/analyzer.py`、`src/reporter.py` 三個進入點啟用嚴格 `disallow_untyped_defs`，這三個模組是 CI 硬閘門檢查的唯一子集：

```bash
mypy --follow-imports=silent src/api_client.py src/analyzer.py src/reporter.py
```

Ruff 是已設定的 Linter／格式化工具：

```bash
ruff check .          # lint
ruff format .         # 格式化
ruff check --fix .    # 自動修正
```

### 2.4 文件守門鏈四件套（`scripts/docs_check.py`）

`docs_check.py` 提供四個獨立檢查模式，可組合啟用：

| 旗標 | 檢查內容 |
|---|---|
| `--bilingual` | 每個 `.md` 是否有 `_zh.md` 對應檔（僅適用於仍維持雙語配對的舊文件目錄） |
| `--freshness N` | `last_verified` 是否超過 N 天（`--all` 預設 30 天） |
| `--frontmatter` | frontmatter 是否存在，且 `title`／`last_verified`／`verified_against` 三個必要鍵非空 |
| `--links` | 文件內部相對連結是否指向 `docs/` 內存在的檔案 |

**這四件套本身不在 CI 硬閘門內**——`ci.yml` 只跑 `scripts/check_doc_links.py`（掃 repo 根目錄 README/Status/Task 與整個 `docs/` 下所有連結，範圍比 `docs_check.py --links` 更廣，且不受 `--exclude` 限制）。`docs_check.py` 是提交文件變更前的手動／半自動稽核工具，例如：

```bash
python scripts/docs_check.py --frontmatter --exclude 'superpowers/**'
python scripts/check_doc_links.py
```

`docs/superpowers/` 底下的計畫文件本來就沒有 frontmatter，因此檢查 frontmatter 時要排除它；連結正確性交給 repo-root 視野的 `check_doc_links.py` 把關。

---

## 3. i18n workflow（含鍵值合約）

系統支援兩種語系：`en`（預設，永遠完整）與 `zh_TW`（完整支援，缺口偵測啟用）。合法語系集合由 `src/i18n/engine.py` 的 `_I18nState._VALID = frozenset({"en", "zh_TW"})` 強制執行，未知語系代碼靜默回退至 `en`。

### 3.1 何時要新增 i18n 鍵

使用者可見文字出現在以下位置時新增鍵：GUI／`src/main.py` 渲染的選單、標籤、按鈕、提示；`src/report/` 的報告區段標題、欄位標籤、KPI 標題；`src/report_scheduler.py` 的排程狀態或郵件本文；呈現給操作員的事件／警報訊息。

**不需要**新增鍵：Python `logging` 內部日誌（永遠英文）；寫入磁碟的資料（規則名稱、原則標籤）——以英文儲存，顯示時透過 `t(key, lang=lang)` 翻譯；測試 fixture 或開發工具的硬編碼字串。

### 3.2 檔案配置（真實來源）

| 檔案 | 用途 |
|---|---|
| `src/i18n_en.json` | 主要英文訊息目錄，真實來源 |
| `src/i18n_zh_TW.json` | 主要 zh_TW 訊息目錄，鍵集須與 en 完全一致 |
| `src/i18n/data/zh_explicit.json` | Illumio 產品術語（workload、PCE、VEN、pairing profile 等）的 zh_TW 權威覆寫值，CI 交叉比對；**執行期不會自動合併進訊息字典**，僅供稽核腳本／品質測試使用 |
| `src/i18n/data/dashboard_approved.json` | 9 個 Dashboard 迷你 KPI 鍵值的核准 zh_TW 翻譯，Category J 迴歸閘道 |
| `src/i18n/data/glossary.json` | zh_TW 中必須保留英文的術語白名單 |
| `src/i18n/data/phrase_overrides.json` | `_translate_text()` 套用的詞組替換規則 |
| `src/i18n/data/strict_prefixes.json` | 缺口時應發 `[MISSING:key]` 而非靜默回退的鍵值前綴 |

**`src/i18n/data/zh_TW.json` 不存在於本 repo**——zh_TW 翻譯來自 `src/i18n_zh_TW.json`（`src/` 根目錄下），不是 `src/i18n/data/` 內部；引擎載入路徑為 `_ZH_MESSAGES_PATH = _ROOT / "i18n_zh_TW.json"`。

### 3.3 新增鍵的步驟

1. **決定鍵名稱**：`<area>_<purpose>` 格式，常見前綴：`gui_`（GUI 元件）、`menu_`（選單）、`alert_`（警報）、`rpt_`（報告／Dashboard）、`rs_`（規則排程器）、`pd_`（原則判斷）、`lbl_`（通用標籤）、`pu_`（原則使用模組）、`rule_`（告警規則 name/desc/rec）、`sched_`（排程器狀態，嚴格前綴）。
2. 在 `src/i18n_en.json` 按字母順序新增英文值，插值用 `{variable_name}` 語法。
3. 在 `src/i18n_zh_TW.json` 新增對應 zh_TW 值——**必須同一個 commit**，CI Category I（`audit_zh_parity_against_en`）強制鍵集一致。
4. 若涵蓋 Illumio 產品術語，先查 `docs/reference/glossary.md`（尚未刪除）確認是否已有核可翻譯，再新增到 `src/i18n/data/zh_explicit.json`；不得在 `i18n_zh_TW.json` 寫入與其矛盾的翻譯（Category E 會擋）。
5. 若為 Dashboard KPI，同步新增到 `src/i18n/data/dashboard_approved.json`。
6. 原始碼中用 `from src.i18n import t`；請求處理器內**一律**顯式傳 `lang`：`t("your_key", lang=lang)`，絕不要用無 `lang` 的 `t("your_key")`（會落到全域語系，並發請求下不可靠）。
7. 執行稽核：`python scripts/audit_i18n_usage.py`（全部 Category）或 `pytest tests/test_i18n_audit.py tests/test_i18n_strings_parity.py -v`；只查單一 Category 用 `--only <字母>`。合併前所有 Category 須以 0 退出碼結束。
8. 切換語言在 UI 中人工驗證：跑起應用程式，設定 → 語言 → 切換 zh_TW，確認無版面溢出或缺字。

### 3.4 `t()` 執行期解析順序

```python
def t(key: str, *, lang: str | None = None, default: str | None = None, **kwargs) -> str: ...
```

1. `_lang = lang if lang in {"en", "zh_TW"} else get_language()`
2. 在 `get_messages(_lang)` 的預建字典查 `key`。
3. 找不到則退回 `_normalized_en_messages()`。
4. 仍找不到且鍵值符合嚴格前綴 → 回傳 `[MISSING:key]`。
5. 仍找不到 → 回傳 `default`（若有），否則 zh_TW 用 `_humanize_key_zh(key)`、en 用 `_humanize_key_en(key)` 產生可讀回退字串。
6. 有 `kwargs` 則套用 `str.format(**kwargs)`。

`set_language()` **僅供程序引導使用**，源碼明文禁止在請求處理器／排程任務／並發上下文呼叫，白名單由 `tests/test_i18n_set_language_callers.py` 強制。並發 Web 請求走每請求語系解析（`src/gui/__init__.py` 的 `_request_lang()`：session > config 預設），不修改全域狀態、不用 thread-local。

### 3.5 UI 標籤 vs 儲存資料

| 類別 | 語言行為 |
|---|---|
| UI 標籤（按鈕、軸標題、KPI 標題、導覽項目） | 每次請求以當前 `lang` 重新翻譯，切換語言即時更新 |
| 儲存資料（`config/alerts.json` 的規則描述／建議、稽核日誌） | 寫入時的語言凍結，切換語言後不重新翻譯 |
| Report HTML | 產生時的語言凍結 |

**Dashboard 快照重譯**：快照 JSON 的 `kpis` 條目可帶 `label_key`（如 `{"label": "Hit Rules", "value": "42", "label_key": "rpt_pu_hit_rules"}`）。`src/gui/routes/dashboard.py` 的 `_retranslate_kpi_labels(data, lang)` 在三個端點（`/api/dashboard`、`/api/dashboard/story`、`/api/dashboard/policy-usage`）遍歷 `kpis`，有 `label_key` 就用 `t(label_key, lang=lang)` 覆寫 `label`，讓 Dashboard 顯示跟隨當前 UI 語言而非快照寫入時的語言。沒有 `label_key` 的舊快照維持原樣，隨新快照產生自然淘汰。

**alerts.json 鍵值解析**：規則記錄有 `name`/`desc`/`rec` 文字欄位與對應 `name_key`/`desc_key`/`rec_key` 鍵值欄位。`src/config.py` 的 `_resolve_rule_keys()` 在 `ConfigManager.load()` 讀完 `alerts.json` 後立即處理三種情況：（1）新式規則已設 `*_key` → 用 `t(key, lang=lang)` 渲染回填；（2）舊式 `[MISSING:key]` 標記 → 重新解析並回填 `*_key`；（3）純舊式純文字且與已知最佳實踐規則的規範渲染相符（透過 `_LEGACY_FILTER_TO_NAME_KEY` 映射）→ 升級為鍵值式儲存，使用者自訂名稱不受影響。`_write_alerts_file()` 儲存時只寫 `*_key`，渲染文字視為暫時性資料。

### 3.6 稽核類別（A–J）

`scripts/audit_i18n_usage.py` 定義十類；`tests/test_i18n_audit.py` 的 `test_non_glossary_categories_clean()` 逐一跑 A、B、C、D、F、G、H、I、J，非零退出即失敗：

| 類別 | 說明 |
|---|---|
| A / B | EN / zh_TW 語系中的佔位符洩漏 |
| C | 翻譯表以外的硬編碼 CJK 字元（JS/HTML，見下方「JS 禁行尾 CJK 註解」） |
| D | zh_TW 字串中的自動翻譯殘留 |
| E | 詞彙漂移（白名單術語須保留英文）——目前 `xfail`，約 90 個已知開放違規 |
| F | 佔位符洩漏變體（格式字串） |
| G | 重複／不一致的佔位符宣告 |
| H | JS/HTML 純文字回退預設值（`_translations[key] \|\| '...'`） |
| I | `i18n_zh_TW.json` 中缺少的已追蹤 EN 鍵值 |
| J | Dashboard zh_TW 核准翻譯迴歸閘道：`dashboard_approved.json` 每個鍵須與核准值完全相符，Han 字元比例 ≥ 0.8（`han_ratio_exceptions` 內的合法拉丁術語除外） |

---

## 4. 常見斷鏈坑

### 4.1 新增流量 filter key 要同步的層

物件／複數 filter key（`src_labels`、`services`、`ports` 等 Phase 1/3 FilterBar 送出的鍵）要在**新增或改名時**同步以下四個位置，任何一層漏改都會**靜默丟棄**該 filter（不報錯、只是查不到預期結果）：

1. **`src/gui/routes/actions.py`（約 L104–165）**——GUI 路由把請求 payload `d` 映射成 `params` dict，餵給 `analyzer.query_flows()`。第 144 行的行內註解明文要求與下面兩層鍵名保持一致：
   > `whitelist（~1053-1064）及 _TRAFFIC_FILTER_CAPABILITIES（traffic_query.py ~90-96）保持一致`
2. **`src/analyzer.py` `query_flows()` 的 `query_filters` whitelist（L1399–1466）**——鍵名須與 (1) 完全一致，否則「在這個 whitelist 被靜默丟棄，永遠到不了 `build_traffic_query_spec` / `_flow_matches_filters`」（L1447–1450 原文註解）。同檔案內還有兩個附屬登記表，同一批鍵要一起檢查：
   - `_OBJECT_FILTER_KEYS`（L63–74）：決定該鍵在 cache 命中路徑要委派給 `TrafficQueryBuilder._flow_matches_filters` 做 client 端比對（legacy scalar 鍵走另一套 `check_flow_match`，兩套比對器互不相通，L59–62、L76–79 原文註解）。
   - `_CACHE_UNEVALUABLE_FILTER_KEYS`（L80–84）：client 端比對器完全無法評估的鍵（label group 展開只存在於 PCE 端）；帶這些鍵時 cache 路徑必須讓路給 API，否則會靜默回傳未過濾資料。
3. **`src/api/traffic_query.py` 的 `_TRAFFIC_FILTER_CAPABILITIES`（L50–130）**——每個鍵登記 `native`（推進 PCE async query payload）／`fallback`（client 端過濾）／`report_only`（fetch 後才套用，如排序、搜尋、分頁）三種 execution 模式之一；未登記的鍵預設降級 `fallback` 並附警告文字。`build_traffic_query_spec()`（L187）依此表把 `raw_filters` 分流進 `native_filters`／`fallback_filters`／`report_only_filters`。
4. **`TrafficQueryBuilder._flow_matches_filters`（`traffic_query.py` L924 起）**——`fallback` 與 cache 命中路徑實際執行比對邏輯的靜態方法；新鍵若登記為 `fallback` 但這裡沒實作對應比對邏輯，capability 表會宣稱支援、但比對永遠不成立。

四層都要動；此鏈已重演兩次斷鏈事故（見 CLAUDE 記憶「Filter key 全鏈清單」），加鍵或改名時務必逐層核對，不要只改其中一兩處。

### 4.2 報表 sidecar `report_type` 與檔名 prefix

`ReportGenerator._write_report_metadata()`（`src/report/report_generator.py` 約 L818–822）把每份報表的 metadata 寫到 `<report_path>.metadata.json`。`_build_report_metadata()`（約 L824–838）**不論 traffic／security_risk／network_inventory 哪個 profile，一律硬編回傳 `"report_type": "traffic"`**（L833）；raw CSV 匯出走另一條路徑，硬編 `"report_type": "traffic_raw_csv"`（`report_generator.py` L658）。

因此前端無法只靠 sidecar 的 `report_type` 分辨這三種 traffic 家族報表——`src/static/js/dashboard.js`（約 L241–250）用**檔名前綴**覆寫：`Illumio_Traffic_Report_SecurityRisk_` → `security_risk`、`Illumio_Traffic_Report_NetworkInventory_` → `network_inventory`、`Illumio_Traffic_Report_\d{4}-`（純日期開頭）→ `traffic`；判斷順序刻意先查 SecurityRisk／NetworkInventory 兩個特化前綴，因為 `Illumio_Traffic_Report_` 是它們的 strict prefix，順序反了會誤判。Policy Diff／Policy Resolver／App Summary 三種報表完全沒有 metadata sidecar，純靠檔名前綴判斷。

前綴表另存一份在 `src/report_scheduler.py` 的 `_REPORT_PREFIXES`（約 L621–631，含 traffic/security_risk/network_inventory/audit/ven_status/policy_usage/policy_diff/policy_resolver/app_summary/rule_hit_count 共 10 類），`dashboard.js` 的行內註解明文標示自己是在 mirror 這份表。**新增一種 traffic 家族報表時**，只在 `_build_report_metadata()` 加新字串是不夠的——前端三段 if-else 與 `_REPORT_PREFIXES` 都要同步加對應的檔名前綴分支，否則 Dashboard 卡片會把新報表誤判成舊的 `traffic`。

### 4.3 JS/HTML 禁行尾 CJK 註解

`scripts/audit_i18n_usage.py` 的 Category C（`_js_html_cjk_literals()`，約 L373–392）逐行掃描 `.js`／`.html`，只放行「整行本身就是純註解」的行——`stripped.startswith("//")`、`"/*"`、`"*"`、`"<!--"`。也就是說：

```javascript
// 正確：整行純註解
// 這裡是中文說明

const x = compute();  // 錯誤：程式碼 + 行尾中文註解，會被 Category C 判定為硬編碼 CJK
```

第二種寫法會被判定為「CJK 出現在非註解位置」而擋下 CI（因為 `stripped` 是以程式碼開頭，不是以 `//` 開頭）。這是全行文字掃描＋整行註解白名單的粗粒度判斷，抓不出「這段 CJK 到底是字串還是行尾註解」，只能用「整行是不是純註解」當代理。另有 `BILINGUAL_DATA_LINES` 白名單（`_is_bilingual_allowed()`，約 L405–412）可針對特定檔案＋關鍵字逐條放行翻譯字典本身的中文值。**規則：JS/HTML 裡的中文只能整行純註解或走白名單資料行，絕不要把中文說明寫成「陳述式 + 行尾 `//` 註解」同一行。**

---

## 5. Release 流程

### 5.1 版本編號

純語意化版本（`X.Y.Z`），單一真相來源是 `src/__init__.py` 的 `__version__`。`scripts/bump_version.sh` 只接受純 `X.Y.Z`，非純 semver（含 codename）一律拒絕。

版本調升同步以下三類檔案（`scripts/bump_version.sh <X.Y.Z>` 一次完成）：

1. `src/__init__.py` 的 `__version__`
2. `CHANGELOG.md`——在第一個既有 `## [` 標題前插入新的 `## [<version>] — <today>` 段落
3. `README.md` 與 `README_zh.md` 的 `![Version]` shield（兩檔存在才改，缺一不擋）

```bash
pytest -q                          # 測試須先過
scripts/bump_version.sh 4.1.1      # 更新三類檔案、commit、打附註標籤 v4.1.1
git push origin main
git push origin v4.1.1
```

只想改檔不 commit／打標籤，用 `--no-tag`（此模式要求工作樹乾淨才能執行帶 tag 的版本，`--no-tag` 則略過此檢查）。`scripts/bump_version.sh` 永不執行 `git push`。

`scripts/resolve_version.sh` 是唯讀的版本解析工具（供打包腳本用），解析順序：`$VERSION` 環境變數逐字使用 → 否則讀 `src/__init__.py` 的 `__version__` 當 base → 若 HEAD 剛好是乾淨的 `v<base>` 標籤 → 印 `<base>`；否則印 `<base>+<short-hash>`（dev build）。

### 5.2 離線套件重建

有依賴變更或要發版時，重新產生離線安裝包：

```bash
scripts/build_offline_bundle.sh
```

輸出 `dist/illumio-ops-<version>-offline-linux-x86_64.tar.gz` 與對應的 Windows zip；`<version>` 由 `resolve_version.sh` 解出。腳本內嵌 python-build-standalone 的下載 URL 與 SHA256 pin（`PBS_TAG`／`PBS_PYTHON`／`PBS_SHA256_*`），升級內嵌 Python 版本時四個欄位要一起改、一起送同一個 commit，且 SHA256 要從發布來源以外的管道（GPG／Sigstore）重新核對，避免 same-origin 供應鏈攻擊。

正式環境安裝／升級統一用 `scripts/setup.sh`（`pip install --require-hashes -r requirements.lock`，systemd service 啟停）。若目標機器無法連網，改用離線套件：`pip install --no-index --find-links wheels -r requirements-offline.txt`。

### 5.3 遷移腳本

破壞性 config 變更需在 `scripts/migrate_*.py` 下提供腳本，且必須具備冪等性（重複執行無作用）。例如 `migrate_rules_to_keys.py` 把 `config/alerts.json` 的規則描述／建議文字改寫成 `desc_key`/`rec_key`，使語言切換可即時生效；未遷移的舊規則仍可運作（loader 以 `[MISSING:*]` 回退）。升級安裝器跑完、正式仰賴新結構前執行一次即可。

### 5.4 發佈前檢查清單

打標籤前完整跑過：測試通過（`pytest -q`）、Lint 無誤（`ruff check .`）、型別檢查通過（CI 的嚴格子集三檔）、i18n 審計乾淨（`python scripts/audit_i18n_usage.py`）、CHANGELOG 已更新、README 徽章版本已更新（`bump_version.sh` 自動處理前三者以外的檔案改寫，但測試／lint／型別／i18n 仍需自行先跑過再執行腳本）、離線套件已就緒（依賴有變更時）、必要的遷移腳本已備妥。
