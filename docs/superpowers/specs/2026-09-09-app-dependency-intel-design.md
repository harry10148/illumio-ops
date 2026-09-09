# App Dependency Intelligence 設計（子專案 2／4，借鑒 illumio-plugger app-dependency-intel）

日期：2026-09-09　狀態：草案待使用者審閱　分支：feat/ven-fleet-manager（執行時各自開分支）

## 0. 背景與範圍

plugger 由 30 天 allowed 流量建 `app|env` 依賴圖，算 blast radius（反向 BFS）、SPOF（provider ≤1 台且
≥2 consumer）、cycles（DFS）、cross-env（prod↔non-prod）、infra hubs、change impact。無持久化、無認證。

本專案已有同一套 `app|env` 節點正規化（mod13／mod14／mod15 的 `_normalize_key_series`、
`readiness_report._workload_app_env_key`）、mod14 的 hub／betweenness、mod07 的跨 label 矩陣、
mod15 的 articulation points 與 BFS。缺：blast radius、SPOF、cycles、有方向的 prod↔non-prod 違規、change impact。

使用者決定：報表新模組 ＋ GUI 查詢工具。

不在範圍：D3 圖、resiliency score（plugger 只在前端 JS，且權重無依據）、GROUP_BY 自訂鍵。

## 1. 架構

```
flow DF（既有 unified schema，含 src/dst app/env）
   └─ src/report/analysis/dependency_graph.py   build_graph(df, *, workloads=None) -> DepGraph（純函式）
        ├─ blast_radius(g, key)      ├─ spof(g)      ├─ cycles(g)
        ├─ cross_env(g)              └─ change_impact(g, targets)
報表：mod16_dependency_intel（TRAFFIC_MODULES 新項；profiles _SEC_INV）→ 段落 'dependency'
GUI ：#/investigate/dependencies   POST /api/dependencies/query（讀 pce_cache，不打 PCE）
```

共用一份 `DepGraph`；報表跑全圖摘要，GUI 針對一個目標查。

## 2. 圖層 `src/report/analysis/dependency_graph.py`

```python
@dataclass
class Edge: consumer: str; provider: str; connections: int; services: Counter[str]  # "port/proto"
                cross_env: bool; first_seen; last_seen
@dataclass
class DepGraph:
    nodes: dict[str, Node]          # key "app|env" -> Node{app, env, workload_count|None, hostnames:set, roles:set}
    edges: dict[tuple[str,str], Edge]
    depends_on: dict[str, set[str]]; depended_by: dict[str, set[str]]
def build_graph(df, *, workloads: list[dict] | None = None, include_unlabeled: bool = False) -> DepGraph
def blast_radius(g, key, max_depth=10) -> dict
def spof(g, *, min_consumers=2, max_workloads=1) -> list[dict]
def cycles(g, *, limit=50) -> list[dict]
def cross_env(g) -> list[dict]
def change_impact(g, targets: list[str]) -> dict
def is_prod_env(env: str) -> bool     # 抽自 mod14:156，mod14 改 import 這裡
```

決定（對 plugger 的修正）：
| plugger | 本案 |
|---|---|
| 只取 allowed | 預設 `policy_decision != "blocked"`（含 potentially_blocked 與 unknown），參數可改 |
| 無 app 的端點丟棄 | `include_unlabeled=False` 時丟，True 時成 `unlabeled|<env>` 節點；報表 False、GUI 可切 |
| SPOF 用 /workloads 數 | `workloads` 給了才算真 SPOF；沒給時用流量中 distinct managed provider hostname 數並標 `approximate=True` |
| cycles 非窮舉遞迴 DFS | Johnson 演算法（簡單環）改成迭代實作，`limit` 截斷並回 `truncated` |
| cross-env 只看 prod↔non-prod | 同；`is_prod_env` 只認 prod／production／prd，其餘含 unlabeled 視 non-prod；方向保留（non-prod→prod 為 critical，prod→non-prod 為 warning） |
| 時間字串比大小 | pandas datetime |
| strength >1000／≥100 | 沿用但放常數，文件寫明是連線數不是位元組 |
| change impact 只比 hostname／IP 精確 | 同時比 `src_hostname`／`dst_hostname`／`src_ip`／`dst_ip`；回 `unmatched_targets` |

`blast_radius` 回：`{target, directly_affected:[key], transitively_affected:[key], total_affected_applications,
total_affected_workloads|None, max_depth, chain:[{key, depth}], truncated}`。

## 3. 報表模組 `mod16_dependency_intel`

- 註冊 `analysis/__init__.py` TRAFFIC_MODULES：新 adapter `_call_df_workloads`（抓 `api.fetch_managed_workloads()`
  一次，與 mod_labels 共用同一次抓取：在 `report_generator` 把 workloads 放進 `self._workloads_cache`）。
- 輸出：`{total_apps, total_edges, spof:[...], spof_approximate, cycles:[...], cycles_truncated,
  cross_env:[...]（critical 先）, top_blast:[前 10 個 blast radius 最大的 provider], attack_posture_items, chart_spec}`。
  `attack_posture_items` 用 `finding_kind="blast_radius"`（report_metadata 已有此 key）。
- HTML 段落 key `dependency`，放在 `infrastructure` 之後 `lateral` 之前；四張表：SPOF、循環依賴、跨環境違規、
  最大爆炸半徑；chart_spec bar（critical／warning cross-env 數）。
- guidance `mod16_dependency_intel` 四鍵；COL_I18N overlay 加欄名。
- 專案規則：長 chain 欄以換行不省略；表列上限 25＋「前 25／共 N」。

## 4. GUI `#/investigate/dependencies`

- 輸入：目標（app|env 下拉，自快照的節點清單；或 hostname／IP 清單 textarea）、視窗（7／14／30 天）、
  是否含 unlabeled。
- `POST /api/dependencies/query` `{mode:"blast"|"impact", target?|targets?, days, include_unlabeled}`：
  `_make_cache_reader(cm)`→`cover_state` 非 full 回 `{ok:False, code:"cache_incomplete", covered_until}`；
  `count_flows` 超過 `read_max_rows` 回 `cache_too_large`；否則 `read_flows_df`→`build_graph`→結果。
  結果快取 5 分鐘（key＝days＋include_unlabeled）避免每次重讀。
- `GET /api/dependencies/nodes?days=` 回節點清單供下拉（同快取）。
- 呈現：摘要卡（直接／間接受影響 app 數、workload 數、深度）、chain 表（深度分組）、SPOF／cross-env 只讀卡
  （來自同一圖）；「在流量搜尋開啟」連結帶 filter。
- coverage.yaml IV-21..IV-24（IV-16..20 給 fleet）；GET_MAP 加 `dependency_nodes`（endpoints.yaml 同步、
  test_v2_coverage_live 的 entry 計數 +1）；POST 留 yaml POST 區；gui-tour.md 加路由（test_docs_gui_tour_routes）。

## 5. 錯誤處理

- 空圖（視窗內無 flow）：報表段落顯示「無資料」而非省略；GUI 提示。
- cycles 超過 limit：明示 truncated。
- SPOF 近似：表頭標「近似（無 workload 清單）」。

## 6. 測試

- 圖層：手工 6 節點 fixture 驗 BFS 深度、SPOF 兩種模式、Johnson 找到 2 個簡單環且 limit=1 時 truncated、
  cross-env 方向與嚴重度、change_impact 同時比 hostname／IP 與 unmatched。
- 模組：`_run_pipeline` 產 HTML 含 `id="dependency"`；chart_spec 合約與 lang；guidance 註冊；
  inventory profile 也含（_SEC_INV）。
- GUI：route mount、cache_incomplete 文案、blast 查詢 stub 渲染 chain。
- 真機：lab 30 天 cache 產 Security & Risk 報表雙語看四表；GUI 對一個 app 查 blast。
