---
title: i18n Contract
audience: [developer]
last_verified: 2026-05-15
verified_against:
  - src/i18n/engine.py
  - src/i18n/__init__.py
  - src/i18n/data/zh_explicit.json
  - src/i18n/data/dashboard_approved.json
  - src/gui/routes/dashboard.py
  - src/config.py
  - tests/test_i18n_audit.py
  - commit 503f029
related_docs:
  - overview.md
  - ../contributing/i18n-workflow.md
  - ../reference/glossary.md
  - ../user-guide/dashboard.md
---

> [English](i18n-contract.md) | **[繁體中文](i18n-contract_zh.md)**
> 📍 [INDEX](../INDEX.md) › 架構 › i18n 介面契約
> 🔍 最後驗證日期 **2026-05-15**，對應 commit `503f029` — 詳見 frontmatter

# i18n 介面契約

本文件說明 illumio-ops 國際化（i18n）子系統的不變量、API 與資料配置。
在新增鍵值、修改翻譯或更改語言切換邏輯之前，請先閱讀本文。

---

## 支援語言

illumio-ops 支援**兩種**語系：

| 代碼 | 名稱 | 狀態 |
|------|------|------|
| `en` | 英文 | 預設；永遠完整 |
| `zh_TW` | 繁體中文 | 完整支援；缺口偵測啟用中 |

不支援其他語系。合法語系集合由
`src/i18n/engine.py` 中的
`_I18nState._VALID = frozenset({"en", "zh_TW"})` 強制執行。
任何未知語系代碼都會靜默回退至 `"en"`。

---

## 儲存

### 真實來源檔案

| 檔案 | 用途 |
|------|------|
| `src/i18n_en.json` | 主要英文訊息目錄 |
| `src/i18n_zh_TW.json` | 主要 zh_TW 訊息目錄 |
| `src/i18n/data/zh_explicit.json` | Illumio 產品術語的 zh_TW **權威**覆寫值 |
| `src/i18n/data/glossary.json` | zh_TW 中**必須保留英文**的術語白名單（如 PCE、VEN、Policy、Workload） |
| `src/i18n/data/dashboard_approved.json` | 9 個 Dashboard 迷你 KPI 鍵值的核准 zh_TW 翻譯 — Category J 迴歸閘道 |
| `src/i18n/data/phrase_overrides.json` | 由 `_translate_text()` 套用的詞組替換規則 |
| `src/i18n/data/token_map_en.json` | Token → 英文詞彙映射（供 `_humanize_key_en()` 使用） |
| `src/i18n/data/token_map_zh.json` | Token → zh_TW 詞彙映射（供 `_humanize_key_zh()` 使用） |
| `src/i18n/data/strict_prefixes.json` | 發生缺口時應發出 `[MISSING:key]` 而非靜默回退的鍵值前綴 |

### zh_TW.json 不存在

`src/i18n/data/zh_TW.json` **不存在於此儲存庫**（B2.1 稽核確認，並於 `503f029` 再次驗證）。
zh_TW 翻譯來自 `src/i18n_zh_TW.json`（位於 `src/` 根目錄），而非 `src/i18n/data/` 內部。

引擎的載入路徑：

```python
_ZH_MESSAGES_PATH = _ROOT / "i18n_zh_TW.json"   # _ROOT = src/
```

`src/i18n/data/zh_explicit.json` 是獨立的覆寫檔，存放 Illumio 特定術語；
它並非完整訊息目錄，也不會在執行期自動合併進訊息字典。

### zh_TW 解析順序

呼叫 `_build_messages("zh_TW")` 時：

1. 在 `_normalized_zh_messages()`（由 `src/i18n_zh_TW.json` 建構）中查找鍵值。
2. 若找到且非空白 → 使用該值。
3. 若鍵值符合**嚴格前綴**（定義於 `strict_prefixes.json`）→ 發出 `[MISSING:key]`。
4. 否則 → 記錄警告並回傳**鍵值名稱本身**作為可視訊號。

`zh_explicit.json` 單獨載入並以 `_ZH_EXPLICIT` 公開，供稽核腳本與品質測試使用；
在執行期不會自動影響 `t()` 的查找結果。

---

## API

### 公開介面（`src/i18n/__init__.py`）

```python
from src.i18n import t, get_messages, set_language, get_language
```

### `t()` — 主要翻譯函式

```python
def t(key: str, *, lang: str | None = None, default: str | None = None, **kwargs) -> str:
```

| 參數 | 型別 | 說明 |
|------|------|------|
| `key` | `str` | 翻譯鍵值（英數字元 + `_`） |
| `lang` | `str \| None` | 指定語系（`"en"` 或 `"zh_TW"`）。`None` → 使用全域語系。 |
| `default` | `str \| None` | 找不到翻譯且鍵值為非嚴格前綴時的回退字串。 |
| `**kwargs` | `Any` | 傳遞給結果字串的 `str.format(**kwargs)`。 |

**`t()` 內部解析順序：**

1. `_lang = lang if lang in {"en", "zh_TW"} else get_language()`
2. 在 `get_messages(_lang)` 的預建字典中查找 `key`。
3. 若未找到，嘗試 `_normalized_en_messages()` 作為後備。
4. 若仍未找到且鍵值符合嚴格前綴 → 回傳 `[MISSING:key]`。
5. 若仍未找到 → 回傳 `default`（若有提供），否則對 zh_TW 使用 `_humanize_key_zh(key)`，對 en 使用 `_humanize_key_en(key)`。
6. 若有 kwargs，套用 `str.format(**kwargs)`。

### 預設語系解析

全域語系存放於執行緒安全的單例 `_I18nState`（Lock 保護的 `str`），預設為 `"en"`：

```python
get_language()           # → "en" | "zh_TW"
set_language("zh_TW")   # 全域設定；僅限開機引導（見下方說明）
```

**`set_language()` 僅供程序引導使用。** 原始碼文件明確禁止在請求處理器、排程任務或任何並發上下文中呼叫。
允許的呼叫者由 `tests/test_i18n_set_language_callers.py` 中的白名單測試強制執行。

### 每請求語系執行緒

對於並發 Web 請求，語系為每個請求獨立解析，不會修改全域狀態：

```python
# src/gui/__init__.py
def _request_lang() -> str:
    """Resolve lang for the current request: session > config default."""
    if has_request_context():
        s_lang = session.get("lang")
        if s_lang:
            return s_lang
    return cm.config.get("settings", {}).get("language", "en")
```

解析後的 `lang` 字串會顯式傳遞給該請求中的每個 `t(key, lang=lang)` 呼叫。
不使用 thread-local 儲存；不修改全域狀態。

---

## UI 標籤 vs 儲存資料的差異

| 類別 | 語言行為 |
|------|----------|
| **UI 標籤** — 按鈕文字、圖表軸標題、KPI 標題、導覽項目 | 每次請求使用當前 `lang` 重新翻譯。切換語言後標籤即時更新。 |
| **儲存資料** — 寫入 `config/alerts.json` 的規則描述與建議、稽核日誌條目 | 在**寫入時**的語言中凍結。切換語言後不會重新翻譯。 |
| **Report HTML** — 由報表引擎產生 | 在**產生時**的語言中凍結。 |

此區別至關重要：以英文命名為「PCE health check failed.」的規則，在操作員切換語言後不會自動變成 zh_TW 字串。
`_resolve_rule_keys` 機制（見下方說明）將已知最佳實踐規則的舊式純文字升級為鍵值式儲存，
使語言切換後可重新翻譯 — 但使用者自訂的規則名稱永遠不會被修改。

---

## 快照重譯模式

Dashboard 快照是在報表產生時寫入磁碟的 JSON 物件。
其 `kpis` 列表包含以下形式的條目：

```json
{ "label": "Hit Rules", "value": "42", "label_key": "rpt_pu_hit_rules" }
```

當快照被提供給瀏覽器時，dashboard 路由會呼叫：

```python
# src/gui/routes/dashboard.py
def _retranslate_kpi_labels(data: dict, lang: str) -> None:
```

此函式遍歷 `data["kpis"]` 中的每個項目。當 `label_key` 存在時，
以 `t(label_key, lang=lang)` 的結果覆寫 `label`，
使 Dashboard 無論快照寫入時的語言為何，始終以當前 UI 語言顯示標籤。

沒有 `label_key` 欄位的舊式快照保持原樣；它們顯示產生時凍結的語言，
並會隨著新快照的產生而自然淘汰。

`_retranslate_kpi_labels` 在三個 dashboard 端點處理器中被呼叫
（`/api/dashboard`、`/api/dashboard/story`、`/api/dashboard/policy-usage`）。

---

## alerts.json 鍵值解析

`config/alerts.json` 存放告警規則。規則記錄有三個文字欄位
（`name`、`desc`、`rec`）和三個對應的鍵值欄位（`name_key`、`desc_key`、`rec_key`）。
鍵值式儲存允許規則不受語言綁定。

### 載入路徑 — `_resolve_rule_keys()`

由 `ConfigManager.load()` 在讀取 `alerts.json` 後立即呼叫：

```python
# src/config.py
def _resolve_rule_keys(self) -> None:
```

每條規則處理三種情況：

1. **新式規則** — `name_key` / `desc_key` / `rec_key` 已設定。
   透過 `t(key, lang=lang)` 渲染並回寫至 `name` / `desc` / `rec`。

2. **舊式 `[MISSING:key]` 標記** — 較早的最佳實踐執行在 i18n 鍵值尚不存在時寫入了 `[MISSING:rule_*]`。
   載入器解析出鍵值後重新解析，並回填 `*_key` 欄位，以便下次 `save()` 時正確持久化。

3. **純舊式純文字** — 無 `*_key`、無 `[MISSING:]`，但純文字值與已知最佳實踐鍵值
   （透過 `_LEGACY_FILTER_TO_NAME_KEY` 衍生）的規範 EN 或 zh_TW 渲染之一相符。
   升級為鍵值式儲存。不符合任何規範渲染的使用者自訂名稱**不受影響**。

### 儲存路徑 — `_write_alerts_file()`

```python
# src/config.py
def _write_alerts_file(self):
    """Atomically write {"rules": self.config['rules']} to alerts.json
    ...
    rendered text is repopulated by load() via _resolve_rule_keys()."""
```

儲存時會在持久化前剝離已渲染的文字 — 磁碟上只寫入 `*_key` 欄位；
`name` / `desc` / `rec` 文字被視為暫時性資料，在每次 `load()` 時重新填充。

### `_LEGACY_FILTER_TO_NAME_KEY`

一個從 `filter_value` 字串到規範 `rule_*` 基礎鍵值的硬編碼映射。
用於情況 3，辨識自動產生的最佳實踐規則：

```python
_LEGACY_FILTER_TO_NAME_KEY = {
    "agent.tampering":          "rule_agent_tampering",
    "user.sign_in,user.login":  "rule_login_failed",
    # ... 共 15 個條目
}
```

---

## label_key vs 已解析標籤

此程式碼庫使用兩種 i18n 鍵值命名慣例：

| 前綴族群 | 使用位置 | 範例 |
|----------|----------|------|
| `gui_*` | Web GUI 標籤、導覽項目、錯誤訊息、按鈕文字 | `gui_err_internal`、`gui_last_activity` |
| `rpt_*` | 報表與 Dashboard 圖表標題、軸標籤、KPI 標題 | `rpt_pd_allowed`、`rpt_pu_hit_rules` |
| `rule_*` | 告警規則 name / desc / rec 文字 | `rule_agent_tampering_desc` |
| `alert_*` | 告警通知欄位標籤與文字 | `alert_field_src_ip` |
| `sched_*` | 排程器狀態訊息 | （嚴格前綴） |

JSON 物件（快照 KPI、FieldMeta、圖表規格）中的 `label_key` 欄位
始終存放上述原始鍵值字串。對應的 `label` 欄位存放當前語言的**已渲染**字串。

**前端程式碼規則：** 始終儲存 `label_key`，將 `label` 視為純顯示用途。
`_retranslate_kpi_labels()` / `FieldMeta.render(lang=)` 模式依賴 `label_key` 的存在。

以 `gui_`、`sched_`、`status_`、`error_`、`pd_` 開頭的鍵值在 `src/gui/_helpers.py` 中
被篩選為「GUI 介面」鍵值並接受更嚴格的驗證。
`strict_prefixes.json` 控制哪些前綴在缺口時發出 `[MISSING:key]`（而非靜默回退），
確保開發者在使用者可見的介面上看到明確的缺口訊號。

---

## 新增鍵值的步驟

> 完整步驟說明：請參閱 [i18n Workflow](../contributing/i18n-workflow.md) *(B3 deliverable — TODO: B3 合併後連結才會生效)*。

簡短版本：

1. 在 `src/i18n_en.json` 中新增英文字串。
2. 在 `src/i18n_zh_TW.json` 中新增 zh_TW 字串。
3. 若為 Illumio 產品術語，在 `src/i18n/data/zh_explicit.json` 中新增或驗證 zh_TW 條目。
4. 若為 Dashboard KPI，在 `src/i18n/data/dashboard_approved.json` 中新增條目。
5. 使用 `t("your_key", lang=lang)` — 在請求處理器中**絕對不要**使用無 `lang` 的 `t("your_key")`。
6. 執行 `python scripts/audit_i18n_usage.py` 並確認零發現。

---

## 稽核測試

### 測試檔案

| 檔案 | 涵蓋範圍 |
|------|----------|
| `tests/test_i18n_audit.py` | CI 閘道：以子程序執行 `scripts/audit_i18n_usage.py`；非零退出時失敗 |
| `tests/test_i18n_quality.py` | 翻譯品質檢查 |
| `tests/test_i18n_lang_param.py` | 驗證 `lang=` 參數的顯式傳遞 |
| `tests/test_i18n_strict_prefixes.py` | 嚴格前綴缺口偵測發出 `[MISSING:key]` |
| `tests/test_i18n_strings_parity.py` | EN/zh_TW 鍵值對等性 |
| `tests/test_i18n_glossary.py` | 詞彙白名單強制執行 |
| `tests/test_i18n_set_language_callers.py` | `set_language()` 呼叫者白名單 |
| `tests/test_i18n_consumers_smoke.py` | i18n 消費者程式碼路徑冒煙測試 |
| `tests/test_i18n_menu_strings.py` | 選單字串完整性 |
| `tests/test_i18n_traffic_strings.py` | 流量報表字串涵蓋範圍 |
| `tests/test_i18n_translate_text_audit.py` | `_translate_text()` 輸出稽核 |

### 稽核類別（A–J）

`scripts/audit_i18n_usage.py` 定義十個類別。`test_non_glossary_categories_clean`
逐一執行 A、B、C、D、F、G、H、I、J，任何發現都會硬性失敗：

| 類別 | 說明 |
|------|------|
| A | EN 語系中的佔位符洩漏 |
| B | zh_TW 語系中的佔位符洩漏 |
| C | 翻譯表以外的硬編碼 CJK 字元 |
| D | zh_TW 字串中的自動翻譯殘留 |
| E | 詞彙漂移 — 白名單術語在 zh_TW 中必須保留英文 *（xfail：約 90 個已知開放違規）* |
| F | 佔位符洩漏變體（格式字串） |
| G | 重複/不一致的佔位符宣告 |
| H | JS/HTML 純文字回退預設值（`_translations[key] \|\| '...'`） |
| I | `i18n_zh_TW.json` 中缺少的已追蹤 EN 鍵值 |
| **J** | **Dashboard zh_TW 核准翻譯迴歸閘道** — `src/i18n/data/dashboard_approved.json` 中的每個鍵值必須與其核准值完全相符，且 Han 字元比例 ≥ 0.8（`han_ratio_exceptions` 中列出的合法拉丁術語詞彙除外） |

Category E 目前為 `xfail`（約 90 個已知開放詞彙違規，記載於 `README.md`）。
其餘所有類別必須保持乾淨。

Category J 於 commit `b9d88de` 新增，涵蓋 9 個 Dashboard 迷你 KPI 翻譯
（如 `rpt_pu_total_rules`、`rpt_pu_hit_rate`），防止操作員在 Dashboard 上看到的翻譯靜默漂移。

---

## 相關文件

- [架構總覽](overview.md) — 整體架構
- [i18n Workflow](../contributing/i18n-workflow.md) — 新增翻譯鍵值（B3 deliverable）
- [詞彙表](../reference/glossary.md) — Illumio 術語
- [Dashboard](../user-guide/dashboard.md) — 操作員視角的 i18n 行為
