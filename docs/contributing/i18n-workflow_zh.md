---
title: i18n Workflow
audience: [developer]
last_verified: 2026-05-15
verified_against:
  - src/i18n/data/zh_explicit.json
  - src/i18n_en.json
  - src/i18n_zh_TW.json
  - tests/test_i18n_audit.py
  - tests/test_i18n_strings_parity.py
  - scripts/audit_i18n_usage.py
  - commit 2e17d81
related_docs:
  - ../architecture/i18n-contract.md
  - ../reference/glossary.md
  - dev-setup.md
  - release-process.md
---

> [English](i18n-workflow.md) | **[繁體中文](i18n-workflow_zh.md)**
> 📍 [INDEX](../INDEX.md) › 貢獻指引 › i18n 工作流程
> 🔍 最後驗證日期 **2026-05-15**，commit `2e17d81` — 詳見 frontmatter 來源列表

# i18n 工作流程

本指南說明如何為 illumio-ops 的 UI 和報告新增及維護國際化（i18n）鍵。
系統支援英文（`en`）與繁體中文（`zh_TW`）。
底層合約（鍵解析、儲存規則、語言切換）請參閱
[`../architecture/i18n-contract.md`](../architecture/i18n-contract.md)。

---

## 何時新增 i18n 鍵

當你引入的使用者可見文字出現在以下位置時，請新增一個鍵：

- `src/gui/` 或 `src/main.py` 渲染的互動選單、標籤、按鈕或提示。
- `src/report/` 中的報告區段標題、欄位標籤或 KPI 標題。
- `src/report_scheduler.py` 中的排程工作狀態或電子郵件本文。
- 呈現給操作員的事件／警報訊息。

**不需要**新增鍵的情況：

- 內部日誌訊息（Python `logging` 呼叫）— 永遠保持英文。
- 寫入磁碟的資料（如規則名稱、原則標籤）— 以英文儲存，顯示時透過
  `t(key, lang=lang)` 翻譯；詳見[常見錯誤](#常見錯誤)。
- 測試 fixture 或開發者工具中的硬編碼字串。

---

## 鍵存在哪裡

| 檔案 | 用途 |
|------|------|
| `src/i18n_en.json` | **真實來源** — 所有鍵的英文值。 |
| `src/i18n_zh_TW.json` | zh_TW 翻譯。必須與 `i18n_en.json` 一對一對應。 |
| `src/i18n/data/zh_explicit.json` | 授權 Illumio 術語詞彙表。涵蓋 Illumio 產品術語（workload、PCE、VEN、pairing profile 等）的已核可 zh_TW 值存放於此，並由 CI 交叉比對。 |
| `src/i18n/data/dashboard_approved.json` | 儀表板 KPI 面板已鎖定 zh_TW 值的鍵子集。CI Category J 強制執行精確比對。 |

交叉參考：[`../architecture/i18n-contract.md`](../architecture/i18n-contract.md)
說明 `t()` 在執行期如何解析鍵，以及 `zh_explicit.json` 如何覆蓋基礎翻譯檔。

---

## 新增鍵的步驟

### 步驟 1 — 決定鍵名稱

鍵遵循 `<area>_<purpose>` 格式，其中 `<area>` 為功能前綴。常見前綴：

| 前綴 | 區域 |
|------|------|
| `gui_` | 互動式 GUI 元件（`src/gui/`） |
| `menu_` | 主選單與子選單標籤 |
| `alert_` | 警報類別／訊息字串 |
| `rpt_` | 報告標頭與電子郵件本文 |
| `rs_` | 規則排程器 UI |
| `pd_` | 原則判斷標籤 |
| `lbl_` | 通用 UI 標籤 |
| `pu_` | 原則使用模組 |

範例：`gui_accel_bulk_btn`、`alert_cat_cluster`、`rs_back`、`pd_1`。

選擇最短且能清楚表達鍵用途的名稱，讓人單獨閱讀時即可理解。

### 步驟 2 — 在 `src/i18n_en.json` 新增英文值

```json
// src/i18n_en.json  (按字母順序插入)
{
  "gui_my_new_label": "My New Label"
}
```

英文值應保持簡潔。插值佔位符使用 `{variable_name}` 語法，
例如 `"Lag: {lag}s"`。

### 步驟 3 — 在 `src/i18n_zh_TW.json` 新增 zh_TW 值

```json
// src/i18n_zh_TW.json
{
  "gui_my_new_label": "我的新標籤"
}
```

兩個檔案必須包含**完全相同的鍵集**；一致性由 CI Category I
（`audit_zh_parity_against_en`）強制執行。

### 步驟 4 — 若鍵涵蓋 Illumio 特定術語：同時更新 `src/i18n/data/zh_explicit.json`

```json
// src/i18n/data/zh_explicit.json
{
  "alert_cat_my_illumio_term": "我的 Illumio 詞彙"
}
```

在自行創作翻譯前，請先查閱
[`../reference/glossary.md`](../reference/glossary.md)
確認是否已有已核可翻譯。稽核工具（`--only E`）會標記任何
`i18n_zh_TW.json` 中與 `zh_explicit.json` 不同的值（若兩個檔案均包含該鍵）。

### 步驟 5 — 在原始碼中透過 `t()` 引用鍵

```python
from src.i18n import t

# 標準用法 — 以使用者目前的語言渲染
label = t("gui_my_new_label")

# 對於寫入儲存資料或電子郵件輸出的字串，明確傳入 lang
subject = t("rpt_email_traffic_subject", lang=lang)
```

匯入路徑：`src/i18n/__init__.py` 公開 `t()` 函式。

### 步驟 6 — 執行稽核測試

```bash
# 快速單元層級一致性檢查（在 repo 根目錄執行，需先啟動 venv）
pytest tests/test_i18n_audit.py tests/test_i18n_strings_parity.py -v

# 完整綜合稽核腳本（所有 Category A–J）
python scripts/audit_i18n_usage.py

# 只執行單一 Category
python scripts/audit_i18n_usage.py --only J   # 儀表板已核可翻譯閘門
```

合併前所有 Category 必須以 0 退出碼結束。

### 步驟 7 — 切換語言在 UI 中驗證

```bash
# 執行應用程式，前往「設定 → 語言」，切換至繁體中文
python -m src.main
```

確認新標籤在兩種語言下均能正確渲染，無版面溢出或缺字問題。

---

## 詞彙表對齊

在翻譯任何 Illumio 產品術語（workload、PCE、VEN、enforcement boundary、
pairing profile、label、IP list 等）之前，請先查閱專案詞彙表：

- [`../reference/glossary.md`](../reference/glossary.md) — 含已核可 EN 和
  zh_TW 術語的人類可讀參考。
- `src/i18n/data/zh_explicit.json` — 稽核腳本使用的機器可讀授權來源
  （Category E：詞彙表違規）。

若詞彙表尚未包含你的術語，請在**同一個 PR**中同時更新兩個檔案。
不得在 `i18n_zh_TW.json` 中新增與 `zh_explicit.json` 矛盾的翻譯 — CI 會捕捉此差異並阻擋合併。

---

## CI 已核可翻譯閘門

**Category J**（`audit_dashboard_approved_translations`）於 commit `b9d88de`
新增，作為 9 個儀表板迷你 KPI 翻譯的迴歸閘門。

**檢查內容：**

1. `src/i18n/data/dashboard_approved.json` 中列出的每個鍵，必須存在於
   `src/i18n_zh_TW.json` 中。
2. zh_TW 值必須與已核可值**完全一致**。
3. 值的漢字比率必須 ≥ 0.8，除非該鍵列於 `han_ratio_exceptions`
   （保留給合理的拉丁詞彙術語，如 `PCE`、`VEN`）。

**導致 CI 失敗的情況：**

- 修改儀表板 KPI 翻譯但未同步更新 `dashboard_approved.json`。
- 貼入與已核可值不符的機器翻譯字串。
- 意外批次重命名鍵，導致儀表板鍵移位。

若有意更新已核可翻譯，請在同一個 commit 中同時修改
`src/i18n_zh_TW.json` 和 `src/i18n/data/dashboard_approved.json`，
並在審查說明中解釋原因。

閘門由 `tests/test_i18n_audit.py` 與 Category A–I 一同執行。

---

## 本機執行 i18n 稽核

```bash
# 所有 Category（A–J）— 開 PR 前的標準執行
python scripts/audit_i18n_usage.py

# 單一 Category
python scripts/audit_i18n_usage.py --only A   # 佔位符洩漏
python scripts/audit_i18n_usage.py --only E   # 詞彙表違規
python scripts/audit_i18n_usage.py --only I   # zh 與 EN 一致性
python scripts/audit_i18n_usage.py --only J   # 儀表板已核可翻譯

# 執行包裝稽核的 pytest 套件
pytest tests/test_i18n_audit.py -v

# 一次執行所有 i18n 相關測試
pytest tests/test_i18n_*.py -v
```

稽核腳本會印出摘要表格。非零退出碼表示至少有一個發現需要處理。
發現項目以 Category（A–J）分組，附帶檔案與行號參考。

---

## 常見錯誤

### 1. 語言洩漏至儲存資料

**錯誤做法：**
```python
# 將 zh_TW 儲存至排程設定 — 語言切換後會出錯
schedule["type_label"] = t("rpt_email_traffic_subject")
```

**正確做法：**
```python
# 在渲染時使用收件人的語言翻譯，而非 UI 語言
type_label = t("rpt_email_traffic_subject", lang=lang)
```

儲存資料（JSON 設定、規則名稱、資料庫欄位）必須永遠以英文儲存，
於輸出時才進行翻譯。`lang` 參數接受 `"en"` 或 `"zh_TW"`。
測試 `tests/test_report_i18n_leakage.py` 強制執行此模式。

### 2. 缺少 zh_TW 對應鍵

在 `i18n_en.json` 新增鍵但 `i18n_zh_TW.json` 中缺少對應項目，
會導致 Category I 失敗。請務必在同一個 commit 中同時新增兩者。
`tests/test_i18n_strings_parity.py` 也會執行一致性檢查。

### 3. 自行創作 Illumio 術語翻譯

在未查閱 `zh_explicit.json` 的情況下，不得自行翻譯 `Workload`、`PCE`、
`VEN`、`Enforcement Boundary`、`Pairing Profile` 或任何 Illumio 產品概念。
未經授權的翻譯會觸發 Category E 失敗，並可能引入術語不一致問題，
事後修正代價高昂。

若 `zh_explicit.json` 尚未包含該術語，請先在此添加（附上來源參考或團隊確認），
再將其加入 `i18n_zh_TW.json`。

---

## 相關文件

- [i18n 合約（架構）](../architecture/i18n-contract.md) — 底層合約
- [詞彙表](../reference/glossary.md) — Illumio 術語
- [開發環境設定](dev-setup.md) — 先準備好 venv
- [發布流程](release-process.md) — 發布前執行哪些稽核閘門
