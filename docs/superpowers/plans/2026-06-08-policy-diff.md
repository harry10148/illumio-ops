# Policy Diff (DRAFT vs ACTIVE) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give operators a git-like, field-level diff between the DRAFT and ACTIVE security policy — scoped to Rulesets and Rules only — with operator attribution sourced from the existing audit-events pipeline, surfaced as a new report module wired into CLI `report` and the scheduler.

**Architecture:** A pure diff engine (`diff_rulesets`) aligns the two already-fetched ruleset lists by stable id and emits added/removed/modified rows per field. A pure attribution function (`attribute_changes`) decorates those rows with the most-recent operator/time, reusing `audit_policy_changes` over the existing `AuditGenerator` event DataFrame. A `PolicyDiffReport` facade (mirroring `SecurityRiskReport`) fetches draft+active rulesets, runs the diff, attributes it, and exports HTML (new exporter) + CSV (reuse `CsvExporter` unchanged). CLI gets `report policy-diff`; the scheduler gets a `policy_diff` dispatch branch plus prune-prefix + email-subject wiring mirroring commit ff93df9.

**Tech Stack:** Python 3.10+, pandas, pytest, click (CLI), JSON i18n (EN + ZH_TW). No new PCE endpoints — draft and active rule_sets are both already fetchable.

**Spec:** `docs/superpowers/specs/2026-06-08-policy-diff-design.md`

**Verified repo facts grounding this plan:**
1. `api_client.get_all_rulesets(force_refresh=False)` → `/sec_policy/draft/rule_sets`; `api_client.get_active_rulesets()` → `/sec_policy/active/rule_sets`. **Both draft and active are fetchable; no new fetch method is needed.**
2. `audit_policy_changes(df)` (`src/report/analysis/audit/audit_mod03_policy.py:81`) returns `draft_events` (DataFrame with `timestamp / event_type / resource_name / actor / change_detail`) — the attribution source.
3. `AuditGenerator(cm, api_client, config_dir, cache_reader=...)._fetch_events()` + `._build_dataframe()` produce the normalized events DataFrame.
4. `CsvExporter(results, report_label).export(output_dir)` walks any nested dict of DataFrames — **reused unchanged**.
5. Scheduler wiring mirrors ff93df9: `_generate_report` dispatch (`report_scheduler.py:248`), `_REPORT_PREFIXES` (line 469), email `type_label` (line 322).

---

### Task 1: Core diff engine — `diff_rulesets`

**Files:**
- Create: `src/report/analysis/policy_diff/__init__.py`
- Create: `src/report/analysis/policy_diff/diff_engine.py`
- Test: `tests/test_policy_diff_engine.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_policy_diff_engine.py`:

```python
"""Tests for the DRAFT-vs-ACTIVE policy diff engine (pure, no I/O)."""
from __future__ import annotations

from src.report.analysis.policy_diff.diff_engine import diff_rulesets


def _rs(rs_id, name, rules, enabled=True, description=""):
    return {
        "href": f"/orgs/1/sec_policy/draft/rule_sets/{rs_id}",
        "name": name,
        "enabled": enabled,
        "description": description,
        "rules": rules,
    }


def _rule(rule_id, *, enabled=True, providers=None, consumers=None, services=None):
    return {
        "href": f"/orgs/1/sec_policy/draft/rule_sets/9/sec_rules/{rule_id}",
        "enabled": enabled,
        "providers": providers or [],
        "consumers": consumers or [],
        "ingress_services": services or [],
    }


def test_added_and_removed_rulesets():
    draft = [_rs(1, "RS-A", []), _rs(2, "RS-NEW", [])]
    active = [_rs(1, "RS-A", []), _rs(3, "RS-GONE", [])]
    out = diff_rulesets(draft, active)
    rs = out["ruleset_changes"]
    changes = {(r["change_type"], r["ruleset_name"]) for r in rs.to_dict("records")}
    assert ("added", "RS-NEW") in changes
    assert ("removed", "RS-GONE") in changes
    assert out["summary"]["rulesets_added"] == 1
    assert out["summary"]["rulesets_removed"] == 1


def test_modified_ruleset_field_level():
    draft = [_rs(1, "RS-A", [], enabled=False)]
    active = [_rs(1, "RS-A", [], enabled=True)]
    out = diff_rulesets(draft, active)
    rows = out["ruleset_changes"].to_dict("records")
    enabled_rows = [r for r in rows if r["field"] == "enabled"]
    assert len(enabled_rows) == 1
    assert enabled_rows[0]["change_type"] == "modified"
    assert enabled_rows[0]["draft_value"] == "False"
    assert enabled_rows[0]["active_value"] == "True"


def test_modified_rule_provider_change():
    d_rule = _rule(5, providers=[{"label": {"href": "/labels/100"}}])
    a_rule = _rule(5, providers=[{"label": {"href": "/labels/200"}}])
    draft = [_rs(9, "RS-R", [d_rule])]
    active = [_rs(9, "RS-R", [a_rule])]
    out = diff_rulesets(draft, active)
    rows = out["rule_changes"].to_dict("records")
    prov_rows = [r for r in rows if r["field"] == "providers"]
    assert len(prov_rows) == 1
    assert "/labels/100" in prov_rows[0]["draft_value"]
    assert "/labels/200" in prov_rows[0]["active_value"]
    assert out["summary"]["rules_modified"] == 1


def test_provider_order_is_not_a_false_diff():
    items_a = [{"label": {"href": "/labels/1"}}, {"label": {"href": "/labels/2"}}]
    items_b = [{"label": {"href": "/labels/2"}}, {"label": {"href": "/labels/1"}}]
    draft = [_rs(9, "RS-R", [_rule(5, providers=items_a)])]
    active = [_rs(9, "RS-R", [_rule(5, providers=items_b)])]
    out = diff_rulesets(draft, active)
    assert out["summary"]["rules_modified"] == 0


def test_empty_inputs_return_valid_empty_structure():
    out = diff_rulesets([], [])
    assert out["summary"]["total_changes"] == 0
    assert out["ruleset_changes"].empty
    assert out["rule_changes"].empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_diff_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.report.analysis.policy_diff'`.

- [ ] **Step 3: Create the package init**

Create `src/report/analysis/policy_diff/__init__.py`:

```python
"""DRAFT-vs-ACTIVE policy diff analysis (Ruleset/Rule scope only)."""
```

- [ ] **Step 4: Write the diff engine**

Create `src/report/analysis/policy_diff/diff_engine.py`:

```python
"""DRAFT-vs-ACTIVE policy diff engine.

PURE derivation (no I/O). Aligns draft and active ruleset lists by stable id
and emits field-level added/removed/modified rows. Scope is Ruleset/Rule ONLY
(IP lists, services, label groups, virtual services, firewall settings are out
of scope for v1). Diff semantics are "DRAFT relative to ACTIVE":
  - added    = id present only in draft (will be created on provision)
  - removed  = id present only in active (will be deleted on provision)
  - modified = id in both, but a whitelisted field differs
"""
from __future__ import annotations

import pandas as pd

_RULESET_COLS = ["change_type", "ruleset_name", "ruleset_id",
                 "field", "draft_value", "active_value",
                 "last_actor", "last_changed", "last_event"]
_RULE_COLS = ["change_type", "ruleset_name", "rule_id",
              "field", "draft_value", "active_value",
              "last_actor", "last_changed", "last_event"]


def _id_from_href(href: str) -> str:
    return str(href or "").rstrip("/").split("/")[-1]


def _summarize_actors(items: list) -> str:
    """Order-stable string summary of a providers/consumers/services list."""
    if not items:
        return "(any)"
    tokens = []
    for it in items:
        if not isinstance(it, dict):
            tokens.append(str(it))
            continue
        if it.get("actors"):
            tokens.append(f"actors:{it['actors']}")
        elif isinstance(it.get("label"), dict) and it["label"].get("href"):
            tokens.append(f"label:{it['label']['href']}")
        elif isinstance(it.get("ip_list"), dict) and it["ip_list"].get("href"):
            tokens.append(f"ip_list:{it['ip_list']['href']}")
        elif isinstance(it.get("workload"), dict) and it["workload"].get("href"):
            tokens.append(f"workload:{it['workload']['href']}")
        elif it.get("proto") is not None or it.get("port") is not None:
            tokens.append(f"svc:{it.get('proto')}/{it.get('port')}")
        elif isinstance(it.get("href"), str):
            tokens.append(f"svc:{it['href']}")
        else:
            tokens.append(str(sorted(it.items())))
    return ", ".join(sorted(tokens))


def _ruleset_fields(rs: dict) -> dict:
    return {
        "name": str(rs.get("name", "")),
        "enabled": str(rs.get("enabled", True)),
        "description": str(rs.get("description", "") or ""),
        "rule_count": str(len(rs.get("rules", []) or [])),
    }


def _rule_fields(rule: dict) -> dict:
    return {
        "enabled": str(rule.get("enabled", True)),
        "providers": _summarize_actors(rule.get("providers", []) or []),
        "consumers": _summarize_actors(rule.get("consumers", []) or []),
        "ingress_services": _summarize_actors(rule.get("ingress_services", []) or []),
    }


def _index_by_id(rulesets: list) -> dict:
    return {_id_from_href(rs.get("href", "")): rs for rs in (rulesets or []) if rs.get("href")}


def _index_rules(rs: dict) -> dict:
    out = {}
    for rule in rs.get("rules", []) or []:
        if rule.get("href"):
            out[_id_from_href(rule["href"])] = rule
    return out


def diff_rulesets(draft: list[dict], active: list[dict]) -> dict:
    draft_idx = _index_by_id(draft)
    active_idx = _index_by_id(active)

    rs_rows: list[dict] = []
    rule_rows: list[dict] = []
    s = {"rulesets_added": 0, "rulesets_removed": 0, "rulesets_modified": 0,
         "rules_added": 0, "rules_removed": 0, "rules_modified": 0}

    def _blank():
        return {"last_actor": "", "last_changed": "", "last_event": ""}

    # ── Ruleset-level ────────────────────────────────────────────────────────
    for rs_id in draft_idx.keys() - active_idx.keys():
        rs = draft_idx[rs_id]
        s["rulesets_added"] += 1
        rs_rows.append({"change_type": "added", "ruleset_name": rs.get("name", ""),
                        "ruleset_id": rs_id, "field": "*",
                        "draft_value": _ruleset_fields(rs)["name"], "active_value": "",
                        **_blank()})
    for rs_id in active_idx.keys() - draft_idx.keys():
        rs = active_idx[rs_id]
        s["rulesets_removed"] += 1
        rs_rows.append({"change_type": "removed", "ruleset_name": rs.get("name", ""),
                        "ruleset_id": rs_id, "field": "*",
                        "draft_value": "", "active_value": _ruleset_fields(rs)["name"],
                        **_blank()})
    for rs_id in draft_idx.keys() & active_idx.keys():
        d_rs, a_rs = draft_idx[rs_id], active_idx[rs_id]
        df_f, af_f = _ruleset_fields(d_rs), _ruleset_fields(a_rs)
        rs_modified = False
        for field in df_f:
            if df_f[field] != af_f[field]:
                rs_modified = True
                rs_rows.append({"change_type": "modified",
                                "ruleset_name": d_rs.get("name", a_rs.get("name", "")),
                                "ruleset_id": rs_id, "field": field,
                                "draft_value": df_f[field], "active_value": af_f[field],
                                **_blank()})
        if rs_modified:
            s["rulesets_modified"] += 1

        # ── Rule-level (within a shared ruleset) ─────────────────────────────
        d_rules, a_rules = _index_rules(d_rs), _index_rules(a_rs)
        rs_name = d_rs.get("name", a_rs.get("name", ""))
        for rid in d_rules.keys() - a_rules.keys():
            s["rules_added"] += 1
            rule_rows.append({"change_type": "added", "ruleset_name": rs_name,
                              "rule_id": rid, "field": "*",
                              "draft_value": "rule", "active_value": "", **_blank()})
        for rid in a_rules.keys() - d_rules.keys():
            s["rules_removed"] += 1
            rule_rows.append({"change_type": "removed", "ruleset_name": rs_name,
                              "rule_id": rid, "field": "*",
                              "draft_value": "", "active_value": "rule", **_blank()})
        for rid in d_rules.keys() & a_rules.keys():
            df_r, af_r = _rule_fields(d_rules[rid]), _rule_fields(a_rules[rid])
            rule_modified = False
            for field in df_r:
                if df_r[field] != af_r[field]:
                    rule_modified = True
                    rule_rows.append({"change_type": "modified", "ruleset_name": rs_name,
                                      "rule_id": rid, "field": field,
                                      "draft_value": df_r[field],
                                      "active_value": af_r[field], **_blank()})
            if rule_modified:
                s["rules_modified"] += 1

    s["total_changes"] = (s["rulesets_added"] + s["rulesets_removed"] + s["rulesets_modified"]
                          + s["rules_added"] + s["rules_removed"] + s["rules_modified"])

    return {
        "ruleset_changes": pd.DataFrame(rs_rows, columns=_RULESET_COLS),
        "rule_changes": pd.DataFrame(rule_rows, columns=_RULE_COLS),
        "summary": s,
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_diff_engine.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/report/analysis/policy_diff/__init__.py src/report/analysis/policy_diff/diff_engine.py tests/test_policy_diff_engine.py
git commit -m "feat(policy-diff): add DRAFT-vs-ACTIVE field-level diff engine"
```

---

### Task 2: Operator attribution — `attribute_changes`

**Files:**
- Create: `src/report/analysis/policy_diff/attribution.py`
- Test: `tests/test_policy_diff_attribution.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_policy_diff_attribution.py`:

```python
"""Tests for policy-diff operator attribution (pure derivation)."""
from __future__ import annotations

import pandas as pd

from src.report.analysis.policy_diff.diff_engine import diff_rulesets
from src.report.analysis.policy_diff.attribution import attribute_changes


def _rs(rs_id, name, enabled):
    return {"href": f"/orgs/1/sec_policy/draft/rule_sets/{rs_id}",
            "name": name, "enabled": enabled, "description": "", "rules": []}


def _diff_with_one_modified_ruleset():
    draft = [_rs(1, "RS-A", False)]
    active = [_rs(1, "RS-A", True)]
    return diff_rulesets(draft, active)


def _policy_events(rows):
    return {"draft_events": pd.DataFrame(rows)}


def test_latest_event_is_attributed():
    diff = _diff_with_one_modified_ruleset()
    events = _policy_events([
        {"resource_name": "RS-A", "actor": "alice", "timestamp": "2026-06-01T10:00:00Z",
         "event_type": "rule_set.update"},
        {"resource_name": "RS-A", "actor": "bob", "timestamp": "2026-06-05T12:00:00Z",
         "event_type": "rule_set.update"},
    ])
    out = attribute_changes(diff, events)
    row = out["ruleset_changes"].to_dict("records")[0]
    assert row["last_actor"] == "bob"           # most recent wins
    assert row["last_changed"] == "2026-06-05T12:00:00Z"
    assert row["last_event"] == "rule_set.update"


def test_no_matching_event_leaves_attribution_blank():
    diff = _diff_with_one_modified_ruleset()
    events = _policy_events([
        {"resource_name": "OTHER-RS", "actor": "carol",
         "timestamp": "2026-06-05T12:00:00Z", "event_type": "rule_set.update"},
    ])
    out = attribute_changes(diff, events)
    row = out["ruleset_changes"].to_dict("records")[0]
    assert row["last_actor"] == ""
    assert row["last_changed"] == ""


def test_empty_events_does_not_raise():
    diff = _diff_with_one_modified_ruleset()
    out = attribute_changes(diff, {"draft_events": pd.DataFrame()})
    assert out["ruleset_changes"].to_dict("records")[0]["last_actor"] == ""


def test_error_events_dict_does_not_raise():
    diff = _diff_with_one_modified_ruleset()
    out = attribute_changes(diff, {"error": "No event data available"})
    assert out["ruleset_changes"].to_dict("records")[0]["last_actor"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_diff_attribution.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.report.analysis.policy_diff.attribution'`.

- [ ] **Step 3: Write the attribution implementation**

Create `src/report/analysis/policy_diff/attribution.py`:

```python
"""Operator attribution for the policy diff.

PURE derivation: decorates each diff row with the most-recent matching audit
event (last_actor / last_changed / last_event). The event source is the output
of audit_policy_changes(df) — specifically its ``draft_events`` DataFrame, whose
columns include resource_name / actor / timestamp / event_type.

Matching is by OBJECT NAME (audit events carry ``resource_name``, not a
href-bearing id). The most recent event per name wins. Names that the event
window does not cover stay blank — a known limitation of live diff.
"""
from __future__ import annotations

import pandas as pd


def _latest_by_name(policy_events: dict) -> dict:
    """name -> {actor, timestamp, event_type} for the most recent event per name."""
    if not isinstance(policy_events, dict):
        return {}
    df = policy_events.get("draft_events")
    if not isinstance(df, pd.DataFrame) or df.empty or "resource_name" not in df.columns:
        return {}
    work = df.copy()
    if "timestamp" not in work.columns:
        work["timestamp"] = ""
    work = work.sort_values("timestamp", ascending=True)  # last row per name = newest
    latest: dict = {}
    for _, row in work.iterrows():
        name = str(row.get("resource_name", "")).strip()
        if not name:
            continue
        latest[name] = {
            "actor": str(row.get("actor", "") or ""),
            "timestamp": str(row.get("timestamp", "") or ""),
            "event_type": str(row.get("event_type", "") or ""),
        }
    return latest


def _apply(df: pd.DataFrame, latest: dict) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df = df.copy()
    for idx, row in df.iterrows():
        hit = latest.get(str(row.get("ruleset_name", "")).strip())
        if hit:
            df.at[idx, "last_actor"] = hit["actor"]
            df.at[idx, "last_changed"] = hit["timestamp"]
            df.at[idx, "last_event"] = hit["event_type"]
    return df


def attribute_changes(diff: dict, policy_events: dict) -> dict:
    latest = _latest_by_name(policy_events)
    diff["ruleset_changes"] = _apply(diff.get("ruleset_changes"), latest)
    diff["rule_changes"] = _apply(diff.get("rule_changes"), latest)
    return diff
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_diff_attribution.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/report/analysis/policy_diff/attribution.py tests/test_policy_diff_attribution.py
git commit -m "feat(policy-diff): attribute diff rows from audit events pipeline"
```

---

### Task 3: HTML exporter — `PolicyDiffHtmlExporter`

**Files:**
- Create: `src/report/exporters/policy_diff_html_exporter.py`
- Test: `tests/test_policy_diff_html_exporter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_policy_diff_html_exporter.py`:

```python
"""Tests for the policy-diff HTML exporter."""
from __future__ import annotations

import os

import pandas as pd

from src.report.exporters.policy_diff_html_exporter import PolicyDiffHtmlExporter


def _diff():
    rs = pd.DataFrame([{
        "change_type": "modified", "ruleset_name": "RS-A", "ruleset_id": "1",
        "field": "enabled", "draft_value": "False", "active_value": "True",
        "last_actor": "bob", "last_changed": "2026-06-05T12:00:00Z",
        "last_event": "rule_set.update",
    }])
    rule = pd.DataFrame(columns=["change_type", "ruleset_name", "rule_id", "field",
                                 "draft_value", "active_value",
                                 "last_actor", "last_changed", "last_event"])
    return {"ruleset_changes": rs, "rule_changes": rule,
            "summary": {"rulesets_added": 0, "rulesets_removed": 0, "rulesets_modified": 1,
                        "rules_added": 0, "rules_removed": 0, "rules_modified": 0,
                        "total_changes": 1}}


def test_exports_html_file_with_content(tmp_path):
    path = PolicyDiffHtmlExporter(_diff(), lang="en").export(str(tmp_path))
    assert os.path.isfile(path)
    assert path.endswith(".html")
    html = open(path, encoding="utf-8").read()
    assert "RS-A" in html
    assert "bob" in html        # attribution rendered
    assert "modified" in html.lower()


def test_no_changes_still_produces_report(tmp_path):
    empty = {"ruleset_changes": pd.DataFrame(), "rule_changes": pd.DataFrame(),
             "summary": {"rulesets_added": 0, "rulesets_removed": 0, "rulesets_modified": 0,
                         "rules_added": 0, "rules_removed": 0, "rules_modified": 0,
                         "total_changes": 0}}
    path = PolicyDiffHtmlExporter(empty, lang="en").export(str(tmp_path))
    assert os.path.isfile(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_diff_html_exporter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.report.exporters.policy_diff_html_exporter'`.

- [ ] **Step 3: Write the exporter**

Create `src/report/exporters/policy_diff_html_exporter.py`:

```python
"""Policy Diff HTML exporter — renders DRAFT-vs-ACTIVE diff + attribution.

Self-contained (no chart deps): summary cards + a Ruleset-changes table + a
Rule-changes table, each row colour-coded by change_type and showing the
attributed operator. Mirrors the facade exporter contract: __init__(results,
lang) + export(output_dir) -> path.
"""
from __future__ import annotations

import datetime
import html as _html
import os

import pandas as pd

from src.i18n import t

_ROW_CLASS = {"added": "pd-added", "removed": "pd-removed", "modified": "pd-modified"}
_CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#1f2937;}
h1{font-size:22px;} h2{font-size:16px;margin-top:28px;}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0;}
.card{border:1px solid #e5e7eb;border-radius:8px;padding:10px 16px;min-width:120px;}
.card .n{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums;}
.card .l{font-size:12px;color:#6b7280;}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px;}
th,td{border:1px solid #e5e7eb;padding:6px 8px;text-align:left;vertical-align:top;}
th{background:#f9fafb;}
.pd-added{background:#ecfdf5;} .pd-removed{background:#fef2f2;} .pd-modified{background:#fffbeb;}
.note{font-size:12px;color:#6b7280;margin-top:24px;}
"""


def _esc(v) -> str:
    return _html.escape(str(v), quote=True)


def _card(n, label) -> str:
    return f'<div class="card"><div class="n">{n}</div><div class="l">{_esc(label)}</div></div>'


class PolicyDiffHtmlExporter:
    def __init__(self, results: dict, lang: str = "en"):
        self._r = results
        self._lang = lang

    def _table(self, df: pd.DataFrame, id_col: str) -> str:
        if df is None or df.empty:
            return f'<p>{_esc(t("rpt_policy_diff_no_changes", lang=self._lang))}</p>'
        cols = ["change_type", "ruleset_name", id_col, "field",
                "draft_value", "active_value", "last_actor", "last_changed"]
        cols = [c for c in cols if c in df.columns]
        head = "".join(f"<th>{_esc(c)}</th>" for c in cols)
        body = []
        for _, row in df.iterrows():
            cls = _ROW_CLASS.get(str(row.get("change_type", "")), "")
            cells = "".join(f"<td>{_esc(row.get(c, ''))}</td>" for c in cols)
            body.append(f'<tr class="{cls}">{cells}</tr>')
        return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        s = self._r.get("summary", {})
        title = t("rpt_policy_diff_report_title", lang=self._lang)
        cards = (
            _card(s.get("rulesets_added", 0), t("rpt_policy_diff_added", lang=self._lang) + " RS")
            + _card(s.get("rulesets_removed", 0), t("rpt_policy_diff_removed", lang=self._lang) + " RS")
            + _card(s.get("rulesets_modified", 0), t("rpt_policy_diff_modified", lang=self._lang) + " RS")
            + _card(s.get("rules_added", 0), t("rpt_policy_diff_added", lang=self._lang) + " Rule")
            + _card(s.get("rules_removed", 0), t("rpt_policy_diff_removed", lang=self._lang) + " Rule")
            + _card(s.get("rules_modified", 0), t("rpt_policy_diff_modified", lang=self._lang) + " Rule")
        )
        html = f"""<!doctype html><html lang="{self._lang}"><head>
<meta charset="utf-8"><title>{_esc(title)}</title><style>{_CSS}</style></head><body>
<h1>{_esc(title)}</h1>
<div class="cards">{cards}</div>
<h2>{_esc(t("rpt_policy_diff_ruleset_changes", lang=self._lang))}</h2>
{self._table(self._r.get("ruleset_changes"), "ruleset_id")}
<h2>{_esc(t("rpt_policy_diff_rule_changes", lang=self._lang))}</h2>
{self._table(self._r.get("rule_changes"), "rule_id")}
<p class="note">{_esc(t("rpt_policy_diff_attribution_note", lang=self._lang))}</p>
</body></html>"""

        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        path = os.path.join(output_dir, f"Illumio_Policy_Diff_Report_{ts}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        return path
```

> **Note:** verify the i18n import path before running — the codebase exposes `t(...)` (used in `report_scheduler.py` and the audit generator). If `from src.i18n import t` raises `ImportError`, run `cd /home/harry/rd/illumio-ops && grep -rn "^from .* import t$\|import t\b" src/report_scheduler.py` and match the exact import line it uses, then update this file's import accordingly. (Task 4 ships the keys this exporter reads.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_diff_html_exporter.py -v`
Expected: PASS (2 tests). If it fails on a missing i18n key, that is expected until Task 4 — re-run after Task 4. To unblock now, the keys can be added in Task 4 first; this plan keeps Task 4 right after.

- [ ] **Step 5: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/report/exporters/policy_diff_html_exporter.py tests/test_policy_diff_html_exporter.py
git commit -m "feat(policy-diff): add HTML exporter for diff + attribution"
```

---

### Task 4: i18n keys (EN + ZH_TW)

**Files:**
- Modify: `src/i18n_en.json`
- Modify: `src/i18n_zh_TW.json`

- [ ] **Step 1: Add the new keys to `src/i18n_en.json`**

Insert these keys in alphabetical position within the existing `rpt_*` block (near `rpt_policy_usage_*` / `rpt_security_report_title` ~line 3330). All use the `rpt_` strict prefix:

```json
  "rpt_policy_diff_active": "ACTIVE",
  "rpt_policy_diff_added": "Added",
  "rpt_policy_diff_attribution_note": "Attribution shows the most recent matching audit event within the report window; changes outside the window are not attributed.",
  "rpt_policy_diff_col_active": "ACTIVE value",
  "rpt_policy_diff_col_actor": "Operator",
  "rpt_policy_diff_col_change_type": "Change",
  "rpt_policy_diff_col_draft": "DRAFT value",
  "rpt_policy_diff_col_field": "Field",
  "rpt_policy_diff_draft": "DRAFT",
  "rpt_policy_diff_modified": "Modified",
  "rpt_policy_diff_no_changes": "No changes.",
  "rpt_policy_diff_removed": "Removed",
  "rpt_policy_diff_report_title": "Illumio Policy Diff Report (DRAFT vs ACTIVE)",
  "rpt_policy_diff_rule_changes": "Rule Changes",
  "rpt_policy_diff_ruleset_changes": "Ruleset Changes",
  "rpt_policy_diff_summary": "Summary",
```

- [ ] **Step 2: Add the SAME keys to `src/i18n_zh_TW.json`**

Insert in the same alphabetical position. Glossary terms (Ruleset, Rule, Policy, PCE, DRAFT, ACTIVE) stay in English per `src/i18n/data/glossary.json`:

```json
  "rpt_policy_diff_active": "ACTIVE",
  "rpt_policy_diff_added": "新增",
  "rpt_policy_diff_attribution_note": "歸因顯示報表時間窗內最新一筆匹配的稽核事件；時間窗外的變更不予歸因。",
  "rpt_policy_diff_col_active": "ACTIVE 值",
  "rpt_policy_diff_col_actor": "操作者",
  "rpt_policy_diff_col_change_type": "變更類型",
  "rpt_policy_diff_col_draft": "DRAFT 值",
  "rpt_policy_diff_col_field": "欄位",
  "rpt_policy_diff_draft": "DRAFT",
  "rpt_policy_diff_modified": "已修改",
  "rpt_policy_diff_no_changes": "無變更。",
  "rpt_policy_diff_removed": "已移除",
  "rpt_policy_diff_report_title": "Illumio Policy Diff 報表（DRAFT vs ACTIVE）",
  "rpt_policy_diff_rule_changes": "Rule 變更",
  "rpt_policy_diff_ruleset_changes": "Ruleset 變更",
  "rpt_policy_diff_summary": "摘要",
```

- [ ] **Step 3: Verify i18n parity + glossary**

Run: `cd /home/harry/rd/illumio-ops && python scripts/audit_i18n_usage.py`
Expected: no NEW parity (Cat I) or glossary (Cat E) failures for the `rpt_policy_diff_*` keys. If the audit flags a glossary violation, edit the ZH_TW value to preserve the flagged English term (e.g. keep "Ruleset"/"Rule"/"Policy" English), then re-run.

- [ ] **Step 4: Run the i18n test suite**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_i18n_audit.py tests/test_i18n_glossary.py -v`
Expected: PASS (no new failures introduced by the added keys).

- [ ] **Step 5: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/i18n_en.json src/i18n_zh_TW.json
git commit -m "i18n(policy-diff): add report strings (EN/ZH_TW)"
```

---

### Task 5: Report facade — `PolicyDiffReport`

**Files:**
- Create: `src/report/policy_diff_report.py`
- Test: `tests/test_policy_diff_report.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_policy_diff_report.py`:

```python
"""Tests for the PolicyDiffReport facade (wiring + export)."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pandas as pd

from src.report.policy_diff_report import PolicyDiffReport


def _draft():
    return [{"href": "/orgs/1/sec_policy/draft/rule_sets/1", "name": "RS-A",
             "enabled": False, "description": "", "rules": []}]


def _active():
    return [{"href": "/orgs/1/sec_policy/active/rule_sets/1", "name": "RS-A",
             "enabled": True, "description": "", "rules": []}]


def test_run_produces_html_with_diff_and_attribution(tmp_path):
    api = MagicMock()
    api.get_all_rulesets.return_value = _draft()
    api.get_active_rulesets.return_value = _active()

    events = {"draft_events": pd.DataFrame([
        {"resource_name": "RS-A", "actor": "bob",
         "timestamp": "2026-06-05T12:00:00Z", "event_type": "rule_set.update"},
    ])}

    with patch("src.report.policy_diff_report.PolicyDiffReport._fetch_policy_events",
               return_value=events):
        path = PolicyDiffReport(cm=MagicMock(), api_client=api).run(
            output_dir=str(tmp_path), lang="en")

    assert os.path.isfile(path)
    html = open(path, encoding="utf-8").read()
    assert "RS-A" in html
    assert "bob" in html


def test_run_uses_force_refresh_for_draft(tmp_path):
    api = MagicMock()
    api.get_all_rulesets.return_value = _draft()
    api.get_active_rulesets.return_value = _active()
    with patch("src.report.policy_diff_report.PolicyDiffReport._fetch_policy_events",
               return_value={"draft_events": pd.DataFrame()}):
        PolicyDiffReport(cm=MagicMock(), api_client=api).run(output_dir=str(tmp_path))
    api.get_all_rulesets.assert_called_once_with(force_refresh=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_diff_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.report.policy_diff_report'`.

- [ ] **Step 3: Write the facade**

Create `src/report/policy_diff_report.py`:

```python
"""Policy Diff report facade — DRAFT-vs-ACTIVE diff + audit attribution.

Mirrors the SecurityRiskReport shape: run(output_dir, lang) -> path. Fetches
both draft and active rulesets (both already exposed by ApiClient), runs the
pure diff engine, attributes rows from the existing audit-events pipeline, and
exports HTML (+ CSV via the shared CsvExporter when fmt requires it).
"""
from __future__ import annotations

import datetime

from loguru import logger

from src.report.analysis.policy_diff.diff_engine import diff_rulesets
from src.report.analysis.policy_diff.attribution import attribute_changes
from src.report.exporters.policy_diff_html_exporter import PolicyDiffHtmlExporter

_DEFAULT_WINDOW_DAYS = 30


class PolicyDiffReport:
    def __init__(self, cm, api_client=None, config_dir: str = "config", cache_reader=None):
        self.cm = cm
        self.api = api_client
        self._config_dir = config_dir
        self._cache = cache_reader

    def _fetch_policy_events(self, lang: str) -> dict:
        """Reuse the audit pipeline to get policy-change events for attribution."""
        from src.report.audit_generator import AuditGenerator
        from src.report.analysis.audit.audit_mod03_policy import audit_policy_changes
        try:
            end = datetime.datetime.now(datetime.timezone.utc)
            start = end - datetime.timedelta(days=_DEFAULT_WINDOW_DAYS)
            gen = AuditGenerator(self.cm, api_client=self.api,
                                 config_dir=self._config_dir, cache_reader=self._cache)
            gen._lang = lang
            events, _src = gen._fetch_events(start, end)
            if not events:
                return {"draft_events": None}
            df = gen._build_dataframe(events)
            return audit_policy_changes(df)
        except Exception as exc:
            logger.warning(f"PolicyDiffReport: attribution events unavailable ({exc})")
            return {"draft_events": None}

    def build(self, lang: str = "en") -> dict:
        """Return the attributed diff module_results (no export)."""
        draft = self.api.get_all_rulesets(force_refresh=True) if self.api else []
        active = self.api.get_active_rulesets() if self.api else []
        diff = diff_rulesets(draft, active)
        diff = attribute_changes(diff, self._fetch_policy_events(lang))
        return diff

    def run(self, output_dir: str = "reports", lang: str = "en", fmt: str = "html") -> str:
        diff = self.build(lang)
        if fmt == "csv":
            from src.report.exporters.csv_exporter import CsvExporter
            return CsvExporter(diff, report_label="Policy_Diff").export(output_dir)
        return PolicyDiffHtmlExporter(diff, lang=lang).export(output_dir)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_diff_report.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Verify CSV path reuses the shared exporter unchanged**

Run: `cd /home/harry/rd/illumio-ops && python -c "from unittest.mock import MagicMock; import pandas as pd; from src.report.policy_diff_report import PolicyDiffReport; api=MagicMock(); api.get_all_rulesets.return_value=[{'href':'/orgs/1/sec_policy/draft/rule_sets/2','name':'RS-NEW','enabled':True,'description':'','rules':[]}]; api.get_active_rulesets.return_value=[]; r=PolicyDiffReport(cm=MagicMock(),api_client=api); r._fetch_policy_events=lambda lang:{'draft_events':None}; import tempfile,os; d=tempfile.mkdtemp(); p=r.run(output_dir=d,fmt='csv'); print('ZIP:',os.path.basename(p)); print('exists', os.path.isfile(p))"`
Expected: prints a `Illumio_Policy_Diff_Report_*_raw.zip` filename and `exists True` (CsvExporter walked the diff DataFrames; no change to CsvExporter).

- [ ] **Step 6: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/report/policy_diff_report.py tests/test_policy_diff_report.py
git commit -m "feat(policy-diff): add PolicyDiffReport facade (HTML + CSV)"
```

---

### Task 6: Wire CLI `report policy-diff`

**Files:**
- Modify: `src/cli/report.py`
- Test: `tests/test_cli_report_policy_diff.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_report_policy_diff.py`:

```python
"""Tests for the `report policy-diff` CLI command."""
from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from src.cli.report import report_group


def test_policy_diff_command_registered():
    assert "policy-diff" in report_group.commands


def test_policy_diff_invokes_report(tmp_path):
    runner = CliRunner()
    with patch("src.cli.report.generate_policy_diff_report",
               return_value=[str(tmp_path / "Illumio_Policy_Diff_Report_x.html")]) as gen:
        result = runner.invoke(report_group,
                               ["policy-diff", "--output-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    gen.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_cli_report_policy_diff.py -v`
Expected: FAIL — `policy-diff` not in `report_group.commands` / `generate_policy_diff_report` does not exist.

- [ ] **Step 3: Add the generator helper + command**

In `src/cli/report.py`, after `generate_inventory_report` (the helper defined right after `generate_security_report`), add:

```python
def generate_policy_diff_report(
    *,
    fmt: str = "html",
    output_dir: str | None = None,
    email: bool = False,
) -> list[str]:
    """Generate the Policy Diff (DRAFT vs ACTIVE) report."""
    from src.api_client import ApiClient
    from src.config import ConfigManager
    from src.report.policy_diff_report import PolicyDiffReport
    from src.main import _make_cache_reader

    cm = ConfigManager()
    api = ApiClient(cm)
    _root_dir, config_dir = _resolve_paths(output_dir)
    out = _resolve_output_dir(cm, output_dir)
    lang = _resolve_lang(cm)

    rpt = PolicyDiffReport(cm, api_client=api, config_dir=config_dir,
                           cache_reader=_make_cache_reader(cm))
    paths: list[str] = []
    if fmt in ("html", "all"):
        paths.append(rpt.run(output_dir=out, lang=lang, fmt="html"))
    if fmt in ("csv", "all"):
        paths.append(rpt.run(output_dir=out, lang=lang, fmt="csv"))
    if not paths:
        paths.append(rpt.run(output_dir=out, lang=lang, fmt="html"))
    if email:
        from src.reporter import Reporter
        Reporter(cm).send_report_files(paths, report_type="policy_diff", lang=lang)
    return paths
```

> **Note:** the `email` branch calls `Reporter.send_report_files`. Before running Step 5 with real email, confirm that method name with `grep -n "def send_report" src/reporter.py`; if the project sends report email via a different method, match it. The CLI test (Step 1) does not exercise email, so this does not block the task.

Then register the command (place it after the `report_security` command):

```python
@report_group.command("policy-diff")
@click.option("--format", "fmt", type=click.Choice(_REPORT_FORMATS), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
@click.option("--email", is_flag=True)
@click.pass_context
def report_policy_diff(ctx: click.Context, fmt: str, output_dir, email: bool) -> None:
    """Generate Policy Diff Report (DRAFT vs ACTIVE, Ruleset/Rule scope)."""
    try:
        paths = generate_policy_diff_report(fmt=fmt, output_dir=output_dir, email=email)
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, f"Connection failed: {exc}")
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except Exception as exc:
        log.exception("policy-diff report failed")
        echo_error(ctx, f"Unexpected error: {exc}")
        ctx.exit(EXIT_SOFTWARE)
        return
    _emit_paths(ctx, paths, fmt)
```

> **Note:** `_REPORT_FORMATS` includes `pdf` and `xlsx`. PolicyDiffReport only implements `html`/`csv`; the helper above maps `all` → both and any other value falls through to `html`. That is intentional for v1 (no PDF/XLSX policy-diff). If you want to reject `pdf`/`xlsx` explicitly, narrow the `click.Choice` to `["html", "csv", "all"]` for this command only.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_cli_report_policy_diff.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Smoke-check the command is wired**

Run: `cd /home/harry/rd/illumio-ops && python -c "from src.cli.report import report_group; print('policy-diff' in report_group.commands)"`
Expected: `True`.

- [ ] **Step 6: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/cli/report.py tests/test_cli_report_policy_diff.py
git commit -m "feat(cli): add report policy-diff command"
```

---

### Task 7: Wire scheduler (`policy_diff` dispatch + prune prefix + email subject), mirroring ff93df9

**Files:**
- Modify: `src/report_scheduler.py`
- Test: `tests/test_traffic_report_split.py` (the file ff93df9 added its scheduler-wiring regression test to)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_traffic_report_split.py`:

```python
def test_scheduler_has_policy_diff_prefix_and_subject():
    """policy_diff must be wired into prune prefixes and the email subject map,
    mirroring how security_risk/network_inventory were wired in ff93df9."""
    from src.report_scheduler import ReportScheduler
    assert "policy_diff" in ReportScheduler._REPORT_PREFIXES
    assert ReportScheduler._REPORT_PREFIXES["policy_diff"].startswith("Illumio_Policy_Diff_Report_")


def test_scheduler_prune_by_count_handles_policy_diff(tmp_path):
    """Count-based pruning must work for a policy_diff schedule (no KeyError)."""
    from src.report_scheduler import ReportScheduler
    # Two report files with the policy_diff prefix; max_reports=1 keeps the newest.
    p1 = tmp_path / "Illumio_Policy_Diff_Report_2026-06-01_0900.html"
    p2 = tmp_path / "Illumio_Policy_Diff_Report_2026-06-02_0900.html"
    p1.write_text("a"); p2.write_text("b")
    sched = ReportScheduler.__new__(ReportScheduler)  # no __init__ needed for prune
    sched._prune_by_count(str(tmp_path), "policy_diff", 1)
    remaining = sorted(f.name for f in tmp_path.iterdir())
    assert remaining == ["Illumio_Policy_Diff_Report_2026-06-02_0900.html"]
```

> If `_prune_by_count` requires instance state beyond the prefixes (verify with `grep -n "_prune_by_count" src/report_scheduler.py` and read its body), adapt the test to the existing prune regression test's construction pattern in this same file (the ff93df9 test `test_scheduler_prune_by_count_handles_new_types` is the canonical example — mirror it).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_traffic_report_split.py -k policy_diff -v`
Expected: FAIL — `"policy_diff" not in _REPORT_PREFIXES`.

- [ ] **Step 3: Add the dispatch branch**

In `src/report_scheduler.py`, in `_generate_report` (after the `elif report_type == "policy_usage":` branch, before the final `else:` at ~line 300), add:

```python
        elif report_type == "policy_diff":
            from src.report.policy_diff_report import PolicyDiffReport
            rpt = PolicyDiffReport(self.cm, api_client=api, config_dir=self._config_dir,
                                   cache_reader=_make_cache_reader(self.cm))
            diff = rpt.build(lang=lang)
            if diff["summary"]["total_changes"] == 0:
                logger.info(f"[Scheduler] '{name}': no DRAFT-vs-ACTIVE changes — emitting empty report")
            from src.report.exporters.policy_diff_html_exporter import PolicyDiffHtmlExporter
            path = PolicyDiffHtmlExporter(diff, lang=lang).export(output_dir)
            return diff, [path]
```

> The exact insertion point: find the line `else:` that logs `Unknown report_type` (~line 300 / `scheduler dispatch 240-310 (2)` shows it). Insert the branch immediately above that `else:`.

- [ ] **Step 4: Add the prune prefix (mirror ff93df9)**

In `src/report_scheduler.py`, in the `_REPORT_PREFIXES` dict (~line 469), add the `policy_diff` entry alongside the others:

```python
        "policy_diff":       "Illumio_Policy_Diff_Report_",
```

- [ ] **Step 5: Add the email subject label (mirror ff93df9)**

In `src/report_scheduler.py`, in the email `type_label` dict (~line 322), add:

```python
                      "policy_diff": t("rpt_policy_diff_report_title", lang=lang),
```

(Place it next to the existing `"security_risk":` / `"network_inventory":` entries that ff93df9 added.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_traffic_report_split.py -v`
Expected: PASS (existing split tests + new policy_diff prefix/prune tests).

- [ ] **Step 7: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/report_scheduler.py tests/test_traffic_report_split.py
git commit -m "feat(scheduler): wire policy_diff into dispatch + prune prefixes + email subject"
```

---

## Final Verification

- [ ] **Run the full policy-diff + i18n + scheduler test scope**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_diff_engine.py tests/test_policy_diff_attribution.py tests/test_policy_diff_html_exporter.py tests/test_policy_diff_report.py tests/test_cli_report_policy_diff.py tests/test_traffic_report_split.py tests/test_i18n_audit.py tests/test_i18n_glossary.py -v`
Expected: all PASS.

- [ ] **Confirm scope discipline (Ruleset/Rule ONLY)**

`diff_engine.py` compares only Ruleset fields (name/enabled/description/rule_count) and Rule fields (enabled/providers/consumers/ingress_services). No IP list, service, label group, virtual service, or firewall-settings comparison exists. Confirm: `cd /home/harry/rd/illumio-ops && grep -niE "ip_list|firewall|virtual_serv|label_group" src/report/analysis/policy_diff/diff_engine.py` returns only `ip_list:` inside `_summarize_actors` (used to *summarize an actor*, not to diff IP-list objects) — no object-level diff of those types.

- [ ] **Confirm no new PCE endpoint was added**

`cd /home/harry/rd/illumio-ops && git diff --stat main -- src/api_client.py` shows **no change** to `api_client.py` (draft + active rulesets were already fetchable; the facade reuses `get_all_rulesets(force_refresh=True)` and `get_active_rulesets()`).

- [ ] **Confirm CsvExporter reused unchanged**

`cd /home/harry/rd/illumio-ops && git diff --stat main -- src/report/exporters/csv_exporter.py` shows **no change** — the diff `module_results` shape (dict of DataFrames) is consumed by the existing generic walker.

---

## Self-Review Notes (author)

- **Spec coverage:** core diff (§3) → Task 1; attribution (§4) → Task 2; HTML exporter (§5.2) → Task 3; i18n (§7) → Task 4; facade + CSV reuse (§5.1/§5.3) → Task 5; CLI (§6.1) → Task 6; scheduler 3 touch-points mirroring ff93df9 (§6.2) → Task 7; tests (§8) distributed across every task + Final Verification. All spec sections mapped.
- **Type consistency:** `diff_rulesets` emits DataFrames with the fixed `_RULESET_COLS`/`_RULE_COLS` (including blank `last_actor/last_changed/last_event`); `attribute_changes` fills exactly those three columns by `ruleset_name`; the HTML exporter and CsvExporter read the same column set. Consistent producer→consumer contract.
- **DRY/YAGNI:** no new PCE endpoint (draft+active already fetchable); CsvExporter reused unchanged; attribution reuses `AuditGenerator._fetch_events/_build_dataframe` + `audit_policy_changes`; `_summarize_actors` matches the actor-summarizing pattern already used in `pu_mod*`. Scope is Ruleset/Rule only — IP lists/services/label groups/firewall settings explicitly excluded.
- **Disclosed deferred refinements (need a quick verify-then-match during impl, not a guess):** (1) i18n import line in the HTML exporter (`from src.i18n import t`) — confirm against `report_scheduler.py`'s import before first run; (2) `Reporter.send_report_files` method name in the CLI email branch — confirm against `src/reporter.py`; (3) `_prune_by_count` construction in the scheduler test — mirror the existing ff93df9 regression test in the same file. Each has an explicit grep-and-match instruction in its step.
- **Placeholders:** none — every code/step has concrete, runnable content.
