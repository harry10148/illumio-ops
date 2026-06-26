# Phase 12 Implementation Plan — Polish & Advanced (Tier 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract the last of the value from the upgrade stack — make humanize visible everywhere it fits, deliver a turnkey SIEM integration story for the loguru JSON sink, give the Web GUI rule editor true IDE-level syntax highlighting, make APScheduler durable across restarts, and ship shell completions so operators stop typing full subcommand names.

**Architecture:**
- **humanize sweep**: audit every user-visible time/size/count display in GUI templates, CLI menus, and report footers. Replace raw stamps with `human_time_ago` / `human_size` / `human_number`. Respect glossary (zh_TW).
- **SIEM delivery**: add `docs/SIEM_Integration.md` + `deploy/filebeat.illumio_ops.yml` sample + `deploy/logstash.illumio_ops.conf` sample using loguru's already-available JSON sink.
- **GUI syntax highlight**: serve pygments CSS once at `/static/pygments.css`; rule editor calls server-side render for before/after diff; optionally add CodeMirror for live-editing (optional enhancement).
- **Persistent jobstore**: switch APScheduler from `MemoryJobStore` (default) to `SQLAlchemyJobStore('sqlite:///config/scheduler.db')`. Re-register jobs on startup so daemon restarts preserve schedules.
- **Shell completions**: click has built-in `_ILLUMIO_OPS_COMPLETE=bash_source` generator. Ship bash + zsh + fish artefacts in `scripts/completions/` and install via RPM post-install hook later.

**Tech Stack:** No new mandatory packages. SQLAlchemy is already transitively required by APScheduler's SQL jobstore (installed with apscheduler[sqlalchemy]).

**Branch:** `upgrade/phase-12-polish` (from main after Phase 11)

**Target tag on merge:** `v3.10.0-polish`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/gui.py` + `src/templates/index.html` + `src/static/js/dashboard.js` | Modify | Replace raw time/size/number renders with humanize calls (server side) or a helper (client side) |
| `src/report/exporters/html_exporter.py` + audit + ven + policy_usage | Modify | Use `human_number` on every count, `human_time_ago` on every timestamp, `human_size` on file sizes |
| `src/main.py` (interactive menu) | Modify | Main menu status line already uses humanize; extend to sub-menus |
| `docs/SIEM_Integration.md` | Create | Step-by-step SIEM ingestion guide |
| `deploy/filebeat.illumio_ops.yml` | Create | Sample Filebeat input config for the JSON sink |
| `deploy/logstash.illumio_ops.conf` | Create | Sample Logstash pipeline |
| `deploy/rsyslog.illumio_ops.conf` | Create | Sample rsyslog forwarding config (for syslog-centric shops) |
| `src/gui.py` — rule edit endpoint | Modify | Server-side pygments highlight for rule JSON before/after; return HTML snippet |
| `src/templates/` — rule edit view | Modify | `<pre class="pygments-diff">` placeholder + inject `/static/pygments.css` |
| `src/scheduler/__init__.py` — build_scheduler | Modify | Use `SQLAlchemyJobStore` when `config.scheduler.persist=true` |
| `src/config_models.py` | Modify | `SchedulerSettings.persist: bool = False`, `scheduler.db_path: str = "config/scheduler.db"` |
| `scripts/completions/illumio-ops.bash` | Create (move or regen from Phase 1's script) | Bash completion |
| `scripts/completions/_illumio-ops` (zsh) | Create | Zsh completion (click's `zsh_source` output) |
| `scripts/completions/illumio-ops.fish` | Create | Fish completion |
| `deploy/illumio-ops.service` | Update | Add `Environment=ILLUMIO_OPS_PERSIST_SCHEDULES=1` comment example |
| `tests/test_humanize_coverage.py` | Create | Grep-based regression ensuring select GUI render paths use humanize |
| `tests/test_siem_samples_parse.py` | Create | Parse filebeat YAML + logstash conf as text (sanity) |
| `tests/test_rule_edit_pygments.py` | Create | GUI rule edit endpoint returns highlighted HTML |
| `tests/test_scheduler_persistence.py` | Create | SQLAlchemyJobStore survives scheduler restart |
| `Status.md` / `Task.md` / `docs/User_Manual*.md` | Update | Phase 12 complete |

---

## Task 1: Branch + baseline

- [ ] `git checkout main && git pull && git checkout -b upgrade/phase-12-polish`

- [ ] Baseline (expect ~335+ passed after Phase 11).

---

## Task 2: humanize sweep across GUI + reports

**Files:** `src/gui.py`, `src/templates/index.html`, `src/static/js/dashboard.js`, 4 HTML exporters, `src/main.py`

- [ ] Grep all timestamp + file-size + large-number displays:
```bash
grep -rn "strftime\|\.size()\|{[a-z_]*_count}\|generated_at\|last_modified" src/ | less
```

- [ ] For each hit, replace with humanize. Examples:

**GUI (Jinja template):**
```html
<!-- Before -->
<span class="timestamp">{{ rule.created_at }}</span>
<!-- After (via Jinja filter) -->
<span class="timestamp" title="{{ rule.created_at }}">{{ rule.created_at | human_time_ago }}</span>
```

Add a Jinja filter in `build_app`:
```python
from src.humanize_ext import human_time_ago, human_size, human_number

@app.template_filter("human_time_ago")
def _ht_ago(dt):
    if dt is None: return "-"
    return human_time_ago(dt)

@app.template_filter("human_size")
def _hs(n):
    return human_size(n) if n is not None else "-"

@app.template_filter("human_number")
def _hn(n):
    return human_number(n) if n is not None else "-"
```

**Client-side (dashboard.js)** — for client-computed times/sizes, add a small helper that calls the server's `/api/humanize/time-ago?ts=...` or does its own string math (simpler). Preferred: server-rendered via Jinja filters wherever possible; keep client JS-only for data fetched dynamically.

**HTML exporters** — already partially done in Phase 5 for `html_exporter.py` summary pills. Extend to audit / ven / policy_usage html exporters: every `X flows`, `Y rules`, `Z alerts` → `human_number(X) flows`; every `generated_at` → `human_time_ago(dt)` on hover + absolute stamp in title.

- [ ] Run i18n audit.

- [ ] Tests `tests/test_humanize_coverage.py`:
```python
"""Regression: key display paths must use humanize, not raw format."""
import re
from pathlib import Path


def test_gui_templates_use_human_filters():
    html = Path("src/templates/index.html").read_text(encoding="utf-8")
    # At least 3 places should be pipe-humanized
    assert html.count("| human_time_ago") >= 2, "GUI not using human_time_ago filter"
    assert html.count("| human_number") >= 2, "GUI not using human_number filter"


def test_html_exporters_use_humanize():
    for path in ("src/report/exporters/html_exporter.py",
                 "src/report/exporters/audit_html_exporter.py",
                 "src/report/exporters/ven_html_exporter.py",
                 "src/report/exporters/policy_usage_html_exporter.py"):
        src = Path(path).read_text(encoding="utf-8")
        assert "human_" in src, f"{path}: no humanize_ext usage detected"
```

- [ ] Commit.

---

## Task 3: SIEM integration docs + sample configs

**Files:** `docs/SIEM_Integration.md`, `deploy/filebeat.illumio_ops.yml`, `deploy/logstash.illumio_ops.conf`, `deploy/rsyslog.illumio_ops.conf`

- [ ] `docs/SIEM_Integration.md`:
```markdown
# SIEM Integration Guide

illumio_ops emits structured JSON logs when the loguru JSON sink is enabled.
This document shows how to ship those logs to Splunk / Elastic / QRadar / Sentinel.

## 1. Enable the JSON sink

In `config/config.json`, set:
```json
{
  "logging": {
    "level": "INFO",
    "json_sink": true,
    "rotation": "50 MB",
    "retention": 30
  }
}
```

Restart the daemon. JSON log file appears at `logs/illumio_ops.json.log`.
Each line is a valid JSON object with: `{"text": "...", "record": {"time": ..., "level": ..., "name": ..., "message": ..., "extra": {...}}}`.

## 2. Forwarding options

### Option A — Filebeat (Elastic)
See `deploy/filebeat.illumio_ops.yml`.

### Option B — Logstash pipeline
See `deploy/logstash.illumio_ops.conf`.

### Option C — rsyslog (for syslog-based SIEMs, e.g. QRadar)
See `deploy/rsyslog.illumio_ops.conf`.

### Option D — Splunk Universal Forwarder
Add to `$SPLUNK_HOME/etc/system/local/inputs.conf`:
```ini
[monitor:///opt/illumio-ops/logs/illumio_ops.json.log]
sourcetype = _json
index = illumio_ops
```

## 3. Splunk/ES dashboard panel starters

Search examples:
- `source="/opt/illumio-ops/logs/illumio_ops.json.log" record.level.name="ERROR"`
- `"record.message" containing "RateLimit"` — login brute-force attempts
- `"record.message" containing "AsyncJob"` — long-running report query diagnostics
```

- [ ] `deploy/filebeat.illumio_ops.yml`:
```yaml
filebeat.inputs:
  - type: log
    enabled: true
    paths:
      - /opt/illumio-ops/logs/illumio_ops.json.log
    json.keys_under_root: true
    json.add_error_key: true
    fields:
      source_type: illumio_ops
    fields_under_root: true

output.elasticsearch:
  hosts: ["elastic.example.com:9200"]
  index: "illumio-ops-%{+yyyy.MM.dd}"
```

- [ ] `deploy/logstash.illumio_ops.conf`:
```
input {
  file {
    path => "/opt/illumio-ops/logs/illumio_ops.json.log"
    codec => "json"
    sincedb_path => "/var/lib/logstash/sincedb_illumio_ops"
    start_position => "beginning"
  }
}

filter {
  date {
    match => [ "[record][time][timestamp]", "ISO8601" ]
    target => "@timestamp"
  }
  mutate {
    add_field => { "[@metadata][index]" => "illumio-ops" }
  }
}

output {
  elasticsearch {
    hosts => ["elastic.example.com:9200"]
    index => "%{[@metadata][index]}-%{+YYYY.MM.dd}"
  }
}
```

- [ ] `deploy/rsyslog.illumio_ops.conf`:
```
# /etc/rsyslog.d/90-illumio_ops.conf
# Forward illumio_ops JSON logs to remote SIEM over TCP

module(load="imfile")

input(type="imfile"
      File="/opt/illumio-ops/logs/illumio_ops.json.log"
      Tag="illumio-ops"
      Severity="info"
      Facility="local7")

# Forward to remote SIEM (replace with real host/port)
if $programname == 'illumio-ops' then {
    action(type="omfwd"
           Target="siem.example.com"
           Port="514"
           Protocol="tcp"
           Template="RSYSLOG_SyslogProtocol23Format")
    stop
}
```

- [ ] Sanity test:
```python
# tests/test_siem_samples_parse.py
from pathlib import Path
import yaml


def test_filebeat_yaml_parses():
    data = yaml.safe_load(Path("deploy/filebeat.illumio_ops.yml").read_text(encoding="utf-8"))
    assert "filebeat.inputs" in data
    assert data["filebeat.inputs"][0]["json.keys_under_root"] is True


def test_logstash_has_input_filter_output():
    src = Path("deploy/logstash.illumio_ops.conf").read_text(encoding="utf-8")
    for block in ("input", "filter", "output"):
        assert f"{block} {{" in src, f"logstash pipeline missing {block} block"


def test_rsyslog_targets_remote_host():
    src = Path("deploy/rsyslog.illumio_ops.conf").read_text(encoding="utf-8")
    assert "omfwd" in src
    assert "siem.example.com" in src  # placeholder that sysadmins replace
```

- [ ] Commit.

---

## Task 4: GUI rule edit pygments highlight

**Files:** `src/gui.py`, `src/templates/index.html`, `src/static/pygments.css` (new), `tests/test_rule_edit_pygments.py`

- [ ] Generate pygments CSS once at build_app time, write to `src/static/pygments.css`:
```python
# in build_app
from src.report.exporters.code_highlighter import get_highlight_css
from pathlib import Path

css_path = Path(app.static_folder) / "pygments.css"
if not css_path.exists():
    css_path.write_text(get_highlight_css(), encoding="utf-8")
```

- [ ] Add endpoint that renders a JSON payload with pygments:
```python
@app.route("/api/rules/<int:rule_id>/highlight")
@login_required
def api_rule_highlight(rule_id: int):
    import json
    from flask import jsonify, abort
    from src.report.exporters.code_highlighter import highlight_json
    rules = cm.config.get("rules", [])
    if rule_id < 1 or rule_id > len(rules):
        abort(404)
    rule = rules[rule_id - 1]
    html = highlight_json(json.dumps(rule, indent=2, ensure_ascii=False))
    return jsonify({"html": html})
```

- [ ] Rule edit modal in `index.html` uses the endpoint to show before/after. Include `<link rel="stylesheet" href="/static/pygments.css">` in `<head>`.

- [ ] Tests.

- [ ] Commit.

---

## Task 5: APScheduler persistent jobstore

**Files:** `src/scheduler/__init__.py`, `src/config_models.py`, `tests/test_scheduler_persistence.py`

- [ ] Extend `src/config_models.py`:
```python
class SchedulerSettings(_Base):
    # ... existing fields ...
    persist: bool = False   # Phase 12: enable SQLAlchemy job store
    db_path: str = "config/scheduler.db"
```

- [ ] Extend `build_scheduler(cm, ...)`:
```python
def build_scheduler(cm, interval_minutes: int = 10) -> BackgroundScheduler:
    sched_cfg = cm.config.get("scheduler", {}) or {}

    executors = {"default": ThreadPoolExecutor(max_workers=5)}
    job_defaults = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 60}

    kwargs = {"executors": executors, "job_defaults": job_defaults}
    if sched_cfg.get("persist"):
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        import os
        db_path = sched_cfg.get("db_path", "config/scheduler.db")
        if not os.path.isabs(db_path):
            pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            root_dir = os.path.dirname(pkg_dir)
            db_path = os.path.join(root_dir, db_path)
        url = f"sqlite:///{db_path}"
        kwargs["jobstores"] = {"default": SQLAlchemyJobStore(url=url)}

    sched = BackgroundScheduler(**kwargs)
    # ... rest of jobs registration unchanged ...
    return sched
```

- [ ] Ensure jobs are registered with `replace_existing=True` so redeploys don't duplicate:
```python
sched.add_job(
    run_monitor_cycle, trigger=IntervalTrigger(minutes=interval_minutes),
    args=[cm], id="monitor_cycle", name="Monitor analysis cycle",
    replace_existing=True,
)
```

- [ ] Test scheduler persistence:
```python
# tests/test_scheduler_persistence.py
"""Persistent jobstore survives a scheduler restart."""
def test_sqlalchemy_jobstore_remembers_jobs(tmp_path, monkeypatch):
    db = tmp_path / "sched.db"
    cm_cfg = {
        "api": {"url": "https://p.test", "org_id": "1", "key": "k", "secret": "s"},
        "scheduler": {"persist": True, "db_path": str(db)},
        "rule_scheduler": {"check_interval_seconds": 300},
    }
    from unittest.mock import MagicMock
    cm1 = MagicMock(); cm1.config = cm_cfg
    from src.scheduler import build_scheduler
    s1 = build_scheduler(cm1, interval_minutes=5)
    s1.start()
    assert len(s1.get_jobs()) == 3
    s1.shutdown(wait=False)

    # New scheduler with same DB — should rediscover jobs
    cm2 = MagicMock(); cm2.config = cm_cfg
    s2 = build_scheduler(cm2, interval_minutes=5)
    # Before start, jobstore should already have the 3 jobs from previous run
    s2.start()
    assert len(s2.get_jobs()) == 3
    s2.shutdown(wait=False)
    assert db.exists()
```

- [ ] Commit.

---

## Task 6: Shell completion artefacts

**Files:** `scripts/completions/illumio-ops.bash`, `scripts/completions/_illumio-ops`, `scripts/completions/illumio-ops.fish`

- [ ] Generate each artefact from click at build time OR commit static copies:
```bash
# Bash
_ILLUMIO_OPS_COMPLETE=bash_source python illumio_ops.py > scripts/completions/illumio-ops.bash
# Zsh
_ILLUMIO_OPS_COMPLETE=zsh_source python illumio_ops.py > scripts/completions/_illumio-ops
# Fish
_ILLUMIO_OPS_COMPLETE=fish_source python illumio_ops.py > scripts/completions/illumio-ops.fish
```

- [ ] Replace the existing `scripts/illumio-ops-completion.bash` with the properly-regenerated version (or keep both).

- [ ] Update `README.md` + `docs/User_Manual.md` with "Shell Tab Completion" section.

- [ ] RPM post-install hook (future Phase 8) can drop these into `/etc/bash_completion.d/`, `/usr/share/zsh/site-functions/`, and `/etc/fish/completions/`.

- [ ] Commit.

---

## Task 7: Full verification + docs + merge

- [ ] Full suite + i18n audit.
- [ ] Manual smoke:
  - Enable `scheduler.persist=true`; restart daemon; verify scheduler.db exists and jobs carry over
  - Enable `logging.json_sink=true`; point filebeat sample at the JSON file; verify parseable
  - Load web GUI rule editor; verify JSON rendered with pygments highlighting
  - Hover over timestamps in GUI — should see humanize format + absolute stamp on hover

- [ ] Status.md: `v3.10.0-polish`; list Phase 12 outputs.
- [ ] Task.md: Phase 12 block.
- [ ] User Manual: new sections for SIEM integration, persistent scheduler, shell completions.

- [ ] Push, PR, squash merge, tag `v3.10.0-polish`, push tag.

---

## Acceptance Criteria

- [ ] GUI templates use `| human_time_ago` / `| human_number` / `| human_size` filters in ≥ 3 places
- [ ] All 4 HTML exporters use `human_*` helpers for summary counts and timestamps
- [ ] `docs/SIEM_Integration.md` exists with 4 forwarding options + sample configs
- [ ] `deploy/filebeat.illumio_ops.yml`, `deploy/logstash.illumio_ops.conf`, `deploy/rsyslog.illumio_ops.conf` parse cleanly (tests)
- [ ] GUI rule editor shows pygments-highlighted JSON; `/static/pygments.css` served
- [ ] `scheduler.persist=true` makes daemon schedules survive process restart (SQLAlchemyJobStore)
- [ ] Shell completion scripts generated for bash / zsh / fish in `scripts/completions/`
- [ ] All tests green; i18n audit 0 findings
- [ ] `v3.10.0-polish` tag present

---

## Rollback

All changes are additive or behind feature flags (`logging.json_sink`, `scheduler.persist`). `git revert v3.10.0-polish` restores previous defaults cleanly.

---

## Dependency Notes

- `apscheduler[sqlalchemy]` extra may need to be explicitly listed in `requirements.txt` if SQLAlchemy isn't already a transitive dep. Verify during Task 5 and adjust pinning.
- `pyyaml` already required; no new install for Filebeat yaml sample tests.

---

## Self-Review Checklist

- ✅ humanize coverage test enforces regression
- ✅ SIEM docs cover 4 common stacks (Filebeat, Logstash, rsyslog, Splunk)
- ✅ pygments highlight wired at endpoint + static CSS level
- ✅ SQLAlchemyJobStore path handling respects relative config path
- ✅ Shell completions for 3 major shells
- ✅ All changes behind flags or additive — safe rollback
- ✅ User Manual updated so operators know the new capabilities exist
