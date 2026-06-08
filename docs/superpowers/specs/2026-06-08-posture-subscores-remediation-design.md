# 設計：態勢分數「具名子分數 + 影響式修補清單」

- **日期**：2026-06-08
- **範圍代號**：P1（借鏡 alexgoller/illumio-plugger 系列的優化規劃，第一項）
- **狀態**：設計待實作（spec → writing-plans）

## 1. 背景與方向

調查 alexgoller/illumio-plugger 生態（pce-posture-report、ai-security-report 等）後確認：illumio-ops 的態勢計分 `src/report/posture.py` 其實**比對方更成熟**——已有 0-100 加權分數（`coverage×0.3 + readiness×0.3 + risk_health×0.4`）、缺項自動重新正規化權重、透明 breakdown、dashboard「如何計算」modal。

因此本 spec 的方向是**優化既有系統的可行動性，而非疊加對外宣稱的合規框架對映層**（合規對映已否決）。借鏡 ai-security-report 的兩個概念——「具名分項計分」與「優先修補清單」——但**完全建立在 `posture.py` 既有輸出之上，零新增 PCE 資料蒐集、零外部依賴（維持氣隙友善）**。

本 spec 只含兩項，皆為純衍生：

- **D — risk_health 具名子分數**：把既有罰分公式換算成三個 0-100 子分數。
- **B — 分數影響式修補清單**：把 breakdown 反推成「先修哪項、各能拉幾分」的排序清單。

明確排除（YAGNI）：per-scope/環境 heatmap（留 P1.5）、態勢分數趨勢化（C）、合規框架對映、LLM 敘述、新獨立報表模組。

## 2. 現況（不得破壞）

- `compute_posture(kpis: dict) -> dict`（`src/report/posture.py:57`）為**純函式（無 I/O）**，回傳 `{score, available, formula, components}`。
- `risk_health` component（`posture.py:213-230`）目前帶 `detail`：
  ```json
  "detail": {"ransomware_apps": 12, "lateral_control_ratio": 0.65,
             "uncovered_pct": 18.0, "penalty": 37.0}
  ```
  其中 `penalty` 是三軸罰分加總；逐軸的 `ransomware_pts / lateral_pts / uncovered_pts` 在函式內部已計算，但**只暴露加總、逐軸值被丟棄**。
- 既有罰分公式（`posture.py` docstring 行 22-35）：
  - `ransomware_pts = min(40, ransomware_apps × 5)`（上限 40）
  - `lateral_pts = round((1 − lateral_control_ratio) × 30)`（上限 30）
  - `uncovered_pts = min(30, uncovered_pct × 0.5)`（上限 30）
  - `penalty = min(100, 三者和)`；`risk_health = max(0, 100 − penalty)`
- 消費端有兩處，皆須保持相容：
  - `src/gui/routes/dashboard.py:195`（即時 dashboard「如何計算」modal）
  - `src/scheduler/jobs.py:258`（排程報表/email 的 posture 區塊）
- 既有可重用資產：`src/report/analysis/attack_posture.py` 的 `RECOMMENDATION_TEMPLATES`（行 41）與 `resolve_recommendation(code, lang)`（行 145）；R01–R05 規則各自的 `rule_rNN_rec` i18n key。

## 3. D — risk_health 具名子分數

### 3.1 行為

`compute_posture` 的 risk_health component **新增** `risk_subscores` 欄位（不動 `score`/`components`/`formula`/既有 `detail`，純擴充）。三個子分數皆為「遏制度」語意，0-100、越高越好：

| key | 換算公式 | 對應上限罰分 |
|---|---|---|
| `ransomware_containment` | `round(100 × (1 − ransomware_pts/40))` | 40 |
| `lateral_containment` | `round(100 × (1 − lateral_pts/30))` | 30 |
| `flow_coverage` | `round(100 × (1 − uncovered_pts/30))` | 30 |

每筆結構：
```json
{
  "key": "ransomware_containment",
  "label_key": "gui_posture_sub_ransomware",
  "value": 0,
  "unit": "%",
  "penalty_points": 40,
  "max_penalty": 40
}
```

### 3.2 與既有 `detail` 的差異（避免誤判為換名）

1. **單位統一**：`detail` 混用數量/比率/百分比，彼此不可比；子分數統一為可比的 0-100 遏制尺標。
2. **暴露逐軸罰分**：`penalty_points` 是目前被丟棄的逐軸成本；`detail` 只有加總 `penalty`。
3. **B 的前提**：B 的排序數學需要逐軸 `penalty_points`，僅靠 `detail` 無法推導。

### 3.3 邊界

- 若某軸訊號缺失（對應 raw 值為 None），該子分數**不輸出**（與既有 component 缺項處理一致），不得以 0 或 100 假填。
- `detail` 維持原樣輸出（向後相容）。

## 4. B — 分數影響式修補清單

### 4.1 介面

新模組 `src/report/posture_advisor.py`，純函式：

```python
def build_remediation(posture: dict, lang: str = "en") -> list[dict]:
    """純衍生：吃 compute_posture() 輸出，回傳依可回收分數排序的修補清單。"""
```

每筆：
```json
{
  "key": "ransomware_containment",
  "label_key": "gui_posture_sub_ransomware",
  "recoverable_points": 6.8,
  "current": 0,
  "target": 100,
  "recommendation_key": "...",
  "evidence_key": "...",
  "evidence_args": {"count": 12}
}
```

### 4.2 `recoverable_points` 計算（含權重重新正規化）

「把該項補到 target，整體 posture `score` 大約能上升幾分」。需用 `compute_posture` 已算出的 `effective_weight`：

- **coverage 缺口**：`eff_cov × (100 − coverage_value)`
- **readiness 缺口**：`eff_rdy × (100 − readiness_value)`
- **risk 子分數缺口**（每軸一筆）：`eff_rsk × penalty_points`
  （risk_health 直接等於 `100 − Σpenalty_points`，故補滿某軸 = risk_health +該軸 penalty_points = 整體 +`eff_rsk × penalty_points`。）

排序：`recoverable_points` 由大到小。`recoverable_points` 四捨五入到小數 1 位。`recoverable_points ≤ 0` 的項目（已達標）不列入。

### 4.3 建議與佐證文字

- `recommendation_key` 優先重用既有 key：risk 三軸對映既有規則建議 / `attack_posture.resolve_recommendation` 模板；coverage/readiness 用對應的 `gui_posture_*` 建議 key。
- `evidence_key` + `evidence_args` 走 `t(key, **args, lang=lang)`，例如 ransomware 軸帶 `ransomware_apps` 數量。
- 本函式**回傳 key 與 args，不在內部渲染最終字串**（呈現端自行 `t()`，與 request-scoped i18n 規範一致）。

## 5. 落點（重用既有渲染，不新建報表）

posture 已同時出現在兩處既有渲染，B+D 接在原處：

1. **GUI dashboard「如何計算」modal**（`dashboard.py:195` 消費端）：原 component 表下方新增「風險子分數」小表（D）+「優先修補（Top N）」清單（B）。
2. **排程報表 / email 的 posture 區塊**（`scheduler/jobs.py:258` 消費端）：同樣帶入子分數與修補清單。

不新增獨立報表模組、不新增 CLI 子命令、不新增蒐集流程。

## 6. i18n

- 子分數 label：`gui_posture_sub_ransomware`、`gui_posture_sub_lateral`、`gui_posture_sub_coverage`。
- 修補清單建議/佐證：沿用 `gui_posture_` 前綴新增所需 key。
- EN 與 ZH_TW 雙檔同步補齊；遵守 glossary preserve-list（Ransomware 等術語不譯）；新增後跑 `python scripts/audit_i18n_usage.py` 驗證 parity。

## 7. 測試

- **D 子分數換算**：表格驅動，給定 raw 輸入 → 預期三軸 0-100 值（含上限飽和、缺項不輸出）。
- **B 排序數學**：合成 posture 輸出 → 預期 `recoverable_points` 數值與排序；驗證權重重新正規化（缺某 component 時 eff_weight 變動後數值正確）；已達標項不列入。
- **向後相容**：`compute_posture` 既有鍵 `score`/`components`/`formula`/`detail` 不變；兩消費端不破。
- **i18n parity**：新 key EN/ZH_TW 齊備且通過 audit。

## 8. 風險與緩解

- *風險*：改動 `compute_posture` 影響兩消費端 → *緩解*：僅新增欄位、不改既有鍵；以向後相容測試把關。
- *風險*：`recoverable_points` 因權重重新正規化算錯給出誤導建議 → *緩解*：直接重用函式內既有 `effective_weight`，並以表格驅動測試覆蓋缺項情境。

## 9. 後續（不在本 spec）

- P1.5：per-scope（environment/app label）態勢 heatmap。
- C：態勢分數趨勢化 + 退步告警（重用 `trend_store`）。
- P2–P5：Policy Diff、Policy Resolver、Teams 告警連接器、AI 輔助規則建議（各自獨立 spec）。
