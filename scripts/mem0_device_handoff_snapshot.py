#!/usr/bin/env python3
"""Device-handoff snapshot to Mem0 cloud for illumio_ops upgrade roadmap.

Stores precise facts verbatim (infer=False) so the next session on a
different device has everything needed to continue Wave C (Phase 7 + 9).

Reads MEM0_API_KEY from env. Safe to re-run — Mem0 dedupes by content.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    if not os.environ.get("MEM0_API_KEY"):
        print("ERROR: MEM0_API_KEY env var not set", file=sys.stderr)
        return 1

    from mem0 import MemoryClient

    client = MemoryClient()
    user_id = "harry10148"
    project_id = "illumio_ops_upgrade_roadmap"

    # Each entry = one self-contained fact. infer=False preserves verbatim.
    facts = [
        # ── 1. Project identity + goals ──────────────────────────────
        (
            "illumio_ops is a Flask-based PCE monitoring tool at "
            "D:\\OneDrive\\RD\\illumio_ops on Windows (Harry's laptop). "
            "GitHub: https://github.com/harry10148/illumio_ops . "
            "Primary deployment target: offline RHEL RPM bundle (NOT Docker). "
            "Python startup (python illumio_ops.py) is dev-only post-roadmap. "
            "pandas is mandatory (41 files, 338 DataFrame ops — cannot remove)."
        ),

        # ── 2. Roadmap structure ────────────────────────────────────
        (
            "illumio_ops upgrade roadmap has 9 phases in docs/superpowers/plans/. "
            "Phase 0 deps, Phase 1 CLI (rich/click/humanize), Phase 2 HTTP "
            "(requests/orjson/cachetools), Phase 3 Settings (pydantic v2), "
            "Phase 4 Web security (flask-wtf/limiter/talisman/login/argon2id), "
            "Phase 5 Reports (xlsx/pdf/plotly/matplotlib/pygments), "
            "Phase 6 Scheduler (APScheduler), Phase 7 Logging (loguru full "
            "replacement), Phase 9 Architecture refactor. Phase 8 RPM packaging "
            "is a separate future plan, not yet written."
        ),

        # ── 3. Completion state ──────────────────────────────────────
        (
            "illumio_ops Waves A+B complete 2026-04-18 via Subagent-Driven Dev. "
            "7 tags on origin: v3.4.0-deps, v3.4.1-cli, v3.4.2-http, "
            "v3.4.3-settings, v3.5.0-websec, v3.5.1-reports, v3.5.2-scheduler. "
            "Main HEAD before Wave C: 8d3c896 (docs: Wave C plans merged). "
            "Test baseline on main: 252 passed, 3 skipped, i18n audit 0 findings."
        ),

        # ── 4. Wave C remaining work ─────────────────────────────────
        (
            "illumio_ops Wave C remaining: Phase 7 (loguru) then Phase 9 "
            "(architecture refactor). Must be sequential: Phase 7 migrates "
            "stdlib logging -> loguru via scripts/migrate_to_loguru.py codemod; "
            "Phase 9 then refactors god-class api_client.py (2542 LOC -> "
            "<800 LOC facade + 3 domain classes). Doing Phase 9 first would "
            "force a second codemod pass over its new logger calls."
        ),

        # ── 5. Plan file locations ───────────────────────────────────
        (
            "illumio_ops plan files all on main branch: "
            "docs/superpowers/plans/2026-04-18-upgrade-roadmap.md (master); "
            "phase-0-deps.md (done), phase-1-cli-rich.md (done), "
            "phase-2-http-requests.md (done), phase-3-settings-pydantic.md (done), "
            "phase-4-web-security.md (done), phase-5-reports-rich.md (done), "
            "phase-6-scheduler-aps.md (done), phase-7-logging-loguru.md (pending), "
            "phase-9-architecture.md (pending). No Phase 8 plan yet."
        ),

        # ── 6. Execution recipe (critical for device handoff) ────────
        (
            "illumio_ops Wave C execution recipe: (1) git clone the repo + "
            "cd in. (2) Create venv at .venv-phase0: `python -m venv .venv-phase0`. "
            "(3) Install deps: `python -m pip install -r requirements.txt "
            "-r requirements-dev.txt`. On Linux/Mac weasyprint works natively; "
            "on Windows it fails OSError but skip tests handle it. "
            "(4) Run baseline: `python -m pytest tests/ -q` should give 252 passed "
            "+ 3 skipped on Windows, or ~254 passed on Linux. "
            "(5) Invoke superpowers:subagent-driven-development skill. "
            "(6) For each phase: create worktree `git worktree add -b "
            "upgrade/phase-N-name ../illumio_ops-phaseN main`, dispatch "
            "implementer subagent with worktree path + plan path + shared venv "
            "python path. (7) On each report-back: dispatch spec reviewer, then "
            "code quality reviewer, then fix subagent if CHANGES_REQUESTED. "
            "(8) Push branch + PR via GitHub API (gh CLI not on Windows — use "
            "git credential fill to get token + curl). (9) Squash merge. "
            "(10) Tag vX.Y.Z-name + push tag. (11) Cleanup: reset main hard + "
            "delete remote branch + delete local branch (worktree must be "
            "removed first or branch delete fails)."
        ),

        # ── 7. Git workflow gotchas ─────────────────────────────────
        (
            "illumio_ops git workflow gotchas: "
            "(a) Status.md and Task.md ALWAYS conflict on rebase between phases "
            "— resolve by keeping both Phase sections + updating version header "
            "to reflect cumulative merged phases. "
            "(b) scripts/audit_i18n_report.md has CRLF on Windows causing "
            "'unstaged changes' blocking rebase — `git stash -u` before rebase. "
            "(c) gh CLI is NOT installed on Windows; use GitHub API via curl + "
            "token from `printf 'protocol=https\\nhost=github.com\\n\\n' | "
            "git credential fill`. (d) Pushing directly to main is blocked by "
            "Claude Code sandbox — always use feature branch + PR. "
            "(e) After merge, `git reset --hard origin/main` on local main to "
            "avoid merge-commit noise from the squash."
        ),

        # ── 8. Wave C merge order ───────────────────────────────────
        (
            "illumio_ops Wave C merge order: Phase 7 first (v3.6.0-loguru), "
            "then rebase Phase 9 on main, then merge Phase 9 (v3.7.0-refactor). "
            "Phase 7 touches 30+ src/ files via codemod; Phase 9 touches "
            "api_client.py + analyzer.py + creates src/api/ package + exceptions.py "
            "+ interfaces.py + href_utils.py. They overlap on api_client.py so "
            "Phase 9 MUST rebase after Phase 7 merges."
        ),

        # ── 9. Phase 7 strategy ──────────────────────────────────────
        (
            "illumio_ops Phase 7 (loguru) strategy: create src/loguru_config.py "
            "with setup_loguru() central config (console + rotating file + "
            "optional JSON sink for SIEM). InterceptHandler routes stdlib "
            "logging from 3rd-party libs into loguru. src/utils.py::setup_logger "
            "delegates to loguru_config. scripts/migrate_to_loguru.py codemod "
            "uses ast + regex to: (1) import logging -> from loguru import logger, "
            "(2) delete `logger = logging.getLogger(__name__)`, (3) convert "
            "%s/%d/%i/%f/%r to {} inside logger.X(...) string literals. "
            "EXCLUDE module_log.py (business logic, not logging infra), "
            "loguru_config.py, utils.py from codemod. Dry-run first via "
            "`python scripts/migrate_to_loguru.py --dry-run`. "
            "Main risk: multi-line logger calls may be missed by regex — "
            "manual review of codemod diff required."
        ),

        # ── 10. Phase 9 strategy ─────────────────────────────────────
        (
            "illumio_ops Phase 9 (refactor) sub-tasks in risk order: "
            "Task 1 A5 delete events/shadow.py, Task 2 Q3 unify extract_id() "
            "to new src/href_utils.py, Task 3 A4 create src/exceptions.py "
            "(IllumioOpsError + APIError/ConfigError/ReportError/AlertError/"
            "SchedulerError/EventError) + audit silent `except: pass`, "
            "Task 4 Q1 decompose Analyzer.run_analysis() 196 lines into 4 "
            "private methods (_fetch_traffic, _run_event_analysis, _run_rule_engine, "
            "_dispatch_alerts), Task 5 residual thread-safety on _rs_log_history "
            "+ module_log _registry + _LAST_INPUT_ACTION + _current_lang, "
            "Task 6 A2 split api_client.py (2542 LOC) into facade + "
            "src/api/traffic_query.py TrafficQueryBuilder + src/api/async_jobs.py "
            "AsyncJobManager + src/api/labels.py LabelResolver (composition, "
            "NOT inheritance). All 50+ public ApiClient methods stay (facade "
            "delegates). Task 7 A1/Q2 create src/interfaces.py with Protocol "
            "definitions so Analyzer depends on Protocol not concrete class. "
            "Task 8 docs + merge."
        ),

        # ── 11. Status.md findings resolved by Wave A+B ─────────────
        (
            "illumio_ops Status.md findings resolved by Wave A+B: "
            "S1 argon2id (Phase 4), S4 flask-wtf CSRF (Phase 4), "
            "S5 flask-limiter rate limit (Phase 4), A3 APScheduler threadpool "
            "(Phase 6), T1 TTLCache thread-safety via _cache_lock RLock (Phase 6), "
            "D2 pydantic config validation (Phase 3), Q5 cachetools.TTLCache (Phase 2). "
            "Remaining for Wave C: A1 (tight coupling), A2 (god-class split), "
            "A4 (silent exception swallowing), A5 (events/shadow.py removal), "
            "Q1 (run_analysis 196 LOC), Q2 (api_client 2542 LOC), Q3 (duplicate "
            "extract_id)."
        ),

        # ── 12. CLI + API surface after Wave A+B ────────────────────
        (
            "illumio_ops CLI surface after Wave A+B: `illumio-ops` subcommands = "
            "version | config (validate|show) | monitor | gui | report "
            "(traffic) | status. Legacy argparse flags still work via argv[1] "
            "dispatcher in illumio_ops.py: --monitor -i N, --gui --port P, "
            "--report --source api|csv --format html|csv|pdf|xlsx|all, "
            "--monitor-gui. Main menu (no args) enters interactive via "
            "src.main.main_menu(). src/cli/ package has: __init__.py, root.py, "
            "monitor.py, gui_cmd.py, report.py, status.py, config.py."
        ),

        # ── 13. ApiClient state after Wave A+B ──────────────────────
        (
            "illumio_ops ApiClient (src/api_client.py) state after Phase 2+6: "
            "2542 LOC, uses requests.Session with urllib3.Retry (429/502/503/504 "
            "backoff, respect Retry-After). 5 TTLCaches: label_cache, "
            "service_ports_cache, _label_href_cache, _label_group_href_cache, "
            "_iplist_href_cache — all TTL=900s, timer=time.time. "
            "self._cache_lock = threading.RLock() wraps every mutation site "
            "(update_label_cache read/write split, invalidate_labels, "
            "invalidate_query_lookup_cache). orjson.loads on response parse "
            "hot paths; json.dumps still for request bodies. "
            "verify_ssl accepts bool OR CA bundle path string. "
            "_request(url, method, data, headers, timeout, stream) -> "
            "(status_code: int, body: bytes | Response) contract PRESERVED — "
            "50+ calling methods unchanged. Phase 9 will split this into facade "
            "+ 3 domain classes."
        ),

        # ── 14. Web GUI state after Wave A+B ────────────────────────
        (
            "illumio_ops Web GUI (src/gui.py) state after Phase 4: build_app(cm) "
            "factory returns Flask app; launch_gui is thin wrapper calling "
            ".run(). flask-login uses AdminUser(UserMixin) + LoginForm(pydantic). "
            "before_request checks current_user.is_authenticated (not "
            "@login_required decorator — chosen for uniform coverage + IP allowlist "
            "in same pass). flask-wtf CSRFProtect with X-CSRFToken + X-CSRF-Token "
            "dual header. flask-limiter @limiter.limit('5 per minute') on "
            "/api/login + custom JSON 429 errorhandler. flask-talisman CSP "
            "(default-src 'self', script-src 'unsafe-inline' needed for SPA) + "
            "HSTS conditional on TLS + Permissions-Policy restricting "
            "camera/microphone/geolocation. /api/reports/generate has "
            "format allowlist (security hardening)."
        ),

        # ── 15. Scheduler state ─────────────────────────────────────
        (
            "illumio_ops scheduler (src/scheduler/) after Phase 6: "
            "build_scheduler(cm, interval_minutes) factory builds "
            "BackgroundScheduler with ThreadPoolExecutor(max_workers=5), "
            "coalesce=True, max_instances=1, misfire_grace_time=60. "
            "3 jobs in src/scheduler/jobs.py: run_monitor_cycle "
            "(IntervalTrigger minutes=N: Analyzer + Reporter), "
            "tick_report_schedules (seconds=60: ReportScheduler.tick), "
            "tick_rule_schedules (seconds=rule_check_interval: ScheduleEngine.check). "
            "src/main.py::run_daemon_loop() starts scheduler inside try, registers "
            "SIGINT + SIGTERM handlers setting _shutdown_event, shutdown in "
            "finally guarded by `if sched.running`. Signature preserved."
        ),

        # ── 16. Reports state ───────────────────────────────────────
        (
            "illumio_ops Reports (src/report/) state after Phase 5: dual-engine "
            "chart_renderer.py with render_plotly_html(spec) offline-inline and "
            "render_matplotlib_png(spec) with Noto Sans CJK TC font fallback. "
            "xlsx_exporter.py openpyxl multi-sheet (Summary + per-module) with "
            "frozen header, red fill on blocked/deny rows, embedded matplotlib "
            "PNG. pdf_exporter.py weasyprint with lazy import + CJK CSS "
            "(@page A4 20mm margins). code_highlighter.py pygments JSON/YAML/"
            "bash wrappers. chart_spec added to mod02 (pie), mod05 (bar), mod07 "
            "(heatmap), mod10 (line), mod15 (network). 4 HTML exporters embed "
            "plotly div + base64 PNG fallback + pygments CSS. CLI --format, "
            "click --format, GUI select, /api/reports/generate all accept "
            "html|csv|pdf|xlsx|all. Only ReportGenerator (traffic) has pdf/xlsx "
            "dispatch wired; audit/ven/policy_usage generators deferred as "
            "follow-up (no chart_spec in those modules yet)."
        ),

        # ── 17. Config state ────────────────────────────────────────
        (
            "illumio_ops config (src/config.py + src/config_models.py) after "
            "Phase 3: ConfigManager.load() validates via pydantic ConfigSchema. "
            "14 BaseModel classes mirror _DEFAULT_CONFIG. cm.config stays as "
            "dict (model.model_dump) for 70+ dict-access callers. "
            "cm.models is the typed view (ConfigSchema instance). On ValidationError, "
            "cm.config falls back to deep-merged raw data (preserves valid "
            "sections); cm.models falls back to ConfigSchema() defaults. "
            "ApiSettings.url field_validator normalizes via HttpUrl oracle but "
            "returns plain string (no trailing slash). Secret fields "
            "(key/secret/password/token) redacted from ValidationError logs. "
            "rule_backups field IS in ConfigSchema (regression fix from review)."
        ),

        # ── 18. Test running recipe ─────────────────────────────────
        (
            "illumio_ops test commands on Linux/Mac: "
            "`python -m pytest tests/ -q` (expect 252+ passed, 1-3 skipped). "
            "i18n audit gate: `python -m pytest tests/test_i18n_audit.py "
            "tests/test_i18n_quality.py -v` (MUST stay 0 findings). "
            "Dependency gate: `python scripts/verify_deps.py` (exits 0 if all "
            "prod packages import). Key test files for each phase are in tests/ "
            "named test_<subject>_contract.py or test_<feature>.py. "
            "test_dependency_baseline.py is the CI entry point."
        ),

        # ── 19. Local memory dir (device-specific, won't transfer) ──
        (
            "illumio_ops local auto-memory (Claude Code) on Windows at "
            "C:\\Users\\harry\\.claude\\projects\\D--OneDrive-RD-illumio-ops\\memory\\"
            "MEMORY.md plus individual .md files. This is device-specific and "
            "does NOT transfer between machines — rely on Mem0 cloud instead "
            "for cross-device context. Mem0 user_id = 'harry10148'."
        ),

        # ── 20. Mem0 integration pattern ────────────────────────────
        (
            "illumio_ops Mem0 integration: scripts/mem0_wave_ab_snapshot.py and "
            "scripts/mem0_device_handoff_snapshot.py read MEM0_API_KEY from env "
            "(never hardcode). Use MemoryClient() default constructor. "
            "user_id='harry10148'. client.add() uses infer=True (default) which "
            "summarizes; use infer=False for verbatim precise facts. "
            "search()/get_all() require version='v2' + filters={'AND': "
            "[{'user_id': '...'}]} format in mem0ai>=2.0. Run scripts in the "
            "venv: `.venv-phase0/Scripts/python.exe scripts/mem0_*.py` on Windows "
            "or `.venv-phase0/bin/python scripts/mem0_*.py` on Linux/Mac."
        ),
    ]

    success, fail = 0, 0
    for text in facts:
        msg = [{"role": "user", "content": text}]
        try:
            # infer=False preserves the fact verbatim for precision
            client.add(
                messages=msg,
                user_id=user_id,
                metadata={
                    "project": project_id,
                    "category": "device_handoff_snapshot",
                    "snapshot_date": "2026-04-18",
                },
                infer=False,
            )
            success += 1
            print(f"OK  [{success:02d}] {text[:80]}...")
        except Exception as exc:
            fail += 1
            print(f"FAIL [{fail}]: {exc}", file=sys.stderr)
            print(f"     text: {text[:80]}...", file=sys.stderr)

    print(f"\nSummary: {success}/{len(facts)} succeeded.")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
