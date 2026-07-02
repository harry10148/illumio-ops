"""
src/report_scheduler.py
Report Schedule Engine — evaluates and runs report schedules at each daemon tick.

Usage (called from daemon loop every 60 seconds):
    scheduler = ReportScheduler(config_manager, reporter)
    scheduler.tick()
"""
from __future__ import annotations

import datetime
import json
from loguru import logger
import os
import re

from src.i18n import t
from src.report.report_metadata import extract_attack_summary
from src.state_store import load_state_file, update_state_file
from src.tz_utils import resolve_tz

def _now_in_schedule_tz(tz_str: str) -> datetime.datetime:
    """Return 'now' in the schedule's timezone for hour/minute matching.

    Semantics by tz_str:
      * 'UTC' / 'UTC+N' / 'UTC-N' / IANA 名稱（如 'Asia/Taipei'）→ NAIVE
        wall-clock in that timezone.
      * 'local' or unset/empty    → UTC, returned as an AWARE datetime.

    NOTE: despite the 'local' label, this intentionally resolves to UTC (NOT
    server-local time). The aware-UTC fallback avoids naive/DST ambiguity and
    mirrors rule_scheduler._now_in_tz; should_run() normalises the aware value
    to naive before the rerun-gap subtraction. Consequence: a schedule set to
    fire at HH:MM with tz='local'/unset fires at HH:MM UTC. Operators on a
    non-UTC server who want local wall-clock must set an explicit 'UTC+N' or
    IANA name.

    時區字串一律經 tz_utils.resolve_tz 解析成 tzinfo，再用
    ``datetime.now(tzinfo)`` 取得該時區「真正」的當下牆鐘 —— 這樣 IANA 名稱
    才不會被誤判成偏移 0（過去只認 'UTC±N'，IANA 名稱會靜默退回 UTC，讓
    cron 分支把 UTC 牆鐘誤標成該時區時間，觸發時刻整整偏移一個 UTC offset）。
    """
    if not tz_str or tz_str == 'local':
        # 'local'/unset are treated as UTC (aware) — see docstring. Kept aware to
        # dodge naive/DST ambiguity; should_run() strips tzinfo before comparing.
        return datetime.datetime.now(datetime.timezone.utc)
    tz_obj = resolve_tz(tz_str)
    return datetime.datetime.now(tz_obj).replace(tzinfo=None)

# State key written to state.json
_STATE_KEY = "report_schedule_states"

# Gap to prevent re-trigger within the same hour window (seconds). Only guards
# the daily/weekly/monthly branch of should_run() — the cron_expr branch's
# anti-dupe comes from CronTrigger.get_next_fire_time(prev, now) instead, so
# sub-hourly cron (e.g. '*/15 * * * *') isn't collapsed to firing once/hour.
_MIN_RERUN_GAP = 3600

# Sentinel for "not provided" — distinguishes None (never run) from missing arg
_UNSET = object()

class ReportScheduler:
    def __init__(self, config_manager, reporter):
        self.cm = config_manager
        self.reporter = reporter
        # Determine paths
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        self._root_dir = os.path.dirname(pkg_dir)
        self._state_file = os.path.join(self._root_dir, "logs", "state.json")
        self._config_dir = os.path.join(self._root_dir, "config")

    # ─── State helpers ────────────────────────────────────────────────────────

    def _load_states(self) -> dict:
        """Load per-schedule state from state.json."""
        data = load_state_file(self._state_file)
        return data.get(_STATE_KEY, {})

    def _save_state(self, schedule_id: int, last_run: str, status: str, error: str = ""):
        """Persist schedule execution result into state.json."""
        try:
            def _merge(existing):
                data = dict(existing)
                states = data.setdefault(_STATE_KEY, {})
                states[str(schedule_id)] = {
                    "last_run": last_run,
                    "status": status,
                    "error": error,
                }
                return data

            update_state_file(self._state_file, _merge)
        except Exception as e:
            logger.error(f"Failed to save schedule state: {e}")

    # ─── Scheduling logic ────────────────────────────────────────────────────

    def should_run(self, schedule: dict, now: datetime.datetime,
                   last_run_str: str | None = _UNSET) -> bool:
        """Return True if this schedule should execute right now.

        Parameters
        ----------
        schedule:
            Schedule dict (must contain at least ``id`` and ``enabled``).
        now:
            Current datetime expressed in the schedule's local timezone
            (naive or aware — normalised below).
        last_run_str:
            ISO-format string of the last run time, or ``None`` if never run.
            When omitted (sentinel), the value is loaded from the persisted
            state file — the normal production path.  Pass ``None`` explicitly
            in tests to skip state-file I/O.

        Due semantics
        -------------
        cron_expr branch: delegates to APScheduler's CronTrigger. Anti-dupe
        for "same cron trigger time only fires once" comes entirely from
        ``get_next_fire_time(prev, now)`` (prev = last_run) — NOT from
        ``_MIN_RERUN_GAP``, which would otherwise collapse sub-hourly cron
        (e.g. ``*/15 * * * *``) down to firing once per hour.

        daily/weekly/monthly branch: catch-up semantics — due when
        ``now >= 排程時刻`` (today's hour:minute) AND
        ``last_run < 排程時刻``. This lets a tick that missed the exact
        minute (e.g. busy running a previous report) still fire once it
        next checks, while ``last_run`` moving past the target prevents a
        second fire the same day. ``_MIN_RERUN_GAP`` additionally guards
        this branch against re-trigger from clock/tick jitter.

        Catch-up scope: limited to the TARGET DAY itself. weekly/monthly
        still require ``now`` to fall on the scheduled weekday/day-of-month
        (day_matches) — an outage that swallows the whole target day means
        zero fires for that period (safe, no replay), NOT a later-in-the-week
        make-up run.
        """
        if not schedule.get("enabled", False):
            return False

        # Schedule 時區（tzinfo 物件），fallback 鏈與 tick() 一致：
        # schedule.timezone → global settings.timezone → UTC。'local'/未設
        # 比照 _now_in_schedule_tz 解讀成 UTC（不是伺服器本地）。`self.cm`
        # 在 bare ReportScheduler.__new__() 測試替身上可能不存在。
        cm = getattr(self, "cm", None)
        global_tz = (cm.config.get('settings', {}).get('timezone', 'local')
                     if cm is not None else None)
        sched_tz = schedule.get("timezone") or global_tz
        if not sched_tz or sched_tz == 'local':
            tz_obj = datetime.timezone.utc
        else:
            # 統一走 tz_utils.resolve_tz——直接得到 tzinfo 物件（不是字串）
            # 餵給 CronTrigger／now_aware，'UTC+N' 這類偏移字串才不會被
            # zoneinfo 誤判成不存在的時區、每個 tick 都多印一次 warning。
            tz_obj = resolve_tz(sched_tz)

        # Resolve last_run_str: use provided value or load from state file.
        if last_run_str is _UNSET:
            states = self._load_states()
            sid = str(schedule.get("id", ""))
            last_run_str = states.get(sid, {}).get("last_run")

        last_run_dt = None
        if last_run_str:
            try:
                last_run_dt = datetime.datetime.fromisoformat(last_run_str)
                # Aware timestamps（GUI「立即執行」路徑寫入 UTC-aware；tick()
                # 寫入 schedule-local naive）必須先「轉換」到 schedule 時區再剝
                # tzinfo——直接 replace(tzinfo=None) 會把 UTC 牆鐘誤讀成
                # schedule-local，非 UTC 時區的排程在 Run Now 之後同一天會被
                # 誤判為「尚未跑過」而重跑（報表重寄）。Naive timestamps 維持
                # 既有解讀（本就是 schedule-local 牆鐘）。
                if last_run_dt.tzinfo is not None:
                    last_run_dt = last_run_dt.astimezone(tz_obj).replace(tzinfo=None)
            except (ValueError, TypeError):
                last_run_dt = None

        # `now` is tz-AWARE for tz='local'/unset but NAIVE for 'UTC'/'UTC+N'
        # (see _now_in_schedule_tz). Normalize to naive throughout so
        # comparisons never mix naive & aware datetimes.
        now_naive = now.replace(tzinfo=None) if now.tzinfo else now

        # cron_expr branch: use APScheduler CronTrigger to decide if due.
        cron_expr = schedule.get("cron_expr")
        if cron_expr:
            try:
                from apscheduler.triggers.cron import CronTrigger
                trigger = CronTrigger.from_crontab(cron_expr, timezone=tz_obj)
                now_aware = now_naive.replace(tzinfo=tz_obj)
                prev = last_run_dt.replace(tzinfo=tz_obj) if last_run_dt else None
                next_fire = trigger.get_next_fire_time(prev, now_aware)
                return next_fire is not None and next_fire <= now_aware
            except Exception:
                logger.warning("Invalid cron_expr for schedule {}", schedule.get("id"))
                return False

        # Rerun-gap guard: only for the daily/weekly/monthly branch below.
        # cron 的重跑保護交給上面「同一 cron 觸發時刻只跑一次」的 next_fire 判定。
        if last_run_dt is not None and (now_naive - last_run_dt).total_seconds() < _MIN_RERUN_GAP:
            return False

        stype = schedule.get("schedule_type", "weekly")
        hour = int(schedule.get("hour", 8))
        minute = int(schedule.get("minute", 0))

        if stype == "daily":
            day_matches = True
        elif stype == "weekly":
            dow = schedule.get("day_of_week", "monday").lower()
            day_matches = now_naive.strftime("%A").lower() == dow
        elif stype == "monthly":
            dom = int(schedule.get("day_of_month", 1))
            day_matches = now_naive.day == dom
        else:
            return False

        if not day_matches:
            return False

        # Catch-up 語意：今天的排程時刻已到（now >= target）且尚未於該時刻後
        # 執行過（last_run < target）即視為 due——取代舊版精確分鐘比對，讓 tick
        # 因執行前一個排程而錯過整分鐘時仍能補跑一次，且只補一次。補跑範圍限
        # 「目標日當天」：weekly/monthly 仍要求 now 落在目標 weekday/day
        # （上面的 day_matches），停機吞掉整個目標日就是該期 0 次（安全、
        # 不重放），不會在之後的日子補跑。
        target = now_naive.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now_naive < target:
            return False
        if last_run_dt is not None and last_run_dt >= target:
            return False
        return True

    # ─── Execution ───────────────────────────────────────────────────────────

    def run_schedule(self, schedule: dict) -> bool:
        """
        Execute a single report schedule: generate report + optionally email it.
        Returns True on success.
        """
        try:
            from src.module_log import ModuleLog as _ML
            _rslog = _ML.get("report_scheduler")
            _rslog.separator(f"Report Schedule: {schedule.get('name', '')}")
            _rslog.info(f"type={schedule.get('report_type')} format={schedule.get('format')} lookback={schedule.get('lookback_days')}d")
        except Exception:
            pass  # intentional fallback: ModuleLog is optional; schedule execution must not fail if logging setup fails

        lang = (
            schedule.get("lang")
            or self.cm.config.get("settings", {}).get("language", "en")
        )

        name = schedule.get("name", "Unnamed")
        report_type = schedule.get("report_type", "traffic")
        lookback_days = int(schedule.get("lookback_days", 7))
        fmt_list = schedule.get("format", ["html"])
        fmt = fmt_list[0] if isinstance(fmt_list, list) and fmt_list else "html"
        if len(fmt_list) > 1:
            fmt = "all"
        send_email = schedule.get("email_report", False)
        custom_recipients = schedule.get("email_recipients", [])

        output_dir = schedule.get("output_dir") or self.cm.config.get("report", {}).get("output_dir", "reports")
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(self._root_dir, output_dir)
        os.makedirs(output_dir, exist_ok=True)

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        end_date = now_utc.strftime("%Y-%m-%dT23:59:59Z")
        start_date = (now_utc - datetime.timedelta(days=lookback_days)).strftime("%Y-%m-%dT00:00:00Z")

        # Read optional traffic filters from schedule config
        schedule_filters = schedule.get('filters') or None

        logger.info(f"[Scheduler] Running schedule '{name}' ({report_type}), range={start_date}→{end_date}")

        try:
            from src.api_client import ApiClient
            with ApiClient(self.cm) as api:
                result, paths = self._generate_report(
                    report_type, api, fmt, output_dir, start_date, end_date, name,
                    filters=schedule_filters, lang=lang, schedule=schedule)

                if result is None:
                    return False

                if send_email and paths:
                    self._send_report_email(schedule, result, paths, start_date, end_date,
                                            custom_recipients, report_type=report_type,
                                            lang=lang)

            logger.info(f"[Scheduler] '{name}': completed, files={[os.path.basename(p) for p in paths]}")
            try:
                _rslog.info(f"Completed: {[os.path.basename(p) for p in paths]}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            max_reports = int(schedule.get("max_reports", 30))
            self._prune_by_count(output_dir, report_type, max_reports)
            self._prune_old_reports(output_dir)
            return True

        except Exception as e:
            try:
                _rslog.error(f"Failed: {e}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            logger.exception(f"[Scheduler] '{name}': failed — {e}")
            raise

    # ── Report type dispatch ────────────────────────────────────────────────

    def _generate_report(self, report_type, api, fmt, output_dir, start_date, end_date, name, filters=None, lang: str = "en", schedule: dict | None = None):
        """Dispatch to the appropriate generator. Returns (result, paths) or (None, [])."""
        from src.main import _make_cache_reader
        if report_type == "traffic":
            from src.report.report_generator import ReportGenerator
            gen = ReportGenerator(self.cm, api_client=api, config_dir=self._config_dir,
                                  cache_reader=_make_cache_reader(self.cm))
            result = gen.generate_from_api(start_date=start_date, end_date=end_date, filters=filters, lang=lang,
                                           traffic_report_profile="traffic")
            if result.record_count == 0:
                logger.warning(f"[Scheduler] '{name}': no traffic data — skipping export")
                return None, []
            paths = gen.export(result, fmt=fmt, output_dir=output_dir,
                               send_email=False, reporter=None,
                               traffic_report_profile="traffic")
            return result, paths

        elif report_type in ("security_risk", "network_inventory"):
            from src.report.report_generator import ReportGenerator
            gen = ReportGenerator(self.cm, api_client=api, config_dir=self._config_dir,
                                  cache_reader=_make_cache_reader(self.cm))
            result = gen.generate_from_api(start_date=start_date, end_date=end_date,
                                           filters=filters, traffic_report_profile=report_type, lang=lang)
            if result.record_count == 0:
                logger.warning(f"[Scheduler] '{name}': no traffic data — skipping export")
                return None, []
            paths = gen.export(result, fmt=fmt, output_dir=output_dir, send_email=False,
                               reporter=None, traffic_report_profile=report_type)
            return result, paths

        elif report_type == "audit":
            from src.report.audit_generator import AuditGenerator
            gen = AuditGenerator(self.cm, api_client=api, config_dir=self._config_dir,
                                 cache_reader=_make_cache_reader(self.cm))
            result = gen.generate_from_api(start_date=start_date, end_date=end_date, lang=lang)
            if result.record_count == 0:
                logger.warning(f"[Scheduler] '{name}': no audit data — skipping export")
                return None, []
            paths = gen.export(result, fmt=fmt, output_dir=output_dir)
            return result, paths

        elif report_type == "ven_status":
            from src.report.ven_status_generator import VenStatusGenerator
            gen = VenStatusGenerator(self.cm, api_client=api)
            result = gen.generate(lang=lang)
            if result.record_count == 0:
                logger.warning(f"[Scheduler] '{name}': no VEN data — skipping export")
                return None, []
            paths = gen.export(result, output_dir=output_dir)
            return result, paths

        elif report_type == "policy_usage":
            from src.report.policy_usage_generator import PolicyUsageGenerator
            gen = PolicyUsageGenerator(self.cm, api_client=api, config_dir=self._config_dir)
            result = gen.generate_from_api(start_date=start_date, end_date=end_date, lang=lang)
            if result.record_count == 0:
                logger.warning(f"[Scheduler] '{name}': no active rules found — skipping export")
                return None, []
            paths = gen.export(result, fmt=fmt, output_dir=output_dir)
            return result, paths

        elif report_type == "policy_diff":
            from src.report.policy_diff_report import PolicyDiffReport
            from src.report.exporters.policy_diff_html_exporter import PolicyDiffHtmlExporter
            from types import SimpleNamespace
            rpt = PolicyDiffReport(self.cm, api_client=api, config_dir=self._config_dir,
                                   cache_reader=_make_cache_reader(self.cm))
            diff = rpt.build(lang=lang)
            if diff["summary"]["total_changes"] == 0:
                logger.info(f"[Scheduler] '{name}': no DRAFT-vs-ACTIVE changes — emitting empty report")
            path = PolicyDiffHtmlExporter(diff, lang=lang).export(output_dir)
            result = SimpleNamespace(record_count=diff["summary"]["total_changes"])
            return result, [path]

        elif report_type == "policy_resolver":
            from src.report.policy_resolver_report import PolicyResolverReport
            from src.report.exporters.policy_resolver_exporter import PolicyResolverExporter
            from types import SimpleNamespace
            rpt = PolicyResolverReport(self.cm, api_client=api, config_dir=self._config_dir)
            results = rpt.resolve()
            # Unlike policy_diff (which emits an empty diff report), a resolver
            # run with no resolved rows has nothing to export — skip the schedule.
            if results["record_count"] == 0:
                logger.warning(f"[Scheduler] '{name}': no policy resolver data — skipping export")
                return None, []
            paths = PolicyResolverExporter(results, lang=lang).export(output_dir, fmt="all")
            result = SimpleNamespace(record_count=results["record_count"])
            return result, paths

        elif report_type == "app_summary":
            from src.report.app_summary_report import AppSummaryReport
            from types import SimpleNamespace
            sched = schedule or {}
            app = (sched.get("app") or "").strip()
            if not app:
                raise ValueError("app_summary schedule requires an 'app' value")
            rep = AppSummaryReport(self.cm, api_client=api, config_dir=self._config_dir,
                                   cache_reader=_make_cache_reader(self.cm))
            path = rep.run(app=app, env=(sched.get("env") or None),
                           output_dir=output_dir, lang=lang)
            result = SimpleNamespace(record_count=1)
            return result, [path]

        else:
            logger.error(f"[Scheduler] Unknown report_type: {report_type}")
            return None, []

    def _send_report_email(self, schedule: dict, result, paths: list,
                            start_date: str, end_date: str,
                            custom_recipients: list, report_type: str,
                            lang: str = "en"):
        """Build and send the scheduled report email."""
        import html as _html

        name = schedule.get("name", "Report")
        date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        subject = f"[Illumio Monitor] {name} — {date_str}"

        # Build HTML body
        esc = lambda s: _html.escape(str(s), quote=True)
        type_label = {"traffic": t("rpt_email_traffic_subject", lang=lang), "audit": t("rpt_email_audit_subject", lang=lang),
                      "security_risk": t("rpt_security_report_title", lang=lang),
                      "network_inventory": t("rpt_inventory_report_title", lang=lang),
                      "ven_status": t("rpt_email_ven_subject", lang=lang),
                      "policy_usage": t("rpt_email_pu_subject", lang=lang),
                      "policy_diff": t("rpt_policy_diff_report_title", lang=lang),
                      "policy_resolver": t("rpt_policy_resolver_title", lang=lang),
                      "app_summary": t("rpt_app_title", lang=lang)}.get(report_type, "Report")
        start_disp = start_date[:10] if start_date else "N/A"
        end_disp = end_date[:10] if end_date else "N/A"

        body = "<html><body style='margin:0;padding:0;background:#F4F4F4;font-family:\"Montserrat\",Arial,sans-serif;color:#313638;'>"
        body += "<div style='max-width:860px;margin:0 auto;padding:16px;'>"
        body += "<div style='border:1px solid #325158;border-radius:10px;background:#fff;overflow:hidden;'>"

        # Header
        body += "<div style='padding:18px 20px;background:#1A2C32;color:#fff;border-left:4px solid #FF5500;'>"
        body += f"<div style='font-size:20px;font-weight:700;margin-bottom:4px;'>{esc(type_label)}</div>"
        body += f"<div style='font-size:12px;color:#989A9B;'>{esc(name)} — {t('rpt_email_scheduled_report', lang=lang)}</div>"
        body += "</div>"

        # KPI bar
        body += "<div style='padding:14px 20px;border-bottom:1px solid #E5E5E5;background:#F4F4F4;display:flex;flex-wrap:wrap;gap:8px;'>"
        body += f"<span style='background:#FF5500;color:#fff;padding:4px 10px;border-radius:999px;font-size:12px;font-weight:700;'>{t('rpt_email_records', lang=lang, count=esc(result.record_count))}</span>"
        body += f"<span style='background:#1A2C32;color:#D6D7D7;padding:4px 10px;border-radius:999px;font-size:12px;'>{t('rpt_email_period', lang=lang, start=esc(start_disp), end=esc(end_disp))}</span>"
        body += f"<span style='background:#E5E5E5;color:#313638;padding:4px 10px;border-radius:999px;font-size:12px;'>{t('rpt_email_source_api', lang=lang)}</span>"
        body += "</div>"

        body += "<div style='padding:16px 20px;'>"

        # KPIs from mod12 (traffic) or equivalent
        kpis = []
        if hasattr(result, "module_results") and result.module_results:
            mod12 = result.module_results.get("mod12") or result.module_results.get("kpis", {})
            if isinstance(mod12, dict):
                kpis = mod12.get("kpis", [])

        if kpis:
            body += "<div style='margin-bottom:16px;'>"
            body += f"<div style='font-size:14px;font-weight:700;color:#1A2C32;margin-bottom:10px;border-bottom:2px solid #FF5500;padding-bottom:4px;'>{t('rpt_email_kpi_title', lang=lang)}</div>"
            body += "<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;'>"
            for kpi in kpis[:8]:
                label = esc(kpi.get("label", ""))
                value = esc(kpi.get("value", ""))
                color = kpi.get("color", "#313638")
                body += f"<div style='background:#F4F4F4;border:1px solid #E5E5E5;border-radius:8px;padding:10px;text-align:center;'>"
                body += f"<div style='font-size:22px;font-weight:700;color:{esc(color)};'>{value}</div>"
                body += f"<div style='font-size:11px;color:#989A9B;margin-top:4px;'>{label}</div>"
                body += "</div>"
            body += "</div></div>"

        # Findings
        findings = getattr(result, "findings", []) or []
        if findings:
            body += "<div style='margin-bottom:16px;'>"
            body += f"<div style='font-size:14px;font-weight:700;color:#1A2C32;margin-bottom:10px;border-bottom:2px solid #BE122F;padding-bottom:4px;'>{t('rpt_email_security_findings', lang=lang)}</div>"
            body += "<table style='width:100%;border-collapse:collapse;font-size:12px;'>"
            body += "<tr style='background:#24393F;color:#D6D7D7;'>"
            body += f"<th style='padding:8px;text-align:left;'>{t('rpt_email_col_id', lang=lang)}</th><th style='padding:8px;text-align:left;'>{t('rpt_email_finding', lang=lang)}</th><th style='padding:8px;text-align:left;'>{t('rpt_email_col_severity', lang=lang)}</th>"
            body += "</tr>"
            sev_colors = {"CRITICAL": "#BE122F", "HIGH": "#F97607", "MEDIUM": "#F59E0B", "LOW": "#166644"}
            for i, f in enumerate(findings[:15]):
                row_bg = "#fff" if i % 2 == 0 else "#F4F4F4"
                # Finding is a dataclass; support dict fallback for forward compatibility
                if hasattr(f, 'severity'):
                    sev   = str(getattr(f, 'severity',    'INFO') or 'INFO').upper()
                    fid   = str(getattr(f, 'rule_id',     ''))
                    fname = str(getattr(f, 'rule_name',   ''))
                    fdesc = str(getattr(f, 'description', ''))
                else:
                    sev   = str(f.get('severity',    'INFO')).upper()
                    fid   = str(f.get('id',          ''))
                    fname = str(f.get('name',        ''))
                    fdesc = str(f.get('description', ''))
                sev_color = sev_colors.get(sev, "#313638")
                body += f"<tr style='background:{row_bg};'>"
                body += f"<td style='padding:8px;border-bottom:1px solid #E5E5E5;font-weight:700;color:#FF5500;'>{esc(fid)}</td>"
                body += f"<td style='padding:8px;border-bottom:1px solid #E5E5E5;'><strong>{esc(fname)}</strong><br><small style='color:#989A9B;'>{esc(fdesc)}</small></td>"
                body += f"<td style='padding:8px;border-bottom:1px solid #E5E5E5;font-weight:700;color:{sev_color};'>{esc(sev)}</td>"
                body += "</tr>"
            body += "</table></div>"

        attack_summary = extract_attack_summary(getattr(result, "module_results", {}) or {}, top_n=3)
        section_labels = {
            "boundary_breaches": t("rpt_email_boundary_breaches", lang=lang),
            "suspicious_pivot_behavior": t("rpt_email_suspicious_pivot_behavior", lang=lang),
            "blast_radius": t("rpt_email_blast_radius", lang=lang),
            "blind_spots": t("rpt_email_blind_spots", lang=lang),
            "action_matrix": t("rpt_email_action_matrix", lang=lang),
        }
        has_attack = any(attack_summary.get(k) for k in section_labels.keys())
        if has_attack:
            body += "<div style='margin-bottom:16px;'>"
            body += f"<div style='font-size:14px;font-weight:700;color:#1A2C32;margin-bottom:10px;border-bottom:2px solid #FF5500;padding-bottom:4px;'>{t('rpt_email_attack_summary', lang=lang)}</div>"
            body += "<table style='width:100%;border-collapse:collapse;font-size:12px;'>"
            body += "<tr style='background:#24393F;color:#D6D7D7;'>"
            body += f"<th style='padding:8px;text-align:left;'>Section</th><th style='padding:8px;text-align:left;'>{t('rpt_email_finding', lang=lang)}</th><th style='padding:8px;text-align:left;'>{t('rpt_email_action', lang=lang)}</th>"
            body += "</tr>"
            _zh = lang == "zh_TW"
            row_index = 0
            for key, label in section_labels.items():
                for item in (attack_summary.get(key) or [])[:2]:
                    row_bg = "#fff" if row_index % 2 == 0 else "#F4F4F4"
                    finding_en = esc(item.get("finding", ""))
                    if key == "action_matrix" and not finding_en:
                        finding_en = esc(item.get("action", ""))
                        if item.get("count") is not None:
                            finding_en = f"{finding_en} (x{esc(item.get('count'))})"
                    finding_html = finding_en
                    if _zh:
                        finding_zh = esc(item.get("finding_zh", ""))
                        if finding_zh:
                            finding_html += f"<br><small style='color:#989A9B;'>{finding_zh}</small>"

                    action_en = esc(item.get("action", ""))
                    action_html = action_en
                    if _zh:
                        action_zh = esc(item.get("action_zh", ""))
                        if action_zh:
                            action_html += f"<br><small style='color:#989A9B;'>{action_zh}</small>"

                    body += f"<tr style='background:{row_bg};'>"
                    body += f"<td style='padding:8px;border-bottom:1px solid #E5E5E5;font-weight:700;color:#1A2C32;'>{esc(label)}</td>"
                    body += f"<td style='padding:8px;border-bottom:1px solid #E5E5E5;'>{finding_html}</td>"
                    body += f"<td style='padding:8px;border-bottom:1px solid #E5E5E5;'>{action_html}</td>"
                    body += "</tr>"
                    row_index += 1
            body += "</table></div>"

        # Attachments note
        if paths:
            body += "<div style='background:#F4F4F4;border:1px solid #E5E5E5;border-radius:8px;padding:12px;margin-bottom:16px;'>"
            body += f"<div style='font-size:13px;font-weight:700;color:#1A2C32;margin-bottom:6px;'>{t('rpt_email_attached_files', lang=lang)}</div>"
            for p in paths:
                body += f"<div style='font-size:12px;color:#313638;padding:2px 0;'>📎 {esc(os.path.basename(p))}</div>"
            body += "</div>"

        body += "</div></div></div></body></html>"

        sent = self.reporter.send_scheduled_report_email(
            subject=subject,
            html_body=body,
            attachment_paths=paths,
            custom_recipients=custom_recipients,
        )
        if sent is False:
            raise RuntimeError(t("rpt_email_failed", lang=lang, error=""))

    # ─── Report retention ────────────────────────────────────────────────────

    # File prefix patterns for each report type (matches .html, .zip, and .json).
    # Most entries are a literal prefix (startswith). 'traffic' needs a regex:
    # TrafficFlowsHtmlExporter._filename emits an UNSUFFIXED filename
    # ('Illumio_Traffic_Report_<ts>.html'), and the bare string
    # 'Illumio_Traffic_Report_' is a strict prefix of BOTH the SecurityRisk and
    # NetworkInventory filenames used by 'security_risk'/'network_inventory', so
    # a literal-prefix match would let a 'traffic' prune delete a sibling
    # schedule's SecurityRisk/NetworkInventory reports (cross-type loss). The
    # regex anchors on the timestamp's leading digit right after the prefix so
    # it matches only the unsuffixed traffic filename.
    _REPORT_PREFIXES = {
        "traffic":           re.compile(r"^Illumio_Traffic_Report_\d{4}-"),
        "security_risk":     "Illumio_Traffic_Report_SecurityRisk_",
        "network_inventory": "Illumio_Traffic_Report_NetworkInventory_",
        "audit":             "illumio_audit_report_",
        "ven_status":        "illumio_ven_status_",
        "policy_usage":      "illumio_policy_usage_report_",
        "policy_diff":       "Illumio_Policy_Diff_Report_",
        "policy_resolver":   "Illumio_Policy_Resolver_",
        "app_summary":       "Illumio_App_Summary_",
    }

    @staticmethod
    def _report_unit_key(fname: str) -> str:
        """Collapse a report file and its metadata sidecar to one report-unit key.

        A single report run emits e.g. ``<stem>.html`` plus its
        ``<stem>.html.metadata.json`` sidecar; both map to the same key so that
        ``max_reports`` limits reports, not individual files.
        """
        name = fname
        if name.endswith(".metadata.json"):
            name = name[: -len(".metadata.json")]
        for ext in (".html", ".zip", ".json"):
            if name.endswith(ext):
                name = name[: -len(ext)]
                break
        return name

    def _prune_by_count(self, output_dir: str, report_type: str, max_reports: int):
        """Keep only the newest max_reports REPORTS for the given report type.

        A report is a UNIT: its ``.html`` (or ``.zip``/``.json``) file plus the
        accompanying ``.html.metadata.json`` sidecar count as ONE report, so
        ``max_reports`` limits reports rather than files. Matching files are
        grouped into units, the units are sorted by their newest member's mtime
        (filename as a deterministic tie-break), and every file in the surplus
        units is deleted. Set max_reports to 0 to disable.
        """
        if max_reports <= 0 or not os.path.isdir(output_dir):
            return
        prefix = self._REPORT_PREFIXES.get(report_type)
        if not prefix:
            return
        # 'prefix' is either a literal string (startswith) or a compiled regex
        # (match) -- see _REPORT_PREFIXES.
        matches = prefix.match if isinstance(prefix, re.Pattern) else \
            (lambda fname: fname.startswith(prefix))

        # Group matching files into report units (report + its metadata sidecar).
        units: dict[str, dict] = {}
        for fname in os.listdir(output_dir):
            if not (matches(fname) and fname.endswith((".html", ".zip", ".json"))):
                continue
            fpath = os.path.join(output_dir, fname)
            try:
                mtime = os.path.getmtime(fpath)
            except OSError:
                continue
            unit = units.setdefault(self._report_unit_key(fname),
                                    {"mtime": mtime, "files": []})
            unit["files"].append(fpath)
            if mtime > unit["mtime"]:
                unit["mtime"] = mtime

        # Sort report units newest-first (mtime, then key for determinism on
        # ties) and delete every file in the units beyond max_reports.
        ordered = sorted(units.items(), key=lambda kv: (kv[1]["mtime"], kv[0]),
                         reverse=True)
        for _key, unit in ordered[max_reports:]:
            for fpath in unit["files"]:
                try:
                    os.remove(fpath)
                    logger.info(f"[Scheduler] Count-pruned: {os.path.basename(fpath)} (limit={max_reports})")
                except Exception as e:
                    logger.warning(f"[Scheduler] Could not prune {fpath}: {e}")

    def _prune_old_reports(self, output_dir: str):
        """Delete report files older than retention_days (default 30).

        Covers .html, .zip, and .json files produced by the report engine.
        Controlled by config.report.retention_days; set to 0 to disable.
        """
        retention_days = int(
            self.cm.config.get("report", {}).get("retention_days", 30)
        )
        if retention_days <= 0:
            return
        if not os.path.isdir(output_dir):
            return

        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=retention_days)
        removed = 0
        for fname in os.listdir(output_dir):
            if not fname.endswith((".html", ".zip", ".json")):
                continue
            fpath = os.path.join(output_dir, fname)
            try:
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fpath), tz=datetime.timezone.utc)
                if mtime < cutoff:
                    os.remove(fpath)
                    removed += 1
                    logger.debug(f"[Scheduler] Pruned old report: {fname}")
            except Exception as e:
                logger.warning(f"[Scheduler] Could not prune {fname}: {e}")
        if removed:
            logger.info(f"[Scheduler] Pruned {removed} report file(s) older than {retention_days} days from {output_dir}")

    # ─── Tick (called every minute from daemon loop) ──────────────────────────

    def tick(self):
        """Check all enabled schedules and run any that are due."""
        self.cm.load()
        schedules = self.cm.config.get("report_schedules", [])
        if not schedules:
            return

        global_tz = self.cm.config.get('settings', {}).get('timezone', 'local')

        for sched in schedules:
            sched_tz = sched.get('timezone') or global_tz
            now = _now_in_schedule_tz(sched_tz)
            try:
                due = self.should_run(sched, now)
            except Exception as e:
                # One malformed schedule must never abort evaluation of the rest.
                logger.error(
                    "[Scheduler] should_run failed for schedule id={}: {}",
                    sched.get("id"), e,
                )
                continue
            if not due:
                continue

            sid = str(sched.get("id", ""))
            name = sched.get("name", "Unnamed")
            run_ts = now.isoformat()

            logger.info(f"[Scheduler] Triggering schedule id={sid} name='{name}'")
            try:
                self.run_schedule(sched)
                self._save_state(sched["id"], run_ts, "success")
            except Exception as e:
                self._save_state(sched["id"], run_ts, "failed", str(e))
