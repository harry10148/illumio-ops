"""
src/report_scheduler.py
Report Schedule Engine — evaluates and runs report schedules at each daemon tick.

Usage (called from daemon loop every 60 seconds):
    scheduler = ReportScheduler(config_manager, reporter)
    scheduler.tick()
"""

import datetime
import json
from loguru import logger
import os
import re

from src.i18n import t, get_language
from src.report.report_metadata import extract_attack_summary
from src.state_store import load_state_file, update_state_file

def _tz_offset_hours(tz_str: str) -> float:
    """Return UTC offset in hours for a timezone string like 'UTC+8' or 'UTC-5'.
    Returns 0 for 'UTC' or 'local' (server local time is handled separately)."""
    if not tz_str or tz_str in ('local', 'UTC'):
        return 0.0
    m = re.match(r'^UTC([+-])(\d+(?:\.\d+)?)$', tz_str)
    if not m:
        return 0.0
    return float(m.group(1) + m.group(2))

def _now_in_schedule_tz(tz_str: str) -> datetime.datetime:
    """Return current naive datetime adjusted to the configured schedule timezone."""
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    if not tz_str or tz_str == 'local':
        # Fall back to server local time
        return datetime.datetime.now()
    if tz_str == 'UTC':
        return now_utc.replace(tzinfo=None)
    offset = _tz_offset_hours(tz_str)
    return (now_utc + datetime.timedelta(hours=offset)).replace(tzinfo=None)

# State key written to state.json
_STATE_KEY = "report_schedule_states"

# Gap to prevent re-trigger within the same hour window (seconds)
_MIN_RERUN_GAP = 3600

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

    def should_run(self, schedule: dict, now: datetime.datetime) -> bool:
        """Return True if this schedule should execute right now."""
        if not schedule.get("enabled", False):
            return False

        # Check re-run gap using persisted last_run
        states = self._load_states()
        sid = str(schedule.get("id", ""))
        last_run_str = states.get(sid, {}).get("last_run")
        last_run_dt = None
        if last_run_str:
            try:
                last_run_dt = datetime.datetime.fromisoformat(last_run_str)
                # Strip tzinfo if present (legacy UTC-stored timestamps) so
                # subtraction works against the naive schedule-local `now`.
                if last_run_dt.tzinfo is not None:
                    last_run_dt = last_run_dt.replace(tzinfo=None)
                if (now - last_run_dt).total_seconds() < _MIN_RERUN_GAP:
                    return False
            except ValueError:
                pass

        # cron_expr branch: use APScheduler CronTrigger to decide if due
        cron_expr = schedule.get("cron_expr")
        if cron_expr:
            try:
                from apscheduler.triggers.cron import CronTrigger
                trigger = CronTrigger.from_crontab(cron_expr, timezone="UTC")
                # Make now timezone-aware for APScheduler
                now_aware = now.replace(tzinfo=datetime.timezone.utc)
                prev = last_run_dt.replace(tzinfo=datetime.timezone.utc) if last_run_dt else None
                next_fire = trigger.get_next_fire_time(prev, now_aware)
                return next_fire is not None and next_fire <= now_aware
            except Exception:
                logger.warning("Invalid cron_expr for schedule {}", schedule.get("id"))
                return False

        stype = schedule.get("schedule_type", "weekly")
        hour = int(schedule.get("hour", 8))
        minute = int(schedule.get("minute", 0))

        if now.hour != hour or now.minute != minute:
            return False

        if stype == "daily":
            return True
        elif stype == "weekly":
            dow = schedule.get("day_of_week", "monday").lower()
            return now.strftime("%A").lower() == dow
        elif stype == "monthly":
            dom = int(schedule.get("day_of_month", 1))
            return now.day == dom

        return False

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
            api = ApiClient(self.cm)

            result, paths = self._generate_report(
                report_type, api, fmt, output_dir, start_date, end_date, name,
                filters=schedule_filters)

            if result is None:
                return False

            if send_email and paths:
                self._send_report_email(schedule, result, paths, start_date, end_date,
                                        custom_recipients, report_type=report_type)

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
            logger.error(f"[Scheduler] '{name}': failed — {e}", exc_info=True)
            raise

    # ── Report type dispatch ────────────────────────────────────────────────

    def _generate_report(self, report_type, api, fmt, output_dir, start_date, end_date, name, filters=None):
        """Dispatch to the appropriate generator. Returns (result, paths) or (None, [])."""
        if report_type == "traffic":
            from src.report.report_generator import ReportGenerator
            gen = ReportGenerator(self.cm, api_client=api, config_dir=self._config_dir)
            result = gen.generate_from_api(start_date=start_date, end_date=end_date, filters=filters)
            if result.record_count == 0:
                logger.warning(f"[Scheduler] '{name}': no traffic data — skipping export")
                return None, []
            paths = gen.export(result, fmt=fmt, output_dir=output_dir,
                               send_email=False, reporter=None)
            return result, paths

        elif report_type == "audit":
            from src.report.audit_generator import AuditGenerator
            gen = AuditGenerator(self.cm, api_client=api, config_dir=self._config_dir)
            result = gen.generate_from_api(start_date=start_date, end_date=end_date)
            if result.record_count == 0:
                logger.warning(f"[Scheduler] '{name}': no audit data — skipping export")
                return None, []
            paths = gen.export(result, fmt=fmt, output_dir=output_dir)
            return result, paths

        elif report_type == "ven_status":
            from src.report.ven_status_generator import VenStatusGenerator
            gen = VenStatusGenerator(self.cm, api_client=api)
            result = gen.generate()
            if result.record_count == 0:
                logger.warning(f"[Scheduler] '{name}': no VEN data — skipping export")
                return None, []
            paths = gen.export(result, output_dir=output_dir)
            return result, paths

        elif report_type == "policy_usage":
            from src.report.policy_usage_generator import PolicyUsageGenerator
            gen = PolicyUsageGenerator(self.cm, api_client=api, config_dir=self._config_dir)
            result = gen.generate_from_api(start_date=start_date, end_date=end_date)
            if result.record_count == 0:
                logger.warning(f"[Scheduler] '{name}': no active rules found — skipping export")
                return None, []
            paths = gen.export(result, fmt=fmt, output_dir=output_dir)
            return result, paths

        else:
            logger.error(f"[Scheduler] Unknown report_type: {report_type}")
            return None, []

    def _send_report_email(self, schedule: dict, result, paths: list,
                            start_date: str, end_date: str,
                            custom_recipients: list, report_type: str):
        """Build and send the scheduled report email."""
        import html as _html

        name = schedule.get("name", "Report")
        date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        subject = f"[Illumio Monitor] {name} — {date_str}"

        # Build HTML body
        esc = lambda s: _html.escape(str(s), quote=True)
        type_label = {"traffic": t("rpt_email_traffic_subject"), "audit": t("rpt_email_audit_subject"),
                      "ven_status": t("rpt_email_ven_subject"),
                      "policy_usage": t("rpt_email_pu_subject")}.get(report_type, "Report")
        start_disp = start_date[:10] if start_date else "N/A"
        end_disp = end_date[:10] if end_date else "N/A"

        body = "<html><body style='margin:0;padding:0;background:#F7F4EE;font-family:\"Montserrat\",Arial,sans-serif;color:#313638;'>"
        body += "<div style='max-width:860px;margin:0 auto;padding:16px;'>"
        body += "<div style='border:1px solid #325158;border-radius:10px;background:#fff;overflow:hidden;'>"

        # Header
        body += "<div style='padding:18px 20px;background:#1A2C32;color:#fff;border-left:4px solid #FF5500;'>"
        body += f"<div style='font-size:20px;font-weight:700;margin-bottom:4px;'>{esc(type_label)}</div>"
        body += f"<div style='font-size:12px;color:#989A9B;'>{esc(name)} — {t('rpt_email_scheduled_report')}</div>"
        body += "</div>"

        # KPI bar
        body += "<div style='padding:14px 20px;border-bottom:1px solid #E3D8C5;background:#F7F4EE;display:flex;flex-wrap:wrap;gap:8px;'>"
        body += f"<span style='background:#FF5500;color:#fff;padding:4px 10px;border-radius:999px;font-size:12px;font-weight:700;'>{t('rpt_email_records', count=esc(result.record_count))}</span>"
        body += f"<span style='background:#1A2C32;color:#D6D7D7;padding:4px 10px;border-radius:999px;font-size:12px;'>{t('rpt_email_period', start=esc(start_disp), end=esc(end_disp))}</span>"
        body += f"<span style='background:#E3D8C5;color:#313638;padding:4px 10px;border-radius:999px;font-size:12px;'>{t('rpt_email_source_api')}</span>"
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
            body += f"<div style='font-size:14px;font-weight:700;color:#1A2C32;margin-bottom:10px;border-bottom:2px solid #FF5500;padding-bottom:4px;'>{t('rpt_email_kpi_title')}</div>"
            body += "<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;'>"
            for kpi in kpis[:8]:
                label = esc(kpi.get("label", ""))
                value = esc(kpi.get("value", ""))
                color = kpi.get("color", "#313638")
                body += f"<div style='background:#F7F4EE;border:1px solid #E3D8C5;border-radius:8px;padding:10px;text-align:center;'>"
                body += f"<div style='font-size:22px;font-weight:700;color:{esc(color)};'>{value}</div>"
                body += f"<div style='font-size:11px;color:#989A9B;margin-top:4px;'>{label}</div>"
                body += "</div>"
            body += "</div></div>"

        # Findings
        findings = getattr(result, "findings", []) or []
        if findings:
            body += "<div style='margin-bottom:16px;'>"
            body += f"<div style='font-size:14px;font-weight:700;color:#1A2C32;margin-bottom:10px;border-bottom:2px solid #BE122F;padding-bottom:4px;'>{t('rpt_email_security_findings')}</div>"
            body += "<table style='width:100%;border-collapse:collapse;font-size:12px;'>"
            body += "<tr style='background:#24393F;color:#D6D7D7;'>"
            body += "<th style='padding:8px;text-align:left;'>ID</th><th style='padding:8px;text-align:left;'>Finding</th><th style='padding:8px;text-align:left;'>Severity</th>"
            body += "</tr>"
            sev_colors = {"CRITICAL": "#BE122F", "HIGH": "#F97607", "MEDIUM": "#F59E0B", "LOW": "#166644"}
            for i, f in enumerate(findings[:15]):
                row_bg = "#fff" if i % 2 == 0 else "#F7F4EE"
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
                body += f"<td style='padding:8px;border-bottom:1px solid #E3D8C5;font-weight:700;color:#FF5500;'>{esc(fid)}</td>"
                body += f"<td style='padding:8px;border-bottom:1px solid #E3D8C5;'><strong>{esc(fname)}</strong><br><small style='color:#989A9B;'>{esc(fdesc)}</small></td>"
                body += f"<td style='padding:8px;border-bottom:1px solid #E3D8C5;font-weight:700;color:{sev_color};'>{esc(sev)}</td>"
                body += "</tr>"
            body += "</table></div>"

        attack_summary = extract_attack_summary(getattr(result, "module_results", {}) or {}, top_n=3)
        section_labels = {
            "boundary_breaches": t("rpt_email_boundary_breaches"),
            "suspicious_pivot_behavior": t("rpt_email_suspicious_pivot_behavior"),
            "blast_radius": t("rpt_email_blast_radius"),
            "blind_spots": t("rpt_email_blind_spots"),
            "action_matrix": t("rpt_email_action_matrix"),
        }
        has_attack = any(attack_summary.get(k) for k in section_labels.keys())
        if has_attack:
            body += "<div style='margin-bottom:16px;'>"
            body += f"<div style='font-size:14px;font-weight:700;color:#1A2C32;margin-bottom:10px;border-bottom:2px solid #FF5500;padding-bottom:4px;'>{t('rpt_email_attack_summary')}</div>"
            body += "<table style='width:100%;border-collapse:collapse;font-size:12px;'>"
            body += "<tr style='background:#24393F;color:#D6D7D7;'>"
            body += f"<th style='padding:8px;text-align:left;'>Section</th><th style='padding:8px;text-align:left;'>{t('rpt_email_finding')}</th><th style='padding:8px;text-align:left;'>{t('rpt_email_action')}</th>"
            body += "</tr>"
            _zh = get_language() == "zh_TW"
            row_index = 0
            for key, label in section_labels.items():
                for item in (attack_summary.get(key) or [])[:2]:
                    row_bg = "#fff" if row_index % 2 == 0 else "#F7F4EE"
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
                    body += f"<td style='padding:8px;border-bottom:1px solid #E3D8C5;font-weight:700;color:#1A2C32;'>{esc(label)}</td>"
                    body += f"<td style='padding:8px;border-bottom:1px solid #E3D8C5;'>{finding_html}</td>"
                    body += f"<td style='padding:8px;border-bottom:1px solid #E3D8C5;'>{action_html}</td>"
                    body += "</tr>"
                    row_index += 1
            body += "</table></div>"

        # Attachments note
        if paths:
            body += "<div style='background:#F7F4EE;border:1px solid #E3D8C5;border-radius:8px;padding:12px;margin-bottom:16px;'>"
            body += f"<div style='font-size:13px;font-weight:700;color:#1A2C32;margin-bottom:6px;'>{t('rpt_email_attached_files')}</div>"
            for p in paths:
                body += f"<div style='font-size:12px;color:#313638;padding:2px 0;'>📎 {esc(os.path.basename(p))}</div>"
            body += "</div>"

        body += "</div></div></div></body></html>"

        self.reporter.send_scheduled_report_email(
            subject=subject,
            html_body=body,
            attachment_paths=paths,
            custom_recipients=custom_recipients,
        )

    # ─── Report retention ────────────────────────────────────────────────────

    # File prefix patterns for each report type (matches both .html and .zip)
    _REPORT_PREFIXES = {
        "traffic":      "Illumio_Traffic_Report_",
        "audit":        "illumio_audit_report_",
        "ven_status":   "illumio_ven_status_",
        "policy_usage": "illumio_policy_usage_report_",
    }

    def _prune_by_count(self, output_dir: str, report_type: str, max_reports: int):
        """Keep only the newest max_reports files for the given report type.

        Files are identified by their name prefix, sorted by mtime descending.
        Set max_reports to 0 to disable.
        """
        if max_reports <= 0 or not os.path.isdir(output_dir):
            return
        prefix = self._REPORT_PREFIXES.get(report_type)
        if not prefix:
            return

        candidates = []
        for fname in os.listdir(output_dir):
            if fname.startswith(prefix) and (fname.endswith(".html") or fname.endswith(".zip")):
                fpath = os.path.join(output_dir, fname)
                try:
                    candidates.append((os.path.getmtime(fpath), fpath))
                except OSError:
                    pass

        # Sort newest-first, delete everything beyond max_reports
        candidates.sort(reverse=True)
        to_delete = candidates[max_reports:]
        for _, fpath in to_delete:
            try:
                os.remove(fpath)
                logger.info(f"[Scheduler] Count-pruned: {os.path.basename(fpath)} (limit={max_reports})")
            except Exception as e:
                logger.warning(f"[Scheduler] Could not prune {fpath}: {e}")

    def _prune_old_reports(self, output_dir: str):
        """Delete report files older than retention_days (default 30).

        Covers .html and .zip files produced by the report engine.
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
            if not (fname.endswith(".html") or fname.endswith(".zip")):
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
            sched_tz = sched.get('timezone', global_tz)
            now = _now_in_schedule_tz(sched_tz)
            if not self.should_run(sched, now):
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
