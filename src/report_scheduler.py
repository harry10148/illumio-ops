"""
src/report_scheduler.py
Report Schedule Engine — evaluates and runs report schedules at each daemon tick.

Usage (called from daemon loop every 60 seconds):
    scheduler = ReportScheduler(config_manager, reporter)
    scheduler.tick()
"""

import datetime
import json
import logging
import os

logger = logging.getLogger(__name__)

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
        if not os.path.exists(self._state_file):
            return {}
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get(_STATE_KEY, {})
        except Exception:
            return {}

    def _save_state(self, schedule_id: int, last_run: str, status: str, error: str = ""):
        """Persist schedule execution result into state.json."""
        try:
            os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
            data = {}
            if os.path.exists(self._state_file):
                with open(self._state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            states = data.setdefault(_STATE_KEY, {})
            states[str(schedule_id)] = {
                "last_run": last_run,
                "status": status,
                "error": error,
            }
            tmp = self._state_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            os.replace(tmp, self._state_file)
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
        if last_run_str:
            try:
                last_run = datetime.datetime.fromisoformat(last_run_str)
                if (now - last_run).total_seconds() < _MIN_RERUN_GAP:
                    return False
            except ValueError:
                pass

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
        name = schedule.get("name", "Unnamed")
        report_type = schedule.get("report_type", "traffic")
        lookback_days = int(schedule.get("lookback_days", 7))
        fmt_list = schedule.get("format", ["excel"])
        fmt = fmt_list[0] if isinstance(fmt_list, list) and fmt_list else "excel"
        if len(fmt_list) > 1:
            fmt = "all"
        send_email = schedule.get("email_report", False)
        custom_recipients = schedule.get("email_recipients", [])

        output_dir = schedule.get("output_dir") or self.cm.config.get("report", {}).get("output_dir", "reports")
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(self._root_dir, output_dir)
        os.makedirs(output_dir, exist_ok=True)

        now_utc = datetime.datetime.utcnow()
        end_date = now_utc.strftime("%Y-%m-%dT23:59:59Z")
        start_date = (now_utc - datetime.timedelta(days=lookback_days)).strftime("%Y-%m-%dT00:00:00Z")

        logger.info(f"[Scheduler] Running schedule '{name}' ({report_type}), range={start_date}→{end_date}")

        try:
            from src.api_client import ApiClient
            api = ApiClient(self.cm)

            paths = []

            if report_type == "traffic":
                from src.report.report_generator import ReportGenerator
                gen = ReportGenerator(self.cm, api_client=api, config_dir=self._config_dir)
                result = gen.generate_from_api(start_date=start_date, end_date=end_date)
                if result.record_count == 0:
                    logger.warning(f"[Scheduler] '{name}': no traffic data — skipping export")
                    return False
                paths = gen.export(result, fmt=fmt, output_dir=output_dir,
                                   send_email=False, reporter=None)
                if send_email and paths:
                    self._send_report_email(schedule, result, paths, start_date, end_date,
                                            custom_recipients, report_type="traffic")

            elif report_type == "audit":
                from src.report.audit_generator import AuditGenerator
                gen = AuditGenerator(self.cm, api_client=api, config_dir=self._config_dir)
                result = gen.generate_from_api(start_date=start_date, end_date=end_date)
                if result.record_count == 0:
                    logger.warning(f"[Scheduler] '{name}': no audit data — skipping export")
                    return False
                paths = gen.export(result, fmt=fmt, output_dir=output_dir)
                if send_email and paths:
                    self._send_report_email(schedule, result, paths, start_date, end_date,
                                            custom_recipients, report_type="audit")

            elif report_type == "ven_status":
                from src.report.ven_status_generator import VenStatusGenerator
                gen = VenStatusGenerator(self.cm, api_client=api)
                result = gen.generate()
                if result.record_count == 0:
                    logger.warning(f"[Scheduler] '{name}': no VEN data — skipping export")
                    return False
                paths = gen.export(result, output_dir=output_dir)
                if send_email and paths:
                    self._send_report_email(schedule, result, paths, start_date, end_date,
                                            custom_recipients, report_type="ven_status")

            logger.info(f"[Scheduler] '{name}': completed, files={[os.path.basename(p) for p in paths]}")
            return True

        except Exception as e:
            logger.error(f"[Scheduler] '{name}': failed — {e}", exc_info=True)
            raise

    def _send_report_email(self, schedule: dict, result, paths: list,
                            start_date: str, end_date: str,
                            custom_recipients: list, report_type: str):
        """Build and send the scheduled report email."""
        import html as _html

        name = schedule.get("name", "Report")
        date_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        subject = f"[Illumio Monitor] {name} — {date_str}"

        # Build HTML body
        esc = lambda s: _html.escape(str(s), quote=True)
        type_label = {"traffic": "Traffic Flow Report", "audit": "Audit Report",
                      "ven_status": "VEN Status Report"}.get(report_type, "Report")
        start_disp = start_date[:10] if start_date else "N/A"
        end_disp = end_date[:10] if end_date else "N/A"

        body = "<html><body style='margin:0;padding:0;background:#F7F4EE;font-family:\"Montserrat\",Arial,sans-serif;color:#313638;'>"
        body += "<div style='max-width:860px;margin:0 auto;padding:16px;'>"
        body += "<div style='border:1px solid #325158;border-radius:10px;background:#fff;overflow:hidden;'>"

        # Header
        body += "<div style='padding:18px 20px;background:#1A2C32;color:#fff;border-left:4px solid #FF5500;'>"
        body += f"<div style='font-size:20px;font-weight:700;margin-bottom:4px;'>{esc(type_label)}</div>"
        body += f"<div style='font-size:12px;color:#989A9B;'>{esc(name)} — Scheduled Report</div>"
        body += "</div>"

        # KPI bar
        body += "<div style='padding:14px 20px;border-bottom:1px solid #E3D8C5;background:#F7F4EE;display:flex;flex-wrap:wrap;gap:8px;'>"
        body += f"<span style='background:#FF5500;color:#fff;padding:4px 10px;border-radius:999px;font-size:12px;font-weight:700;'>Records: {esc(result.record_count)}</span>"
        body += f"<span style='background:#1A2C32;color:#D6D7D7;padding:4px 10px;border-radius:999px;font-size:12px;'>Period: {esc(start_disp)} → {esc(end_disp)}</span>"
        body += f"<span style='background:#E3D8C5;color:#313638;padding:4px 10px;border-radius:999px;font-size:12px;'>Source: API</span>"
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
            body += "<div style='font-size:14px;font-weight:700;color:#1A2C32;margin-bottom:10px;border-bottom:2px solid #FF5500;padding-bottom:4px;'>Key Performance Indicators</div>"
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
            body += "<div style='font-size:14px;font-weight:700;color:#1A2C32;margin-bottom:10px;border-bottom:2px solid #BE122F;padding-bottom:4px;'>Security Findings</div>"
            body += "<table style='width:100%;border-collapse:collapse;font-size:12px;'>"
            body += "<tr style='background:#24393F;color:#D6D7D7;'>"
            body += "<th style='padding:8px;text-align:left;'>ID</th><th style='padding:8px;text-align:left;'>Finding</th><th style='padding:8px;text-align:left;'>Severity</th>"
            body += "</tr>"
            sev_colors = {"CRITICAL": "#BE122F", "HIGH": "#F97607", "MEDIUM": "#F59E0B", "LOW": "#166644"}
            for i, f in enumerate(findings[:15]):
                row_bg = "#fff" if i % 2 == 0 else "#F7F4EE"
                sev = str(f.get("severity", "INFO")).upper()
                sev_color = sev_colors.get(sev, "#313638")
                body += f"<tr style='background:{row_bg};'>"
                body += f"<td style='padding:8px;border-bottom:1px solid #E3D8C5;font-weight:700;color:#FF5500;'>{esc(f.get('id',''))}</td>"
                body += f"<td style='padding:8px;border-bottom:1px solid #E3D8C5;'><strong>{esc(f.get('name',''))}</strong><br><small style='color:#989A9B;'>{esc(f.get('description',''))}</small></td>"
                body += f"<td style='padding:8px;border-bottom:1px solid #E3D8C5;font-weight:700;color:{sev_color};'>{esc(sev)}</td>"
                body += "</tr>"
            body += "</table></div>"

        # Attachments note
        if paths:
            body += "<div style='background:#F7F4EE;border:1px solid #E3D8C5;border-radius:8px;padding:12px;margin-bottom:16px;'>"
            body += "<div style='font-size:13px;font-weight:700;color:#1A2C32;margin-bottom:6px;'>Attached Files</div>"
            for p in paths:
                body += f"<div style='font-size:12px;color:#313638;padding:2px 0;'>📎 {esc(os.path.basename(p))}</div>"
            body += "</div>"

        body += "</div></div></div></body></html>"

        # Send with attachments
        excel_path = next((p for p in paths if p.endswith(".xlsx")), None)
        self.reporter.send_scheduled_report_email(
            subject=subject,
            html_body=body,
            attachment_paths=paths,
            custom_recipients=custom_recipients,
        )

    # ─── Tick (called every minute from daemon loop) ──────────────────────────

    def tick(self):
        """Check all enabled schedules and run any that are due."""
        self.cm.load()
        schedules = self.cm.config.get("report_schedules", [])
        if not schedules:
            return

        now = datetime.datetime.utcnow()

        for sched in schedules:
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
