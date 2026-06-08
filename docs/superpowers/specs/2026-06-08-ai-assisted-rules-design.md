# 設計：AI 輔助規則建議（heuristic core + 可選 LLM enrich）

- **日期**：2026-06-08
- **範圍代號**：P5（借鏡 alexgoller/illumio-plugger 系列的優化規劃，第五項）
- **狀態**：設計待實作（spec → writing-plans）

## 1. 背景與方向

PCE 的 Explorer 流量裡帶有 **blocked / potentially_blocked** 的決策。維運者要把這些「被擋或可能被擋」的流量轉成「該不該開的 allow rule」時，目前完全靠人工：逐筆看 src/dst/port/proto、判斷哪些是合理依賴、再手動寫規則。

本功能把這個分析自動化成**建議（recommendation only）**：

- 吃一批 blocked / potentially_blocked 流量記錄 → 依 `src_label / dst_label / port / proto` 分組 → 產出**最小 allow-rule 候選**，每筆帶 heuristic 的 **confidence / risk 分數**與**rationale code**（佐證理由），輸出成報表（HTML + CSV）。
- **核心是 heuristic engine，零外部相依、air-gap 安全、永遠可用、完全 deterministic**。
- **可選的 LLM 層**（Ollama / OpenAI / Anthropic）用來「**豐富**」heuristic 既有結果的說明文字，**預設停用**（`provider="none"`）。heuristic 結果本身必須完整、可單獨交付。

### 1.1 安全與非破壞性（硬性約束）

- **只建議、永不套用**：本功能**不會**呼叫任何 provision / create-rule API，不寫入 `config["rules"]`，不觸碰 `alerts.json`。輸出僅是報表與候選清單。報表頁與 CLI 輸出都必須明示「這些是建議，未在 PCE 上佈署任何規則」。
- **預設 100% 離線**：`provider="none"` 時**任何路徑都不得發出網路請求**。LLM 只有在使用者於 `config.json` 明確設定非 `none` 的 provider 時才會被呼叫。此約束以測試強制（§7，`test_null_provider_makes_no_network_call`）。
- **secret 不入 log**：`api_key` 屬於 secret，沿用 repo lesson **L-12**（曾因 log 洩漏 token → 一律 redact）。`src/config.py` 既有 `_SECRET_FIELD_TOKENS = {"key","secret","password","secret_key","token"}` 與 `_format_error_input()` 已可遮蔽含 `key` 的欄位；本 spec 的欄位命名為 `api_key`（含 `key`）即自動命中既有遮蔽，且 provider 層**禁止**將 config 整包或 `api_key` 寫入 `logger`。

## 2. 現況（不得破壞）

- **流量決策編碼**：`src/analyzer.py::check_flow_match`（~256-266）已是 canonical 解碼邏輯——
  ```python
  p = f.get("pd")
  raw_dec = str(f.get("policy_decision", "")).lower()
  flow_pd = -1
  if p is not None:                                   flow_pd = int(p)
  elif "blocked" in raw_dec and "potentially" not in raw_dec: flow_pd = 2   # blocked
  elif "potentially" in raw_dec:                      flow_pd = 1            # potentially_blocked
  elif "allowed" in raw_dec:                          flow_pd = 0           # allowed
  ```
  → **本 spec 直接重用同一套對映**（blocked=2、potentially_blocked=1、allowed=0），不另立常數。
- **流量記錄形狀**（`check_flow_match` 消費的欄位）：
  - 標籤在 `f["src"]` / `f["dst"]` 的 dict（透過 `_check_flow_labels` 取 key→value）。
  - port 在 `f.get("dst_port")` 或 `f["service"]["port"]`。
  - proto 在 `f.get("proto")` 或 `f["service"]["proto"]`（數值，如 6=TCP、17=UDP）。
  - rule dict 形狀：`{pd, port, proto, src_label, dst_label, src_ip_in, dst_ip_in, ...}`（`check_flow_match` 各條件）。**heuristic 產出的候選規則沿用同一 dict 形狀**，以便日後可被 `check_flow_match` 直接驗證。
- **blocked 流量來源**（兩條，皆已存在、皆不改）：
  - 線上：`src/api/traffic_query.py::fetch_traffic_for_report(start, end, policy_decisions=["blocked","potentially_blocked","allowed"], filters)`。
  - 離線快取：`src/pce_cache/reader.py::CacheReader.read_flows_agg(start, end)`（回傳 `{bucket_day, src_workload, dst_workload, port, protocol, action, flow_count, bytes_total}`）與 `read_flows_raw(start, end)`（回傳原始 flow dict）。
- **可重用資產**：
  - `src/report/analysis/attack_posture.py::RECOMMENDATION_TEMPLATES`（行 41）+ `resolve_recommendation(code, lang="en")`（行 145）——deterministic rationale 模板的 pattern（`{code: {"en":..., "zh_TW":...}}`，缺 code 回 fallback、缺 lang 回 `en`）。
  - `src/report/security_risk_report.py`——report facade 形狀：`class X: __init__(self, cm, api_client=None, config_dir="config", cache_reader=None)` + `run(output_dir="reports", lang="en") -> str`。
  - `src/report/exporters/csv_exporter.py::CsvExporter(results: dict, report_label="Traffic").export(output_dir="reports") -> str`（stdlib-only、零相依、走 `module_results` 內的 DataFrame）。
  - `src/report/exporters/html_exporter.py`——自含式 HTML（內嵌 CSS、語言切換、`render_df_table`）。
- **config**：`src/config_models.py` 為 pydantic v2，root `ConfigSchema(_Base)`（行 309）。`_Base` 為 `extra="forbid"`。`_DEFAULT_CONFIG`（`src/config.py:49`）須與 schema 同步新增同名 key。

## 3. A — Heuristic 核心（純函式、deterministic、零相依）

新模組 `src/report/analysis/rule_suggester.py`。

### 3.1 介面

```python
def suggest_rules(flows: list[dict], *, min_pd: int = 1) -> list[dict]:
    """純衍生：吃 blocked/potentially_blocked 流量記錄，回傳依分數排序的 allow-rule 候選。

    - 無 I/O、無網路、deterministic。
    - min_pd=1 表示納入 potentially_blocked(1) 與 blocked(2)；min_pd=2 只看 blocked。
    """
```

### 3.2 行為

1. **解碼 + 過濾**：對每筆 flow 用與 `check_flow_match` 相同的規則算出 `flow_pd`（blocked=2 / potentially_blocked=1 / allowed=0 / 未知=-1），只保留 `flow_pd >= min_pd`。
2. **正規化身分**：抽出 `src_label`（`src` 的 `role`/`app`/`env` 任一可用標籤，缺則 `unlabeled`）、`dst_label`、`port`（int）、`proto`（int）。
3. **分組**：以 `(src_label, dst_label, port, proto)` 為 group key 聚合；累計 `flow_count`（優先用 agg 的 `flow_count`，raw 則計 1）與 distinct 流量筆數。
4. **每組產生一筆候選**（最小 allow rule，沿用 rule dict 形狀）：
   ```json
   {
     "src_label": "role:web",
     "dst_label": "role:db",
     "port": 3306,
     "proto": 6,
     "pd": 0,
     "observed_flows": 42,
     "observed_blocked": 30,
     "observed_potentially": 12,
     "confidence": 0.78,
     "risk": "medium",
     "rationale_code": "WELL_KNOWN_DB_PORT",
     "rationale_args": {"port": 3306}
   }
   ```
5. **confidence（0..1，deterministic）**：以觀測量為主——`confidence = round(min(1.0, observed_flows / 50.0), 2)`（量越大越像穩定依賴）。**不引入隨機性、不引入時間相依**。
6. **risk（low/medium/high，deterministic）**：以 port 風險決定——高風險 port（如 22/3389/445/135/23）→ `high`；已知服務 port（如 3306/5432/443/80/53）→ `low`；其餘 → `medium`。風險越高，越提醒人工審查（**不是**越推薦）。
7. **rationale_code**：deterministic 對映（見 §4），讓報表端 `resolve_rule_rationale(code, lang)` 取出說明文字。
8. **排序**：`(risk 由高到低, confidence 由高到低, src_label, dst_label, port, proto)`——**固定且可重現**（與 `attack_posture.rank_posture_items` 同精神）。

### 3.3 邊界

- 空輸入 → 回 `[]`。
- 同一 group 同時有 blocked 與 potentially_blocked → 合併為一筆，`observed_blocked` / `observed_potentially` 分計。
- port/proto 無法轉 int → 該 flow 跳過（不丟例外）。
- **此函式不做 i18n**：只回 `rationale_code` + `rationale_args`，呈現端自行 `t()`（與既有 request-scoped i18n 規範一致）。

## 4. B — Rationale 模板（deterministic，借鏡 attack_posture）

於 `rule_suggester.py` 內，仿 `RECOMMENDATION_TEMPLATES` / `resolve_recommendation`：

```python
RULE_RATIONALE_TEMPLATES: dict[str, dict[str, str]] = {
    "WELL_KNOWN_DB_PORT": {
        "en": "Recurring blocked flows to a well-known database port ({port}); likely a legitimate app-to-DB dependency. Review before allowing.",
        "zh_TW": "重複出現往資料庫常見 Port（{port}）的 Blocked 流量，可能是合理的 App-to-DB 依賴，建議審查後再 Allow。",
    },
    "HIGH_RISK_PORT": {
        "en": "Blocked flows on a high-risk port ({port}); treat with caution and confirm the source is authorized before allowing.",
        "zh_TW": "高風險 Port（{port}）的 Blocked 流量，請審慎確認來源已授權後再 Allow。",
    },
    "GENERIC_RECURRING_BLOCK": {
        "en": "Recurring blocked flows between these workloads on {port}/{proto}; candidate for a scoped allow rule after review.",
        "zh_TW": "這些 Workload 之間在 {port}/{proto} 上重複被 Block，審查後可考慮新增收斂範圍的 Allow 規則。",
    },
}

def resolve_rule_rationale(code: str, lang: str = "en", **args) -> str:
    """Deterministic rationale text; missing code → safe fallback, missing lang → en."""
```

- 缺 code → 安全 fallback（"Review the blocked flows and apply a least-privilege allow rule only if the dependency is legitimate."）。
- 缺 lang → 回 `en`。
- glossary：zh_TW 的 **Block / Blocked / Allow / Port / Workload / App / Policy** 等須保留英文（`src/i18n/data/glossary.json` preserve-list），模板已遵循。

## 5. C — Provider 抽象（可選 LLM enrich，預設關閉）

新模組 `src/report/analysis/rule_providers.py`。

### 5.1 介面

```python
class Provider(Protocol):
    def enrich(self, suggestions: list[dict], lang: str) -> list[dict]: ...

class NullProvider:
    """Default. Returns heuristic suggestions UNCHANGED. Never touches the network."""
    def enrich(self, suggestions, lang="en"):
        return suggestions
```

- 真 provider（`OllamaProvider` / `OpenAIProvider` / `AnthropicProvider`）為**薄 adapter**：把每筆 suggestion 的結構化欄位（src/dst/port/proto/risk/observed_*）送給 LLM，要求回傳一段補充說明，寫進該筆的 `llm_note` 欄位（**僅新增說明，不改 heuristic 的 src/dst/port/proto/risk/confidence**）。
- **任何 provider 失敗（連線、逾時、解析、缺套件）→ 退回原 heuristic 結果**（log 一行 warning，**不含 api_key**），絕不讓 LLM 故障影響核心交付。
- `make_provider(cfg: dict) -> Provider`：依 `cfg["provider"]` 回對應 adapter；`"none"` 或未知 → `NullProvider`。`"none"` 路徑**不 import 任何網路套件、不建立任何 client**。

### 5.2 預設關閉 + air-gap 強制

- `make_provider({"provider":"none", ...})` 回 `NullProvider`；其 `enrich` 為純回傳，**保證零網路**。
- 測試以 monkeypatch 攔截 socket / requests，斷言 `provider="none"` 全程**零呼叫**（§7）。

### 5.3 secret 處理

- `api_key` 只在真 provider 的 client 建構當下讀取，**不寫入任何 log、不放進回傳 dict、不進報表**。
- provider 失敗的 warning log 只記 `provider` 名稱與錯誤類別，**不記 endpoint 的 query、不記 api_key**。

## 6. D — 報表落點（HTML + CSV，重用既有 exporter）

新 facade `src/report/ai_rules_report.py`，仿 `security_risk_report.py`：

```python
class AiRulesReport:
    def __init__(self, cm, api_client=None, config_dir="config", cache_reader=None): ...
    def run(self, output_dir="reports", lang="en") -> str:
        # 1. 取流量：cache_reader.read_flows_raw() 優先（離線），否則 api fetch_traffic_for_report()
        # 2. suggestions = suggest_rules(flows)
        # 3. provider = make_provider(cm.config.get("ai_rules", {})); suggestions = provider.enrich(suggestions, lang)
        # 4. 組 module_results（含 rationale 文字 + 「未佈署任何規則」免責），HTML + CSV 匯出
        # 回傳 HTML 路徑
```

- **CSV**：把 suggestions 轉成 `pandas.DataFrame`（欄位：src_label, dst_label, port, proto, risk, confidence, observed_flows, observed_blocked, observed_potentially, rationale），塞進 `module_results` 後交給 `CsvExporter(results, report_label="AI_Rule_Suggestions").export(output_dir)`。
- **HTML**：一張表（`render_df_table` 或既有 html_exporter pattern），頂部固定一句免責：「Suggestions only — no rules were created or applied on the PCE.」（i18n key `rpt_ai_rules_disclaimer`）。
- **零資料**：`flows` 為空或 suggestions 為空 → 回 `""`（與 `security_risk_report` 一致）。

### 6.1 CLI 入口

於 `src/cli/report.py` 新增 `report ai-rules` 子命令（mirror `report_traffic` 結構）：

```
illumio-ops report ai-rules [--source api|cache] [--format html|csv] [--output-dir DIR]
```

- 預設 `--source cache`（離線優先、air-gap 友善）。
- handler `generate_ai_rules_report(...)` 取 `cm`、`_make_cache_reader(cm)`、`_resolve_lang(cm)`，呼叫 `AiRulesReport(...).run(...)`，以 `_emit_paths` 輸出（沿用 `--json`）。
- `report_group` 已在 `src/cli/root.py:89` 註冊，無需改 root。

## 7. config

`src/config_models.py` 新增（放在 `ConfigSchema` 之前）：

```python
class AiRulesSettings(_Base):
    enabled: bool = False
    provider: Literal["none", "ollama", "openai", "anthropic"] = "none"
    model: str = ""
    endpoint: str = ""
    api_key: str = ""
```

`ConfigSchema` 新增欄位：`ai_rules: AiRulesSettings = Field(default_factory=AiRulesSettings)`。

`src/config.py::_DEFAULT_CONFIG` 同步新增：
```python
"ai_rules": {"enabled": False, "provider": "none", "model": "", "endpoint": "", "api_key": ""},
```

- 預設 `provider="none"` → 預設離線。
- `api_key` 含子字串 `key` → 自動命中 `_SECRET_FIELD_TOKENS`，validation 錯誤 log 自動 redact（L-12）。

## 8. i18n

新 key（`rpt_` 前綴；同時加入 `src/i18n_en.json` 與 `src/i18n_zh_TW.json`）：

- `rpt_ai_rules_title`、`rpt_ai_rules_disclaimer`、`rpt_ai_rules_col_src`、`rpt_ai_rules_col_dst`、`rpt_ai_rules_col_port`、`rpt_ai_rules_col_proto`、`rpt_ai_rules_col_risk`、`rpt_ai_rules_col_confidence`、`rpt_ai_rules_col_observed`、`rpt_ai_rules_col_rationale`、`rpt_ai_rules_empty`。

rationale 模板字串走 `RULE_RATIONALE_TEMPLATES`（程式內，與 `attack_posture` 同模式），不放 i18n json。zh_TW 須遵守 glossary（Block/Blocked/Allow/Port/Workload/App/Policy 保留英文）。以 `python scripts/audit_i18n_usage.py` 驗證 parity（category I）與 glossary（category E）。

## 9. 測試

- `tests/test_rule_suggester.py`：
  - 空輸入 → `[]`。
  - 合成 blocked + potentially_blocked → 正確分組、`observed_blocked`/`observed_potentially` 分計、confidence/risk deterministic、排序固定。
  - `min_pd=2` 時排除 potentially_blocked。
  - rationale_code 對映正確；`resolve_rule_rationale` 缺 code/缺 lang 的 fallback。
  - **deterministic**：同輸入跑兩次結果完全相同。
- `tests/test_rule_providers.py`：
  - `NullProvider.enrich` 原樣回傳。
  - `make_provider({"provider":"none"})` 回 `NullProvider`。
  - **`test_null_provider_makes_no_network_call`**：monkeypatch `socket.socket` 拋例外，跑 `make_provider({"provider":"none"}).enrich(...)`，斷言**未發生任何 socket 建立**（air-gap 強制）。
  - fake provider（測試內定義，回 `llm_note`）→ 只新增 `llm_note`，heuristic 欄位不變。
  - 真 provider 失敗（fake 拋例外）→ 退回原 suggestions。**測試中無任何真實網路**。
- `tests/test_ai_rules_report.py`：合成 flows → `run()` 產出 HTML 檔存在、含免責字串；空 flows → 回 `""`。
- `tests/test_config_ai_rules.py`：預設 config 有 `ai_rules` 且 `provider=="none"`、`enabled is False`；含 `api_key` 的無效 config validation log 被 redact（不含明文）。
- i18n：`python scripts/audit_i18n_usage.py` 0 findings（parity + glossary）。

## 10. 風險與緩解

| 風險 | 緩解 |
|---|---|
| LLM 故障影響核心 | provider 失敗一律退回 heuristic；core 零相依、永遠可用 |
| api_key 洩漏（L-12） | 欄位命名含 `key` → 自動 redact；provider 禁 log secret；測試斷言 |
| 誤以為會自動建規則 | 報表 + CLI 皆固定免責句；不呼叫任何 provision API；不寫 config["rules"] |
| air-gap 違反 | `provider="none"` 為預設且不 import 網路套件；測試以 socket 攔截強制零網路 |
| heuristic 不 deterministic | 分數只看觀測量與固定 port 表；排序鍵固定；測試跑兩次比對 |

## 11. 後續（不在本 spec）

- GUI 頁面（v1 明確 out of scope）。
- 把候選餵給 `check_flow_match` 做「若新增此規則可解掉幾筆 blocked」的影響模擬。
- provider 的 prompt 模板抽出與快取。
