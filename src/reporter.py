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

    def _now_str(self) -> str:
        """Return current time formatted in the configured timezone."""
        tz_str = self.cm.config.get('settings', {}).get('timezone', 'local')
        try:
            if not tz_str or tz_str == 'local':
                offset = datetime.datetime.now(datetime.timezone.utc).astimezone().utcoffset()
                tz = datetime.timezone(offset)
            elif tz_str == 'UTC':
                tz = datetime.timezone.utc
            elif tz_str.startswith('UTC+') or tz_str.startswith('UTC-'):
                sign = 1 if tz_str[3] == '+' else -1
                total_minutes = int(sign * float(tz_str[4:]) * 60)
                tz = datetime.timezone(datetime.timedelta(minutes=total_minutes))
            else:
                tz = datetime.timezone.utc
            now = datetime.datetime.now(tz)
            offset_s = now.strftime('%z')
            sign = offset_s[0]; hh = offset_s[1:3]; mm = offset_s[3:5]
            tz_label = f"UTC{sign}{hh}:{mm}" if mm != '00' else f"UTC{sign}{hh}"
            return now.strftime('%Y-%m-%d %H:%M') + f' ({tz_label})'
        except Exception:
            return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

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
                    f"<span style='display:inline-block; background:#D1FAE5; color:#166644; padding:2px 5px; border-radius:4px; font-size:10px; margin:2px 3px 0 0;'>{esc(l.get('key'))}:{esc(l.get('value'))}</span>"
                    for l in labels
                ]
            )
            proc_line = (
                f"<div style='font-size:10px; color:#2D454C; margin-top:4px;'>Proc: {esc(proc)}</div>"
                if proc
                else ""
            )
            user_line = (
                f"<div style='font-size:10px; color:#989A9B;'>User: {esc(user)}</div>"
                if user
                else ""
            )
            return (
                f"<strong>{esc(name)}</strong><br><small>{esc(ip)}</small>"
                f"{proc_line}{user_line}<div style='margin-top:2px;'>{badges}</div>"
            )

        table_html = "<table style='width:100%; border-collapse:collapse; font-family:\"Montserrat\",Arial,sans-serif; font-size:12px; border:1px solid #325158;'>"
        table_html += "<tr style='background-color:#24393F; color:#D6D7D7; text-align:left;'>"
        table_html += f"<th style='padding:8px; border:1px solid #325158; width:96px;'>{esc(t('table_value'))}</th>"
        table_html += f"<th style='padding:8px; border:1px solid #325158; width:132px;'>{esc(t('table_first_seen'))} /<br>{esc(t('table_last_seen'))}</th>"
        table_html += f"<th style='padding:8px; border:1px solid #325158; width:44px; text-align:center;'>{esc(t('table_dir'))}</th>"
        table_html += f"<th style='padding:8px; border:1px solid #325158;'>{esc(t('table_source'))}</th>"
        table_html += f"<th style='padding:8px; border:1px solid #325158;'>{esc(t('table_destination'))}</th>"
        table_html += f"<th style='padding:8px; border:1px solid #325158; width:88px;'>{esc(t('table_service'))}</th>"
        table_html += f"<th style='padding:8px; border:1px solid #325158; width:74px; text-align:center;'>{esc(t('table_num_conns'))}</th>"
        table_html += f"<th style='padding:8px; border:1px solid #325158; width:88px;'>{esc(t('table_decision'))}</th>"
        table_html += "</tr>"

        for i, d in enumerate(data_list):
            row_bg = "#ffffff" if i % 2 == 0 else "#F7F4EE"
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
                "blocked": f"<span style='display:inline-block; color:white; background:#BE122F; padding:2px 6px; border-radius:12px; font-weight:700;'>{esc(t('decision_blocked'))}</span>",
                "potentially_blocked": f"<span style='display:inline-block; color:white; background:#F97607; padding:2px 6px; border-radius:12px; font-weight:700;'>{esc(t('decision_potential'))}</span>",
                "allowed": f"<span style='display:inline-block; color:white; background:#166644; padding:2px 6px; border-radius:12px; font-weight:700;'>{esc(t('decision_allowed'))}</span>",
            }
            decision = str(d.get("policy_decision")).lower()
            decision_html = pd_map.get(decision, esc(decision))
            table_html += f"<tr style='background:{row_bg};'>"
            table_html += f"<td style='padding:8px; border:1px solid #325158; font-weight:700; color:#FF5500;'>{val_str}</td>"
            table_html += f"<td style='padding:8px; border:1px solid #325158; white-space:nowrap; font-size:10px;'>{t_first}<br>{t_last}</td>"
            table_html += f"<td style='padding:8px 6px; border:1px solid #325158; text-align:center; font-weight:700;'>{esc(direction)}</td>"
            table_html += f"<td style='padding:8px 10px; border:1px solid #325158; word-break:break-word;'>{actor_view(d, True)}</td>"
            table_html += f"<td style='padding:8px 10px; border:1px solid #325158; word-break:break-word;'>{actor_view(d, False)}</td>"
            table_html += f"<td style='padding:8px 6px; border:1px solid #325158; text-align:center;'>{esc(port)} / {esc(proto_str)}</td>"
            table_html += f"<td style='padding:8px; border:1px solid #325158; text-align:center;'><strong>{esc(count)}</strong></td>"
            table_html += f"<td style='padding:8px; border:1px solid #325158;'>{decision_html}</td>"
            table_html += "</tr>"

        table_html += "</table>"
        return table_html

    def _build_plain_text_report(self):
        import re

        def clean_ansi(text):
            return re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", str(text))

        body = f"{t('report_header')}\n"
        body += f"{t('generated_at', time=self._now_str())}\n"
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

    def _build_line_message(self, subj: str) -> str:
        """Build a LINE-optimised plain-text alert message (no long run-on lines)."""
        import re

        def clean(text):
            return re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", str(text))

        def fmt_talkers(raw: str) -> str:
            """Split comma-separated Top Talkers into one entry per line."""
            items = [s.strip() for s in raw.replace('<br>', ',').split(',') if s.strip()]
            return '\n'.join(f"    • {clean(i)}" for i in items)

        lines = [subj, f"產生時間: {self._now_str()}", "─" * 20]

        if self.health_alerts:
            lines.append(f"\n🔴 {t('health_alerts_header')}")
            for a in self.health_alerts:
                lines.append(f"  [{clean(a.get('time',''))}] {clean(a.get('status',''))}")
                lines.append(f"  {clean(a.get('details',''))}")

        if self.event_alerts:
            lines.append(f"\n🟠 {t('security_events_header')}")
            for a in self.event_alerts:
                sev = clean(str(a.get('severity', '')).upper())
                cnt = a.get('count', 0)
                lines.append(f"  [{clean(a.get('time',''))}] {clean(a.get('rule',''))} ({sev} ×{cnt})")
                if a.get('desc'):
                    lines.append(f"  {clean(a['desc'])}")

        if self.traffic_alerts:
            lines.append(f"\n🛡 {t('traffic_alerts_header')}")
            for a in self.traffic_alerts:
                lines.append(f"  ▸ {clean(a.get('rule',''))}")
                lines.append(f"    次數: {clean(a.get('count', 0))}  |  {clean(a.get('criteria',''))}")
                talkers = fmt_talkers(a.get('details', ''))
                if talkers:
                    lines.append(f"    {t('traffic_toptalkers')}:")
                    lines.append(talkers)

        if self.metric_alerts:
            lines.append(f"\n📊 {t('metric_alerts_header')}")
            for a in self.metric_alerts:
                lines.append(f"  ▸ {clean(a.get('rule',''))}")
                lines.append(f"    值: {clean(a.get('count', 0))}  |  {clean(a.get('criteria',''))}")
                talkers = fmt_talkers(a.get('details', ''))
                if talkers:
                    lines.append(f"    {t('traffic_toptalkers')}:")
                    lines.append(talkers)

        return '\n'.join(lines)

    def _send_line(self, subj):
        token = self.cm.config.get("alerts", {}).get("line_channel_access_token", "")
        target_id = self.cm.config.get("alerts", {}).get("line_target_id", "")
        if not token or not target_id:
            print(f"{Colors.WARNING}{t('line_config_missing')}{Colors.ENDC}")
            return

        message_text = self._build_line_message(subj)
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

    # ── Event detail renderer ────────────────────────────────────────────────

    @staticmethod
    def _render_event_detail_html(events: list, esc) -> str:
        """Convert raw Illumio event list into structured human-readable HTML cards."""
        if not events:
            return ""

        _RESOURCE_LABELS = {
            'sec_rule': 'Security Rule', 'rule_set': 'Ruleset',
            'sec_policy': 'Policy Provision', 'user': 'User Auth',
            'request': 'API Auth', 'authz_csrf': 'CSRF Check',
            'agent': 'VEN Agent', 'workload': 'Workload',
            'label': 'Label', 'ip_list': 'IP List',
            'service': 'Service', 'ven': 'VEN',
        }
        _VERB_STYLE = {
            'create': ('Created', '#166644', '#D1FAE5'),
            'update': ('Updated', '#F97607', '#FFF3CD'),
            'delete': ('Deleted', '#BE122F', '#FEE2E2'),
            'sign_in': ('Sign-In', '#325158', '#E0F2FE'),
            'authentication_failed': ('Auth Fail', '#BE122F', '#FEE2E2'),
            'tampering': ('Tampering', '#BE122F', '#FEE2E2'),
            'suspend': ('Suspended', '#F97607', '#FFF3CD'),
            'clone_detected': ('Clone Detected', '#BE122F', '#FEE2E2'),
            'csrf_validation_failure': ('CSRF Failure', '#BE122F', '#FEE2E2'),
        }

        def _actor(ev):
            cb = ev.get('created_by') or {}
            user = (cb.get('user') or {})
            agent = (cb.get('agent') or {})
            username = user.get('username') or user.get('name') or ''
            hostname = agent.get('hostname') or agent.get('name') or ''
            if username and hostname:
                return f"{username} @ {hostname}"
            return username or hostname or 'System'

        def _fmt_val(v):
            if v is None:
                return '(none)'
            if isinstance(v, bool):
                return str(v).lower()
            if isinstance(v, dict):
                name = v.get('name') or v.get('value') or v.get('hostname') or ''
                if name:
                    return str(name)
                href = v.get('href', '')
                return href.strip('/').split('/')[-1] if href else json.dumps(v)[:60]
            if isinstance(v, list):
                if not v:
                    return '(empty)'
                first = v[0]
                label = (first.get('name') or first.get('value') or str(first))[:40] if isinstance(first, dict) else str(first)[:40]
                return f"{label}{f' (+{len(v)-1} more)' if len(v) > 1 else ''}"
            return str(v)[:120]

        def _diff_rows(before, after):
            if not (before and after):
                return ''
            skip = {'href', 'updated_at', 'created_at', 'created_by', 'update_type'}
            all_keys = sorted(set(list(before.keys()) + list(after.keys())) - skip)
            changes = [(k, before.get(k), after.get(k)) for k in all_keys if before.get(k) != after.get(k)]
            if not changes:
                return ''
            rows = "<table style='width:100%; border-collapse:collapse; margin-top:6px; font-size:10px;'>"
            rows += ("<tr>"
                     "<th style='text-align:left; padding:3px 6px; background:#24393F; color:#D6D7D7; width:24%;'>Field</th>"
                     "<th style='text-align:left; padding:3px 6px; background:#24393F; color:#D6D7D7; width:38%;'>Before</th>"
                     "<th style='text-align:left; padding:3px 6px; background:#24393F; color:#D6D7D7; width:38%;'>After</th>"
                     "</tr>")
            for k, bv, av in changes[:5]:
                rows += (f"<tr>"
                         f"<td style='padding:3px 6px; border-bottom:1px solid #E3D8C5; color:#989A9B;'>{esc(k)}</td>"
                         f"<td style='padding:3px 6px; border-bottom:1px solid #E3D8C5; color:#BE122F; word-break:break-word;'>{esc(_fmt_val(bv))}</td>"
                         f"<td style='padding:3px 6px; border-bottom:1px solid #E3D8C5; color:#166644; word-break:break-word;'>{esc(_fmt_val(av))}</td>"
                         f"</tr>")
            if len(changes) > 5:
                rows += f"<tr><td colspan='3' style='padding:3px 6px; color:#989A9B;'>… {len(changes)-5} more field(s) changed</td></tr>"
            rows += "</table>"
            return rows

        cards = []
        for ev in events[:3]:
            event_type = ev.get('event_type', '')
            ts = (ev.get('timestamp', '')[:19].replace('T', ' ')) if ev.get('timestamp') else ''
            status = ev.get('status', '')
            actor = _actor(ev)

            resource_prefix = event_type.split('.')[0] if '.' in event_type else event_type
            verb_key = event_type.split('.')[-1] if '.' in event_type else ''
            resource_label = _RESOURCE_LABELS.get(resource_prefix, resource_prefix.replace('_', ' ').title())
            verb_label, verb_color, verb_bg = _VERB_STYLE.get(verb_key, (verb_key.replace('_', ' ').title() or 'Event', '#325158', '#E0F2FE'))

            rc = ev.get('resource_changes')
            if isinstance(rc, list):
                # PCE format: list of {field, before, after}
                before = {item['field']: item.get('before') for item in rc if isinstance(item, dict) and 'field' in item}
                after  = {item['field']: item.get('after')  for item in rc if isinstance(item, dict) and 'field' in item}
            elif isinstance(rc, dict):
                before = rc.get('before') or {}
                after  = rc.get('after')  or {}
            else:
                before, after = {}, {}
            workloads = ev.get('workloads_affected') or {}

            # Human-readable summary line
            extras = []
            if event_type == 'sec_policy.create':
                count = workloads.get('total_affected', 0)
                extras.append(f"{count} workload(s) affected")
            elif verb_key == 'create' and after:
                name = after.get('name') or after.get('hostname') or ''
                if name:
                    extras.append(f"Resource: {name}")
            elif event_type.startswith(('user.', 'request.')):
                src_ip = ev.get('src_ip') or ''
                if src_ip:
                    extras.append(f"Source IP: {src_ip}")
            elif event_type.startswith('agent.'):
                wl_name = (after or before).get('hostname') or (after or before).get('name') or ''
                if wl_name:
                    extras.append(f"Workload: {wl_name}")

            status_color = '#166644' if status == 'success' else '#BE122F'
            diff_html = _diff_rows(before, after)

            card = (
                f"<div style='padding:8px 10px; background:#F7F4EE; border-left:3px solid {verb_color};"
                f" margin-bottom:6px; border-radius:0 4px 4px 0;'>"
                f"<div style='display:flex; flex-wrap:wrap; gap:4px; align-items:center; margin-bottom:4px;'>"
                f"<span style='background:{verb_bg}; color:{verb_color}; padding:2px 6px; border-radius:4px; font-size:10px; font-weight:700;'>{esc(verb_label)}</span>"
                f"<span style='background:#EDE9FE; color:#8B407A; padding:2px 6px; border-radius:4px; font-size:10px;'>{esc(resource_label)}</span>"
                f"<span style='color:{status_color}; border:1px solid {status_color}; padding:1px 5px; border-radius:4px; font-size:10px;'>{esc(status.upper())}</span>"
                f"<code style='font-size:10px; color:#8B407A; margin-left:2px;'>{esc(event_type)}</code>"
                f"<span style='margin-left:auto; font-size:10px; color:#989A9B; white-space:nowrap;'>{esc(ts)}</span>"
                f"</div>"
                f"<div style='font-size:11px; color:#313638;'><strong>Actor:</strong> {esc(actor)}"
            )
            if extras:
                card += f"&nbsp; &bull; &nbsp;{esc(' | '.join(extras))}"
            card += "</div>"
            if diff_html:
                card += diff_html
            card += "</div>"
            cards.append(card)

        if len(events) > 3:
            cards.append(f"<div style='font-size:10px; color:#989A9B; padding:2px 6px;'>… and {len(events)-3} more event(s) in this alert</div>")

        return "".join(cards)

    # ── Mail sender ──────────────────────────────────────────────────────────

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

        generated_at = self._now_str()
        total_items = (
            len(self.health_alerts)
            + len(self.event_alerts)
            + len(self.traffic_alerts)
            + len(self.metric_alerts)
        )
        # ── Illumio brand palette ───────────────────────────────────────────
        # System Cyan 120/110/100: #1A2C32 / #24393F / #2D454C
        # Illumio Orange: #FF5500  |  Circuit Gold: #FFA22F / #F97607
        # Risk Red: #BE122F / #F43F51  |  Safeguard Green: #166644 / #299B65
        # Server Slate: #313638  |  Zero Trust Tan: #F7F4EE / #E3D8C5
        # Protocol Purple: #8B407A
        section_style = "margin-top:18px; border:1px solid #325158; border-radius:8px; overflow:hidden;"
        header_style = "padding:10px 14px; font-size:14px; font-weight:700; font-family:'Montserrat',Arial,sans-serif;"
        table_style = "width:100%; border-collapse:collapse; table-layout:fixed;"
        th_style = "text-align:left; padding:10px; background:#24393F; border-bottom:1px solid #325158; font-size:12px; color:#D6D7D7; font-family:'Montserrat',Arial,sans-serif;"
        td_style = "padding:10px; border-bottom:1px solid #E3D8C5; font-size:12px; color:#313638; vertical-align:top; word-break:break-word; font-family:'Montserrat',Arial,sans-serif;"

        body = "<html><body style='margin:0; padding:0; background:#F7F4EE; font-family:\"Montserrat\",Arial,sans-serif; line-height:1.5; color:#313638;'>"
        body += "<div style='max-width:1100px; margin:0 auto; padding:16px;'>"
        body += "<div style='border:1px solid #325158; border-radius:10px; background:#ffffff; overflow:hidden;'>"
        body += "<div style='padding:18px 20px; background:#1A2C32; color:#ffffff; border-left:4px solid #FF5500;'>"
        body += f"<div style='font-size:20px; font-weight:700; margin-bottom:4px; font-family:\"Montserrat\",Arial,sans-serif;'>{esc(t('report_header'))}</div>"
        body += f"<div style='font-size:12px; color:#989A9B;'>{esc(t('generated_at', time=generated_at))}</div>"
        body += "</div>"
        body += "<div style='padding:14px 20px; border-bottom:1px solid #E3D8C5; background:#F7F4EE;'>"
        body += f"<span style='display:inline-block; margin-right:8px; background:#FF5500; color:#ffffff; padding:4px 8px; border-radius:999px; font-size:12px; font-weight:700;'>Total {esc(total_items)}</span>"
        body += f"<span style='display:inline-block; margin-right:8px; background:#FEE2E2; color:#BE122F; padding:4px 8px; border-radius:999px; font-size:12px; font-weight:700;'>Health {esc(len(self.health_alerts))}</span>"
        body += f"<span style='display:inline-block; margin-right:8px; background:#FFF3CD; color:#F97607; padding:4px 8px; border-radius:999px; font-size:12px; font-weight:700;'>Event {esc(len(self.event_alerts))}</span>"
        body += f"<span style='display:inline-block; margin-right:8px; background:#D1FAE5; color:#166644; padding:4px 8px; border-radius:999px; font-size:12px; font-weight:700;'>Traffic {esc(len(self.traffic_alerts))}</span>"
        body += f"<span style='display:inline-block; background:#EDE9FE; color:#8B407A; padding:4px 8px; border-radius:999px; font-size:12px; font-weight:700;'>Metric {esc(len(self.metric_alerts))}</span>"
        body += "</div><div style='padding:0 20px 20px 20px;'>"

        if self.health_alerts:
            body += f"<div style='{section_style}'>"
            body += f"<div style='{header_style} background:#FEE2E2; color:#BE122F;'>{esc(t('health_alerts_header'))}</div>"
            body += f"<table style='{table_style}'><thead><tr><th style='{th_style}'>{esc(t('health_time'))}</th><th style='{th_style}'>{esc(t('health_status'))}</th><th style='{th_style}'>{esc(t('health_details'))}</th></tr></thead><tbody>"
            for a in self.health_alerts:
                body += f"<tr><td style='{td_style}'>{esc(a.get('time', ''))}</td><td style='{td_style} color:#BE122F; font-weight:700;'>{esc(a.get('status', ''))}</td><td style='{td_style}'>{fmt_multiline(a.get('details', ''))}</td></tr>"
            body += "</tbody></table></div>"

        if self.event_alerts:
            body += f"<div style='{section_style}'>"
            body += f"<div style='{header_style} background:#FFF3CD; color:#F97607;'>{esc(t('security_events_header'))}</div>"
            body += f"<table style='{table_style}'><thead><tr><th style='{th_style}'>{esc(t('event_time'))}</th><th style='{th_style}'>{esc(t('event_name'))}</th><th style='{th_style}'>{esc(t('event_severity'))}</th><th style='{th_style}'>{esc(t('event_source'))}</th></tr></thead><tbody>"
            for a in self.event_alerts:
                sev_color = "#BE122F" if a.get("severity") == "error" else "#F97607"
                body += f"<tr><td style='{td_style}'>{esc(a.get('time', ''))}</td><td style='{td_style}'><strong>{esc(a.get('rule', ''))}</strong><br><small style='color:#989A9B;'>{esc(a.get('desc', ''))}</small></td><td style='{td_style} color:{sev_color}; font-weight:700;'>{esc(str(a.get('severity', '')).upper())} ({esc(a.get('count', 0))})</td><td style='{td_style}'>{esc(a.get('source', ''))}</td></tr>"
                if a.get("raw_data"):
                    detail_html = self._render_event_detail_html(a.get("raw_data", []), esc)
                    body += f"<tr><td colspan='4' style='padding:8px 10px; background:#ffffff; border-bottom:1px solid #E3D8C5;'>{detail_html}</td></tr>"
            body += "</tbody></table></div>"

        if self.traffic_alerts:
            body += f"<div style='{section_style}'>"
            body += f"<div style='{header_style} background:#D1FAE5; color:#166644;'>{esc(t('traffic_alerts_header'))}</div>"
            body += f"<table style='{table_style}'><thead><tr><th style='{th_style}'>{esc(t('traffic_rule'))}</th><th style='{th_style}'>{esc(t('traffic_count'))}</th><th style='{th_style}'>{esc(t('traffic_criteria'))}</th><th style='{th_style}'>{esc(t('traffic_toptalkers'))}</th></tr></thead><tbody>"
            for a in self.traffic_alerts:
                body += f"<tr><td style='{td_style}'><strong>{esc(a.get('rule', ''))}</strong></td><td style='{td_style} font-size:16px; font-weight:700; color:#FF5500;'>{esc(a.get('count', 0))}</td><td style='{td_style} color:#989A9B; font-size:11px;'>{fmt_multiline(a.get('criteria', ''))}</td><td style='{td_style}'>{fmt_multiline(a.get('details', ''))}</td></tr>"
                body += f"<tr><td colspan='4' style='padding:10px; background:#ffffff; border-bottom:1px solid #E3D8C5;'>{self.generate_pretty_snapshot_html(a.get('raw_data', []))}</td></tr>"
            body += "</tbody></table></div>"

        if self.metric_alerts:
            body += f"<div style='{section_style}'>"
            body += f"<div style='{header_style} background:#EDE9FE; color:#8B407A;'>{esc(t('metric_alerts_header'))}</div>"
            body += f"<table style='{table_style}'><thead><tr><th style='{th_style}'>{esc(t('traffic_rule'))}</th><th style='{th_style}'>{esc(t('table_value'))}</th><th style='{th_style}'>{esc(t('traffic_criteria'))}</th><th style='{th_style}'>{esc(t('traffic_toptalkers'))}</th></tr></thead><tbody>"
            for a in self.metric_alerts:
                body += f"<tr><td style='{td_style}'><strong>{esc(a.get('rule', ''))}</strong></td><td style='{td_style} font-size:16px; font-weight:700; color:#8B407A;'>{esc(a.get('count', 0))}</td><td style='{td_style} color:#989A9B; font-size:11px;'>{fmt_multiline(a.get('criteria', ''))}</td><td style='{td_style}'>{fmt_multiline(a.get('details', ''))}</td></tr>"
                body += f"<tr><td colspan='4' style='padding:10px; background:#ffffff; border-bottom:1px solid #E3D8C5;'>{self.generate_pretty_snapshot_html(a.get('raw_data', []))}</td></tr>"
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

    def send_scheduled_report_email(self, subject, html_body, attachment_paths=None,
                                     custom_recipients=None):
        """
        Send a scheduled report email with multiple optional file attachments.
        Uses custom_recipients if provided; otherwise falls back to email.recipients.

        Args:
            subject (str):                   Email subject.
            html_body (str):                 HTML email body.
            attachment_paths (list[str]):    Optional list of file paths to attach.
            custom_recipients (list[str]):   Override recipients for this schedule.

        Returns:
            bool: True on success, False on error.
        """
        import os
        from email.mime.base import MIMEBase
        from email import encoders

        cfg = self.cm.config["email"]
        recipients = (
            [r.strip() for r in custom_recipients if r.strip()]
            if custom_recipients
            else cfg.get("recipients", [])
        )
        if not recipients:
            print(f"{Colors.WARNING}{t('no_recipients')}{Colors.ENDC}")
            return False

        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"] = cfg["sender"]
        msg["To"] = ",".join(recipients)
        msg.attach(MIMEText(html_body, "html"))

        for path in (attachment_paths or []):
            if path and os.path.exists(path):
                try:
                    with open(path, "rb") as f:
                        part = MIMEBase("application", "octet-stream")
                        part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f'attachment; filename="{os.path.basename(path)}"',
                    )
                    msg.attach(part)
                except (IOError, OSError) as e:
                    print(f"{Colors.WARNING}Warning: could not attach {path}: {e}{Colors.ENDC}")

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
            s.sendmail(cfg["sender"], recipients, msg.as_string())
            s.quit()
            print(f"{Colors.GREEN}{t('mail_sent', host=host, port=port)}{Colors.ENDC}")
            return True
        except Exception as e:
            print(f"{Colors.FAIL}{t('mail_failed', error=e)}{Colors.ENDC}")
            return False

    def send_report_email(self, subject, html_body, attachment_path=None):
        """
        Send a traffic flow report email with an optional file attachment.
        Used by the Report feature — does NOT affect existing alert email flow.

        Args:
            subject (str):          Email subject line.
            html_body (str):        HTML email body (e.g., Module 12 executive summary).
            attachment_path (str):  Optional path to a file to attach (e.g., .xlsx report).

        Returns:
            bool: True on success, False on error.
        """
        import os
        from email.mime.base import MIMEBase
        from email import encoders

        cfg = self.cm.config["email"]
        if not cfg["recipients"]:
            print(f"{Colors.WARNING}{t('no_recipients')}{Colors.ENDC}")
            return False

        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"] = cfg["sender"]
        msg["To"] = ",".join(cfg["recipients"])
        msg.attach(MIMEText(html_body, "html"))

        if attachment_path and os.path.exists(attachment_path):
            try:
                with open(attachment_path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                filename = os.path.basename(attachment_path)
                part.add_header(
                    "Content-Disposition", f'attachment; filename="{filename}"'
                )
                msg.attach(part)
            except (IOError, OSError) as e:
                print(f"{Colors.WARNING}Warning: could not attach file {attachment_path}: {e}{Colors.ENDC}")

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
            return True
        except Exception as e:
            print(f"{Colors.FAIL}{t('mail_failed', error=e)}{Colors.ENDC}")
            return False
