import datetime
import json
import html
import smtplib
import urllib.request
import urllib.parse
import urllib.error
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from src.utils import Colors
from src.i18n import t


class Reporter:
    def __init__(self, config_manager):
        self.cm = config_manager
        self.health_alerts = []
        self.event_alerts = []
        self.traffic_alerts = []
        self.metric_alerts = []

    def add_health_alert(self, alert):
        self.health_alerts.append(alert)

    def add_event_alert(self, alert):
        self.event_alerts.append(alert)

    def add_traffic_alert(self, alert):
        self.traffic_alerts.append(alert)

    def add_metric_alert(self, alert):
        self.metric_alerts.append(alert)

    def generate_pretty_snapshot_html(self, data_list):
        import re

        def clean_ansi(text):
            return re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", str(text))

        def esc(text):
            return html.escape(clean_ansi(text), quote=True)

        if not data_list:
            return "<div style='padding:10px 12px; color:#6b7280; font-size:12px;'>No data</div>"

        def actor_view(item, is_source=True):
            actor = item.get("source" if is_source else "destination", {})
            raw = item.get("src" if is_source else "dst", {})
            svc = item.get("service", {})

            ip = actor.get("ip") or raw.get("ip") or "-"
            wl = raw.get("workload", {})
            name = actor.get("name") or wl.get("name") or wl.get("hostname") or ip
            labels = actor.get("labels") or wl.get("labels", [])

            if is_source:
                proc = actor.get("process") or raw.get("process_name") or ""
                user = actor.get("user") or raw.get("user_name") or ""
            else:
                proc = (
                    actor.get("process")
                    or raw.get("process_name")
                    or svc.get("process_name")
                    or ""
                )
                user = (
                    actor.get("user")
                    or raw.get("user_name")
                    or svc.get("user_name")
                    or ""
                )

            badges = "".join(
                [
                    f"<span style='display:inline-block; background:#e1ecf4; color:#2c5e77; padding:2px 5px; border-radius:4px; font-size:10px; margin:2px 3px 0 0;'>{esc(l.get('key'))}:{esc(l.get('value'))}</span>"
                    for l in labels
                ]
            )
            proc_line = (
                f"<div style='font-size:10px; color:#334155; margin-top:4px;'>Proc: {esc(proc)}</div>"
                if proc
                else ""
            )
            user_line = (
                f"<div style='font-size:10px; color:#475569;'>User: {esc(user)}</div>"
                if user
                else ""
            )
            return (
                f"<strong>{esc(name)}</strong><br><small>{esc(ip)}</small>"
                f"{proc_line}{user_line}<div style='margin-top:2px;'>{badges}</div>"
            )

        table_html = "<table style='width:100%; border-collapse:collapse; table-layout:fixed; font-family:Arial,sans-serif; font-size:12px; border:1px solid #e5e7eb;'>"
        table_html += "<tr style='background-color:#f8fafc; text-align:left;'>"
        table_html += f"<th style='padding:8px; border:1px solid #e5e7eb; width:96px;'>{esc(t('table_value'))}</th>"
        table_html += f"<th style='padding:8px; border:1px solid #e5e7eb; width:132px;'>{esc(t('table_first_seen'))} /<br>{esc(t('table_last_seen'))}</th>"
        table_html += f"<th style='padding:8px; border:1px solid #e5e7eb; width:44px; text-align:center;'>{esc(t('table_dir'))}</th>"
        table_html += f"<th style='padding:8px; border:1px solid #e5e7eb;'>{esc(t('table_source'))}</th>"
        table_html += f"<th style='padding:8px; border:1px solid #e5e7eb;'>{esc(t('table_destination'))}</th>"
        table_html += f"<th style='padding:8px; border:1px solid #e5e7eb; width:88px;'>{esc(t('table_service'))}</th>"
        table_html += f"<th style='padding:8px; border:1px solid #e5e7eb; width:74px; text-align:center;'>{esc(t('table_num_conns'))}</th>"
        table_html += f"<th style='padding:8px; border:1px solid #e5e7eb; width:88px;'>{esc(t('table_decision'))}</th>"
        table_html += "</tr>"

        for i, d in enumerate(data_list):
            row_bg = "#ffffff" if i % 2 == 0 else "#fbfdff"
            val_str = esc(d.get("_metric_fmt", "-"))
            ts_r = d.get("timestamp_range", {})
            t_first = esc(
                ts_r.get("first_detected", d.get("timestamp", "-"))
                .replace("T", " ")
                .split(".")[0]
            )
            t_last = esc(ts_r.get("last_detected", "-").replace("T", " ").split(".")[0])

            direction = (
                "IN"
                if d.get("flow_direction") == "inbound"
                else "OUT"
                if d.get("flow_direction") == "outbound"
                else d.get("flow_direction", "-")
            )
            svc = d.get("service", {})
            port = d.get("dst_port") or svc.get("port") or "-"
            proto = d.get("proto") or svc.get("proto") or "-"
            proto_str = "TCP" if proto == 6 else "UDP" if proto == 17 else str(proto)
            count = d.get("num_connections") or d.get("count") or 1
            pd_map = {
                "blocked": f"<span style='display:inline-block; color:white; background:#dc3545; padding:2px 6px; border-radius:12px; font-weight:700;'>{esc(t('decision_blocked'))}</span>",
                "potentially_blocked": f"<span style='display:inline-block; color:#4a3500; background:#ffc107; padding:2px 6px; border-radius:12px; font-weight:700;'>{esc(t('decision_potential'))}</span>",
                "allowed": f"<span style='display:inline-block; color:white; background:#16a34a; padding:2px 6px; border-radius:12px; font-weight:700;'>{esc(t('decision_allowed'))}</span>",
            }
            decision = str(d.get("policy_decision")).lower()
            decision_html = pd_map.get(decision, esc(decision))
            table_html += f"<tr style='background:{row_bg};'>"
            table_html += f"<td style='padding:8px; border:1px solid #e5e7eb; font-weight:700; color:#6f42c1;'>{val_str}</td>"
            table_html += f"<td style='padding:8px; border:1px solid #e5e7eb; white-space:nowrap; font-size:10px;'>{t_first}<br>{t_last}</td>"
            table_html += f"<td style='padding:8px 6px; border:1px solid #e5e7eb; text-align:center; font-weight:700;'>{esc(direction)}</td>"
            table_html += f"<td style='padding:8px 10px; border:1px solid #e5e7eb; word-break:break-word;'>{actor_view(d, True)}</td>"
            table_html += f"<td style='padding:8px 10px; border:1px solid #e5e7eb; word-break:break-word;'>{actor_view(d, False)}</td>"
            table_html += f"<td style='padding:8px 6px; border:1px solid #e5e7eb; text-align:center;'>{esc(port)} / {esc(proto_str)}</td>"
            table_html += f"<td style='padding:8px; border:1px solid #e5e7eb; text-align:center;'><strong>{esc(count)}</strong></td>"
            table_html += f"<td style='padding:8px; border:1px solid #e5e7eb;'>{decision_html}</td>"
            table_html += "</tr>"

        table_html += "</table>"
        return table_html

    def _build_plain_text_report(self):
        import re

        def clean_ansi(text):
            return re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", str(text))

        body = f"{t('report_header')}\n"
        body += f"{t('generated_at', time=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))}\n"
        body += "-" * 20 + "\n\n"

        if self.health_alerts:
            body += f"{t('health_alerts_header')}\n"
            for a in self.health_alerts:
                body += clean_ansi(f"[{a['time']}] {a['status']} - {a['details']}\n")
            body += "\n"

        if self.event_alerts:
            body += f"{t('security_events_header')}\n"
            for a in self.event_alerts:
                body += clean_ansi(
                    f"[{a['time']}] {a['rule']} ({a.get('severity', '').upper()} x{a['count']})\n"
                )
                body += clean_ansi(f"Desc: {a['desc']}\n")
            body += "\n"

        if self.traffic_alerts:
            body += f"{t('traffic_alerts_header')}\n"
            for a in self.traffic_alerts:
                body += clean_ansi(
                    f"- {a['rule']} : {a['count']} ({a.get('criteria', '')})\n"
                )
                body += clean_ansi(
                    f"  {t('traffic_toptalkers')}: {a['details'].replace('<br>', ', ')}\n"
                )
            body += "\n"

        if self.metric_alerts:
            body += f"{t('metric_alerts_header')}\n"
            for a in self.metric_alerts:
                body += clean_ansi(
                    f"- {a['rule']} : {a['count']} ({a.get('criteria', '')})\n"
                )
                body += clean_ansi(
                    f"  {t('traffic_toptalkers')}: {a['details'].replace('<br>', ', ')}\n"
                )
            body += "\n"
        return body

    def send_alerts(self, force_test=False):
        if (
            not any(
                [
                    self.health_alerts,
                    self.event_alerts,
                    self.traffic_alerts,
                    self.metric_alerts,
                ]
            )
            and not force_test
        ):
            return

        alerts_config = self.cm.config.get("alerts", {})
        active_channels = alerts_config.get("active", ["mail"])

        total_issues = (
            len(self.health_alerts)
            + len(self.event_alerts)
            + len(self.traffic_alerts)
            + len(self.metric_alerts)
        )
        subj = (
            t("mail_subject_test")
            if force_test
            else t("mail_subject", count=total_issues)
        )

        if "mail" in active_channels:
            self._send_mail(subj)

        if "line" in active_channels:
            self._send_line(subj)

        if "webhook" in active_channels:
            self._send_webhook(subj)

    def _send_line(self, subj):
        token = self.cm.config.get("alerts", {}).get("line_channel_access_token", "")
        target_id = self.cm.config.get("alerts", {}).get("line_target_id", "")
        if not token or not target_id:
            print(f"{Colors.WARNING}{t('line_config_missing')}{Colors.ENDC}")
            return

        message_text = f"{subj}\n\n{self._build_plain_text_report()}"
        url = "https://api.line.me/v2/bot/message/push"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            "to": target_id,
            "messages": [{"type": "text", "text": message_text}],
        }
        data = json.dumps(payload).encode("utf-8")

        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    print(f"{Colors.GREEN}{t('line_alert_sent')}{Colors.ENDC}")
                else:
                    print(
                        f"{Colors.FAIL}{t('line_alert_failed', error='', status=response.status)}{Colors.ENDC}"
                    )
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            print(
                f"{Colors.FAIL}{t('line_alert_failed', error=f'{e} - {error_body}', status=e.code)}{Colors.ENDC}"
            )
        except Exception as e:
            print(
                f"{Colors.FAIL}{t('line_alert_failed', error=e, status='')}{Colors.ENDC}"
            )

    def _send_webhook(self, subj):
        webhook_url = self.cm.config.get("alerts", {}).get("webhook_url", "")
        if not webhook_url:
            print(f"{Colors.WARNING}{t('webhook_url_missing')}{Colors.ENDC}")
            return

        payload = {
            "subject": subj,
            "health_alerts": self.health_alerts,
            "event_alerts": self.event_alerts,
            "traffic_alerts": self.traffic_alerts,
            "metric_alerts": self.metric_alerts,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        headers = {"Content-Type": "application/json"}
        data = json.dumps(payload).encode("utf-8")

        try:
            req = urllib.request.Request(
                webhook_url, data=data, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status in [200, 201, 202, 204]:
                    print(f"{Colors.GREEN}{t('webhook_alert_sent')}{Colors.ENDC}")
                else:
                    print(
                        f"{Colors.FAIL}{t('webhook_alert_failed', error='', status=response.status)}{Colors.ENDC}"
                    )
        except urllib.error.HTTPError as e:
            try:
                error_body = e.read().decode("utf-8")
            except Exception:
                error_body = "Could not read error body"
            print(
                f"{Colors.FAIL}{t('webhook_alert_failed', error=f'{e} - {error_body}', status=e.code)}{Colors.ENDC}"
            )
        except (urllib.error.URLError, TimeoutError) as e:
            print(
                f"{Colors.FAIL}{t('webhook_alert_failed', error=f'Connection Error/Timeout: {e}', status='')}{Colors.ENDC}"
            )
        except Exception as e:
            print(
                f"{Colors.FAIL}{t('webhook_alert_failed', error=e, status='')}{Colors.ENDC}"
            )

    def _send_mail(self, subj):
        cfg = self.cm.config["email"]
        if not cfg["recipients"]:
            print(f"{Colors.WARNING}{t('no_recipients')}{Colors.ENDC}")
            return

        def esc(text):
            return html.escape(str(text), quote=True)

        def fmt_multiline(text):
            normalized = str(text).replace("<br>", "\n")
            return esc(normalized).replace("\n", "<br>")

        generated_at = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
        total_items = (
            len(self.health_alerts)
            + len(self.event_alerts)
            + len(self.traffic_alerts)
            + len(self.metric_alerts)
        )
        section_style = "margin-top:18px; border:1px solid #e5e7eb; border-radius:8px; overflow:hidden;"
        header_style = "padding:10px 14px; font-size:14px; font-weight:700;"
        table_style = "width:100%; border-collapse:collapse; table-layout:fixed;"
        th_style = "text-align:left; padding:10px; background:#f8fafc; border-bottom:1px solid #e5e7eb; font-size:12px; color:#475569;"
        td_style = "padding:10px; border-bottom:1px solid #edf2f7; font-size:12px; color:#1f2937; vertical-align:top; word-break:break-word;"

        body = "<html><body style='margin:0; padding:0; background:#f3f6fb; font-family:Arial,sans-serif; line-height:1.5; color:#1f2937;'>"
        body += "<div style='max-width:980px; margin:0 auto; padding:16px;'>"
        body += "<div style='border:1px solid #dbe4f0; border-radius:10px; background:#ffffff; overflow:hidden;'>"
        body += "<div style='padding:18px 20px; background:#0f172a; color:#ffffff;'>"
        body += f"<div style='font-size:20px; font-weight:700; margin-bottom:4px;'>{esc(t('report_header'))}</div>"
        body += f"<div style='font-size:12px; color:#cbd5e1;'>{esc(t('generated_at', time=generated_at))}</div>"
        body += "</div>"
        body += "<div style='padding:14px 20px; border-bottom:1px solid #eef2f7; background:#fbfdff;'>"
        body += f"<span style='display:inline-block; margin-right:8px; background:#ffedd5; color:#9a3412; padding:4px 8px; border-radius:999px; font-size:12px; font-weight:700;'>Total {esc(total_items)}</span>"
        body += f"<span style='display:inline-block; margin-right:8px; background:#fee2e2; color:#991b1b; padding:4px 8px; border-radius:999px; font-size:12px; font-weight:700;'>Health {esc(len(self.health_alerts))}</span>"
        body += f"<span style='display:inline-block; margin-right:8px; background:#fef3c7; color:#92400e; padding:4px 8px; border-radius:999px; font-size:12px; font-weight:700;'>Event {esc(len(self.event_alerts))}</span>"
        body += f"<span style='display:inline-block; margin-right:8px; background:#e0f2fe; color:#0c4a6e; padding:4px 8px; border-radius:999px; font-size:12px; font-weight:700;'>Traffic {esc(len(self.traffic_alerts))}</span>"
        body += f"<span style='display:inline-block; background:#ede9fe; color:#4c1d95; padding:4px 8px; border-radius:999px; font-size:12px; font-weight:700;'>Metric {esc(len(self.metric_alerts))}</span>"
        body += "</div><div style='padding:0 20px 20px 20px;'>"

        if self.health_alerts:
            body += f"<div style='{section_style}'>"
            body += f"<div style='{header_style} background:#fff1f2; color:#be123c;'>{esc(t('health_alerts_header'))}</div>"
            body += f"<table style='{table_style}'><thead><tr><th style='{th_style}'>{esc(t('health_time'))}</th><th style='{th_style}'>{esc(t('health_status'))}</th><th style='{th_style}'>{esc(t('health_details'))}</th></tr></thead><tbody>"
            for a in self.health_alerts:
                body += f"<tr><td style='{td_style}'>{esc(a.get('time', ''))}</td><td style='{td_style} color:#dc2626; font-weight:700;'>{esc(a.get('status', ''))}</td><td style='{td_style}'>{fmt_multiline(a.get('details', ''))}</td></tr>"
            body += "</tbody></table></div>"

        if self.event_alerts:
            body += f"<div style='{section_style}'>"
            body += f"<div style='{header_style} background:#fffbeb; color:#a16207;'>{esc(t('security_events_header'))}</div>"
            body += f"<table style='{table_style}'><thead><tr><th style='{th_style}'>{esc(t('event_time'))}</th><th style='{th_style}'>{esc(t('event_name'))}</th><th style='{th_style}'>{esc(t('event_severity'))}</th><th style='{th_style}'>{esc(t('event_source'))}</th></tr></thead><tbody>"
            for a in self.event_alerts:
                sev_color = "#dc2626" if a.get("severity") == "error" else "#d97706"
                body += f"<tr><td style='{td_style}'>{esc(a.get('time', ''))}</td><td style='{td_style}'><strong>{esc(a.get('rule', ''))}</strong><br><small style='color:#64748b;'>{esc(a.get('desc', ''))}</small></td><td style='{td_style} color:{sev_color}; font-weight:700;'>{esc(str(a.get('severity', '')).upper())} ({esc(a.get('count', 0))})</td><td style='{td_style}'>{esc(a.get('source', ''))}</td></tr>"
                if a.get("raw_data"):
                    raw_json = esc(json.dumps(a.get("raw_data", {}), indent=2))
                    body += f"<tr><td colspan='4' style='padding:10px; background:#f8fafc; border-bottom:1px solid #edf2f7;'><div style='font-size:11px; color:#64748b; margin-bottom:5px;'>{esc(t('raw_snapshot'))}</div><pre style='margin:0; background:#eef2f7; padding:8px; border-radius:4px; font-size:10px; white-space:pre-wrap; word-break:break-word;'>{raw_json}</pre></td></tr>"
            body += "</tbody></table></div>"

        if self.traffic_alerts:
            body += f"<div style='{section_style}'>"
            body += f"<div style='{header_style} background:#eff6ff; color:#1d4ed8;'>{esc(t('traffic_alerts_header'))}</div>"
            body += f"<table style='{table_style}'><thead><tr><th style='{th_style}'>{esc(t('traffic_rule'))}</th><th style='{th_style}'>{esc(t('traffic_count'))}</th><th style='{th_style}'>{esc(t('traffic_criteria'))}</th><th style='{th_style}'>{esc(t('traffic_toptalkers'))}</th></tr></thead><tbody>"
            for a in self.traffic_alerts:
                body += f"<tr><td style='{td_style}'><strong>{esc(a.get('rule', ''))}</strong></td><td style='{td_style} font-size:16px; font-weight:700; color:#dc2626;'>{esc(a.get('count', 0))}</td><td style='{td_style} color:#475569; font-size:11px;'>{fmt_multiline(a.get('criteria', ''))}</td><td style='{td_style}'>{fmt_multiline(a.get('details', ''))}</td></tr>"
                body += f"<tr><td colspan='4' style='padding:10px; background:#ffffff; border-bottom:1px solid #edf2f7;'>{self.generate_pretty_snapshot_html(a.get('raw_data', []))}</td></tr>"
            body += "</tbody></table></div>"

        if self.metric_alerts:
            body += f"<div style='{section_style}'>"
            body += f"<div style='{header_style} background:#f5f3ff; color:#5b21b6;'>{esc(t('metric_alerts_header'))}</div>"
            body += f"<table style='{table_style}'><thead><tr><th style='{th_style}'>{esc(t('traffic_rule'))}</th><th style='{th_style}'>{esc(t('table_value'))}</th><th style='{th_style}'>{esc(t('traffic_criteria'))}</th><th style='{th_style}'>{esc(t('traffic_toptalkers'))}</th></tr></thead><tbody>"
            for a in self.metric_alerts:
                body += f"<tr><td style='{td_style}'><strong>{esc(a.get('rule', ''))}</strong></td><td style='{td_style} font-size:16px; font-weight:700; color:#6f42c1;'>{esc(a.get('count', 0))}</td><td style='{td_style} color:#475569; font-size:11px;'>{fmt_multiline(a.get('criteria', ''))}</td><td style='{td_style}'>{fmt_multiline(a.get('details', ''))}</td></tr>"
                body += f"<tr><td colspan='4' style='padding:10px; background:#ffffff; border-bottom:1px solid #edf2f7;'>{self.generate_pretty_snapshot_html(a.get('raw_data', []))}</td></tr>"
            body += "</tbody></table></div>"

        body += "</div></div></div></body></html>"

        msg = MIMEMultipart()
        msg["Subject"] = subj
        msg["From"] = cfg["sender"]
        msg["To"] = ",".join(cfg["recipients"])
        msg.attach(MIMEText(body, "html"))
        try:
            smtp_conf = self.cm.config.get("smtp", {})
            host = smtp_conf.get("host", "localhost")
            port = int(smtp_conf.get("port", 25))

            s = smtplib.SMTP(host, port)
            s.ehlo()
            if smtp_conf.get("enable_tls"):
                s.starttls()
                s.ehlo()

            if smtp_conf.get("enable_auth"):
                s.login(smtp_conf.get("user"), smtp_conf.get("password"))

            s.sendmail(cfg["sender"], cfg["recipients"], msg.as_string())
            s.quit()
            print(f"{Colors.GREEN}{t('mail_sent', host=host, port=port)}{Colors.ENDC}")
        except Exception as e:
            print(f"{Colors.FAIL}{t('mail_failed', error=e)}{Colors.ENDC}")
