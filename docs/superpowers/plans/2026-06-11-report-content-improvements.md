# 報表內容改善（分析師視角評估後續）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落實 2026-06-11 微分段分析師視角報表評估的改善建議：修復死掉的章節導讀卡、報表圖表靜態化（5MB→~200KB）、新增標籤治理與基準漂移兩個模組、mod10 併入 mod02 精簡章節。

**Architecture:** 全部變更集中在報表引擎（`src/report/`）。圖表改用既有 matplotlib 路徑輸出 SVG 內嵌（不再內嵌 4.84MB plotly.js）；兩個新分析模組為純函式、由 `report_generator` 直接呼叫（不進 registry，仿 `_trend_deltas` 注入模式）；漂移偵測新增一個 gzip 簽章集儲存層（仿 `trend_store` 的 load-before-save 模式）。

**Tech Stack:** Python 3.10 / pandas / matplotlib（Agg backend，已 vendored）/ pytest。i18n 雙檔同步（`src/i18n_en.json` + `src/i18n_zh_TW.json`），glossary 詞彙（Label/Port/Policy/Workload/Service/Ruleset）在 zh_TW 保留英文。

**評估出處：** 本計劃對應 2026-06-11 分析師評估的建議：精簡 #1（Plotly）、補充 #2（標籤治理）、補充 #3（基準漂移）、精簡 #2（mod10 併入），外加計劃撰寫時發現的導讀卡 bug。**刻意不含**：App-centric 報表（須與 P4 Teams 一起設計）、V-E 弱掃整合（須先決定匯入格式）— 各自另開計劃。

---

## 已驗證的關鍵事實（計劃撰寫時確認）

| 事實 | 證據 |
|------|------|
| 章節導讀卡全部不渲染：`REGISTRY` key 是全名（`mod02_policy_decisions`），exporter 呼叫用短 id（`mod02`），`get_guidance('mod02')` → None | `src/report/section_guidance.py:26-197` vs `src/report/exporters/html_exporter.py:633-670`；實測 `get_guidance('mod02') is None == True` |
| 報表 5.05MB 中 4.84MB 是內嵌 plotly.js | 對 `Illumio_Traffic_Report_SecurityRisk_2026-06-11_1336.html` 的 script 區塊量測 |
| chart_renderer 已有 matplotlib 靜態路徑（`render_matplotlib_png`，xlsx 用） | `src/report/exporters/chart_renderer.py:318-403` |
| 流量 df 有 `src_app/src_env/src_loc/src_role`、`dst_*` 同組、`src_managed`/`dst_managed`（bool）、`src_ip/dst_ip/port/proto/num_connections` | `src/report/parsers/api_parser.py:73-97`、`mod08_unmanaged_hosts.py:14-16` |
| `ApiClient.fetch_managed_workloads(max_results=10000) -> list`（workload dicts 含 labels） | `src/api_client.py:637-650` |
| export() 時 `result.dataframe` 仍可用 | `src/report/report_generator.py:405` |
| trend 注入模式：export() 時計算並塞進 `result.module_results["_trend_deltas"]` | `report_generator.py:454-461` |
| 兩個 profile 的章節清單 | `html_exporter.py:1511-1530`（`_ordered_section_keys`） |

執行環境：worktree（由 superpowers:using-git-worktrees 建立）、`./venv/bin/python`（在 worktree 內先 `ln -sfn /home/harry/rd/illumio-ops/venv venv`）。完整測試：`./venv/bin/python -m pytest tests/ -q`（基線 1716 passed, 5 skipped）。

---

## 檔案結構（異動地圖）

```
src/report/section_guidance.py             # T1: REGISTRY key 改短 id（或加別名解析）
src/report/exporters/chart_renderer.py     # T2: 抽出 _build_matplotlib_figure + render_matplotlib_svg
src/report/exporters/html_exporter.py      # T3: 圖表改 SVG；T5/T6: 新區段；T7: mod10 併入 mod02
src/report/flow_history.py                 # T4: 新檔 — flow 簽章集 gz 儲存
src/report/analysis/mod_drift.py           # T5: 新檔 — 基準漂移模組（純函式）
src/report/analysis/mod_labels.py          # T6: 新檔 — 標籤治理模組（純函式）
src/report/report_generator.py             # T5: export() 注入 mod_drift；T6: generate_from_api 注入 mod_labels
src/i18n_en.json, src/i18n_zh_TW.json      # T5/T6: 新區段 i18n key
tests/test_section_guidance_keys.py        # T1 新測試
tests/test_chart_static_svg.py             # T2 新測試
tests/test_html_exporter_static_charts.py  # T3 新測試
tests/test_flow_history.py                 # T4 新測試
tests/test_mod_drift.py                    # T5 新測試
tests/test_mod_labels.py                   # T6 新測試
```

---

### Task 1: 修復章節導讀卡 key 不匹配（quick win）

`render_section_guidance('mod02', ...)`（html_exporter.py:633 起共 13 處呼叫）查 `REGISTRY` 時拿到 None → 所有導讀卡靜默消失。修法：在 `get_guidance` / `visible_in` 做前綴正規化，REGISTRY 保持全名 key 不動（改動面最小）。

**Files:**
- Modify: `src/report/section_guidance.py:200-211`
- Test: `tests/test_section_guidance_keys.py`（新檔）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_section_guidance_keys.py
"""Every section-guidance id used by the HTML exporter must resolve."""
import re
from pathlib import Path

from src.report.section_guidance import REGISTRY, get_guidance


def _exporter_called_ids() -> set[str]:
    src = Path("src/report/exporters/html_exporter.py").read_text(encoding="utf-8")
    return set(re.findall(r"render_section_guidance\('([\w]+)'", src))


def test_short_id_resolves_to_full_registry_key():
    assert get_guidance("mod02") is not None
    assert get_guidance("mod02").module_id == "mod02_policy_decisions"


def test_full_key_still_resolves():
    assert get_guidance("mod02_policy_decisions") is not None


def test_unknown_id_returns_none():
    assert get_guidance("mod99") is None


def test_every_exporter_call_site_resolves():
    called = _exporter_called_ids()
    assert called, "expected to find render_section_guidance call sites"
    missing = {mid for mid in called if get_guidance(mid) is None}
    # 允許尚未撰寫 guidance 的模組存在，但至少 mod02/mod03/mod04/mod08 必須命中
    for must in ("mod02", "mod03", "mod04", "mod08"):
        assert must not in missing, f"{must} guidance must resolve"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_section_guidance_keys.py -v`
Expected: FAIL — `get_guidance("mod02") is not None` 斷言失敗

- [ ] **Step 3: 實作前綴解析**

`src/report/section_guidance.py` — 取代 `get_guidance`（line 200-202）：

```python
def get_guidance(module_id: str) -> Optional[SectionGuidance]:
    """Return guidance for a module, or None if not registered.

    Accepts either the full registry key ("mod02_policy_decisions") or the
    short id the exporters use ("mod02") — short ids match by prefix.
    """
    g = REGISTRY.get(module_id)
    if g is not None:
        return g
    prefix = module_id + "_"
    for key, value in REGISTRY.items():
        if key.startswith(prefix):
            return value
    return None
```

`visible_in`（line 205-211）改為複用 `get_guidance`：

```python
def visible_in(module_id: str, profile: ProfileVisibility, detail_level: DetailLevel = "full") -> bool:
    """Return True if the section should render in the given profile."""
    g = get_guidance(module_id)
    if g is None:
        return True  # unregistered modules render by default
    return profile in g.profile_visibility
```

- [ ] **Step 4: 跑測試確認通過**

Run: `./venv/bin/python -m pytest tests/test_section_guidance_keys.py -v`
Expected: 4 passed

- [ ] **Step 5: 實機驗證導讀卡出現**

Run: `./venv/bin/python -m pytest tests/ -q -k "guidance or exporter" 2>&1 | tail -2`
Expected: 全 PASS。另外抽查：寫一個臨時 python -c 呼叫 `render_section_guidance('mod02', 'security_risk', 'full', lang='en')` 確認回傳非空字串且含 `section-guidance`。

- [ ] **Step 6: Commit**

```bash
git add src/report/section_guidance.py tests/test_section_guidance_keys.py
git commit -m "fix(report): section guidance cards never rendered — short-id lookup missed full registry keys"
```

---

### Task 2: chart_renderer 抽出共用 figure builder + 新增 SVG 輸出

`render_matplotlib_png`（chart_renderer.py:318-403）把 spec→Figure 的邏輯寫死在 PNG 輸出裡。抽出 `_build_matplotlib_figure(spec, lang) -> Figure`，PNG 與新的 SVG 輸出共用。

**Files:**
- Modify: `src/report/exporters/chart_renderer.py:318-403`
- Test: `tests/test_chart_static_svg.py`（新檔）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_chart_static_svg.py
"""Static SVG chart rendering (shares the matplotlib builder with PNG)."""
import pytest

from src.report.exporters.chart_renderer import render_matplotlib_png, render_matplotlib_svg

BAR_SPEC = {
    "type": "bar",
    "title": "Top Ports",
    "x_label": "Port",
    "y_label": "Flows",
    "data": {"labels": ["443", "80", "22"], "values": [120, 80, 15]},
}


def test_svg_output_is_svg_markup():
    svg = render_matplotlib_svg(BAR_SPEC, lang="en")
    assert isinstance(svg, str)
    assert "<svg" in svg
    assert "</svg>" in svg


def test_svg_unsupported_type_raises():
    with pytest.raises(ValueError):
        render_matplotlib_svg({"type": "sankey", "data": {}}, lang="en")


def test_png_still_works_after_refactor():
    png = render_matplotlib_png(BAR_SPEC, lang="en")
    assert isinstance(png, (bytes, bytearray))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_chart_static_svg.py -v`
Expected: FAIL — ImportError: cannot import name 'render_matplotlib_svg'

- [ ] **Step 3: 重構 + 實作**

`src/report/exporters/chart_renderer.py`：把 `render_matplotlib_png` 的本體（326 行的 spec 解析到 398 行的 `fig.tight_layout()`，含 bar/pie/line/heatmap/network 分支與 `ValueError`）原封不動搬進新函式 `_build_matplotlib_figure`，PNG/SVG 各自做輸出：

```python
def _build_matplotlib_figure(spec: dict[str, Any], *, lang: str = "en"):
    """Build a matplotlib Figure from a chart spec (shared by PNG/SVG output).

    Raises ValueError for unsupported chart types. Caller owns plt.close(fig).
    """
    chart_type = spec.get("type")
    data = spec.get("data", {})
    title = _resolve_chart_text(spec, "title", lang=lang)
    x_label = _resolve_chart_text(spec, "x_label", lang=lang)
    y_label = _resolve_chart_text(spec, "y_label", lang=lang)

    fig, ax = plt.subplots(figsize=(8, 5), dpi=100)
    # …（原 334-395 行的 bar/pie/line/heatmap/network 分支，逐字搬移，
    #    含 else 分支的 plt.close(fig); raise ValueError）…
    ax.set_title(title)
    fig.tight_layout()
    return fig


def render_matplotlib_png(spec: dict[str, Any], *, lang: str = "en") -> bytes:
    """Render chart spec as a PNG byte string (for Excel embedding)."""
    fig = _build_matplotlib_figure(spec, lang=lang)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    return buf.getvalue()


def render_matplotlib_svg(spec: dict[str, Any], *, lang: str = "en") -> str:
    """Render chart spec as inline-embeddable SVG markup (for HTML reports)."""
    fig = _build_matplotlib_figure(spec, lang=lang)
    buf = io.BytesIO()
    fig.savefig(buf, format="svg")
    plt.close(fig)
    svg = buf.getvalue().decode("utf-8")
    # 去掉 XML 宣告與 DOCTYPE，留下 <svg>…</svg> 以便直接內嵌 HTML
    idx = svg.find("<svg")
    return svg[idx:] if idx != -1 else svg
```

注意：「逐字搬移」指 334-395 行分支內容完全不改；`render_matplotlib_png` 原函式的 docstring 三行（title/axis 經 `_resolve_chart_text` 解析…）搬到 `_build_matplotlib_figure`。確認原 PNG 函式 403 行附近的 `return buf.getvalue()` 已涵蓋。

- [ ] **Step 4: 跑測試確認通過（含既有圖表測試）**

Run: `./venv/bin/python -m pytest tests/test_chart_static_svg.py tests/test_report_chart_font_size.py tests/test_chart_label_i18n.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/report/exporters/chart_renderer.py tests/test_chart_static_svg.py
git commit -m "feat(report): extract shared matplotlib builder, add SVG chart output"
```

---

### Task 3: HTML 報表圖表改用靜態 SVG（移除內嵌 plotly.js）

`_render_chart_for_html`（html_exporter.py:88-98）改呼叫 `render_matplotlib_svg`；`FirstChartTracker` 機制（為了只內嵌一次 plotly.js）整個失去存在意義，呼叫端的 `include_js=self._chart_tracker.consume()` 一併清除。**範圍涵蓋所有 HTML exporter**：先 `grep -rn "render_plotly_html\|FirstChartTracker\|_render_chart_for_html" src/report/exporters/` 列出全部呼叫點（已知 html_exporter.py:33,88-98,443,845,1010,1067,1399；audit/ven/policy_usage exporter 若有引用一併處理）。

**Files:**
- Modify: `src/report/exporters/html_exporter.py:33,88-98,443` + 各圖表呼叫點
- Modify: 其他引用 `render_plotly_html`/`FirstChartTracker` 的 exporter（以 grep 結果為準）
- Test: `tests/test_html_exporter_static_charts.py`（新檔）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_html_exporter_static_charts.py
"""HTML reports embed static SVG charts, not plotly.js."""
from src.report.exporters.html_exporter import _render_chart_for_html

BAR_SPEC = {
    "type": "bar",
    "title": "Top Ports",
    "data": {"labels": ["443", "80"], "values": [12, 8]},
}


def test_chart_html_is_static_svg():
    html = _render_chart_for_html(BAR_SPEC)
    assert "<svg" in html
    assert "plotly" not in html.lower()


def test_none_spec_renders_empty():
    assert _render_chart_for_html(None) == ""


def test_invalid_spec_degrades_gracefully():
    # 不支援的 type 不得讓整份報表炸掉 — 回傳空字串並繼續
    assert _render_chart_for_html({"type": "sankey", "data": {}}) == ""
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_html_exporter_static_charts.py -v`
Expected: FAIL（現行實作回傳 plotly div，或簽名含必填 include_js）

- [ ] **Step 3: 實作**

(a) `html_exporter.py:88-98` 取代 `_render_chart_for_html`：

```python
def _render_chart_for_html(spec: dict | None, include_js: bool = False) -> str:
    """Render a chart spec as inline static SVG. include_js is accepted for
    backward compatibility and ignored (plotly.js is no longer embedded)."""
    if not spec:
        return ""
    try:
        svg = render_matplotlib_svg(spec, lang=get_language())
    except Exception as exc:  # noqa: BLE001 — a bad chart must not kill the report
        logger.warning("[HtmlExporter] chart render failed (skipped): {}", exc)
        return ""
    return f'<figure class="chart-static">{svg}</figure>'
```

注意：函式簽名保留 `include_js` 參數避免一次改動全部呼叫點失敗；確認檔頭有 `logger`（loguru）與 `get_language` 的既有 import，並把 line 33 的 import 改為 `from .chart_renderer import render_matplotlib_svg`（移除 `render_plotly_html, FirstChartTracker` 的 import，若其他 exporter 仍引用則只在該檔保留其本身的 import）。

(b) 清除 tracker：刪除 `html_exporter.py:443` 的 `self._chart_tracker = FirstChartTracker()`；4 個呼叫點（845, 1010, 1067, 1399 — 行號以 grep 為準）的 `, include_js=self._chart_tracker.consume()` 參數刪除。其他 exporter 檔若有同模式，一併處理。

(c) lang 正確性：`_render_chart_for_html` 是模組層函式拿不到 `self._lang`，沿用 `get_language()` 會重演 T3（前計劃）的洩漏 — 改為**由呼叫端傳 lang**：簽名定為 `_render_chart_for_html(spec, lang: str = "en", include_js: bool = False)`，所有呼叫點傳 `lang=self._lang`，函式內 `render_matplotlib_svg(spec, lang=lang)`。測試第 1 個 case 改成 `_render_chart_for_html(BAR_SPEC, lang="en")`。

(d) CSS：在 `src/report/exporters/report_css.py` 加一條（位置仿既有 figure/chart 類）：

```css
.chart-static svg{max-width:100%;height:auto;}
```

- [ ] **Step 4: 跑測試 + 量測檔案大小**

Run: `./venv/bin/python -m pytest tests/test_html_exporter_static_charts.py tests/ -q -k "exporter or chart" 2>&1 | tail -2`
Expected: 全 PASS

實機驗證（lab PCE 可用時）：
```bash
./venv/bin/python illumio-ops.py report security --output-dir /tmp/review_reports 2>&1 | tail -1
ls -la /tmp/review_reports/*.html   # 預期 < 500KB（原 ~5MB）
grep -c "plotly.js" /tmp/review_reports/Illumio_Traffic_Report_SecurityRisk_*.html  # 預期 0
```

- [ ] **Step 5: Commit**

```bash
git add src/report/exporters/ tests/test_html_exporter_static_charts.py
git commit -m "feat(report): static SVG charts in HTML reports — drop 4.8MB embedded plotly.js (5MB→<500KB)"
```

---

### Task 4: flow_history — 每次報表落地 flow 簽章集（gz）

漂移偵測需要「上一期看過哪些連線」。新增與 `trend_store` 同型的小儲存層：每次 export 把 `(src_app, dst_app, port, proto)` 簽章集存成 json.gz，下一期載入比對。app 層級（非 IP 層級）讓檔案大小有界且語意對齊微分段政策。

**Files:**
- Create: `src/report/flow_history.py`
- Test: `tests/test_flow_history.py`（新檔）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_flow_history.py
"""Per-run flow-signature persistence for baseline drift detection."""
import pandas as pd

from src.report.flow_history import (
    build_signatures,
    load_previous_signatures,
    save_signatures,
)


def _df():
    return pd.DataFrame([
        {"src_app": "Web", "dst_app": "DB", "port": 3306, "proto": "TCP"},
        {"src_app": "Web", "dst_app": "DB", "port": 3306, "proto": "TCP"},  # dup → 1 sig
        {"src_app": "", "dst_app": "Cache", "port": 6379, "proto": "TCP"},  # unlabeled src
    ])


def test_build_signatures_dedupes_and_marks_unlabeled():
    sigs = build_signatures(_df())
    assert sigs == {"Web|DB|3306|TCP", "(unlabeled)|Cache|6379|TCP"}


def test_save_then_load_roundtrip(tmp_path):
    out = str(tmp_path)
    save_signatures(out, "traffic", {"A|B|443|TCP"}, generated_at="2026-06-01T00:00:00")
    sigs, ts = load_previous_signatures(out, "traffic")
    assert sigs == {"A|B|443|TCP"}
    assert ts == "2026-06-01T00:00:00"


def test_load_returns_none_when_no_history(tmp_path):
    sigs, ts = load_previous_signatures(str(tmp_path), "traffic")
    assert sigs is None and ts is None


def test_retention_keeps_last_12(tmp_path):
    out = str(tmp_path)
    for i in range(15):
        save_signatures(out, "traffic", {f"A|B|{i}|TCP"}, generated_at=f"2026-06-01T00:00:{i:02d}")
    import pathlib
    files = list(pathlib.Path(out, "history", "traffic").glob("flows_*.json.gz"))
    assert len(files) == 12
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_flow_history.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 實作 flow_history.py**

```python
# src/report/flow_history.py
"""Per-run flow-signature snapshots for baseline drift detection.

Stores the set of observed (src_app, dst_app, port, proto) signatures per
report run, alongside trend_store's KPI history:

    {output_dir}/history/{report_type}/flows_{ts}.json.gz

Schema: {"_generated_at": iso_ts, "signatures": [sorted str, ...]}
App-level (not IP-level) signatures keep files bounded and align with how
microsegmentation policy is expressed. Retention: newest 12 files.
"""
from __future__ import annotations

import datetime
import gzip
import json
from pathlib import Path

import pandas as pd
from loguru import logger

_UNLABELED = "(unlabeled)"
_KEEP = 12


def _history_dir(output_dir: str, report_type: str) -> Path:
    return Path(output_dir) / "history" / report_type


def build_signatures(df: pd.DataFrame) -> set[str]:
    """Distinct 'src_app|dst_app|port|proto' signatures; blank labels → (unlabeled)."""
    if df is None or df.empty:
        return set()
    src = df["src_app"].fillna("").astype(str).replace("", _UNLABELED)
    dst = df["dst_app"].fillna("").astype(str).replace("", _UNLABELED)
    port = df["port"].fillna(0).astype(int).astype(str)
    proto = df["proto"].fillna("").astype(str)
    return set(src + "|" + dst + "|" + port + "|" + proto)


def save_signatures(
    output_dir: str,
    report_type: str,
    signatures: set[str],
    generated_at: str | None = None,
) -> str:
    """Persist a signature set and prune to the newest 12 files."""
    ts = generated_at or datetime.datetime.now().isoformat(timespec="seconds")
    safe_ts = ts.replace(":", "").replace("-", "").replace("T", "_")[:15]
    hdir = _history_dir(output_dir, report_type)
    hdir.mkdir(parents=True, exist_ok=True)
    path = hdir / f"flows_{safe_ts}.json.gz"
    payload = {"_generated_at": ts, "signatures": sorted(signatures)}
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    for old in sorted(hdir.glob("flows_*.json.gz"))[:-_KEEP]:
        old.unlink(missing_ok=True)
    logger.info("[FlowHistory] Saved {} signatures → {}", len(signatures), path)
    return str(path)


def load_previous_signatures(
    output_dir: str,
    report_type: str,
) -> tuple[set[str] | None, str | None]:
    """Load the most recent signature set, or (None, None) when absent."""
    hdir = _history_dir(output_dir, report_type)
    if not hdir.is_dir():
        return None, None
    files = sorted(hdir.glob("flows_*.json.gz"))
    if not files:
        return None, None
    try:
        with gzip.open(files[-1], "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        return set(payload.get("signatures", [])), payload.get("_generated_at")
    except Exception as exc:  # noqa: BLE001 — corrupt history must not kill reports
        logger.warning("[FlowHistory] Failed to load {}: {}", files[-1], exc)
        return None, None
```

注意 `test_retention_keeps_last_12` 中同秒時間戳：`safe_ts` 取到秒，15 次迴圈用了不同秒數（`00:{i:02d}`），檔名不會互撞。

- [ ] **Step 4: 跑測試確認通過**

Run: `./venv/bin/python -m pytest tests/test_flow_history.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/report/flow_history.py tests/test_flow_history.py
git commit -m "feat(report): per-run flow-signature history (gz) for baseline drift detection"
```

---

### Task 5: 基準漂移模組 + Security 報表區段

純函式模組比較本期 vs 上期簽章集 → 新出現／消失的 app-to-app 連線。`report_generator.export()` 在 trend 區塊旁注入（load 前期 → 算 drift → save 本期），exporter 在 SecurityRisk profile 的 `summary` 之後渲染 `drift` 區段。

**Files:**
- Create: `src/report/analysis/mod_drift.py`
- Modify: `src/report/report_generator.py:454-461`（trend 區塊內）
- Modify: `src/report/exporters/html_exporter.py`（`_sec` dict、`_mod_drift_html`、SecurityRisk `_ordered_section_keys`）
- Modify: `src/report/section_guidance.py`（REGISTRY 加 `mod_drift`）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_mod_drift.py`（新檔）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_mod_drift.py
"""Baseline drift: new / disappeared app-to-app flows vs previous run."""
import pandas as pd

from src.report.analysis.mod_drift import baseline_drift


def _df():
    return pd.DataFrame([
        {"src_app": "Web", "dst_app": "DB", "port": 3306, "proto": "TCP", "num_connections": 40},
        {"src_app": "Web", "dst_app": "Cache", "port": 6379, "proto": "TCP", "num_connections": 7},
    ])


def test_no_previous_returns_unavailable():
    res = baseline_drift(_df(), prev_signatures=None, prev_generated_at=None)
    assert res["available"] is False


def test_new_and_disappeared_pairs_detected():
    prev = {"Web|DB|3306|TCP", "Batch|DB|3306|TCP"}
    res = baseline_drift(_df(), prev_signatures=prev, prev_generated_at="2026-06-01T00:00:00")
    assert res["available"] is True
    assert res["new_count"] == 1                       # Web→Cache:6379 是新的
    assert res["disappeared_count"] == 1               # Batch→DB 不見了
    new_rows = res["new_pairs"]
    assert list(new_rows.iloc[0][["Src App", "Dst App"]]) == ["Web", "Cache"]
    assert int(new_rows.iloc[0]["Connections"]) == 7
    gone = res["disappeared_pairs"]
    assert list(gone.iloc[0][["Src App", "Dst App"]]) == ["Batch", "DB"]
    assert res["prev_generated_at"] == "2026-06-01T00:00:00"


def test_identical_periods_produce_zero_drift():
    prev = {"Web|DB|3306|TCP", "Web|Cache|6379|TCP"}
    res = baseline_drift(_df(), prev_signatures=prev, prev_generated_at="x")
    assert res["new_count"] == 0 and res["disappeared_count"] == 0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_mod_drift.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 實作 mod_drift.py**

```python
# src/report/analysis/mod_drift.py
"""Baseline drift — app-to-app connection pairs new/disappeared vs previous run.

PURE function: signature comparison only, no I/O. The previous-period
signature set is loaded by report_generator.export() via flow_history and
passed in. The App Group Summary concept ("has the connection baseline
changed?") applied at whole-estate level.
"""
from __future__ import annotations

import pandas as pd

from src.report.flow_history import build_signatures, _UNLABELED


def _sig_to_row(sig: str) -> dict:
    src, dst, port, proto = sig.split("|", 3)
    return {"Src App": src, "Dst App": dst, "Port": port, "Proto": proto}


def baseline_drift(
    df: pd.DataFrame,
    prev_signatures: set[str] | None,
    prev_generated_at: str | None,
    top_n: int = 20,
) -> dict:
    if prev_signatures is None:
        return {"available": False}

    current = build_signatures(df)
    new_sigs = sorted(current - prev_signatures)
    gone_sigs = sorted(prev_signatures - current)

    # 新連線帶上本期連線數，按量排序讓分析師先看大的
    conn_by_sig: dict[str, int] = {}
    if df is not None and not df.empty:
        work = df.copy()
        work["_sig"] = (
            work["src_app"].fillna("").astype(str).replace("", _UNLABELED) + "|"
            + work["dst_app"].fillna("").astype(str).replace("", _UNLABELED) + "|"
            + work["port"].fillna(0).astype(int).astype(str) + "|"
            + work["proto"].fillna("").astype(str)
        )
        conn_by_sig = work.groupby("_sig")["num_connections"].sum().to_dict()

    new_rows = [dict(_sig_to_row(s), Connections=int(conn_by_sig.get(s, 0))) for s in new_sigs]
    new_rows.sort(key=lambda r: r["Connections"], reverse=True)
    gone_rows = [_sig_to_row(s) for s in gone_sigs]

    return {
        "available": True,
        "prev_generated_at": prev_generated_at,
        "new_count": len(new_sigs),
        "disappeared_count": len(gone_sigs),
        "new_pairs": pd.DataFrame(new_rows[:top_n]),
        "disappeared_pairs": pd.DataFrame(gone_rows[:top_n]),
    }
```

（`flow_history` 的 `_UNLABELED` 由底線開頭表內部常數 — 為避免跨模組引用私名，在 `flow_history.py` 把它改名為公開的 `UNLABELED` 並同步 `build_signatures` 與本模組的 import 與 T4 測試。）

- [ ] **Step 4: 跑測試確認通過**

Run: `./venv/bin/python -m pytest tests/test_mod_drift.py tests/test_flow_history.py -v`
Expected: 全 PASS

- [ ] **Step 5: report_generator 注入**

`src/report/report_generator.py` — 在 trend 區塊（line 454-461，`save_snapshot` 之後、同一個 try 內）加：

```python
            # Baseline drift: compare this run's flow signatures vs last run, then archive.
            from src.report.flow_history import build_signatures, load_previous_signatures, save_signatures
            from src.report.analysis.mod_drift import baseline_drift
            if result.dataframe is not None and not result.dataframe.empty:
                _prev_sigs, _prev_ts = load_previous_signatures(output_dir, "traffic")
                result.module_results["mod_drift"] = baseline_drift(
                    result.dataframe, prev_signatures=_prev_sigs, prev_generated_at=_prev_ts)
                save_signatures(output_dir, "traffic", build_signatures(result.dataframe), generated_at=ts)
```

（`ts` 沿用該區塊既有的時間戳變數；確認此段在既有 try/except 保護內 — 報表不得因 drift 失敗而中斷。）

- [ ] **Step 6: exporter 區段 + 導讀 + i18n**

(a) `html_exporter.py` 新增渲染方法（放在 `_mod10_html` 附近）：

```python
    def _mod_drift_html(self):
        _s = self._s
        _lang = self._lang
        m = self._r.get('mod_drift', {})
        if not m.get('available'):
            return f'<p class="note">{t("rpt_drift_first_run", lang=_lang)}</p>'
        head = (
            f'<p class="section-intro">{t("rpt_drift_baseline_from", lang=_lang)}'
            f' {(m.get("prev_generated_at") or "")[:16]}</p>'
        )
        return (
            head
            + f'<h3>{t("rpt_drift_new_pairs", lang=_lang)} ({m.get("new_count", 0)})</h3>'
            + _df_to_html(m.get('new_pairs'), lang=_lang)
            + f'<h3>{t("rpt_drift_disappeared", lang=_lang)} ({m.get("disappeared_count", 0)})</h3>'
            + _df_to_html(m.get('disappeared_pairs'), lang=_lang)
        )
```

(b) `_sec` dict（line 631-675）加一項（放在 `'uncovered'` 之後）：

```python
            'drift': self._section('drift', 'rpt_tr_sec_drift', 'Baseline Drift',
                          render_section_guidance('mod_drift', profile=profile, detail_level=detail_level, lang=self._lang) + self._mod_drift_html(),
                          'rpt_tr_sec_drift_intro', 'Compare this period\'s app-to-app connections against the previous report to spot new paths and disappeared baselines.') + '\n',
```

(c) `SecurityRiskHtmlExporter._ordered_section_keys`（line ~1513）在 `'summary'` 後插入 `'drift'`：

```python
        return ['summary', 'drift', 'overview', 'policy', 'uncovered', 'ransomware',
                'user', 'allowed', 'readiness', 'infrastructure', 'lateral', 'findings']
```

（若 Task 7 已先執行移除 `'allowed'`，以當時清單為準插入 `'drift'`。）

(d) `section_guidance.py` REGISTRY 加：

```python
    "mod_drift": SectionGuidance(
        module_id="mod_drift",
        purpose_key="rpt_guidance_mod_drift_purpose",
        watch_signals_key="rpt_guidance_mod_drift_signals",
        how_to_read_key="rpt_guidance_mod_drift_how",
        recommended_actions_key="rpt_guidance_mod_drift_actions",
        primary_audience="security",
        profile_visibility=("security_risk",),
        min_detail_level="full",
    ),
```

(e) i18n 兩檔（字母序插入）：

`src/i18n_en.json`：
```json
  "rpt_drift_baseline_from": "Baseline: previous report generated at",
  "rpt_drift_disappeared": "Disappeared Pairs (seen last period, absent now)",
  "rpt_drift_first_run": "No previous flow baseline — drift will appear from the next report onward.",
  "rpt_drift_new_pairs": "New App-to-App Pairs (not seen last period)",
  "rpt_guidance_mod_drift_actions": "Verify each new pair with the app owner; investigate unexpected new paths to databases or identity services first; confirm disappeared pairs are intentional decommissions.",
  "rpt_guidance_mod_drift_how": "New pairs are sorted by connection volume. '(unlabeled)' means the endpoint had no App Label in that period.",
  "rpt_guidance_mod_drift_purpose": "Detect changes in the app-to-app connection baseline between report runs — the earliest signal of intrusion, shadow change, or drift.",
  "rpt_guidance_mod_drift_signals": "New pairs touching databases, identity infrastructure, or high-risk Ports; large numbers of disappeared pairs after a policy change.",
  "rpt_tr_sec_drift": "Baseline Drift",
  "rpt_tr_sec_drift_intro": "Compare this period's app-to-app connections against the previous report to spot new paths and disappeared baselines.",
```

`src/i18n_zh_TW.json`：
```json
  "rpt_drift_baseline_from": "基準：前次報表產生於",
  "rpt_drift_disappeared": "消失的連線配對（上期有、本期無）",
  "rpt_drift_first_run": "尚無前期流量基準 — 從下一次報表開始顯示漂移。",
  "rpt_drift_new_pairs": "新出現的 App 對 App 連線（上期未見）",
  "rpt_guidance_mod_drift_actions": "逐一與應用負責人確認新配對；優先調查通往資料庫或身分服務的非預期新路徑；確認消失的配對屬計畫性下線。",
  "rpt_guidance_mod_drift_how": "新配對依連線量排序。「(unlabeled)」表示該端點當期沒有 App Label。",
  "rpt_guidance_mod_drift_purpose": "偵測兩次報表之間 App 對 App 連線基準的變化 — 入侵、影子變更與漂移的最早訊號。",
  "rpt_guidance_mod_drift_signals": "觸及資料庫、身分基礎設施或高風險 Port 的新配對；政策變更後大量消失的配對。",
  "rpt_tr_sec_drift": "基準漂移",
  "rpt_tr_sec_drift_intro": "將本期 App 對 App 連線與前次報表比對，找出新路徑與消失的基準。",
```

- [ ] **Step 7: 驗證**

Run: `./venv/bin/python -m pytest tests/test_mod_drift.py tests/ -q -k "exporter or drift or report_generator" 2>&1 | tail -2 && ./venv/bin/python scripts/audit_i18n_usage.py 2>&1 | tail -1`
Expected: 全 PASS；i18n 0 findings

- [ ] **Step 8: Commit**

```bash
git add src/report/analysis/mod_drift.py src/report/flow_history.py src/report/report_generator.py src/report/exporters/html_exporter.py src/report/section_guidance.py src/i18n_en.json src/i18n_zh_TW.json tests/test_mod_drift.py tests/test_flow_history.py
git commit -m "feat(report): baseline-drift section — new/disappeared app pairs vs previous run"
```

---

### Task 6: 標籤治理模組 + Inventory 報表區段

方法論階段一/二的缺口：標籤品質沒有任何模組度量。新模組從兩個來源評估：(1) workloads inventory（`fetch_managed_workloads`，best-effort）→ 未標籤 workload 清單與覆蓋率；(2) 流量 df → managed 端點缺標籤的流量占比、同一 IP 出現多組標籤的衝突。區段放 NetworkInventory profile。

**Files:**
- Create: `src/report/analysis/mod_labels.py`
- Modify: `src/report/report_generator.py`（`generate_from_api` 內、`_run_modules` 之後）
- Modify: `src/report/exporters/html_exporter.py`（`_sec`、`_mod_labels_html`、NetworkInventory `_ordered_section_keys`）
- Modify: `src/report/section_guidance.py`、`src/i18n_en.json`、`src/i18n_zh_TW.json`
- Test: `tests/test_mod_labels.py`（新檔）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_mod_labels.py
"""Label hygiene: unlabeled workloads, flow label coverage, conflicting labels."""
import pandas as pd

from src.report.analysis.mod_labels import label_hygiene

LABEL_KEYS = ("app", "env", "loc", "role")


def _workloads():
    def wl(hostname, labels):
        return {"hostname": hostname,
                "labels": [{"key": k, "value": v} for k, v in labels.items()]}
    return [
        wl("web01", {"app": "Web", "env": "Prod", "loc": "DC1", "role": "Web"}),
        wl("db01", {"app": "DB", "env": "Prod"}),          # 缺 loc, role
        wl("tmp01", {}),                                    # 全缺
    ]


def _flows():
    return pd.DataFrame([
        {"src_ip": "10.0.0.1", "src_app": "Web", "src_env": "Prod", "src_loc": "DC1", "src_role": "Web",
         "dst_ip": "10.0.0.2", "dst_app": "", "dst_env": "", "dst_loc": "", "dst_role": "",
         "src_managed": True, "dst_managed": True, "port": 443, "proto": "TCP", "num_connections": 5},
        {"src_ip": "10.0.0.1", "src_app": "Web2", "src_env": "Prod", "src_loc": "DC1", "src_role": "Web",
         "dst_ip": "8.8.8.8", "dst_app": "", "dst_env": "", "dst_loc": "", "dst_role": "",
         "src_managed": True, "dst_managed": False, "port": 53, "proto": "UDP", "num_connections": 2},
    ])


def test_workload_label_coverage():
    res = label_hygiene(_flows(), _workloads())
    assert res["workload_data_available"] is True
    assert res["total_workloads"] == 3
    assert res["fully_labeled_pct"] == round(1 / 3 * 100, 1)
    unl = res["unlabeled_workloads"]
    assert set(unl["Hostname"]) == {"db01", "tmp01"}
    assert "loc, role" in set(unl["Missing Keys"]) or "loc, role" in list(unl["Missing Keys"])


def test_flow_label_gap_counts_managed_only():
    res = label_hygiene(_flows(), _workloads())
    # dst 10.0.0.2 是 managed 且無標籤 → 算 gap；8.8.8.8 unmanaged 不算
    assert res["managed_unlabeled_flow_count"] == 1


def test_label_conflicts_detected():
    # 10.0.0.1 同 IP 出現兩組不同標籤（Web vs Web2）→ 衝突
    res = label_hygiene(_flows(), _workloads())
    conflicts = res["label_conflicts"]
    assert len(conflicts) == 1
    assert conflicts.iloc[0]["IP"] == "10.0.0.1"


def test_no_workloads_still_reports_flow_side():
    res = label_hygiene(_flows(), None)
    assert res["workload_data_available"] is False
    assert res["managed_unlabeled_flow_count"] == 1
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/test_mod_labels.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 實作 mod_labels.py**

```python
# src/report/analysis/mod_labels.py
"""Label hygiene — labeling quality metrics for microsegmentation governance.

Bad labels mean bad policy: this module measures (1) workload-inventory label
coverage (unlabeled VENs even when silent), (2) traffic from/to managed-but-
unlabeled endpoints, (3) endpoints observed with conflicting label sets.
PURE function: workloads list is fetched by the caller (best-effort).
"""
from __future__ import annotations

import pandas as pd

LABEL_KEYS = ("app", "env", "loc", "role")


def _workload_labels(wl: dict) -> dict[str, str]:
    out = {}
    for item in wl.get("labels") or []:
        if isinstance(item, dict) and item.get("key"):
            out[item["key"]] = item.get("value", "")
    return out


def _workload_metrics(workloads: list | None, top_n: int) -> dict:
    if not workloads:
        return {"workload_data_available": False}
    rows = []
    fully = 0
    for wl in workloads:
        labels = _workload_labels(wl)
        missing = [k for k in LABEL_KEYS if not labels.get(k)]
        if missing:
            rows.append({"Hostname": wl.get("hostname") or wl.get("name", ""),
                         "Missing Keys": ", ".join(missing)})
        else:
            fully += 1
    total = len(workloads)
    return {
        "workload_data_available": True,
        "total_workloads": total,
        "fully_labeled_count": fully,
        "fully_labeled_pct": round(fully / total * 100, 1) if total else 0.0,
        "unlabeled_workload_count": len(rows),
        "unlabeled_workloads": pd.DataFrame(rows[:top_n]),
        "chart_spec": {
            "type": "bar",
            "title_key": "rpt_labels_chart_title",
            "title": "Label Coverage",
            "data": {"labels": ["Fully labeled", "Missing labels"],
                     "values": [fully, len(rows)]},
        },
    }


def _flow_metrics(df: pd.DataFrame, top_n: int) -> dict:
    if df is None or df.empty:
        return {"managed_unlabeled_flow_count": 0,
                "label_conflicts": pd.DataFrame()}
    src_unlabeled = (df["src_managed"] == True) & (df["src_app"].fillna("") == "")  # noqa: E712
    dst_unlabeled = (df["dst_managed"] == True) & (df["dst_app"].fillna("") == "")  # noqa: E712
    gap_count = int((src_unlabeled | dst_unlabeled).sum())

    # 同一 managed IP 出現多組 (app,env,loc,role) → 標籤衝突
    frames = []
    for side in ("src", "dst"):
        sub = df[df[f"{side}_managed"] == True]  # noqa: E712
        if sub.empty:
            continue
        cols = [f"{side}_ip"] + [f"{side}_{k}" for k in LABEL_KEYS]
        part = sub[cols].copy()
        part.columns = ["IP"] + list(LABEL_KEYS)
        frames.append(part)
    conflicts = pd.DataFrame(columns=["IP", "Distinct Label Sets"])
    if frames:
        seen = pd.concat(frames, ignore_index=True).drop_duplicates()
        counts = seen.groupby("IP").size()
        bad_ips = counts[counts > 1]
        conflicts = pd.DataFrame({
            "IP": bad_ips.index.tolist(),
            "Distinct Label Sets": bad_ips.values.tolist(),
        }).head(top_n)
    return {"managed_unlabeled_flow_count": gap_count, "label_conflicts": conflicts}


def label_hygiene(df: pd.DataFrame, workloads: list | None, top_n: int = 20) -> dict:
    out = _workload_metrics(workloads, top_n)
    out.update(_flow_metrics(df, top_n))
    return out
```

注意 `rpt_labels_chart_title` 需在 Step 6 的 i18n 一併加入（chart_renderer 透過 `_resolve_chart_text` 用 `title_key` 取本地化標題）。

- [ ] **Step 4: 跑測試確認通過**

Run: `./venv/bin/python -m pytest tests/test_mod_labels.py -v`
Expected: 4 passed

- [ ] **Step 5: report_generator 注入**

`src/report/report_generator.py` `generate_from_api` 內、`_run_modules` 呼叫完成後（line ~615 的 modules 迴圈之後；先讀上下文找出 results 組裝點）加：

```python
        # Label hygiene (Inventory profile section): workloads fetch is best-effort.
        try:
            from src.report.analysis.mod_labels import label_hygiene
            _workloads = None
            if self.api is not None:
                _workloads = self.api.fetch_managed_workloads()
            results["mod_labels"] = label_hygiene(df, _workloads)
        except Exception as exc:  # noqa: BLE001 — hygiene must not break the report
            logger.warning("[Report] label hygiene skipped: {}", exc)
            results["mod_labels"] = {"workload_data_available": False,
                                     "managed_unlabeled_flow_count": 0}
```

`generate_from_csv` 路徑：同樣呼叫但 `_workloads = None`（CSV 模式無 API）。兩個路徑都要插（grep `_run_modules(` 找出所有呼叫點）。

- [ ] **Step 6: exporter 區段 + 導讀 + i18n**

(a) `html_exporter.py` 渲染方法：

```python
    def _mod_labels_html(self):
        _lang = self._lang
        m = self._r.get('mod_labels', {})
        parts = []
        if m.get('workload_data_available'):
            parts.append(
                f'<p class="section-intro">{t("rpt_labels_coverage", lang=_lang)}: '
                f'<b>{m.get("fully_labeled_pct", 0)}%</b> '
                f'({m.get("fully_labeled_count", 0)}/{m.get("total_workloads", 0)})</p>')
            parts.append(_render_chart_for_html(m.get('chart_spec'), lang=_lang))
            parts.append(f'<h3>{t("rpt_labels_unlabeled_workloads", lang=_lang)} '
                         f'({m.get("unlabeled_workload_count", 0)})</h3>')
            parts.append(_df_to_html(m.get('unlabeled_workloads'), lang=_lang))
        else:
            parts.append(f'<p class="note">{t("rpt_labels_no_inventory", lang=_lang)}</p>')
        parts.append(f'<h3>{t("rpt_labels_flow_gap", lang=_lang)}: '
                     f'{m.get("managed_unlabeled_flow_count", 0)}</h3>')
        conflicts = m.get('label_conflicts')
        if conflicts is not None and hasattr(conflicts, 'empty') and not conflicts.empty:
            parts.append(f'<h3>{t("rpt_labels_conflicts", lang=_lang)} ({len(conflicts)})</h3>')
            parts.append(_df_to_html(conflicts, lang=_lang))
        return ''.join(parts)
```

（`_render_chart_for_html` 的 `lang=` 參數簽名以 Task 3 完成後為準；若 Task 3 尚未執行，改為當下簽名。）

(b) `_sec` dict 加：

```python
            'labels': self._section('labels', 'rpt_tr_sec_labels', 'Label Hygiene',
                          render_section_guidance('mod_labels', profile=profile, detail_level=detail_level, lang=self._lang) + self._mod_labels_html(),
                          'rpt_tr_sec_labels_intro', 'Measure Label coverage and conflicts — labeling quality determines Policy quality.') + '\n',
```

(c) `NetworkInventoryHtmlExporter._ordered_section_keys`（line ~1528）在 `'overview'` 後插入 `'labels'`：

```python
        return ['summary', 'overview', 'labels', 'policy', 'matrix', 'unmanaged',
                'distribution', 'bandwidth', 'ringfence', 'change_impact']
```

(d) `section_guidance.py` REGISTRY 加：

```python
    "mod_labels": SectionGuidance(
        module_id="mod_labels",
        purpose_key="rpt_guidance_mod_labels_purpose",
        watch_signals_key="rpt_guidance_mod_labels_signals",
        how_to_read_key="rpt_guidance_mod_labels_how",
        recommended_actions_key="rpt_guidance_mod_labels_actions",
        primary_audience="platform",
        profile_visibility=("network_inventory",),
        min_detail_level="full",
    ),
```

(e) i18n 兩檔（字母序）：

`src/i18n_en.json`：
```json
  "rpt_guidance_mod_labels_actions": "Assign the missing Label keys on listed Workloads; resolve conflicting label sets at the source system; re-run the report to confirm coverage improves.",
  "rpt_guidance_mod_labels_how": "Coverage counts Workloads carrying all four keys (app/env/loc/role). Flow gap counts flows where a managed endpoint has no App Label. Conflicts list IPs observed with more than one label set.",
  "rpt_guidance_mod_labels_purpose": "Measure labeling quality — incomplete or conflicting Labels make Policy unreliable and block enforcement progress.",
  "rpt_guidance_mod_labels_signals": "Coverage below 90%; any conflict rows; a rising flow gap after onboarding new Workloads.",
  "rpt_labels_chart_title": "Label Coverage",
  "rpt_labels_conflicts": "Conflicting Label Sets per IP",
  "rpt_labels_coverage": "Fully-labeled Workloads",
  "rpt_labels_flow_gap": "Flows touching managed-but-unlabeled endpoints",
  "rpt_labels_no_inventory": "Workload inventory unavailable (CSV source or API error) — showing flow-derived metrics only.",
  "rpt_labels_unlabeled_workloads": "Workloads with Missing Label Keys",
  "rpt_tr_sec_labels": "Label Hygiene",
  "rpt_tr_sec_labels_intro": "Measure Label coverage and conflicts — labeling quality determines Policy quality.",
```

`src/i18n_zh_TW.json`：
```json
  "rpt_guidance_mod_labels_actions": "為清單中的 Workload 補齊缺少的 Label key；於來源系統解決標籤衝突；重新產出報表確認覆蓋率改善。",
  "rpt_guidance_mod_labels_how": "覆蓋率計算同時具備四個 key（app/env/loc/role）的 Workload。流量缺口計算 managed 端點缺 App Label 的流量。衝突清單列出被觀察到多組標籤的 IP。",
  "rpt_guidance_mod_labels_purpose": "度量標籤品質 — 不完整或互相衝突的 Label 會讓 Policy 不可靠並阻礙強制執行的推進。",
  "rpt_guidance_mod_labels_signals": "覆蓋率低於 90%；任何衝突列；新 Workload 上線後流量缺口上升。",
  "rpt_labels_chart_title": "Label 覆蓋率",
  "rpt_labels_conflicts": "同一 IP 的衝突 Label 組合",
  "rpt_labels_coverage": "完整標籤的 Workload",
  "rpt_labels_flow_gap": "涉及 managed 但未標籤端點的流量",
  "rpt_labels_no_inventory": "無法取得 Workload 清單（CSV 來源或 API 錯誤）— 僅顯示流量推導指標。",
  "rpt_labels_unlabeled_workloads": "缺少 Label key 的 Workload",
  "rpt_tr_sec_labels": "Label 治理",
  "rpt_tr_sec_labels_intro": "度量 Label 覆蓋率與衝突 — 標籤品質決定 Policy 品質。",
```

- [ ] **Step 7: 驗證**

Run: `./venv/bin/python -m pytest tests/test_mod_labels.py tests/ -q -k "exporter or label or report_generator" 2>&1 | tail -2 && ./venv/bin/python scripts/audit_i18n_usage.py 2>&1 | tail -1`
Expected: 全 PASS；i18n 0 findings

- [ ] **Step 8: Commit**

```bash
git add src/report/analysis/mod_labels.py src/report/report_generator.py src/report/exporters/html_exporter.py src/report/section_guidance.py src/i18n_en.json src/i18n_zh_TW.json tests/test_mod_labels.py
git commit -m "feat(report): label-hygiene section — coverage, unlabeled workloads, conflicting label sets"
```

---

### Task 7: mod10（Allowed Traffic）併入 mod02 區段

mod10 與 mod02 的 allowed 細分重疊；mod10 獨有價值是「allowed-from-unmanaged 稽核表」。把該表併入 `_mod02_html` 的 allowed 小節之後，SecurityRisk 移除獨立 `'allowed'` 章節。**模組本身保留**（CSV/XLSX 匯出與既有依賴不動）。

**Files:**
- Modify: `src/report/exporters/html_exporter.py:839-880`（`_mod02_html`）、`:1061-1077`（刪 `_mod10_html`）、`:652-654`（刪 `_sec['allowed']`）、`:1513`（SecurityRisk keys 移除 `'allowed'`）
- Test: 既有 exporter 測試 + 1 個新斷言

- [ ] **Step 1: 寫失敗測試（加到 `tests/test_html_exporter_static_charts.py` 末尾，或現有 exporter 測試檔）**

先 `grep -rln "SecurityRiskHtmlExporter" tests/` 找出已能組出完整報表 HTML 的既有測試 fixture，沿用其 module_results 構造；新增：

```python
def test_audit_flags_render_inside_policy_section(<沿用既有 fixture>):
    # 構造 mod02 + mod10（帶 audit_flags 一列）後 export，斷言：
    html = <render>
    assert 'id="allowed"' not in html                  # 獨立章節已移除
    assert 'rpt_tr_audit_flags' not in html            # i18n key 不洩漏
    assert '<h3' in html and 'Audit Flags' in html or '稽核' in html  # 表仍在（policy 區段內）
```

（依 fixture 實際語言調整斷言字串；核心是「audit flags 表存在但獨立 allowed 區段不存在」。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `./venv/bin/python -m pytest tests/ -q -k "audit_flags_render" -v`
Expected: FAIL（目前仍有獨立 allowed 區段）

- [ ] **Step 3: 實作**

(a) `_mod02_html`（line 874 的 return 之前）追加 mod10 稽核表：

```python
        # Folded in from the former standalone "Allowed Traffic" section:
        # allowed-from-unmanaged audit flags are the security-relevant remainder.
        m10 = self._r.get('mod10', {})
        flags = m10.get('audit_flags')
        if flags is not None and hasattr(flags, 'empty') and not flags.empty:
            table_html += (
                self._subnote('rpt_tr_audit_flags_subnote')
                + f'<h3>{_s("rpt_tr_audit_flags")} ({m10.get("audit_flag_count", 0)})</h3>'
                + _df_to_html(flags, lang=_lang)
            )
```

(b) 刪除 `_mod10_html` 方法（line 1061-1077）與 `_sec` dict 的 `'allowed'` 項（line 652-654）。

(c) `SecurityRiskHtmlExporter._ordered_section_keys` 移除 `'allowed'`（注意與 Task 5 插入 `'drift'` 的清單合流）：

```python
        return ['summary', 'drift', 'overview', 'policy', 'uncovered', 'ransomware',
                'user', 'readiness', 'infrastructure', 'lateral', 'findings']
```

(d) 檢查殘留：`grep -n "mod10\|'allowed'" src/report/exporters/html_exporter.py` — 除了 `_mod02_html` 內新增的引用外不應殘留；`render_section_guidance('mod10'...)` 呼叫一併刪除。mod10 模組與 registry **不動**。

- [ ] **Step 4: 跑測試確認通過**

Run: `./venv/bin/python -m pytest tests/ -q -k "exporter or mod02 or mod10" 2>&1 | tail -2`
Expected: 全 PASS（若有舊測試斷言 allowed 區段存在，更新它 — 那正是本任務目的）

- [ ] **Step 5: Commit**

```bash
git add src/report/exporters/html_exporter.py tests/
git commit -m "refactor(report): fold Allowed Traffic audit flags into Policy Decisions, drop standalone section"
```

---

## 完成後整體驗證

```bash
./venv/bin/python -m pytest tests/ -q                       # 全套件（基線 1716+，不得有新失敗）
./venv/bin/python scripts/audit_i18n_usage.py               # 0 findings
# lab PCE 實機（可選）：
./venv/bin/python illumio-ops.py report security --output-dir /tmp/review_reports
# 確認：檔案 <500KB、無 plotly.js、Baseline Drift 區段（首次顯示 first-run note）、
# 第二次產出後 drift 有資料；inventory 報表含 Label Hygiene 區段；導讀卡實際渲染。
```

## 後續（本計劃不含）

- **App-centric 報表 profile**（對齊 PCE App Group Summary，服務 app owner/稽核）— 與 P4 Teams 同捲設計，另開計劃。
- **V-E 弱掃整合輕量版**（弱掃 CSV × mod14/15 reachability）— 先決定匯入格式，另開計劃。
- chart_renderer.py:208 的 `get_language()` 同類洩漏（前次審查發現）— Task 3 改為呼叫端傳 lang 後，順帶確認 `_resolve_chart_text` 的 lang 傳遞鏈；若仍有殘留另開小修。

## Self-Review 紀錄

- 評估建議 → 任務對應：導讀卡 bug→T1、Plotly 靜態化→T2+T3、標籤治理→T6、基準漂移→T4+T5、mod10 併入→T7；App-centric 與 V-E 明確列為不含。
- 跨任務一致性：`render_matplotlib_svg`（T2 定義、T3 使用）、`build_signatures/save_signatures/load_previous_signatures`（T4 定義、T5 使用）、`_render_chart_for_html(spec, lang=...)`（T3 改簽名、T6 使用並註明以 T3 後簽名為準）、`_ordered_section_keys` 的 drift/allowed 合流（T5(c) 與 T7(c) 互相註記）。
- 不確定點均附現場確認指令而非留白：T3 的全 exporter grep、T5 Step 5 的 try 區塊定位、T6 Step 5 的 `_run_modules` 呼叫點 grep、T7 Step 1 的 fixture 沿用。
- `flow_history.UNLABELED` 命名（T5 Step 3 括號註記）：實作時統一為公開名，T4 測試同步。
