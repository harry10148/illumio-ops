# 頻寬計算基準 — 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把頻寬的分母從硬編的 600 秒換成 flow 的實際觀測時距，並讓「算不出速率」成為一個明說的狀態，而不是一個看起來像量測值的 0。

**Architecture:** 核心是 `calculate_mbps` 的回傳契約從「一律給數字」變成三態：點值／下界／不可得。`note` 字串承載這個區分——它在本 codebase 裡**已經是有作用的欄位**（`_basis_decision` 以 `bw_note == "(Interval)"` 決定量測基準），不是純顯示。三態確立後，呼叫端各自決定行為：告警比對門檻、查詢與報表決定怎麼呈現。

**Tech Stack:** Python 3.12、pytest、pandas（報表 parser）

**Spec:** `docs/superpowers/specs/2026-08-23-bandwidth-basis-design.md`

## Global Constraints

- **統一公式**：一律回報 `≥ (dst_bo + dst_bi) × 8 ÷ (span + 1)`，其中 span 為
  `last_detected − first_detected` 的秒數。span 夠大時下界與點值在顯示精度內重合，
  `span == 0` 不是特例。時間戳為秒解析度，真實時距 ∈ (span−1, span+1)，故 `span+1` 是
  可證明的下界分母。
- **`ddms`/`tdms` 存在時走原路徑不變**（syslog／fluentd 來源、帶該欄位的 CSV）。那是真實
  持續時間，優於估計。
- **`bytes == 0` 一律視為「速率不可得」，不試圖分辨成因**。async query 的欄位永遠存在且
  為 0，沒有任何欄位能區分「未量測」與「量測到零」；`state` 已實測否證（兩環境 `snapshot`
  差八倍），**不得用它判斷**。
- **不得靜默當 0**：0 永遠小於任何正門檻，等於規則悄悄失效。不可得必須走守門並計數。
- **下界 `>=` 門檻即觸發**：真實速率嚴格大於下界，故相等時真值必定超過門檻。寫 `>` 會製造
  一個可確定判斷卻故意漏掉的告警。
- `calculate_volume_mb` 的**分母**不動（它沒有分母），但「零 vs 不可得」的混淆同類，見 Task 4。
- 新的使用者可見文案進三份字典，不得提及端點、狀態碼或內部欄位名。
- 前景執行測試並帶 timeout。**不要跑全套**——orchestrator 在任務之間自己跑。

---

### Task 1: `calculate_mbps` 的三態回傳

**Files:**
- Modify: `src/analyzer.py`（`calculate_mbps` 於 `:286`；note 常數見 `:306,312,318`）
- Test: `tests/test_analyzer.py`（既有；`:28` 有 `calculate_mbps` 的既有測試，先讀）

**Interfaces:**
- Produces: `calculate_mbps(flow) -> (val, note, bytes, denom)`，其中
  `val is None` ＝不可得；`note` 為 `"(Interval)"` / `"(Avg)"` / `BOUND_NOTE` / `""`
- Consumes: `flow_aggregation_start` 既有的雙位置時間戳讀法（頂層與巢狀 `timestamp_range`）

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_analyzer.py` 加測試。先讀 `:20-40` 既有的 `calculate_mbps` 測試照其風格：

- 有 `ddms` 且 delta bytes > 0 → 走 Priority-1，note 為 `"(Interval)"`，值不變（既有行為）
- 有 `tdms`（無 ddms）→ 走 Priority-2 真實分母，note 為 `"(Avg)"`
- 無 `ddms`/`tdms`，`timestamp_range` 跨 214848 秒、bytes 13248009806581
  → 值約 493 Mbps（非 176640），note 為下界標記
- 無 `ddms`/`tdms`，`first_detected == last_detected` → 分母為 1 秒，note 為下界標記
- bytes 為 0 → `val is None`，note 為 `""`
- 時間戳缺漏 → `val is None`
- 巢狀 `timestamp_range` 與頂層 `first_detected`/`last_detected` 兩種形狀都認

**守門測試**（比照 `tests/test_config_models.py:131` 的集合斷言風格，非子字串）：

```python
def test_calculate_mbps_no_longer_assumes_a_sampling_interval():
    """600 秒是 PCE interval_sec 的文件預設值，但該欄位不在 async query 的回傳裡，
    所以它曾是唯一會用到的分母。任何一個重新出現都代表假分母回來了。"""
    import inspect, re
    from src import analyzer
    src = inspect.getsource(analyzer.calculate_mbps)
    banned = {"interval_sec", "600"}
    found = {b for b in banned if re.search(r"\b%s\b" % re.escape(b), src)}
    assert found == set(), f"assumed-denominator tokens are back: {found}"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 600 ./venv/bin/python -m pytest tests/test_analyzer.py -q -p no:randomly -k "mbps"`
Expected: FAIL — 現行實作回 176640 且 `interval_sec`/600 仍在原始碼中

- [ ] **Step 3: 實作**

在 `src/analyzer.py` 的 note 常數區（`DELTA_BASIS_NOTE` 附近）新增：

```python
# 速率為下界而非點值：時間戳只有秒解析度，真實時距 ∈ (span−1, span+1)，
# 因此 bytes ÷ (span+1) 是可證明為真的下限。呼叫端據此以「≥」呈現，
# 告警則在「下界 >= 門檻」時即可確定觸發（真值嚴格更大）。
BOUND_BASIS_NOTE = "(>=)"
```

改寫 `calculate_mbps` 的 Priority-2 分支：`tdms` 欄位存在且 > 0 時維持現行行為（note `"(Avg)"`）；
否則由 flow 的時間戳求 span——讀法**必須比照 `flow_aggregation_start`**（頂層與巢狀
`timestamp_range` 兩處都認），以 `span + 1` 為分母、note 為 `BOUND_BASIS_NOTE`。
`total_bytes <= 0` 或時間戳無法解析 → 回 `(None, "", 0.0, 0.0)`。
**移除** `flow.get("interval_sec", 600)` 與 `"(Avg est.)"`。

- [ ] **Step 4: 測試通過**

Run: `timeout 600 ./venv/bin/python -m pytest tests/test_analyzer.py -q -p no:randomly`

- [ ] **Step 5: Commit**

```bash
git add src/analyzer.py tests/test_analyzer.py
git commit -m "fix(analyzer): measure bandwidth against the flow's own span, not an assumed interval"
```

---

### Task 2: 告警與規則模擬的三分支

**Files:**
- Modify: `src/analyzer.py`（告警引擎 `:1726` 起、`_basis_decision` `:1636`、規則模擬 `:2718`）
- Test: `tests/test_analyzer_bucket_basis_guard.py`（**既有**，已測守門的抑制與計數回報，見其 `test_short_window_rule_is_suppressed_and_warns` / `test_suppression_is_recorded_for_the_operator_facing_stats`——新測試加在同檔，沿用其 fixture）

**Interfaces:**
- Consumes: Task 1 的三態回傳與 `BOUND_BASIS_NOTE`

- [ ] **Step 1: 寫失敗測試**

三條，各對應 spec §3 的一個分支：

- 點值且大於門檻 → 觸發
- **下界恰等於門檻 → 觸發**（真值嚴格大於下界；寫 `>` 會漏報）
- 下界小於門檻 → 不觸發，且**進守門並計數**（不得當成「評估後未達標」）
- `val is None`（不可得）→ 進守門並計數，**不得**被當成 0 評估

守門的計數與回報沿用既有的 `info["reasons"]` 機制（`analyzer.py:1770-1775`），
新增一個 reason 名稱；不要另建第二套計數。

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 900 ./venv/bin/python -m pytest tests/test_analyzer_bucket_basis_guard.py -q -p no:randomly`

- [ ] **Step 3: 實作**

**先確認一件事再動手**：`_basis_decision`（`:1636`）以 `bw_note == "(Interval)"` 判斷
`interval_scoped`。新的 note 值都不等於 `"(Interval)"`，所以它們會落到「嘗試視窗增量、
不成則守門」那條路——**這正是我們要的行為**，該行不需要改。動它之前先確認你的理解與此一致。

告警引擎（`:1726` 起）與規則模擬（`:2718` 起）各自加入三分支。兩處**必須同基準**——
該處註解已載明模擬與引擎不可分歧。

- [ ] **Step 4: 測試通過**

```bash
timeout 900 ./venv/bin/python -m pytest tests/test_analyzer_bucket_basis_guard.py tests/test_analyzer.py -q -p no:randomly
```

- [ ] **Step 5: Commit**

```bash
git add src/analyzer.py tests/test_analyzer_bucket_basis_guard.py
git commit -m "fix(alerts): fire on a lower bound that clears the threshold, guard when it cannot"
```

---

### Task 3: 查詢、報表 parser 與顯示

**Files:**
- Modify: `src/analyzer.py`（`_shape_traffic_row` 於 `:2224`）、`src/cli/_render.py`（`format_unit` `:326`）、`src/report/parsers/api_parser.py`（`:57`）、`src/report/parsers/csv_parser.py`（`_estimate_bandwidth` `:301`）
- Modify: 三份 i18n 字典
- Test: `tests/test_bandwidth_basis_parsers.py`（**新建**——本 repo 沒有 parser 專用測試檔，`grep -rln "csv_parser\|api_parser" tests/` 只命中間接使用者）、`tests/test_traffic_data_source.py`（既有）

**Interfaces:**
- Consumes: Task 1 的三態

- [ ] **Step 1: 寫失敗測試**

- `_shape_traffic_row` 收到 `bw_val=None` 時**不寫入** `max_bandwidth_mbps`/`formatted_bandwidth`
  （此行為 2F-1 已實作，加測試釘住它，防止本案改壞）
- 下界列的 `formatted_bandwidth` 帶「≥」前綴，且與同值的點值列可區分
- `format_unit(0, 'bandwidth')` 目前回 `"0.00 Mbps"`——新增：`None` 回 `—`
- `csv_parser._estimate_bandwidth`：`clip(lower=1)` 移除，改為 `span + 1`；
  時間戳缺漏回 `NaN`（`_fmt_bw` 已將 NaN render 為 `—`）
- **跨 parser 一致性**：同一筆 flow 分別經 `api_parser` 與 `csv_parser`，
  `bandwidth_mbps` 必須相等（目前兩者定義不同，差距可達數百倍）

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 900 ./venv/bin/python -m pytest tests/test_bandwidth_basis_parsers.py tests/test_traffic_data_source.py -q -p no:randomly`

- [ ] **Step 3: 實作**

依 Step 1 各條。新 i18n 鍵（三份字典）：頻寬不可得時的顯示字串、以及下界的「≥」前綴
若需獨立鍵。文案不得出現「counter」「EDC」等內部詞彙——對操作者說的是「這筆流量沒有可用的
速率資料」。

- [ ] **Step 4: 測試通過**

```bash
timeout 900 ./venv/bin/python -m pytest tests/test_bandwidth_basis_parsers.py tests/test_traffic_data_source.py tests/test_v2_investigate_e2e.py -q -p no:randomly
timeout 300 ./venv/bin/python scripts/audit_i18n_usage.py
timeout 300 ./venv/bin/python -m pytest tests/test_i18n_no_reviewer_copy.py tests/test_i18n_zh_explicit_sync.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/analyzer.py src/cli/_render.py src/report/parsers/api_parser.py src/report/parsers/csv_parser.py src/i18n_zh_TW.json src/i18n_en.json src/i18n/data/zh_explicit.json tests/
git commit -m "fix(reports): give the two parsers one bandwidth definition, and show an unavailable rate as such"
```

---

### Task 4: 報表統計與 volume 的「零 vs 不可得」

**Files:**
- Modify: `src/report/analysis/mod11_bandwidth.py`（`bandwidth_analysis` `:6`）、`src/report/rules_engine.py`（`_b008_bandwidth_anomaly` `:538`）
- Test: `tests/test_bandwidth_basis_analysis.py`（**新建**——`bandwidth_analysis` 與 `_b008` 目前無專用測試，只被 `test_phase11_chart_coverage.py` 與 `test_report_i18n_leakage.py` 間接觸及，不要改那兩個檔的既有斷言）

**Interfaces:**
- Consumes: Task 3 的 parser 輸出

- [ ] **Step 1: 寫失敗測試**

- `bandwidth_analysis` 的 max / mean / P95：當輸入含下界列時，統計量本身也不是點值，
  結果須標明；`top_bandwidth` 不得把下界列當點值排序後無標記呈現
- 不可得（NaN）的列不參與統計，且統計結果須帶「N 筆無速率資料」的計數
- `_b008_bandwidth_anomaly` 實際運算對象是 `bytes_total` 的百分位數——**那是總量異常，
  不是頻寬異常**。rule_name 與文案改為反映實際運算對象；`rule_id` `B008` 不變（外部可能已引用）

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 900 ./venv/bin/python -m pytest tests/test_bandwidth_basis_analysis.py -q -p no:randomly`

- [ ] **Step 3: 實作**

依 Step 1。文案改動走三份字典與 `src/report/exporters/report_i18n.py`（先確認該檔是否
為報表文案的來源）。

- [ ] **Step 4: 測試通過**

```bash
timeout 900 ./venv/bin/python -m pytest tests/test_bandwidth_basis_analysis.py tests/test_phase11_chart_coverage.py tests/test_report_i18n_leakage.py -q -p no:randomly
```

- [ ] **Step 5: Commit**

```bash
git add src/report/ tests/ src/i18n_zh_TW.json src/i18n_en.json src/i18n/data/zh_explicit.json
git commit -m "fix(reports): stop presenting statistics over lower bounds as point values"
```

---

### Task 5: 門檻遷移比對表（交付物）

**Files:**
- Create: `scripts/bandwidth_basis_diff.py`
- Test: `tests/test_bandwidth_basis_diff.py`

**Interfaces:**
- Consumes: Task 1 的新 `calculate_mbps`

- [ ] **Step 1: 寫失敗測試**

腳本以唯讀方式開 cache DB，對每一列同時算「舊分母（600 秒）」與「新分母（span+1）」，
依既有的 bandwidth 規則門檻輸出比對表。測試以合成資料驅動，斷言：

- 輸出含每條規則的舊 `max_val` 與新 `max_val`
- 標明哪些規則的觸發狀態會改變（舊觸發→新不觸發、或反之）
- 統計因「不可得」而未評估的 flow 筆數
- 腳本**不寫入任何檔案、不修改 DB**（以唯讀 URI 開啟）

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 600 ./venv/bin/python -m pytest tests/test_bandwidth_basis_diff.py -q -p no:randomly`

- [ ] **Step 3: 實作**

`scripts/bandwidth_basis_diff.py`，接受 `--db` 與 `--json`。舊分母的算法逐字寫在腳本裡
（不要保留舊程式碼在 `analyzer.py` 只為了這支腳本用）。

- [ ] **Step 4: 測試通過 + 真機產出**

```bash
timeout 600 ./venv/bin/python -m pytest tests/test_bandwidth_basis_diff.py -q -p no:randomly
```

真機產出由 orchestrator 執行（需 ssh 至測試機），結果附進交付回報。

- [ ] **Step 5: Commit**

```bash
git add scripts/bandwidth_basis_diff.py tests/test_bandwidth_basis_diff.py
git commit -m "feat(scripts): compare alert thresholds across the old and new bandwidth basis"
```

---

### Task 6: 文件與 CHANGELOG

**Files:**
- Modify: `docs/reference/traffic-metrics.md`、`CHANGELOG.md`

- [ ] **Step 1: 文件**

`traffic-metrics.md` 的 §5.2 從「目前的數字沒有物理意義」改為描述新行為，§7 的總結一併更新；
§6.3 的驗證區塊改為驗證新舊差異（該檔的原則是每個宣稱都附可重跑的指令，維持之）。
`last_verified` 更新為執行當日。

`CHANGELOG.md` 的 `### Fixed` 記本案，照既有條目的散文語氣：說明舊數字為何錯、新數字的
語意、以及**操作者必須重新檢視 bandwidth 規則的門檻**。

- [ ] **Step 2: 閘門通過**

```bash
timeout 300 ./venv/bin/python -m pytest tests/test_docs_check.py -q -p no:randomly
timeout 300 ./venv/bin/python scripts/docs_check.py --all
timeout 300 ./venv/bin/python scripts/check_doc_links.py
```

- [ ] **Step 3: Commit**

```bash
git add docs/reference/traffic-metrics.md CHANGELOG.md
git commit -m "docs: record the bandwidth basis change and its effect on thresholds"
```

---

## 自我檢查（撰寫時已執行）

- **Spec 覆蓋**：§3 統一公式→T1；三分支→T2；§4.1 `calculate_mbps`→T1；§4.2 呼叫端表
  →T2（告警／模擬）、T3（查詢／parser）、T4（dashboard 排序併入 T3 的顯示層）；
  §4.3 三態顯示→T3；§4.4 遷移比對表→T5；§4.5 B008 命名→T4；§5 測試→逐條對應；
  附錄 A.1 三條修正（門檻相等、統一下界、報表統計）→T2、T1、T4。
- **符號查證**：`calculate_mbps` `analyzer.py:286`；`_basis_decision` 的
  `bw_note == "(Interval)"` 於 `:1636`；告警引擎 `:1726`；`_shape_traffic_row` `:2224`；
  規則模擬 `:2718`；`format_unit` `_render.py:326`；`_fmt_bw` `html_exporter.py:122`
  （已處理 NaN → `—`）；`_estimate_bandwidth` `csv_parser.py:301`；
  `_b008_bandwidth_anomaly` `rules_engine.py:538`。
- **已知風險**：note 字串是有作用的欄位（`_basis_decision` 比對它），T2 Step 3 已明文
  要求實作者先確認理解再動手。
- **測試檔歸屬已查證**：Task 2 用既有的 `tests/test_analyzer_bucket_basis_guard.py`
  （該檔已在測守門的抑制與計數回報，正是本案的行為）；Task 3、4 各新建一個檔——
  本 repo 沒有 parser 或 `mod11` 的專用測試檔，`bandwidth_analysis`/`_b008` 只被
  `test_phase11_chart_coverage.py` 與 `test_report_i18n_leakage.py` 間接觸及，
  **不要改那兩個檔的既有斷言**。

## 本計畫不處理

- **告警門檻的實際數值**：由使用者依 T5 的比對表重設
- **改用 syslog／fluentd 取得 `ddms`/`tdms`**：資料管線變更，範圍遠大於本案
- **`WindowDelta` 在真機上覆蓋率過低**（obs 表只追蹤少量 flow）：獨立議題
- **PCE 端的資料可得性**（Enhanced Data Collection 是否開啟）
