# 報表內容 v2（MITRE ATT&CK 對應 + V-E 弱掃整合輕量版）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 兩個報表內容增強：(1) Security Findings 補 MITRE ATT&CK technique 對應（SOC 溝通語言）；(2) 弱掃 CSV（Qualys/Tenable 匯出）× 既有流量可達性 → 「可達且有 CVE」的 V-E 輕量版區段。

**Architecture:** MITRE 對應是純資料表（rule_id → technique 清單）+ findings 渲染擴充，規則引擎本體不動。V-E 是新 parser（欄位別名容錯）+ 新純函式模組（IP join 流量入站可達性）+ CLI `--vuln-csv` 選項 + security profile 新區段。兩者互相獨立，可分開交付。

**Tech Stack:** Python / pandas / pytest；i18n 雙檔 + glossary；區段接線沿用 drift/labels 已建立的模式（_sec + _nav_spec + _ordered_section_keys + section_guidance REGISTRY + 導讀 i18n keys）。

**拍板的設計決策（執行前如不同意請先說）：**
1. MITRE 對應只到 **findings 卡片**（technique 晶片 + attack.mitre.org 連結）；mod12 攻擊摘要不動（YAGNI，v2 再說）。治理型規則（如 B005 低覆蓋率、R 系列 draft 規則）**不硬湊** technique，留空。
2. V-E 為 **CLI-only**（`--vuln-csv`），GUI 上傳留待下一版。
3. 「可達」定義：該 IP 在報表期間內出現為**非 blocked 流量的目的端**（dst_ip）。不做圖論路徑推導（mod14/15 的 reachability 是 app 層，IP join 直接用流量事實更可靠）。

**執行環境：** worktree + venv symlink。基線 `./venv/bin/python -m pytest tests/ -q` → 1740 passed, 5 skipped（以執行當下 main 為準）。

---

## 已驗證事實

| 事實 | 出處 |
|------|------|
| `Finding` dataclass（可變）欄位：rule_id/rule_name/severity/category/description/recommendation/evidence — 無 technique 欄 | src/report/rules/_base.py:17-40 |
| findings 卡渲染於 `_findings_html`，rule_id 晶片在 ~line 1208 `finding-rule-id` span | src/report/exporters/html_exporter.py:1156-1230 |
| 內建規則：B001-B009 + L001-L010（rules_engine.py 內），R01-R05（rules/ 目錄） | rules_engine.py、rules/__init__.py |
| CLI security 命令選項模式（keyword args、--output-dir 等） | src/cli/report.py:56-102 |
| 流量 df 欄位：dst_ip / policy_decision / num_connections / src_app / dst_app | parsers/api_parser.py:73-116 |
| 新區段接線完整模式（_sec/_nav_spec/_ordered_section_keys/guidance/i18n） | git show 889dc07（drift）為範本 |
| `_run_pipeline(df, source, ...)` 內可注入模組結果（mod_labels 模式，lang 可得） | report_generator.py:536-577 |

## 檔案結構

```
src/report/analysis/mitre_map.py        # T1: rule_id → technique 對應表（純資料）
src/report/rules/_base.py               # T2: Finding 加 technique_ids 欄位
src/report/rules_engine.py              # T2: evaluate() 後標註
src/report/exporters/html_exporter.py   # T3: findings 卡 technique 晶片；T6: vuln 區段
src/report/parsers/vuln_csv.py          # T4: 弱掃 CSV parser（欄位別名）
src/report/analysis/mod_vuln.py         # T5: V-E 輕量模組（純函式）
src/report/report_generator.py          # T6: vuln_csv 參數 + 注入
src/cli/report.py                       # T6: --vuln-csv
src/report/section_guidance.py          # T6: mod_vuln 導讀
src/i18n_en.json, src/i18n_zh_TW.json   # T3/T6
tests/test_mitre_map.py / test_vuln_csv_parser.py / test_mod_vuln.py  # 新測試
```

---

### Task 1: MITRE 對應表（純資料模組）

**Files:** Create `src/report/analysis/mitre_map.py`；Test `tests/test_mitre_map.py`

- [ ] **Step 1（先盤點實際規則 id）:** `grep -n "rule_id=\|RULE_ID\|'B0\|'L0" src/report/rules_engine.py | head -30` 與 `ls src/report/rules/` — 列出全部實際 rule_id（B001-B009、L001-L010、R01-R05 的確切字串）。
- [ ] **Step 2（失敗測試）:**

```python
# tests/test_mitre_map.py
"""Every mapped technique id is well-formed; governance rules stay unmapped."""
import re

from src.report.analysis.mitre_map import RULE_TECHNIQUES, techniques_for

_TID = re.compile(r"^T\d{4}(\.\d{3})?$")


def test_all_technique_ids_well_formed():
    for rule_id, techs in RULE_TECHNIQUES.items():
        for tid, name in techs:
            assert _TID.match(tid), f"{rule_id}: bad technique id {tid}"
            assert name


def test_lookup_known_and_unknown():
    assert techniques_for("B006")          # lateral movement 必有對應
    assert techniques_for("B005") == ()    # 治理型規則不對應
    assert techniques_for("NOPE") == ()
```

- [ ] **Step 3（實作）:**

```python
# src/report/analysis/mitre_map.py
"""Static MITRE ATT&CK technique mapping for built-in findings rules.

Pure data. Governance rules (coverage/policy-hygiene: B005, L008, R01-R05)
intentionally map to () — forcing a technique onto them would mislead SOC
readers. Update alongside rules_engine when rules change.
"""
from __future__ import annotations

RULE_TECHNIQUES: dict[str, tuple[tuple[str, str], ...]] = {
    # B-series — ransomware / coverage / behavioral
    "B001": (("T1486", "Data Encrypted for Impact"), ("T1021.002", "SMB/Windows Admin Shares")),
    "B002": (("T1486", "Data Encrypted for Impact"), ("T1021.001", "Remote Desktop Protocol")),
    "B003": (("T1486", "Data Encrypted for Impact"),),
    "B004": (("T1046", "Network Service Discovery"),),
    # B005 low policy coverage — governance, unmapped
    "B006": (("T1021", "Remote Services"),),
    "B007": (("T1078", "Valid Accounts"),),
    "B008": (("T1048", "Exfiltration Over Alternative Protocol"),),
    "B009": (("T1570", "Lateral Tool Transfer"),),
    # L-series — lateral movement family
    "L001": (("T1040", "Network Sniffing"),),                       # cleartext services
    "L002": (("T1046", "Network Service Discovery"),),              # legacy discovery
    "L003": (("T1210", "Exploitation of Remote Services"),),        # database exposure
    "L004": (("T1558", "Steal or Forge Kerberos Tickets"),),        # identity infrastructure
    "L005": (("T1021", "Remote Services"),),                        # graph reachability
    "L006": (("T1090", "Proxy"),),                                  # unmanaged pivot
    "L007": (("T1210", "Exploitation of Remote Services"),),        # unmanaged → critical services
    # L008 enforcement gap — governance, unmapped
    "L009": (("T1048", "Exfiltration Over Alternative Protocol"),),
    "L010": (("T1041", "Exfiltration Over C2 Channel"),),
}


def techniques_for(rule_id: str) -> tuple[tuple[str, str], ...]:
    return RULE_TECHNIQUES.get(rule_id, ())
```

依 Step 1 盤點結果核對：每個實際存在的 rule_id 若語意與上表註解不符（例如 L004 不是 identity），**以 rules_engine 內該規則的實際語意修正對應**並在報告列出修改；map 中不存在於引擎的 id 移除。
- [ ] **Step 4:** 測試 passed。Commit `feat(report): MITRE ATT&CK technique map for built-in finding rules`

### Task 2: Finding 標註 technique_ids

**Files:** Modify `src/report/rules/_base.py:17-40`、`src/report/rules_engine.py`（evaluate 收尾處）；Test 加到 `tests/test_mitre_map.py`

- [ ] **Step 1（失敗測試）:**

```python
def test_findings_annotated_with_techniques():
    from src.report.rules._base import Finding
    f = Finding(rule_id="B006", rule_name="x", severity="HIGH", category="lateral",
                description="d", recommendation="r")
    assert f.technique_ids == ()  # 預設空

    from src.report.rules_engine import annotate_techniques
    out = annotate_techniques([f])
    assert out[0].technique_ids == (("T1021", "Remote Services"),)
```

- [ ] **Step 2（實作）:** `_base.py` Finding 加欄位 `technique_ids: tuple = ()`（放在 evidence 之後，預設值殿後）。rules_engine.py 加模組層函式並在 `evaluate()` 回傳前套用：

```python
def annotate_techniques(findings: list) -> list:
    """Attach MITRE technique tuples to findings (pure, in-place safe)."""
    from src.report.analysis.mitre_map import techniques_for
    for f in findings:
        f.technique_ids = techniques_for(f.rule_id)
    return findings
```

（`evaluate()` 的 return 行改 `return annotate_techniques(findings)` — 先讀該函式確認回傳點。）
- [ ] **Step 3:** 測試 + `pytest -k "rules or finding" | tail -1` 無新失敗。Commit `feat(report): findings carry MITRE technique ids`

### Task 3: Findings 卡渲染 technique 晶片

**Files:** Modify `src/report/exporters/html_exporter.py`（_findings_html ~1208）、`src/report/exporters/report_css.py`、i18n 兩檔；Test 加到 `tests/test_html_exporter_static_charts.py`

- [ ] **Step 1（失敗測試）:** 用該檔既有的 e2e fixture，注入一個帶 `technique_ids=(("T1021","Remote Services"),)` 的 finding，斷言 HTML 含 `mitre-chip`、`T1021`、`href="https://attack.mitre.org/techniques/T1021/"`。
- [ ] **Step 2（實作）:** `_findings_html` 的 rule-id span（~1208）之後插入：

```python
                tech_html = ''.join(
                    f'<a class="mitre-chip" target="_blank" rel="noopener" '
                    f'href="https://attack.mitre.org/techniques/{tid.replace(".", "/")}/" '
                    f'title="{_esc_attr(name)}">{tid}</a>'
                    for tid, name in getattr(f, "technique_ids", ()) or ()
                )
```

（`_esc_attr`：用該檔既有的 escape helper 名稱；晶片接在 finding-header 內 rule-id 旁。）CSS（report_css.py）加：

```css
.mitre-chip{display:inline-block;font-size:10px;padding:1px 6px;border:1px solid var(--border,#d1d5db);border-radius:9px;margin-left:4px;text-decoration:none;color:inherit;}
```

i18n：無新文字 key（technique 名稱為官方英文，不翻譯 — 在報告註明此決策）。
- [ ] **Step 3:** 測試 + `pytest -k "exporter" | tail -1`。Commit `feat(report): MITRE technique chips on finding cards (linked to attack.mitre.org)`

### Task 4: 弱掃 CSV parser

**Files:** Create `src/report/parsers/vuln_csv.py`；Test `tests/test_vuln_csv_parser.py`

- [ ] **Step 1（失敗測試）:**

```python
# tests/test_vuln_csv_parser.py
"""Vuln CSV ingest: column aliases (Qualys/Tenable exports), normalization."""
import pandas as pd
import pytest

from src.report.parsers.vuln_csv import load_vulns


def _write(tmp_path, text):
    p = tmp_path / "v.csv"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_generic_columns(tmp_path):
    df = load_vulns(_write(tmp_path, "ip,cve_id,severity,cvss\n10.0.0.5,CVE-2024-1234,High,8.1\n"))
    assert list(df.columns) == ["ip", "cve_id", "severity", "cvss"]
    assert df.iloc[0]["cve_id"] == "CVE-2024-1234"
    assert df.iloc[0]["cvss"] == 8.1


def test_tenable_aliases(tmp_path):
    df = load_vulns(_write(tmp_path, "IP Address,CVE,Risk,CVSS V3 Base Score\n10.0.0.5,CVE-2024-1,Critical,9.8\n"))
    assert df.iloc[0]["ip"] == "10.0.0.5" and df.iloc[0]["severity"] == "Critical"


def test_missing_required_column_raises(tmp_path):
    with pytest.raises(ValueError, match="ip"):
        load_vulns(_write(tmp_path, "host,cve_id\nh1,CVE-1\n"))


def test_rows_without_cve_dropped(tmp_path):
    df = load_vulns(_write(tmp_path, "ip,cve_id\n10.0.0.5,\n10.0.0.6,CVE-2024-2\n"))
    assert len(df) == 1
```

- [ ] **Step 2（實作）:**

```python
# src/report/parsers/vuln_csv.py
"""Vulnerability-scan CSV ingest for the V-E lite report section.

Accepts generic exports plus common Qualys/Tenable column names via alias
matching (case-insensitive). Required: an IP column and a CVE column.
Output schema: DataFrame[ip, cve_id, severity, cvss].
"""
from __future__ import annotations

import pandas as pd

_ALIASES = {
    "ip": ("ip", "ip address", "ip_address", "asset ip", "host ip", "ipv4"),
    "cve_id": ("cve_id", "cve", "cve id", "cveid", "vulnerability id"),
    "severity": ("severity", "risk", "risk factor", "vuln severity"),
    "cvss": ("cvss", "cvss v3 base score", "cvss3 base score", "cvss base score", "cvss_score"),
}


def _pick(columns: list[str], aliases: tuple[str, ...]) -> str | None:
    lowered = {c.lower().strip(): c for c in columns}
    for a in aliases:
        if a in lowered:
            return lowered[a]
    return None


def load_vulns(path: str) -> pd.DataFrame:
    raw = pd.read_csv(path, dtype=str)
    cols = list(raw.columns)
    picked = {std: _pick(cols, aliases) for std, aliases in _ALIASES.items()}
    for required in ("ip", "cve_id"):
        if picked[required] is None:
            raise ValueError(f"vuln CSV missing a recognizable '{required}' column "
                             f"(accepted: {', '.join(_ALIASES[required])})")
    out = pd.DataFrame({
        "ip": raw[picked["ip"]].fillna("").str.strip(),
        "cve_id": raw[picked["cve_id"]].fillna("").str.strip(),
        "severity": raw[picked["severity"]].fillna("") if picked["severity"] else "",
        "cvss": pd.to_numeric(raw[picked["cvss"]], errors="coerce") if picked["cvss"] else None,
    })
    out = out[(out["ip"] != "") & (out["cve_id"] != "")].reset_index(drop=True)
    return out
```

- [ ] **Step 3:** 測試 4 passed。Commit `feat(report): vulnerability-scan CSV parser with Qualys/Tenable column aliases`

### Task 5: V-E 輕量模組

**Files:** Create `src/report/analysis/mod_vuln.py`；Test `tests/test_mod_vuln.py`

- [ ] **Step 1（失敗測試）:**

```python
# tests/test_mod_vuln.py
"""V-E lite: vulnerable IPs that are reachable (non-blocked inbound) ranked by exposure."""
import pandas as pd

from src.report.analysis.mod_vuln import vuln_exposure


def _flows():
    return pd.DataFrame([
        {"src_ip": "10.0.0.1", "src_app": "Web", "dst_ip": "10.0.0.5", "dst_app": "DB",
         "port": 3306, "proto": "TCP", "policy_decision": "allowed", "num_connections": 9},
        {"src_ip": "10.0.0.2", "src_app": "Batch", "dst_ip": "10.0.0.5", "dst_app": "DB",
         "port": 3306, "proto": "TCP", "policy_decision": "potentially_blocked", "num_connections": 3},
        {"src_ip": "10.0.0.3", "src_app": "X", "dst_ip": "10.0.0.7", "dst_app": "Y",
         "port": 22, "proto": "TCP", "policy_decision": "blocked", "num_connections": 5},
    ])


def _vulns():
    return pd.DataFrame([
        {"ip": "10.0.0.5", "cve_id": "CVE-2024-1", "severity": "Critical", "cvss": 9.8},
        {"ip": "10.0.0.7", "cve_id": "CVE-2024-2", "severity": "High", "cvss": 8.0},   # 只被 blocked 流量觸及
        {"ip": "10.9.9.9", "cve_id": "CVE-2024-3", "severity": "Low", "cvss": 2.0},    # 無流量
    ])


def test_only_reachable_vulns_exposed():
    res = vuln_exposure(_flows(), _vulns())
    assert res["available"] is True
    exposed = res["exposed"]
    assert list(exposed["IP"]) == ["10.0.0.5"]          # 10.0.0.7 blocked-only、10.9.9.9 無流量
    row = exposed.iloc[0]
    assert row["CVE"] == "CVE-2024-1"
    assert row["Inbound Sources"] == 2                   # 兩個不同 src_ip（allowed+pb 都算可達）
    assert row["Dst App"] == "DB"


def test_summary_counts():
    res = vuln_exposure(_flows(), _vulns())
    assert res["total_vulns"] == 3
    assert res["exposed_count"] == 1
    assert res["unreached_count"] == 2


def test_empty_vulns_unavailable():
    assert vuln_exposure(_flows(), None)["available"] is False
    assert vuln_exposure(_flows(), pd.DataFrame())["available"] is False
```

- [ ] **Step 2（實作）:**

```python
# src/report/analysis/mod_vuln.py
"""V-E lite — vulnerable assets that are actually reachable east-west.

Joins a vulnerability-scan CSV (ip, cve_id, severity, cvss) against observed
traffic: a vuln is "exposed" when its IP appears as the DESTINATION of any
non-blocked flow in the report window. Pure function; ranking favours
severity (cvss) and inbound source breadth — the analyst's patch-first list.
"""
from __future__ import annotations

import pandas as pd

_SEV_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def vuln_exposure(df: pd.DataFrame, vulns: pd.DataFrame | None, top_n: int = 25) -> dict:
    if vulns is None or vulns.empty:
        return {"available": False}

    reach = pd.DataFrame(columns=["dst_ip", "dst_app", "Inbound Sources", "Inbound Connections", "Top Ports"])
    if df is not None and not df.empty:
        nb = df[df["policy_decision"].astype(str) != "blocked"]
        if not nb.empty:
            grp = nb.groupby("dst_ip")
            reach = pd.DataFrame({
                "dst_ip": grp.size().index,
                "dst_app": grp["dst_app"].first().values,
                "Inbound Sources": grp["src_ip"].nunique().values,
                "Inbound Connections": grp["num_connections"].sum().values,
                "Top Ports": grp["port"].apply(
                    lambda s: ", ".join(str(p) for p in s.value_counts().head(3).index)).values,
            })

    joined = vulns.merge(reach, left_on="ip", right_on="dst_ip", how="left")
    exposed = joined[joined["dst_ip"].notna()].copy()
    exposed["_sev"] = exposed["severity"].astype(str).str.lower().map(_SEV_RANK).fillna(0)
    exposed["_cvss"] = pd.to_numeric(exposed["cvss"], errors="coerce").fillna(0)
    exposed = exposed.sort_values(["_sev", "_cvss", "Inbound Sources"], ascending=False)

    table = pd.DataFrame({
        "IP": exposed["ip"], "CVE": exposed["cve_id"], "Severity": exposed["severity"],
        "CVSS": exposed["cvss"], "Dst App": exposed["dst_app"].fillna(""),
        "Inbound Sources": exposed["Inbound Sources"].astype(int),
        "Inbound Connections": exposed["Inbound Connections"].astype(int),
        "Top Ports": exposed["Top Ports"],
    }).head(top_n).reset_index(drop=True)

    return {
        "available": True,
        "total_vulns": int(len(vulns)),
        "exposed_count": int(exposed["ip"].nunique() and len(exposed)),
        "unreached_count": int(len(vulns) - len(exposed)),
        "exposed": table,
        "chart_spec": {
            "type": "bar",
            "title_key": "rpt_vuln_chart_title",
            "title": "Exposed vs Unreached Vulnerabilities",
            "data": {"labels": ["Exposed", "Unreached"],
                     "values": [int(len(exposed)), int(len(vulns) - len(exposed))]},
        },
    }
```

（`exposed_count` 語意 = exposed 列數；測試以此為準。chart data labels 比照 mod_labels 模式以 t() 本地化 — 加 `lang` 參數與 `rpt_vuln_chart_exposed`/`rpt_vuln_chart_unreached` keys，實作時直接做，與 mod_labels 097f1da 同 pattern。）
- [ ] **Step 3:** 測試 passed。Commit `feat(report): V-E lite module — reachable vulnerable assets ranked for patching`

### Task 6: CLI --vuln-csv + security profile 區段

**Files:** Modify `src/cli/report.py`（security 命令）、`src/report/report_generator.py`、`src/report/exporters/html_exporter.py`、`src/report/section_guidance.py`、i18n 兩檔；Test：e2e 斷言加到 `tests/test_mod_vuln.py`

- [ ] **Step 1:** CLI：security 命令（src/cli/report.py，沿用既有選項 decorator 風格）加 `--vuln-csv PATH`（type=click.Path(exists=True), default None, help "Vulnerability-scan CSV (ip + cve columns; Qualys/Tenable exports accepted) for the V-E exposure section."），傳入 generator（generate 函式簽名加 `vuln_csv_path: str | None = None`）。
- [ ] **Step 2:** report_generator：`generate_from_api`/`generate_from_csv` 簽名加 `vuln_csv_path=None` 並存 `self._vuln_csv_path`；`_run_pipeline` 在 mod_labels 注入旁加（同 try/except warning 模式）：

```python
        if getattr(self, "_vuln_csv_path", None):
            try:
                from src.report.parsers.vuln_csv import load_vulns
                from src.report.analysis.mod_vuln import vuln_exposure
                results["mod_vuln"] = vuln_exposure(df, load_vulns(self._vuln_csv_path), lang=lang)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[Report] vuln exposure skipped: {exc}")
                results["mod_vuln"] = {"available": False}
```

- [ ] **Step 3:** exporter（鏡像 drift 接線）：`_mod_vuln_html`（available=False 且未提供 CSV 時整節不渲染 — `_sec['vuln']` 在 `self._r.get('mod_vuln') is None` 時設 `''`；有 mod_vuln 才渲染卡 + 表）；`_sec['vuln']`、`_nav_spec['vuln']`、SecurityRisk `_ordered_section_keys` 在 `'ransomware'` 後插 `'vuln'`；guidance REGISTRY `mod_vuln`（security_risk only）。
- [ ] **Step 4:** i18n 兩檔（en/zh，glossary 注意 CVE/CVSS/IP 保留原文）：`rpt_tr_sec_vuln`: "Vulnerability Exposure (V-E lite)" / "弱點暴露（V-E lite）"、`rpt_tr_sec_vuln_intro`、`rpt_tr_nav_vuln`、`rpt_vuln_chart_title`、`rpt_vuln_chart_exposed`、`rpt_vuln_chart_unreached`、`rpt_vuln_exposed_table`: "Reachable Vulnerable Assets" / "可達的弱點資產"、`rpt_vuln_summary`: "{exposed} of {total} vulnerable assets are reachable east-west" / "{total} 個弱點資產中有 {exposed} 個可由東西向流量觸及"、guidance 4 keys（purpose/signals/how/actions，內容比照 drift 寫法：目的=把修補優先序對齊實際可達性；訊號=Critical 且 Inbound Sources 高；怎麼讀=排序邏輯；行動=優先修補或以 Policy 圍堵）。
- [ ] **Step 5（e2e）:** tests/test_mod_vuln.py 加一個走真 export 的測試（仿 test_drift_section_reaches_html_output fixture）：generator 設 `_vuln_csv_path` 指向 tmp CSV → export html → 斷言 `id="vuln"` 與 "CVE-2024-1" 在 HTML；未設路徑時 `id="vuln"` 不出現。
- [ ] **Step 6:** 全驗證：`pytest -k "vuln or mitre or exporter" -q | tail -1`、i18n audit 0、glossary 測試 passed、全套件無新失敗。
- [ ] **Step 7:** Commit `feat(report): --vuln-csv V-E lite section in the security report`

---

## 完成後整體驗證

```bash
./venv/bin/python -m pytest tests/ -q && ./venv/bin/python scripts/audit_i18n_usage.py
# lab：./venv/bin/python illumio-ops.py report security --vuln-csv /tmp/test_vulns.csv --output-dir /tmp/x
#（用 lab 真 IP 做 3 列 CSV）→ HTML 有 V-E 區段；findings 卡有 MITRE 晶片可點。
```

## Self-Review 紀錄
- F 對應 T1-T3、B 對應 T4-T6；三個拍板決策列於開頭供執行前否決。
- T1 Step 1 強制先盤點實際 rule_id 再核對對應表（語意不符以引擎為準），避免我憑描述推測的 L 系列對應出錯。
- mod_vuln 的 `exposed_count` 語意已在程式碼註記與測試對齊（列數，非去重 IP 數）。
