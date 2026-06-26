# Phase 11 Implementation Plan — Chart & Dashboard Expansion (Tier 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fully saturate chart coverage across all traffic modules (+10 modules), replace the static Web GUI dashboard with live plotly, add interactive rule editing powered by questionary + pygments, and give report schedules full cron syntax via APScheduler CronTrigger. This is where the package investment starts showing up in every daily view.

**Architecture:**
- **Traffic module charts**: Apply same chart_spec pattern to the 10 remaining modules (mod01/03/04/06/08/09/11/12/13/14). Where possible, reuse existing aggregations already computed.
- **GUI dashboard**: add `/api/dashboard/chart/<chart_id>` endpoint returning plotly JSON; `dashboard.js` uses `Plotly.react()` to render. Cards/KPIs use humanize-formatted values.
- **Interactive rule edit**: `illumio-ops rule edit <id>` uses `questionary.form()` for structured input, then `pygments.highlight_json()` shows the before/after diff before save.
- **Cron schedules**: extend `ReportSchedule` pydantic model to accept `cron_expr: Optional[str]`; `tick_report_schedules` job switches between old daily/weekly/monthly logic and APScheduler `CronTrigger` evaluation.

**Tech Stack:** No new packages.

**Branch:** `upgrade/phase-11-charts-dashboard` (from main after Phase 10)

**Target tag on merge:** `v3.9.0-dashboard`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/report/analysis/mod01_traffic_overview.py` | Add chart_spec | KPI sparkline or time-series |
| `src/report/analysis/mod03_uncovered_flows.py` | Add chart_spec | donut covered vs uncovered |
| `src/report/analysis/mod04_ransomware_exposure.py` | Add chart_spec | horizontal bar by severity |
| `src/report/analysis/mod06_user_process.py` | Add chart_spec | bar: top 10 processes |
| `src/report/analysis/mod08_unmanaged_hosts.py` | Add chart_spec | bar by environment |
| `src/report/analysis/mod09_traffic_distribution.py` | Add chart_spec | bar port histogram |
| `src/report/analysis/mod11_bandwidth.py` | Add chart_spec | line over time |
| `src/report/analysis/mod12_executive_summary.py` | Add chart_spec | donut + KPI |
| `src/report/analysis/mod13_readiness.py` | Add chart_spec | bar readiness score per dimension |
| `src/report/analysis/mod14_infrastructure.py` | Add chart_spec | network graph |
| `src/report/exporters/chart_renderer.py` | Extend | Optional: stacked-bar, gauge (if natural fit) |
| `src/gui.py` | Add API endpoint | `/api/dashboard/chart/<chart_id>` → plotly JSON |
| `src/static/js/dashboard.js` | Replace chart section | `Plotly.react()` live-update pattern |
| `src/templates/index.html` | Update dashboard section | div placeholders for each plotly chart |
| `src/cli/rule.py` | Add edit subcommand | `rule edit <id>` with questionary.form + pygments diff |
| `src/config_models.py` | Extend ReportSchedule | `cron_expr: Optional[str]` |
| `src/report_scheduler.py` | Accept cron_expr | CronTrigger-based firing |
| `src/scheduler/jobs.py` | Update tick_report_schedules | route daily/weekly vs cron |
| `tests/test_phase11_chart_coverage.py` | Create | all 10 new modules produce chart_spec |
| `tests/test_gui_dashboard_plotly_endpoint.py` | Create | /api/dashboard/chart returns valid plotly JSON |
| `tests/test_cli_rule_edit.py` | Create | rule edit interactive flow with CliRunner input |
| `tests/test_cron_schedule.py` | Create | cron_expr validation + job firing |

---

## Task 1: Branch + baseline + coverage meta-test

- [ ] `git checkout main && git pull && git checkout -b upgrade/phase-11-charts-dashboard`.

- [ ] Baseline tests (expect 325+ passed after Phase 10).

- [ ] Write `tests/test_phase11_chart_coverage.py` asserting the 10 new chart-bearing modules emit chart_spec (failing test initially).

- [ ] Commit test baseline.

---

## Task 2: Traffic mod01 / mod03 / mod04 — simple specs

**Files:** 3 analysis modules + i18n

- [ ] **mod01 traffic_overview** — KPI line:
```python
# Assuming hourly_counts = {hour_dt: flow_count}
if hourly_counts:
    result["chart_spec"] = {
        "type": "line",
        "title": t("rpt_mod01_title", default="Traffic Flow Timeline"),
        "x_label": t("rpt_time", default="Time"),
        "y_label": t("rpt_flow_count", default="Flows"),
        "data": {
            "x": [h.isoformat() for h in sorted(hourly_counts.keys())],
            "y": [hourly_counts[h] for h in sorted(hourly_counts.keys())],
        },
        "i18n": {"lang": get_language()},
    }
```

- [ ] **mod03 uncovered_flows** — donut:
```python
result["chart_spec"] = {
    "type": "pie",
    "title": t("rpt_mod03_title", default="Covered vs Uncovered Flows"),
    "data": {
        "labels": [t("rpt_covered", default="Covered by rule"),
                   t("rpt_uncovered", default="Uncovered")],
        "values": [covered_count, uncovered_count],
    },
    "i18n": {"lang": get_language()},
}
```

- [ ] **mod04 ransomware_exposure** — horizontal bar via type=bar with descending sort:
```python
top_assets = sorted(asset_risk.items(), key=lambda x: x[1], reverse=True)[:10]
if top_assets:
    result["chart_spec"] = {
        "type": "bar",
        "title": t("rpt_mod04_title", default="Top 10 Ransomware Risk Assets"),
        "x_label": t("rpt_asset", default="Asset"),
        "y_label": t("rpt_risk_score", default="Risk score"),
        "data": {
            "labels": [a[:30] for a, _ in top_assets],
            "values": [s for _, s in top_assets],
        },
        "i18n": {"lang": get_language()},
    }
```

- [ ] i18n keys added.

- [ ] Commit:
```bash
git add src/report/analysis/mod01_*.py src/report/analysis/mod03_*.py src/report/analysis/mod04_*.py src/i18n*
git commit -m "feat(reports): chart_spec on mod01/03/04 (timeline, donut, bar)"
```

---

## Task 3: mod06 / mod08 / mod09 — bar / histogram specs

**Files:** 3 modules + i18n

- [ ] **mod06 user_process** — top processes bar:
```python
top_procs = sorted(process_counts.items(), key=lambda x: x[1], reverse=True)[:10]
result["chart_spec"] = {
    "type": "bar",
    "title": t("rpt_mod06_title", default="Top Processes by Flow Count"),
    "x_label": t("rpt_process", default="Process"),
    "y_label": t("rpt_flow_count", default="Flows"),
    "data": {
        "labels": [p[:30] for p, _ in top_procs],
        "values": [c for _, c in top_procs],
    },
    "i18n": {"lang": get_language()},
}
```

- [ ] **mod08 unmanaged_hosts** — bar by environment:
```python
if hosts_by_env:
    result["chart_spec"] = {
        "type": "bar",
        "title": t("rpt_mod08_title", default="Unmanaged Hosts by Environment"),
        "x_label": t("rpt_env", default="Environment"),
        "y_label": t("rpt_host_count", default="Host count"),
        "data": {
            "labels": list(hosts_by_env.keys()),
            "values": list(hosts_by_env.values()),
        },
        "i18n": {"lang": get_language()},
    }
```

- [ ] **mod09 traffic_distribution** — top ports bar (effectively a histogram):
```python
top_ports = sorted(port_counts.items(), key=lambda x: x[1], reverse=True)[:20]
result["chart_spec"] = {
    "type": "bar",
    "title": t("rpt_mod09_title", default="Top 20 Ports by Flow Count"),
    "x_label": t("rpt_port", default="Port"),
    "y_label": t("rpt_flow_count", default="Flows"),
    "data": {
        "labels": [str(p) for p, _ in top_ports],
        "values": [c for _, c in top_ports],
    },
    "i18n": {"lang": get_language()},
}
```

- [ ] i18n + commit.

---

## Task 4: mod11 / mod12 / mod13 / mod14 — advanced specs

**Files:** 4 modules + i18n; possibly `chart_renderer.py` extension for gauge type

- [ ] **mod11 bandwidth** — line over time (reuse mod01 pattern with bandwidth values).

- [ ] **mod12 executive_summary** — donut of top-level split:
```python
# e.g., allowed vs blocked, managed vs unmanaged, high-risk vs low
result["chart_spec"] = {
    "type": "pie",
    "title": t("rpt_mod12_title", default="Environment Health Summary"),
    "data": {
        "labels": [t("rpt_healthy", default="Healthy"),
                   t("rpt_warning", default="Warning"),
                   t("rpt_critical", default="Critical")],
        "values": [healthy, warning, critical],
    },
    "i18n": {"lang": get_language()},
}
```

- [ ] **mod13 readiness** — bar by readiness dimension (or extend chart_renderer to support `type="gauge"` if desired):
```python
result["chart_spec"] = {
    "type": "bar",
    "title": t("rpt_mod13_title", default="Enforcement Readiness Score"),
    "x_label": t("rpt_dimension", default="Dimension"),
    "y_label": t("rpt_score", default="Score (%)"),
    "data": {
        "labels": [t("rpt_r_coverage", default="Coverage"),
                   t("rpt_r_stability", default="Stability"),
                   t("rpt_r_telemetry", default="Telemetry"),
                   t("rpt_r_compliance", default="Compliance")],
        "values": [cov_pct, stab_pct, tel_pct, comp_pct],
    },
    "i18n": {"lang": get_language()},
}
```

- [ ] **mod14 infrastructure** — network graph (reuse type="network" from mod15):
```python
result["chart_spec"] = {
    "type": "network",
    "title": t("rpt_mod14_title", default="Infrastructure Service Topology"),
    "data": {
        "nodes": [{"id": svc, "label": svc} for svc in services],
        "edges": [(src, dst) for src, dst in service_calls],
    },
    "i18n": {"lang": get_language()},
}
```

- [ ] (Optional) Extend `chart_renderer.py` to support `type="gauge"` if mod13 needs radial visualization. Otherwise the bar pattern above is fine.

- [ ] i18n + commit.

---

## Task 5: GUI dashboard — plotly live endpoint

**Files:** `src/gui.py`, `src/templates/index.html`, `src/static/js/dashboard.js`, `tests/test_gui_dashboard_plotly_endpoint.py`

- [ ] Add Flask endpoint:
```python
# src/gui.py, inside _create_app / build_app
@app.route("/api/dashboard/chart/<chart_id>")
@login_required
def api_dashboard_chart(chart_id: str):
    """Return plotly JSON for a dashboard chart.
    chart_ids: 'traffic_timeline', 'policy_decisions', 'ven_status', 'rule_hits'
    """
    from flask import jsonify, abort
    from src.report.exporters.chart_renderer import render_plotly_html
    # Registry pattern:
    builders = {
        "traffic_timeline": _build_traffic_timeline_spec,
        "policy_decisions": _build_policy_decisions_spec,
        "ven_status": _build_ven_status_spec,
        "rule_hits": _build_rule_hits_spec,
    }
    builder = builders.get(chart_id)
    if not builder:
        abort(404)
    spec = builder(cm)  # each builder returns a chart_spec dict
    # Return plotly JSON (not HTML) for client-side Plotly.react()
    import plotly.graph_objects as go
    fig = _spec_to_plotly_figure(spec)
    return jsonify(fig.to_plotly_json())
```

- [ ] Add 4 builder helper functions that query the current state (cached traffic summary, active rules, etc.) and build chart_spec dicts. Keep them isolated — each ≤ 30 lines.

- [ ] Add `_spec_to_plotly_figure(spec)` helper that converts chart_spec to a `plotly.graph_objects.Figure` instance (not HTML string).

- [ ] `src/templates/index.html` — dashboard section has 4 divs:
```html
<div class="dashboard-charts">
  <div id="chart-traffic-timeline"></div>
  <div id="chart-policy-decisions"></div>
  <div id="chart-ven-status"></div>
  <div id="chart-rule-hits"></div>
</div>
```

- [ ] `src/static/js/dashboard.js` — fetch + Plotly.react:
```js
async function loadDashboardCharts() {
  const charts = ["traffic_timeline", "policy_decisions", "ven_status", "rule_hits"];
  for (const id of charts) {
    const resp = await fetch(`/api/dashboard/chart/${id}`,
                             { headers: { "X-CSRFToken": _csrfToken() } });
    if (!resp.ok) continue;
    const fig = await resp.json();
    const el = document.getElementById(`chart-${id.replace(/_/g,'-')}`);
    if (el) Plotly.react(el, fig.data, fig.layout, { responsive: true });
  }
}
setInterval(loadDashboardCharts, 60000);  // refresh every minute
loadDashboardCharts();  // initial
```

- [ ] Make sure `plotly.min.js` is included offline in `src/static/js/` (inline from the chart_renderer inline bundle, or add a separate asset). Approach A: serve it from Flask static; Approach B: compute once at first chart render and cache.

- [ ] Tests — mock ApiClient, hit `/api/dashboard/chart/traffic_timeline`, verify JSON has `data` + `layout` keys.

- [ ] Commit.

---

## Task 6: CLI `illumio-ops rule edit <id>` interactive

**Files:** `src/cli/rule.py` (extend), `tests/test_cli_rule_edit.py`

- [ ] Add `edit` command:
```python
@rule_group.command("edit")
@click.argument("rule_id", type=int)
@click.option("--no-preview", is_flag=True, help="Skip the diff preview before save")
def edit_rule(rule_id: int, no_preview: bool) -> None:
    """Interactively edit a rule."""
    import json
    import questionary
    from src.config import ConfigManager
    from src.report.exporters.code_highlighter import highlight_json
    from rich.console import Console

    cm = ConfigManager()
    rules = cm.config.get("rules", [])
    if rule_id < 1 or rule_id > len(rules):
        raise click.ClickException(f"rule_id {rule_id} out of range (1..{len(rules)})")
    rule = rules[rule_id - 1]
    before = json.dumps(rule, indent=2, ensure_ascii=False)

    # Questionary form — only the most common fields
    name = questionary.text("Rule name:", default=rule.get("name", "")).unsafe_ask()
    enabled = questionary.confirm("Enabled?", default=rule.get("enabled", True)).unsafe_ask()
    threshold_str = questionary.text(
        "Threshold (blank to keep):",
        default=str(rule.get("threshold", "")),
    ).unsafe_ask()

    rule["name"] = name
    rule["enabled"] = enabled
    if threshold_str.strip():
        try:
            rule["threshold"] = int(threshold_str)
        except ValueError:
            rule["threshold"] = threshold_str

    after = json.dumps(rule, indent=2, ensure_ascii=False)

    if not no_preview:
        console = Console()
        console.print("[bold]Before:[/bold]")
        console.print(highlight_json(before))
        console.print("[bold]After:[/bold]")
        console.print(highlight_json(after))
        if not questionary.confirm("Save changes?", default=True).unsafe_ask():
            click.echo("Aborted.")
            return

    cm.save()
    click.echo(f"[green]Rule {rule_id} saved.[/green]")
```

- [ ] Test uses `CliRunner.invoke(..., input="name1\ny\n5\ny\n")` to feed the interactive prompts, or mocks `questionary` functions.

- [ ] Commit.

---

## Task 7: ReportSchedule cron_expr support

**Files:** `src/config_models.py`, `src/report_scheduler.py`, `src/scheduler/jobs.py`, `tests/test_cron_schedule.py`

- [ ] Extend `ReportSchedule` pydantic model:
```python
class ReportSchedule(_Base):
    model_config = ConfigDict(extra="allow")
    id: Optional[int] = None
    name: str = ""
    cron_expr: Optional[str] = None  # e.g. "0 8 * * MON-FRI"
    # existing daily/weekly/monthly fields kept for backward-compat
    schedule_type: Optional[str] = None
    ...
```

- [ ] In `src/report_scheduler.py::tick()` (or whatever decides if a schedule is due now), add cron_expr branch:
```python
from apscheduler.triggers.cron import CronTrigger

def is_due(schedule, now):
    if schedule.get("cron_expr"):
        try:
            trigger = CronTrigger.from_crontab(schedule["cron_expr"])
            # "due now" means: next_fire_time after last_run_at was <= now
            last = schedule.get("last_run_at")
            next_fire = trigger.get_next_fire_time(last, now)
            return next_fire is not None and next_fire <= now
        except ValueError:
            logger.warning("Invalid cron_expr for schedule %s", schedule.get("id"))
            return False
    # Fall through to existing daily/weekly/monthly logic
    ...
```

- [ ] Write `tests/test_cron_schedule.py` — verify "0 8 * * MON-FRI" fires on Mon 08:00 but not Sat 08:00 (use freezegun).

- [ ] UI: add a `cron_expr` field to the scheduler modal in `index.html` with a hint (e.g., placeholder "0 8 * * MON-FRI — leave blank to use daily/weekly/monthly above"). `dashboard.js` sends it through.

- [ ] Commit.

---

## Task 8: Verification + docs + merge

- [ ] Full suite + i18n audit.
- [ ] Manual smoke:
  - Open web GUI dashboard → verify 4 live plotly charts render + auto-refresh after 1 minute
  - `illumio-ops rule edit 1` → interactive prompts + highlighted diff
  - Add a `cron_expr` schedule → wait for fire, check logs
- [ ] Status.md: `v3.9.0-dashboard`; list new capabilities.
- [ ] Task.md: Phase 11 block.
- [ ] Push, PR, squash merge, tag `v3.9.0-dashboard`, push tag.

---

## Acceptance Criteria

- [ ] All 15 traffic analysis modules produce chart_spec (was 5 after Phase 5)
- [ ] HTML traffic report renders 15 charts (vs 5)
- [ ] Web GUI dashboard shows 4 live plotly charts refreshing every 60s
- [ ] `illumio-ops rule edit 1` → interactive edit flow + pygments diff
- [ ] Report schedule with `cron_expr: "0 8 * * MON-FRI"` fires correctly
- [ ] All tests green; i18n audit 0 findings
- [ ] `v3.9.0-dashboard` tag present

---

## Rollback

Additive changes only; `git revert v3.9.0-dashboard` restores previous dashboard/schedule behavior.

---

## Self-Review Checklist

- ✅ 10 new chart_spec additions mapped to specific modules
- ✅ Dashboard endpoint + client code specified with file paths
- ✅ Rule edit command uses questionary + pygments as designed
- ✅ cron_expr coexists with legacy schedule_type (backward compat)
- ✅ i18n keys listed for each chart title and axis
- ✅ TDD: Task 1 coverage meta-test, Task 5/6/7 have test-first patterns
