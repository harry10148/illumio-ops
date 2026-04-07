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

        snapshot_labels = {
            "value": "數值",
            "first_seen": "首次偵測",
            "last_seen": "最後偵測",
            "direction": "方向",
            "source": "來源端",
            "destination": "目的端",
            "service": "服務",
            "connections": "連線數",
            "decision": "判定",
        }

        if not data_list:
            return "<div style='padding:10px 12px; color:#6b7280; font-size:12px;'>暫無快照資料</div>"

        def actor_view(item, is_source=True):
            actor = item.get("source" if is_source else "destination", {})
            raw = item.get("src" if is_source else "dst", {})
            svc = item.get("service", {})

            ip = actor.get("ip") or raw.get("ip") or "-"
            wl = raw.get("workload", {})
            name = actor.get("name") or wl.get("name") or wl.get("hostname") or ip
            labels = actor.get("labels") or wl.get("labels", [])

            # process/user attribution depends on flow_direction:
            # outbound → captured by src VEN → belongs to source
            # inbound  → captured by dst VEN → belongs to destination
            flow_dir = (item.get("flow_direction") or "").lower()
            svc_proc = svc.get("process_name") or ""
            svc_user = svc.get("user_name") or ""
            if flow_dir == "outbound":
                raw_proc = svc_proc if is_source else ""
                raw_user = svc_user if is_source else ""
            elif flow_dir == "inbound":
                raw_proc = "" if is_source else svc_proc
                raw_user = "" if is_source else svc_user
            else:
                raw_proc, raw_user = "", ""
            # actor.get("process") is already set correctly when flow went through query_flows
            proc = actor.get("process") or raw_proc
            user = actor.get("user") or raw_user

            badges = "".join(
                [
                    f"<span style='display:inline-block; background:#E5F2F9; color:#2D454C; padding:2px 5px; border-radius:4px; font-size:10px; margin:2px 3px 0 0; border:1px solid #C2E2F0;'>{esc(l.get('key'))}:{esc(l.get('value'))}</span>"
                    for l in labels
                ]
            )
            proc_line = (
                f"<div style='font-size:10px; color:#313638; margin-top:4px;'><strong>程序:</strong> {esc(proc)}</div>"
                if proc
                else ""
            )
            user_line = (
                f"<div style='font-size:10px; color:#6F7274;'><strong>使用者:</strong> {esc(user)}</div>"
                if user
                else ""
            )
            return (
                f"<strong style='color:#FF5500;'>{esc(name)}</strong><br><small style='color:#313638;'>{esc(ip)}</small>"
                f"{proc_line}{user_line}<div style='margin-top:2px;'>{badges}</div>"
            )

        table_html = "<table style='width:100%; border-collapse:collapse; font-family:\"Montserrat\",Arial,sans-serif; font-size:12px; border:1px solid #D6D7D7;'>"
        table_html += "<tr style='background-color:#1A2C32; color:#FFFFFF; text-align:left;'>"
        table_html += f"<th style='padding:10px 8px; border:1px solid #325158; width:96px;'>{snapshot_labels['value']}</th>"
        table_html += f"<th style='padding:10px 8px; border:1px solid #325158; width:132px;'>{snapshot_labels['first_seen']} /<br>{snapshot_labels['last_seen']}</th>"
        table_html += f"<th style='padding:10px 6px; border:1px solid #325158; width:72px; text-align:center;'>{snapshot_labels['direction']}</th>"
        table_html += f"<th style='padding:10px 8px; border:1px solid #325158;'>{snapshot_labels['source']}</th>"
        table_html += f"<th style='padding:10px 8px; border:1px solid #325158;'>{snapshot_labels['destination']}</th>"
        table_html += f"<th style='padding:10px 8px; border:1px solid #325158; width:88px;'>{snapshot_labels['service']}</th>"
        table_html += f"<th style='padding:10px 8px; border:1px solid #325158; width:74px; text-align:center;'>{snapshot_labels['connections']}</th>"
        table_html += f"<th style='padding:10px 8px; border:1px solid #325158; width:88px;'>{snapshot_labels['decision']}</th>"
        table_html += "</tr>"

        for i, d in enumerate(data_list):
            row_bg = "#ffffff" if i % 2 == 0 else "#F5F5F5"
            val_str = esc(d.get("_metric_fmt", "-"))
            ts_r = d.get("timestamp_range", {})
            t_first = esc(
                ts_r.get("first_detected", d.get("timestamp", "-"))
                .replace("T", " ")
                .split(".")[0]
            )
            t_last = esc(ts_r.get("last_detected", "-").replace("T", " ").split(".")[0])

            direction = (
                "Inbound"
                if d.get("flow_direction") == "inbound"
                else "Outbound"
                if d.get("flow_direction") == "outbound"
                else d.get("flow_direction", "-")
            )
            svc = d.get("service", {})
            port = d.get("dst_port") or svc.get("port") or "-"
            proto = d.get("proto") or svc.get("proto") or "-"
            proto_str = "TCP" if proto == 6 else "UDP" if proto == 17 else str(proto)
            count = d.get("num_connections") or d.get("count") or 1
            pd_map = {
                "blocked": "<span style='display:inline-block; color:white; background:#BE122F; padding:2px 8px; border-radius:4px; font-weight:700; font-size:10px;'>Blocked</span>",
                "potentially_blocked": "<span style='display:inline-block; color:white; background:#F97607; padding:2px 8px; border-radius:4px; font-weight:700; font-size:10px;'>Potential</span>",
                "allowed": "<span style='display:inline-block; color:white; background:#166644; padding:2px 8px; border-radius:4px; font-weight:700; font-size:10px;'>Allowed</span>",
            }
            decision = str(d.get("policy_decision")).lower()
            decision_html = pd_map.get(decision, esc(decision))
            table_html += f"<tr style='background:{row_bg};'>"
            table_html += f"<td style='padding:10px 8px; border:1px solid #D6D7D7; font-weight:700; color:#FF5500;'>{val_str}</td>"
            table_html += f"<td style='padding:10px 8px; border:1px solid #D6D7D7; white-space:nowrap; font-size:10px; color:#6F7274;'>{t_first}<br>{t_last}</td>"
            table_html += f"<td style='padding:10px 6px; border:1px solid #D6D7D7; text-align:center; font-weight:700; color:#313638;'>{esc(direction)}</td>"
            table_html += f"<td style='padding:10px; border:1px solid #D6D7D7; word-break:break-word;'>{actor_view(d, True)}</td>"
            table_html += f"<td style='padding:10px; border:1px solid #D6D7D7; word-break:break-word;'>{actor_view(d, False)}</td>"
            table_html += f"<td style='padding:10px 6px; border:1px solid #D6D7D7; text-align:center; color:#313638;'>{esc(port)} / {esc(proto_str)}</td>"
            table_html += f"<td style='padding:10px 8px; border:1px solid #D6D7D7; text-align:center; color:#313638;'><strong>{esc(count)}</strong></td>"
            table_html += f"<td style='padding:10px 8px; border:1px solid #D6D7D7;'>{decision_html}</td>"
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
                body += clean_ansi(f"說明: {a['desc']}\n")
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
        """Build a LINE-friendly alert digest for fast triage."""
        import re

        def clean(text):
            return re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", str(text))

        def compact(raw: str) -> str:
            return re.sub(r"\s+", " ", clean(raw)).strip()

        def top_talkers(raw: str, limit: int = 2) -> list[str]:
            items = [compact(s) for s in raw.replace("<br>", ",").split(",") if compact(s)]
            return items[:limit]

        def severity_label(value: str) -> str:
            mapping = {
                "crit": "重大",
                "critical": "重大",
                "emerg": "重大",
                "alert": "高風險",
                "err": "高風險",
                "error": "高風險",
                "warn": "警告",
                "warning": "警告",
                "info": "資訊",
            }
            return mapping.get(str(value).lower(), "資訊")

        def event_recommendation(event_type: str) -> str:
            recommendations = {
                "agent.tampering": "先確認是否為授權變更，再檢查主機與防火牆設定。",
                "agent.clone_detected": "檢查是否有重複或未授權的 VEN 映像。",
                "agent.suspend": "確認暫停原因，並檢查是否影響策略落地。",
                "agent.service_not_available": "確認 VEN 服務狀態與主機連線是否正常。",
                "system_task.agent_missed_heartbeats_check": "優先確認 VEN 與 PCE 之間的連線品質。",
                "system_task.agent_offline_check": "確認主機是否離線、關機或網路中斷。",
                "request.authentication_failed": "檢查帳號與 API 使用來源，排除暴力嘗試。",
                "request.authorization_failed": "確認權限設定與 API 呼叫來源是否合理。",
                "sec_policy.create": "確認本次 Policy Provision 是否為預期操作。",
            }
            return recommendations.get(event_type, "請至 Web GUI 查看完整事件內容與上下文。")

        def health_recommendation(status: str) -> str:
            normalized = compact(status).lower()
            if normalized in {"503", "error", "critical"}:
                return "優先確認 PCE 健康狀態與核心服務可用性。"
            return "建議檢查叢集節點負載與延遲狀況。"

        def section_header(title: str, count: int) -> str:
            return f"\n【{title}】共 {count} 筆"

        def append_kv_block(lines: list[str], items: list[tuple[str, str]]):
            for label, value in items:
                if value:
                    lines.append(f"{label}：{value}")

        total_issues = (
            len(self.health_alerts)
            + len(self.event_alerts)
            + len(self.traffic_alerts)
            + len(self.metric_alerts)
        )
        lines = [
            "Illumio 告警摘要",
            f"產出時間：{self._now_str()}",
            f"總告警數：{total_issues}",
            f"健康告警：{len(self.health_alerts)}  安全事件：{len(self.event_alerts)}",
            f"流量告警：{len(self.traffic_alerts)}  指標告警：{len(self.metric_alerts)}",
            "請優先處理重大與高風險項目。",
        ]

        if self.health_alerts:
            lines.append(section_header("健康告警", len(self.health_alerts)))
            for idx, a in enumerate(self.health_alerts[:2], start=1):
                status = compact(a.get("status", ""))
                label = "重大" if status in {"503", "error", "critical"} else "警告"
                lines.append(f"{idx}. [{label}] {compact(a.get('rule', '健康檢查'))}")
                append_kv_block(
                    lines,
                    [
                        ("時間", compact(a.get("time", ""))),
                        ("狀態", status),
                        ("摘要", compact(a.get("details", ""))),
                        ("建議", health_recommendation(status)),
                    ],
                )
                lines.append("")
            remaining = len(self.health_alerts) - 2
            if remaining > 0:
                lines.append(f"其餘 {remaining} 筆健康告警請至 GUI 查看。")

        if self.event_alerts:
            lines.append(section_header("安全事件", len(self.event_alerts)))
            for idx, a in enumerate(self.event_alerts[:3], start=1):
                raw = a.get("raw_data") or []
                ev0 = raw[0] if raw else {}
                event_type = compact(ev0.get("event_type", ""))
                label = severity_label(a.get("severity", "info"))
                source = compact(a.get("source", ""))
                target = ""
                resource = ev0.get("resource") or {}
                if event_type.startswith(("agent.", "agents.")):
                    target = (
                        compact((resource.get("agent") or {}).get("hostname"))
                        or compact((resource.get("workload") or {}).get("name"))
                    )
                elif event_type.startswith(("user.", "request.")):
                    target = compact((resource.get("user") or {}).get("username"))
                lines.append(f"{idx}. [{label}] {compact(a.get('rule', '事件告警'))}")
                append_kv_block(
                    lines,
                    [
                        ("時間", compact(a.get("time", ""))[:19]),
                        ("來源", source),
                        ("對象", target),
                        ("摘要", compact(a.get("desc", ""))),
                        ("建議", event_recommendation(event_type)),
                    ],
                )
                if event_type:
                    lines.append(f"事件類型：{event_type}")
                lines.append("")
            remaining = len(self.event_alerts) - 3
            if remaining > 0:
                lines.append(f"其餘 {remaining} 筆安全事件請至 Web GUI 查看完整內容。")

        if self.traffic_alerts:
            lines.append(section_header("流量告警", len(self.traffic_alerts)))
            for idx, a in enumerate(self.traffic_alerts[:2], start=1):
                lines.append(f"{idx}. [警告] {compact(a.get('rule', '流量告警'))}")
                append_kv_block(
                    lines,
                    [
                        ("條件", compact(a.get("criteria", ""))),
                        ("次數", compact(a.get("count", ""))),
                        ("建議", "先確認來源端、目的端與連接埠是否符合預期。"),
                    ],
                )
                talkers = top_talkers(a.get("details", ""))
                if talkers:
                    lines.append("熱門連線：")
                    lines.extend(f"- {item}" for item in talkers)
                lines.append("")
            remaining = len(self.traffic_alerts) - 2
            if remaining > 0:
                lines.append(f"其餘 {remaining} 筆流量告警請至 GUI 查看。")

        if self.metric_alerts:
            lines.append(section_header("指標告警", len(self.metric_alerts)))
            for idx, a in enumerate(self.metric_alerts[:2], start=1):
                lines.append(f"{idx}. [警告] {compact(a.get('rule', '指標告警'))}")
                append_kv_block(
                    lines,
                    [
                        ("條件", compact(a.get("criteria", ""))),
                        ("數值", compact(a.get("count", ""))),
                        ("建議", "請檢查是否有尖峰流量、異常傳輸或資源使用失衡。"),
                    ],
                )
                talkers = top_talkers(a.get("details", ""))
                if talkers:
                    lines.append("熱門連線：")
                    lines.extend(f"- {item}" for item in talkers)
                lines.append("")
            remaining = len(self.metric_alerts) - 2
            if remaining > 0:
                lines.append(f"其餘 {remaining} 筆指標告警請至 GUI 查看。")

        lines.append("完整內容請至 Illumio PCE Ops Web GUI 查看。")
        return "\n".join(line for line in lines if line is not None).strip()

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
            'sec_rule': 'Security Rule',
            'rule_set': 'Ruleset',
            'sec_policy': 'Policy Provision',
            'user': '使用者驗證',
            'request': 'API 驗證',
            'authz_csrf': 'CSRF 驗證',
            'agent': 'VEN Agent',
            'agents': 'VEN Agents',
            'workload': '工作負載',
            'workloads': '工作負載',
            'system_task': '系統工作',
            'lost_agent': 'Lost Agent',
            'cluster': '叢集',
            'api_key': 'API Key',
            'pce_health': 'PCE 健康檢查',
            'label': '標籤',
            'ip_list': 'IP 清單',
            'service': '服務',
            'ven': 'VEN',
            'pairing_profile': '配對設定檔',
            'authentication_settings': '認證設定',
            'firewall_settings': '防火牆設定',
        }
        _VERB_STYLE = {
            'create': ('已建立', '#166644', '#D1FAE5'),
            'update': ('已更新', '#F97607', '#FFF3CD'),
            'delete': ('已刪除', '#BE122F', '#FEE2E2'),
            'sign_in': ('登入', '#325158', '#E0F2FE'),
            'sign_out': ('登出', '#325158', '#E0F2FE'),
            'authentication_failed': ('驗證失敗', '#BE122F', '#FEE2E2'),
            'tampering': ('遭竄改', '#BE122F', '#FEE2E2'),
            'suspend': ('已暫停', '#F97607', '#FFF3CD'),
            'clone_detected': ('偵測到複製', '#BE122F', '#FEE2E2'),
            'csrf_validation_failure': ('CSRF 驗證失敗', '#BE122F', '#FEE2E2'),
            'unpair': ('已解除配對', '#BE122F', '#FEE2E2'),
            'deactivate': ('已停用', '#F97607', '#FFF3CD'),
            'activate': ('已啟用', '#166644', '#D1FAE5'),
            'goodbye': ('離線', '#325158', '#E0F2FE'),
            'refresh_policy': ('Policy 重新整理', '#325158', '#E0F2FE'),
            'agent_missed_heartbeats_check': ('心跳遺失檢查', '#F97607', '#FFF3CD'),
            'agent_offline_check': ('離線檢查', '#F97607', '#FFF3CD'),
            'missed_heartbeats_check': ('心跳遺失檢查', '#F97607', '#FFF3CD'),
            'offline_check': ('離線檢查', '#F97607', '#FFF3CD'),
            'found': ('已找回', '#166644', '#D1FAE5'),
            'service_not_available': ('服務不可用', '#BE122F', '#FEE2E2'),
            'authenticate': ('驗證成功', '#166644', '#D1FAE5'),
            'login_session_terminated': ('登入工作階段終止', '#F97607', '#FFF3CD'),
            'pce_session_terminated': ('PCE 工作階段終止', '#F97607', '#FFF3CD'),
            'authorization_failed': ('授權失敗', '#BE122F', '#FEE2E2'),
            'pce_health': ('健康檢查', '#F97607', '#FFF3CD'),
        }
        _STATUS_LABELS = {
            'success': '成功',
            'failure': '失敗',
            'warn': '警告',
            'warning': '警告',
            'error': '錯誤',
            'info': '資訊',
        }
        _FIELD_LABELS = {
            'labels': '標籤',
            'mode': '模式',
            'name': '名稱',
            'enabled': '啟用狀態',
            'service': '服務',
            'consumers': '來源端',
            'provision_status': '佈署狀態',
            'batch_id': '批次 ID',
            'fqdns': 'FQDN',
            'nodes': '節點數',
            'service_status': '服務狀態',
        }

        def _actor(ev):
            cb = ev.get('created_by') or {}
            user = (cb.get('user') or {})
            agent = (cb.get('agent') or {})
            username = user.get('username') or user.get('name') or ''
            hostname = agent.get('hostname') or agent.get('name') or ''
            if username and hostname:
                return f"{username} @ {hostname}"
            return username or hostname or '系統'

        def _fmt_val(v):
            if v is None:
                return '無'
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
                    return '空白'
                first = v[0]
                label = (first.get('name') or first.get('value') or str(first))[:40] if isinstance(first, dict) else str(first)[:40]
                return f"{label}{f'（另 {len(v)-1} 筆）' if len(v) > 1 else ''}"
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
                     "<th style='text-align:left; padding:3px 6px; background:#24393F; color:#D6D7D7; width:24%;'>欄位</th>"
                     "<th style='text-align:left; padding:3px 6px; background:#24393F; color:#D6D7D7; width:38%;'>變更前</th>"
                     "<th style='text-align:left; padding:3px 6px; background:#24393F; color:#D6D7D7; width:38%;'>變更後</th>"
                     "</tr>")
            for k, bv, av in changes[:5]:
                field_label = _FIELD_LABELS.get(k, k)
                rows += (f"<tr>"
                         f"<td style='padding:3px 6px; border-bottom:1px solid #E3D8C5; color:#989A9B;'>{esc(field_label)}</td>"
                         f"<td style='padding:3px 6px; border-bottom:1px solid #E3D8C5; color:#BE122F; word-break:break-word;'>{esc(_fmt_val(bv))}</td>"
                         f"<td style='padding:3px 6px; border-bottom:1px solid #E3D8C5; color:#166644; word-break:break-word;'>{esc(_fmt_val(av))}</td>"
                         f"</tr>")
            if len(changes) > 5:
                rows += f"<tr><td colspan='3' style='padding:3px 6px; color:#989A9B;'>另有 {len(changes)-5} 個欄位異動</td></tr>"
            rows += "</table>"
            return rows

        cards = []
        for ev in events[:5]:
            event_type = ev.get('event_type', '')
            ts = (ev.get('timestamp', '')[:19].replace('T', ' ')) if ev.get('timestamp') else ''
            status = ev.get('status', '')
            actor = _actor(ev)

            resource_prefix = event_type.split('.')[0] if '.' in event_type else event_type
            verb_key = event_type.split('.')[-1] if '.' in event_type else ''
            resource_label = _RESOURCE_LABELS.get(resource_prefix, resource_prefix.replace('_', ' ').title())
            verb_label, verb_color, verb_bg = _VERB_STYLE.get(verb_key, (verb_key.replace('_', ' ').title() or '事件', '#325158', '#E0F2FE'))

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
                extras.append(f"影響工作負載: {count} 台")
            elif event_type in ('agents.unpair', 'workloads.unpair'):
                count = workloads.get('total_affected', 0)
                if count:
                    extras.append(f"影響工作負載: {count} 台")
                wl_name = (after or before).get('hostname') or (after or before).get('name') or ''
                if wl_name:
                    extras.append(f"工作負載: {wl_name}")
            elif verb_key == 'create' and after:
                name = after.get('name') or after.get('hostname') or ''
                if name:
                    extras.append(f"資源: {name}")
            elif event_type.startswith(('user.', 'request.')):
                resource = ev.get('resource') or {}
                res_user = (resource.get('user') or {}).get('username') or ''
                cb_user = ((ev.get('created_by') or {}).get('user') or {}).get('username') or ''
                username = res_user or cb_user
                src_ip = ev.get('src_ip') or ''
                if username:
                    extras.append(f"帳號: {username}")
                if src_ip:
                    extras.append(f"IP: {src_ip}")
            elif event_type.startswith(('agent.', 'agents.')):
                resource = ev.get('resource') or {}
                wl_name = (
                    (resource.get('agent') or {}).get('hostname')
                    or (resource.get('workload') or {}).get('name')
                    or (after or before).get('hostname')
                    or (after or before).get('name')
                    or ''
                )
                if wl_name:
                    extras.append(f"工作負載: {wl_name}")
                src_ip = ev.get('src_ip') or ''
                if src_ip:
                    extras.append(f"IP: {src_ip}")

            status_color = '#166644' if status == 'success' else '#BE122F'
            status_label = _STATUS_LABELS.get(status.lower(), status.upper())
            diff_html = _diff_rows(before, after)

            card = (
                f"<div style='padding:8px 10px; background:#F7F4EE; border-left:3px solid {verb_color};"
                f" margin-bottom:6px; border-radius:0 4px 4px 0;'>"
                f"<div style='display:flex; flex-wrap:wrap; gap:4px; align-items:center; margin-bottom:4px;'>"
                f"<span style='background:{verb_bg}; color:{verb_color}; padding:2px 6px; border-radius:4px; font-size:10px; font-weight:700;'>{esc(verb_label)}</span>"
                f"<span style='background:#EDE9FE; color:#8B407A; padding:2px 6px; border-radius:4px; font-size:10px;'>{esc(resource_label)}</span>"
                f"<span style='color:{status_color}; border:1px solid {status_color}; padding:1px 5px; border-radius:4px; font-size:10px;'>{esc(status_label)}</span>"
                f"<code style='font-size:10px; color:#8B407A; margin-left:2px;'>{esc(event_type)}</code>"
                f"<span style='margin-left:auto; font-size:10px; color:#989A9B; white-space:nowrap;'>{esc(ts)}</span>"
                f"</div>"
                f"<div style='font-size:11px; color:#313638;'><strong>操作來源:</strong> {esc(actor)}"
            )
            if extras:
                card += f"&nbsp; &bull; &nbsp;{esc(' | '.join(extras))}"
            card += "</div>"
            if diff_html:
                card += diff_html
            card += "</div>"
            cards.append(card)

        if len(events) > 5:
            cards.append(f"<div style='font-size:10px; color:#989A9B; padding:2px 6px;'>此告警另含 {len(events)-5} 筆事件</div>")

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
        summary_items = [
            ("健康告警", len(self.health_alerts), "#FDECEC", "#BE122F"),
            ("安全事件", len(self.event_alerts), "#E5F2F9", "#1A2C32"),
            ("流量告警", len(self.traffic_alerts), "#FFF0E3", "#FF5500"),
            ("指標告警", len(self.metric_alerts), "#FFF5E8", "#F97607"),
        ]
        summary_html = "".join(
            f"""
        <div style="display:inline-block; width:44%; min-width:170px; margin:0 12px 12px 0; vertical-align:top; background:{bg}; border:1px solid rgba(49,54,56,0.08); border-radius:16px; padding:16px 18px; box-sizing:border-box;">
          <div style="font-size:11px; letter-spacing:0.08em; text-transform:uppercase; color:#6F7274; margin-bottom:8px;">{label}</div>
          <div style="font-size:28px; line-height:1; font-weight:800; color:{fg};">{count}</div>
        </div>
"""
            for label, count, bg, fg in summary_items
        )
        severity_labels = {
            "crit": "重大",
            "critical": "重大",
            "emerg": "緊急",
            "alert": "高風險",
            "err": "錯誤",
            "error": "錯誤",
            "warn": "警告",
            "warning": "警告",
            "info": "資訊",
        }
        # ── Illumio brand palette ───────────────────────────────────────────
        # System Cyan 120/110/100: #1A2C32 / #24393F / #2D454C
        # Illumio Orange: #FF5500  |  Circuit Gold: #FFA22F / #F97607
        # Risk Red: #BE122F / #F43F51  |  Safeguard Green: #166644 / #299B65
        # Server Slate: #313638  |  Zero Trust Tan: #F7F4EE / #E3D8C5
        # Protocol Purple: #8B407A
        section_style = "margin-top:28px; border:1px solid #E6E2D8; border-radius:20px; overflow:hidden; background:#FFFFFF; box-shadow:0 12px 28px rgba(26,44,50,0.08);"
        header_style = "padding:16px 20px; font-size:15px; font-weight:800; font-family:'Montserrat',Arial,sans-serif; letter-spacing:0.02em;"
        table_style = "width:100%; border-collapse:collapse; table-layout:fixed;"
        th_style = "text-align:left; padding:14px 14px; background:#F8F5EF; border-bottom:1px solid #E6E2D8; font-size:11px; color:#6F7274; font-family:'Montserrat',Arial,sans-serif; text-transform:uppercase; letter-spacing:0.08em;"
        td_style = "padding:14px 14px; border-bottom:1px solid #F0ECE4; font-size:13px; color:#313638; vertical-align:top; word-break:break-word; font-family:'Montserrat',Arial,sans-serif; line-height:1.55;"
        section_note_style = "padding:0 20px 18px 20px; font-size:12px; line-height:1.6; color:#6F7274; background:#FFFFFF;"

        body = f"""
<html>
<body style="margin:0; padding:0; background:#F3F0E9; font-family:'Montserrat',Arial,sans-serif; color:#313638;">
  <div style="max-width:980px; margin:0 auto; padding:32px 20px 40px;">
    <div style="background:#FFFFFF; border-radius:28px; overflow:hidden; border:1px solid #E6E2D8; box-shadow:0 20px 48px rgba(26,44,50,0.12);">
      <div style="padding:32px 36px; background:linear-gradient(135deg, #FFF7F0 0%, #FFFFFF 48%, #F2F7F8 100%); border-bottom:1px solid #ECE7DD;">
        <div style="display:flex; align-items:center; gap:14px; margin-bottom:20px;">
          <div style="background:#FF5500; color:#FFFFFF; padding:10px 18px; border-radius:999px; font-weight:800; font-size:17px; letter-spacing:0.02em;">Illumio PCE Ops</div>
          <div style="color:#6F7274; font-size:13px; font-weight:600; letter-spacing:0.08em; text-transform:uppercase;">正式告警通知</div>
        </div>
        <div style="font-size:12px; color:#8C8E8F; letter-spacing:0.08em; text-transform:uppercase; margin-bottom:10px;">告警摘要</div>
        <h1 style="color:#1A2C32; font-size:32px; line-height:1.2; margin:0 0 12px 0; font-weight:800;">{esc(subj)}</h1>
        <p style="color:#6F7274; font-size:14px; line-height:1.7; margin:0 0 16px 0;">本通知彙整近期健康狀態、安全事件、流量異常與指標異常，方便你快速掌握風險並安排後續處置。</p>
        <div style="display:flex; flex-wrap:wrap; gap:18px; margin-bottom:22px;">
          <div style="min-width:220px;">
            <div style="font-size:11px; color:#8C8E8F; letter-spacing:0.08em; text-transform:uppercase; margin-bottom:6px;">產出時間</div>
            <div style="font-size:16px; font-weight:700; color:#24393F;">{esc(generated_at)}</div>
          </div>
          <div style="min-width:180px;">
            <div style="font-size:11px; color:#8C8E8F; letter-spacing:0.08em; text-transform:uppercase; margin-bottom:6px;">通知範圍</div>
            <div style="font-size:16px; font-weight:700; color:#24393F;">健康 / 事件 / 流量 / 指標</div>
          </div>
        </div>
        <div>{summary_html}</div>
      </div>
      <div style="padding:8px 36px 36px;">
"""

        if self.health_alerts:
            body += f"""
      <div style="{section_style}">
        <div style="{header_style} background:#BE122F; color:#FFFFFF;">{esc(t('health_alerts_header'))}</div>
        <div style="{section_note_style} border-bottom:1px solid #F0ECE4;">此區塊彙整 PCE 或 Cluster 健康異常，適合優先確認是否影響連線品質、控制面或服務可用性。</div>
        <table style="{table_style}">
          <thead>
            <tr>
              <th style="{th_style} width:140px;">{esc(t('health_time', default='時間'))}</th>
              <th style="{th_style}">{esc(t('health_status', default='狀態'))}</th>
              <th style="{th_style}">{esc(t('health_details', default='詳細資訊'))}</th>
            </tr>
          </thead>
          <tbody>
"""
            for a in self.health_alerts:
                body += f"""
            <tr>
              <td style="{td_style} font-size:11px; color:#6F7274;">{esc(a.get('time',''))}</td>
              <td style="{td_style} font-weight:700; color:#BE122F;">{esc(a.get('status',''))}</td>
              <td style="{td_style}">{fmt_multiline(a.get('details',''))}</td>
            </tr>
"""
            body += "</tbody></table></div>"

        if self.event_alerts:
            body += f"""
      <div style="{section_style}">
        <div style="{header_style} background:#1A2C32; color:#FFFFFF;">{esc(t('security_events_header'))}</div>
        <div style="{section_note_style} border-bottom:1px solid #F0ECE4;">此區塊列出近期重要事件與操作脈絡，協助你快速判斷是否需要追查帳號、工作負載或策略變更。</div>
        <table style="{table_style}">
          <thead>
            <tr>
              <th style="{th_style} width:140px;">{esc(t('event_time'))}</th>
              <th style="{th_style}">{esc(t('event_name'))}</th>
              <th style="{th_style} width:100px;">{esc(t('event_severity'))}</th>
              <th style="{th_style}">{esc(t('event_source'))}</th>
            </tr>
          </thead>
          <tbody>
"""
            for a in self.event_alerts:
                sev_color = "#BE122F" if a.get("severity") in ["crit", "emerg", "alert", "err", "error"] else "#F97607"
                sev_label = severity_labels.get(str(a.get("severity", "")).lower(), str(a.get("severity", "")).upper())
                body += f"""
            <tr>
              <td style="{td_style} font-size:11px; color:#6F7274;">{esc(a.get('time',''))}</td>
              <td style="{td_style}"><strong>{esc(a.get('rule',''))}</strong><br><small style="color:#6F7274;">{esc(a.get('desc',''))}</small></td>
              <td style="{td_style} text-align:center;"><span style="background:{sev_color}; color:#FFFFFF; padding:2px 6px; border-radius:4px; font-size:10px; font-weight:700;">{esc(sev_label)} ({esc(a.get('count',0))})</span></td>
              <td style="{td_style}">{esc(a.get('source',''))}</td>
            </tr>
"""
                if a.get("raw_data"):
                    detail_html = self._render_event_detail_html(a.get("raw_data", []), esc)
                    body += f"<tr><td colspan='4' style='padding:14px 14px 16px; background:#FCFAF6; border-bottom:1px solid #E6E2D8;'>{detail_html}</td></tr>"
            body += "</tbody></table></div>"

        if self.traffic_alerts:
            body += f"""
      <div style="{section_style}">
        <div style="{header_style} background:#FF5500; color:#FFFFFF;">{esc(t('traffic_alerts_header'))}</div>
        <div style="{section_note_style} border-bottom:1px solid #F0ECE4;">此區塊摘要異常流量與代表性連線，方便你從條件、熱門連線與快照資料判讀風險輪廓。</div>
        <table style="{table_style}">
          <thead>
            <tr>
              <th style="{th_style}">{esc(t('traffic_rule'))}</th>
              <th style="{th_style} width:80px; text-align:center;">{esc(t('traffic_count'))}</th>
              <th style="{th_style}">條件</th>
            </tr>
          </thead>
          <tbody>
"""
            for a in self.traffic_alerts:
                body += f"""
            <tr>
              <td style="{td_style} font-weight:700; color:#FF5500;">{esc(a.get('rule',''))}</td>
              <td style="{td_style} text-align:center; font-weight:700; font-size:16px; color:#FF5500;">{esc(a.get('count',0))}</td>
              <td style="{td_style} font-size:11px; color:#6F7274;">{esc(a.get('criteria',''))}</td>
            </tr>
            <tr>
              <td colspan="3" style="{td_style} background:#FCFAF6; font-size:12px; padding:16px;">
                <div style="margin-bottom:10px; padding:12px 14px; border:1px solid #ECE7DD; border-radius:14px; background:#FFFFFF;"><strong style="color:#24393F;">{esc(t('traffic_toptalkers'))}:</strong> {fmt_multiline(a.get('details',''))}</div>
                {self.generate_pretty_snapshot_html(a.get('raw_data', []))}
              </td>
            </tr>
"""
            body += "</tbody></table></div>"

        if self.metric_alerts:
            body += f"""
      <div style="{section_style}">
        <div style="{header_style} background:#F97607; color:#FFFFFF;">{esc(t('metric_alerts_header'))}</div>
        <div style="{section_note_style} border-bottom:1px solid #F0ECE4;">此區塊整理高頻寬或高數值異常，適合用來快速發現尖峰行為、流量放大或資源使用失衡。</div>
        <table style="{table_style}">
          <thead>
            <tr>
              <th style="{th_style}">{esc(t('traffic_rule'))}</th>
              <th style="{th_style} width:100px; text-align:center;">數值</th>
              <th style="{th_style}">條件</th>
            </tr>
          </thead>
          <tbody>
"""
            for a in self.metric_alerts:
                body += f"""
            <tr>
              <td style="{td_style} font-weight:700; color:#313638;">{esc(a.get('rule',''))}</td>
              <td style="{td_style} text-align:center; font-weight:700; font-size:16px; color:#FF5500;">{esc(a.get('count',0))}</td>
              <td style="{td_style} font-size:11px; color:#6F7274;">{esc(a.get('criteria',''))}</td>
            </tr>
            <tr>
              <td colspan="3" style="{td_style} background:#FCFAF6; font-size:12px; padding:16px;">
                <div style="margin-bottom:10px; padding:12px 14px; border:1px solid #ECE7DD; border-radius:14px; background:#FFFFFF;"><strong style="color:#24393F;">{esc(t('traffic_toptalkers'))}:</strong> {fmt_multiline(a.get('details',''))}</div>
                {self.generate_pretty_snapshot_html(a.get('raw_data', []))}
              </td>
            </tr>
"""
            body += "</tbody></table></div>"

        body += """
      <div style="margin-top:32px; padding:24px 8px 4px; border-top:1px solid #ECE7DD; text-align:center;">
        <p style="color:#8C8E8F; font-size:11px; line-height:1.8; margin:0;">
          此通知由 <strong>Illumio PCE Ops</strong> 自動產生。<br>
          請依你的告警流程進行確認與處置。
        </p>
      </div>
    </div>
    </div>
  </div>
</body>
</html>
"""

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
