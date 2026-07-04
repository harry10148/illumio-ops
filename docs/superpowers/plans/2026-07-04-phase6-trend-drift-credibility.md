# Phase 6：趨勢與 Drift 可信度 Implementation Plan（拆分計劃最終期）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** spec L 節：trend/drift 快照記錄視窗/資料來源/profile 並於不一致時警語（trend）或拒絕比較（drift 視窗不一致）；drift 消失配對過濾雜訊（ICMP/port 0/ephemeral 高 port）並把 `(unlabeled)→(unlabeled)` 配對收合為統計行。

**Architecture:** 中繼資料一律以 `_` 前綴 key 存入既有 payload（compute_deltas 已跳過 `_` 開頭——舊快照天生相容）；一致性檢查只比對「兩份快照都有」的欄位（舊檔缺欄不觸發警語）；L2 過濾在**比較端對稱套用**（產生端過濾會讓既存 12 個含雜訊 baseline 誤判大量假消失——盤點確認的風險）。

**Tech Stack:** Python / pytest。

**Spec:** `docs/superpowers/specs/2026-07-02-traffic-security-report-split-design.md` L 節（2 項）。

## Global Constraints

- 註解繁中、無 emoji；commit 英文 conventional-commits；每 task 一個 commit；surgical；TDD。
- **環境三道防線**：每個 Bash 命令 `cd <worktree 絕對路徑> && ` 開頭；commit 前 rev-parse 驗證、後 log+branch 確認；禁主 checkout 寫操作；**禁 `git add -A`**。
- **舊快照相容鐵律**：讀取端一律 `.get(..., default)`；缺 metadata 欄位 = 不觸發任何警語/拒絕（靜默向後相容）；新欄位 `_` 前綴（trend_store 的 KPI 迭代已跳過）。
- mod_drift 維持純函式（無 I/O）；flow_history/trend_store 的檔案格式向前擴充不破壞舊讀取端。
- i18n 兩 json en/zh 同步、檔尾單一 newline；glossary 合規。
- 定位以程式碼內容為準（行號會漂移）。

## 現況地圖（盤點 @04b4bfb，實作者速查）

| 對象 | 事實 |
|---|---|
| trend_store | payload = `{"_generated_at": ts, **kpi_dict}`（:59）——無 window/source/profile；`compute_deltas`（:82-119）無一致性檢查、跳過 `_` 開頭 key（:94）；`load_previous` 取 files[-2]；profile 區隔僅靠目錄名（traffic_security_risk 等） |
| flow_history | payload = `{"_generated_at": ts, "signatures": [...]}`（:54）；gzip、保留 12 檔；`load_previous_signatures`（:63-80）取 files[-1] 回 `(set, ts)`；簽名 `src_app|dst_app|port|proto`（:31-39）；`UNLABELED = "(unlabeled)"`（:23，帶括號） |
| mod_drift | 純函式（:21-57）；`prev_signatures is None → {"available": False}`；集合差無過濾；回傳 new/disappeared_count（全量）+ 兩 DataFrame（[:top_n]）；disappeared 無 Connections 欄 |
| 產生端 context | `report_generator.export()` :511-533：`_trend_key`/`ts` 可得；**`result.date_range`（tuple start,end）/`result.data_source`（csv/api/cache/mixed）/`traffic_report_profile` 全部可得但未傳入 save**；drift 僅 security_risk 跑（:524）；其他三 generator 同構只存 kpi+ts（ven :138-149、pu :310-322、audit :767-779） |
| 參考 pattern | change-impact snapshot（report_generator.py:636-647）已存 `profile` + `query_window {start,end}`——repo 內現成示範 |
| 渲染端 | trend：`_trend_deltas_section`（html_exporter.py:218-265）——警語插 heading（:221）後；drift：`_mod_drift_html`（:1111-1126）——head 段（:1116-1119）顯示 baseline 時間，拒絕比較 = 以 note 取代 new/disappeared 表 |
| L2 過濾事實 | ICMP proto 字串 "ICMP"/"ICMPv6"（parser 映射）；ICMP/缺 port → 簽名 port 段 "0"；port>0 為全 repo 排除慣例；**ephemeral 界線無先例——新增常數 49152（IANA 動態埠起點）**；過濾必須比較端對稱（見 Architecture） |
| 既有測試 | test_mod_drift.py（count 斷言 :24-25、HTML 內嵌 count 字串 :86——過濾後語意需更新）；test_flow_history.py（簽名字面值）；test_trend_store_canonical.py；test_traffic_report_trend_keying.py |
| i18n | drift 4 key 於兩 json :3043-3046 區塊；新 key 插同區 |

---

### Task 1: Drift 消失配對過濾 + unlabeled 收合（spec L2）

**Files:**
- Modify: `src/report/analysis/mod_drift.py`
- Modify: `src/report/exporters/html_exporter.py`（`_mod_drift_html` 兩表各加統計行）
- Modify: 兩 json（2 新 key）
- Modify: `tests/test_mod_drift.py`（count 語意更新）
- Test: `tests/test_mod_drift_noise_filter.py`（新檔）

**Interfaces（設計裁決，記 commit body）:**
- 過濾在 `baseline_drift` 內對 `current` 與 `prev` **兩集合對稱**套用後才做差集（新舊 baseline 對稱去雜訊，無不對稱誤判）。
- 雜訊判準（模組常數 + 純函式）：
```python
_EPHEMERAL_PORT_MIN = 49152   # IANA 動態/私有埠起點；repo 無既有先例，於此定錨
_NOISE_PROTOS = ("ICMP", "ICMPv6")


def _is_noise_signature(sig: str) -> bool:
    """雜訊簽名（spec L2）：ICMP、port 0、ephemeral 高 port。

    簽名格式 src|dst|port|proto（flow_history.build_signatures）。
    解析失敗的畸形簽名視為雜訊（不進 drift 表）。
    """
    parts = sig.split("|", 3)
    if len(parts) != 4:
        return True
    port, proto = parts[2], parts[3]
    if proto in _NOISE_PROTOS:
        return True
    try:
        port_num = int(port)
    except ValueError:
        return True
    return port_num == 0 or port_num >= _EPHEMERAL_PORT_MIN
```
- `(unlabeled)→(unlabeled)` 收合（**new 與 disappeared 兩側都做**——spec 分號子句未限定側別，對稱處理）：src 段與 dst 段皆等於 `flow_history.UNLABELED` 的簽名不進表格，改計數。
- 回傳 dict 新增：`new_unlabeled_collapsed: int`、`disappeared_unlabeled_collapsed: int`（0 = 不顯示統計行）。
- **count 語意（既有測試更新）**：`new_count`/`disappeared_count` = 過濾後且未收合的有效配對數（表格母體）；收合數另計。
- 渲染：兩表各自在 `<h3>` 後、表格前，`collapsed > 0` 時加一行 `<p class="note">`（i18n `rpt_drift_unlabeled_collapsed`：en "{n} (unlabeled) → (unlabeled) pairs collapsed into this summary line." / zh "{n} 組 (unlabeled) → (unlabeled) 配對已收合為此統計行。"）；過濾行為在 drift head 加一行說明（i18n `rpt_drift_noise_filtered`：en "Noise pairs (ICMP, port 0, ephemeral ports ≥49152) are excluded from drift comparison." / zh "雜訊配對（ICMP、port 0、ephemeral 高 port ≥49152）已排除於漂移比較之外。"）。

- [ ] **Step 1: RED 測試**——`tests/test_mod_drift_noise_filter.py`：fixture prev/current 各含 TCP 正常配對 + ICMP 配對 + port 0 + port 55000 + `(unlabeled)|(unlabeled)|443|TCP`：斷言 (a) 雜訊簽名不進兩表也不進 count；(b) prev 獨有的 ICMP 簽名**不**被報為 disappeared（對稱性的判別測試——這是產生端過濾做不到的）；(c) unlabeled 配對收合計數正確且不在表格；(d) `_is_noise_signature` 單元案例（含畸形簽名）。既有 test_mod_drift.py 的 count 斷言依新語意檢視（fixture 全 TCP 正常配對——應不受影響，驗證後照實記錄）。
- [ ] **Step 2: 確認 FAIL**
- [ ] **Step 3: 實作（GREEN）**——mod_drift 過濾+收合；exporter 兩統計行 + head 說明行；i18n 兩 key。
- [ ] **Step 4: 聚焦 + 全套**：`python3 -m pytest tests/test_mod_drift_noise_filter.py tests/test_mod_drift.py tests/test_flow_history.py -v && python3 -m pytest -q`
- [ ] **Step 5: Commit** `feat(drift): filter noise pairs and collapse unlabeled pairs in comparison`

---

### Task 2: Trend 快照中繼資料 + 不一致警語（spec L1 之 trend）

**Files:**
- Modify: `src/report/trend_store.py`（save_snapshot 吃 meta、新 `snapshot_mismatch` 純函式）
- Modify: `src/report/report_generator.py`（traffic 產生端傳 meta + 計算 mismatch 存 `_trend_mismatch`）
- Modify: `src/report/{audit_generator,policy_usage_generator}.py`（傳可得的 window meta；ven 為時點快照無 window——只傳 profile/source 可得者）
- Modify: `src/report/exporters/html_exporter.py`（`_trend_deltas_section` 警語）
- Modify: 兩 json（警語 key）
- Test: `tests/test_trend_meta.py`（新檔）

**Interfaces:**
- `save_snapshot(report_type, kpi_dict, generated_at, *, meta: dict | None = None)`：meta 以 `_meta` 單一 key 存入 payload（`payload["_meta"] = {"window": {"start","end"}, "data_source", "profile"}`——比照 change-impact 的 query_window pattern；`_` 前綴故 compute_deltas 天生跳過）。
- 新純函式：
```python
def snapshot_mismatch(current_meta: dict | None, previous_payload: dict | None) -> list[dict]:
    """回傳不一致欄位清單 [{"field", "previous", "current"}]。

    只比對兩邊都存在的欄位（舊快照無 _meta → 空清單，靜默相容）。
    window 以天數比較（差 >1 天視為不一致）；data_source/profile 字串不等即不一致。
    """
```
- 產生端：traffic 傳 `meta={"window": {"start": result.date_range[0], "end": result.date_range[1]}, "data_source": result.data_source, "profile": traffic_report_profile}`（date_range 空容錯）；audit/pu 傳各自 window（讀各 export 現場可得的 start/end——實作時確認變數，無則略）；ven 傳 `{"profile": "ven"}` 級最小 meta 或不傳（時點快照）。mismatch 結果存 `result.module_results["_trend_mismatch"]`（比照 `_trend_deltas` 慣例）。
- 渲染：`_trend_deltas_section` 簽名加 `mismatch: list | None = None`，非空時在 heading 後插 `<p class="note note-warn">`（i18n `rpt_trend_mismatch_warning`：en "Comparison caveat: {fields} differ from the previous snapshot — deltas may not be like-for-like." / zh "比較注意：{fields} 與前次快照不一致——差異值可能非同基準比較。"；fields 為欄位名逗號串）。三個包裝呼叫端（traffic/audit/ven）傳入各自 `_trend_mismatch`（.get 容錯）。

- [ ] **Step 1: RED 測試**——`tests/test_trend_meta.py`：(a) save→load roundtrip 含 `_meta`；(b) compute_deltas 對含 `_meta` 的 payload 不把 meta 當 KPI；(c) `snapshot_mismatch`：window 7 天 vs 1 天 → mismatch；同窗 ±1 天內 → 無；cache vs api → mismatch；舊 payload 無 _meta → 空；(d) 渲染級：mismatch 非空時警語出現在 trend 區、空時不出現。
- [ ] **Step 2: 確認 FAIL**
- [ ] **Step 3: 實作（GREEN）**
- [ ] **Step 4: 聚焦 + 全套**：含 test_trend_store_canonical.py、test_traffic_report_trend_keying.py（既有語意零回歸）
- [ ] **Step 5: Commit** `feat(trend): record snapshot window/source/profile and warn on mismatched comparison`

---

### Task 3: Drift baseline 中繼資料 + 視窗不一致拒絕比較（spec L1 之 drift）

**Files:**
- Modify: `src/report/flow_history.py`（save_signatures 吃 meta；新 `load_previous_baseline` 回 `(set, ts, meta)`——保留舊 `load_previous_signatures` 委派以相容）
- Modify: `src/report/analysis/mod_drift.py`（`baseline_drift` 加 `prev_meta`/`current_meta` 可選參數；視窗差 >1 天 → 回 `{"available": True, "comparable": False, "mismatch": [...], "prev_generated_at": ...}` 不做差集；data_source 不一致 → 照常比較但帶 `mismatch` 警語欄）
- Modify: `src/report/report_generator.py`（drift 段傳 meta——與 Task 2 同一組 context）
- Modify: `src/report/exporters/html_exporter.py`（`_mod_drift_html`：`comparable is False` → 拒絕比較 note 取代兩表；有 mismatch 但 comparable → head 加警語——重用 Task 2 的警語 key）
- Modify: 兩 json（拒絕比較 note key）
- Test: `tests/test_drift_meta.py`（新檔）

**Interfaces:**
- flow_history payload 加 `"_meta": {...}`（同 Task 2 形狀）；舊檔 `.get("_meta")` → None → 不觸發任何檢查。
- 拒絕比較 note（i18n `rpt_drift_incomparable`：en "Baseline window differs materially from this run ({prev} vs {curr}) — drift comparison skipped to avoid false disappearances. A fresh baseline has been saved." / zh "前次基準的資料視窗與本次差異過大（{prev} vs {curr}）——已略過漂移比較以避免假性消失，並已存入新基準。"）。
- 拒絕比較時**仍照常 save 本期 baseline**（下次即可比）——產生端順序不變（盤點：先 load/比較後 save，天然滿足）。

- [ ] **Step 1: RED 測試**——(a) roundtrip 含 meta + 舊檔無 meta 相容；(b) baseline_drift：7 天 prev vs 1 天 curr → comparable False、無 new/disappeared key 或空表（形狀決定後鎖定）、mismatch 記 window；同窗 → 照常；cache vs api → comparable True + mismatch 非空；無 meta（舊檔）→ 完全現行行為；(c) 渲染級：comparable False → note 出現且兩表不出現；警語情境 → head 警語。
- [ ] **Step 2: 確認 FAIL**
- [ ] **Step 3: 實作（GREEN）**——注意 `{"available": False}` 首次語意不變；`comparable` 僅在 available True 時出現。
- [ ] **Step 4: 聚焦 + 全套**：含 test_mod_drift.py/test_mod_drift_noise_filter.py（Task 1 疊加零回歸）、test_flow_history.py
- [ ] **Step 5: Commit** `feat(drift): baseline metadata with window-mismatch refusal (spec L1)`

---

### Task 4: 樣本 E2E + CHANGELOG + 手冊（拆分計劃收官）

- [ ] **Step 1: E2E（專案 CLAUDE.md 硬性規則）**——真實管線連續多次 export 驗證：(1) 首次（無 baseline/trend）→ first-run notes；(2) 二次同窗 → drift 兩表 + 過濾說明行 + unlabeled 收合行（fixture 含雜訊與 unlabeled 配對）+ trend deltas 無警語；(3) 三次改窗（date_range 7天→1天）→ drift 拒絕比較 note（兩表消失）+ trend 警語含 window；(4) 舊格式快照（手工去除 _meta）→ 行為與現行完全相同（相容證明）；en/zh 各驗、零裸 key、逐頁截斷檢查。
- [ ] **Step 2: 回歸**——全套 + naive-datetime。
- [ ] **Step 3: CHANGELOG（L1/L2 兩點）+ 手冊 en/zh（drift/trend 章描述同步）**。**加一段拆分計劃收官註記**：spec（2026-07-02）六期全數交付（Phase 1-6 + XLSX 統一）——記入 CHANGELOG 條目結尾一句即可，勿誇大。
- [ ] **Step 4: Commit** `docs: document trend/drift credibility hardening (phase 6)`

---

## Self-Review 檢核

1. **Spec 覆蓋**：L1 → Task 2（trend 警語）+ Task 3（drift 拒絕比較/警語）；L2 → Task 1。拆分 spec 至此全數交付。
2. **相依**：Task 1 獨立先行；Task 3 依賴 Task 2 的 meta 形狀與警語 key（按序）；Task 4 收尾。
3. **相容鐵律可驗證**：每 task 都有「舊檔無 meta → 現行為」的測試；E2E 第 4 點做整合級相容證明。
4. **對稱過濾的判別測試**：Task 1 Step 1(b) 是核心——prev 獨有雜訊不得成為 disappeared。
5. **count 語意變更明列**：Task 1 的 count 改為過濾後有效配對（記 commit body），既有斷言逐一檢視。
