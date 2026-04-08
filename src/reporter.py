import datetime
import json
import html
import logging
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from src.alerts import build_output_plugin, get_output_registry, render_alert_template
from src.events import normalize_event, persist_dispatch_results
from src.utils import Colors
from src.i18n import t

logger = logging.getLogger(__name__)

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(PKG_DIR)
STATE_FILE = os.path.join(ROOT_DIR, "logs", "state.json")


class Reporter:
    def __init__(self, config_manager):
        self.cm = config_manager
        self.health_alerts = []
        self.event_alerts = []
        self.traffic_alerts = []
        self.metric_alerts = []
        self.last_dispatch_results = []

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

    def _get_output_plugin(self, name: str):
        try:
            return build_output_plugin(name, self.cm)
        except KeyError:
            logger.warning("Unknown alert output plugin requested: %s", name)
            return None

    def _active_pce_url(self) -> str:
        active_id = self.cm.config.get("active_pce_id")
        if active_id is not None:
            for profile in self.cm.config.get("pce_profiles", []):
                if profile.get("id") == active_id and profile.get("url"):
                    return str(profile.get("url")).strip()
        return str(self.cm.config.get("api", {}).get("url", "")).strip()

    @staticmethod
    def _clean_text(value) -> str:
        return re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", str(value or ""))

    @classmethod
    def _compact_text(cls, value) -> str:
        return re.sub(r"\s+", " ", cls._clean_text(value)).strip()

    @staticmethod
    def _severity_label(value: str) -> str:
        mapping = {
            "crit": "重大",
            "critical": "重大",
            "emerg": "重大",
            "alert": "高風險",
            "err": "錯誤",
            "error": "錯誤",
            "warn": "警告",
            "warning": "警告",
            "info": "資訊",
        }
        return mapping.get(str(value or "").lower(), str(value or "").upper() or "資訊")

    @staticmethod
    def _status_label(value: str) -> str:
        mapping = {
            "success": "成功",
            "failure": "失敗",
            "warning": "警告",
            "warn": "警告",
            "error": "錯誤",
            "info": "資訊",
        }
        return mapping.get(str(value or "").lower(), str(value or "") or "N/A")

    @staticmethod
    def _event_recommendation(event_type: str) -> str:
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

    def _event_console_link(self, event: dict) -> str:
        href = str((event or {}).get("href", "") or "").strip()
        base = self._active_pce_url().rstrip("/")
        if not href or not base:
            return ""
        for suffix in ("/api/v2", "/api/v1", "/api"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        if "/orgs/" in href:
            _, _, tail = href.partition("/orgs/")
            _, _, href = tail.partition("/")
            href = "/" + href if href else ""
        return f"{base}/#{href}" if href else base

    @staticmethod
    def _summarize_notification_info(info) -> str:
        if not isinstance(info, dict):
            return ""
        parts = []
        for key, value in info.items():
            if isinstance(value, dict):
                inner = ", ".join(f"{k}={v}" for k, v in value.items())
                parts.append(f"{key}: {inner}")
            elif isinstance(value, list):
                parts.append(f"{key}: {', '.join(str(v) for v in value[:4])}")
            else:
                parts.append(f"{key}: {value}")
        return "; ".join(parts[:4])

    def _build_resource_change_payload(self, entry: dict) -> dict:
        resource = entry.get("resource") if isinstance(entry, dict) else {}
        resource_type = ""
        resource_name = ""
        resource_href = ""
        if isinstance(resource, dict):
            for key, value in resource.items():
                if isinstance(value, dict):
                    resource_type = key
                    resource_name = (
                        value.get("name")
                        or value.get("username")
                        or value.get("hostname")
                        or value.get("value")
                        or ""
                    )
                    resource_href = value.get("href", "")
                    break

        changes = []
        raw_changes = entry.get("changes") if isinstance(entry, dict) else {}
        if isinstance(raw_changes, dict):
            for field, diff in raw_changes.items():
                if isinstance(diff, dict):
                    before = diff.get("before")
                    after = diff.get("after")
                else:
                    before = ""
                    after = diff
                changes.append({
                    "field": str(field),
                    "before": self._clean_text(before),
                    "after": self._clean_text(after),
                })
        elif isinstance(entry, dict) and "field" in entry:
            changes.append({
                "field": str(entry.get("field")),
                "before": self._clean_text(entry.get("before")),
                "after": self._clean_text(entry.get("after")),
            })

        change_type = str((entry or {}).get("change_type", "") or "").strip() or ("update" if changes else "")
        return {
            "change_type": change_type,
            "resource_type": resource_type,
            "resource_name": self._clean_text(resource_name),
            "resource_href": self._clean_text(resource_href),
            "changes": changes,
        }

    def _build_notification_payload(self, entry: dict) -> dict:
        info = entry.get("info") if isinstance(entry, dict) else {}
        return {
            "notification_type": self._clean_text((entry or {}).get("notification_type", "")),
            "summary": self._summarize_notification_info(info),
            "info": info if isinstance(info, dict) else {},
        }

    def _build_vendor_event_payloads(self, events: list, parsed_events: list | None = None) -> list[dict]:
        payloads = []
        parsed_by_event_id = {}
        for item in parsed_events or []:
            if isinstance(item, dict) and item.get("event_id"):
                parsed_by_event_id[item["event_id"]] = item

        for raw_event in events or []:
            parsed = parsed_by_event_id.get(raw_event.get("href")) or normalize_event(raw_event)
            action = raw_event.get("action") if isinstance(raw_event.get("action"), dict) else {}
            resource_changes = [
                self._build_resource_change_payload(item)
                for item in (raw_event.get("resource_changes") or [])
                if isinstance(item, dict)
            ]
            notifications = [
                self._build_notification_payload(item)
                for item in (raw_event.get("notifications") or [])
                if isinstance(item, dict)
            ]
            payloads.append({
                "event_id": parsed.get("event_id", ""),
                "href": self._clean_text(raw_event.get("href", "")),
                "pce_link": self._event_console_link(raw_event),
                "timestamp": self._clean_text(parsed.get("timestamp") or raw_event.get("timestamp", "")),
                "event_type": self._clean_text(parsed.get("event_type") or raw_event.get("event_type", "")),
                "status": self._clean_text(parsed.get("status") or raw_event.get("status", "")),
                "status_label": self._status_label(parsed.get("status") or raw_event.get("status", "")),
                "severity": self._clean_text(parsed.get("severity") or raw_event.get("severity", "")),
                "severity_label": self._severity_label(parsed.get("severity") or raw_event.get("severity", "")),
                "created_by": self._clean_text(parsed.get("actor") or "System"),
                "actor": self._clean_text(parsed.get("actor") or "System"),
                "target_name": self._clean_text(parsed.get("target_name", "")),
                "target_type": self._clean_text(parsed.get("target_type", "")),
                "resource_name": self._clean_text(parsed.get("resource_name", "")),
                "resource_type": self._clean_text(parsed.get("resource_type", "")),
                "source_ip": self._clean_text(parsed.get("source_ip", "")),
                "parser_notes": list(parsed.get("parser_notes") or []),
                "known_event_type": bool(parsed.get("known_event_type")),
                "action": {
                    "api_method": self._clean_text(action.get("api_method") or parsed.get("action_method", "")),
                    "api_endpoint": self._clean_text(action.get("api_endpoint") or parsed.get("action_path", "")),
                    "label": self._clean_text(parsed.get("action", "")),
                    "http_status_code": self._clean_text(action.get("http_status_code", "")),
                    "src_ip": self._clean_text(action.get("src_ip") or parsed.get("source_ip", "")),
                    "info": action.get("info") if isinstance(action.get("info"), dict) else {},
                },
                "resource_changes": resource_changes,
                "resource_changes_count": len(resource_changes),
                "notifications": notifications,
                "notifications_count": len(notifications),
                "recommendation": self._event_recommendation(parsed.get("event_type") or raw_event.get("event_type", "")),
                "raw_event": raw_event,
            })
        return payloads

    def _build_event_alert_payload(self, alert: dict) -> dict:
        events = alert.get("raw_data") or []
        parsed_events = alert.get("parsed_data") or []
        vendor_events = self._build_vendor_event_payloads(events, parsed_events)
        first = vendor_events[0] if vendor_events else {}
        return {
            "rule": self._clean_text(alert.get("rule", "")),
            "desc": self._clean_text(alert.get("desc", "")),
            "severity": self._clean_text(alert.get("severity", "")),
            "severity_label": self._severity_label(alert.get("severity", "")),
            "count": int(alert.get("count", len(vendor_events) or 0) or 0),
            "time": self._clean_text(alert.get("time", "")),
            "source": self._clean_text(alert.get("source") or first.get("actor", "")),
            "target": self._clean_text(alert.get("target") or first.get("target_name", "")),
            "resource_type": self._clean_text(alert.get("resource_type") or first.get("resource_type", "")),
            "resource_name": self._clean_text(alert.get("resource_name") or first.get("resource_name", "")),
            "action": self._clean_text(alert.get("action") or first.get("action", {}).get("label", "")),
            "events": vendor_events,
        }

    def _build_all_event_alert_payloads(self) -> list[dict]:
        return [self._build_event_alert_payload(alert) for alert in self.event_alerts]

    def _build_webhook_payload(self, subj: str) -> dict:
        rendered = render_alert_template(
            "webhook_payload.json.tmpl",
            subject_json=json.dumps(subj, ensure_ascii=False),
            content_model_json=json.dumps("vendor_pretty_cool_events_baseline", ensure_ascii=False),
            health_alerts_json=json.dumps(self.health_alerts, ensure_ascii=False),
            event_alerts_json=json.dumps(self.event_alerts, ensure_ascii=False),
            event_alert_payloads_json=json.dumps(self._build_all_event_alert_payloads(), ensure_ascii=False),
            traffic_alerts_json=json.dumps(self.traffic_alerts, ensure_ascii=False),
            metric_alerts_json=json.dumps(self.metric_alerts, ensure_ascii=False),
            timestamp_json=json.dumps(datetime.datetime.now(datetime.timezone.utc).isoformat(), ensure_ascii=False),
        )
        return json.loads(rendered)

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

    def send_alerts(self, force_test=False, channels=None):
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
            self.last_dispatch_results = []
            return []

        alerts_config = self.cm.config.get("alerts", {})
        active_channels = alerts_config.get("active", ["mail"])
        if channels is not None:
            requested = [str(channel).strip() for channel in channels if str(channel).strip()]
            active_channels = [channel for channel in requested if channel in active_channels or force_test]

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
        results = []
        registry = get_output_registry()
        ordered_channels = []
        seen = set()
        for channel in active_channels:
            key = str(channel).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            ordered_channels.append(key)

        for channel in ordered_channels:
            if channel not in registry:
                logger.warning("Configured alert channel has no registered plugin: %s", channel)
                results.append({
                    "channel": channel,
                    "status": "failed",
                    "target": "",
                    "error": "plugin unavailable",
                })
                continue
            plugin = self._get_output_plugin(channel)
            if not plugin:
                results.append({
                    "channel": channel,
                    "status": "failed",
                    "target": "",
                    "error": "plugin unavailable",
                })
                continue
            try:
                results.append(plugin.send(self, subj))
            except Exception as exc:
                logger.exception("Alert plugin %s failed during send", channel)
                results.append({
                    "channel": channel,
                    "status": "failed",
                    "target": "",
                    "error": str(exc),
                })

        self.last_dispatch_results = results
        counts = {
            "health": len(self.health_alerts),
            "events": len(self.event_alerts),
            "traffic": len(self.traffic_alerts),
            "metrics": len(self.metric_alerts),
        }
        try:
            persist_dispatch_results(
                STATE_FILE,
                results,
                subject=subj,
                counts=counts,
                force_test=force_test,
            )
        except Exception as exc:
            logger.warning("Failed to persist dispatch history: %s", exc)
        return results

    def _build_line_message(self, subj: str) -> str:
        """Build a LINE-friendly alert digest aligned to the vendor event content baseline."""
        def section_header(title: str, count: int) -> str:
            return f"\n【{title}】共 {count} 筆"

        total_issues = (
            len(self.health_alerts)
            + len(self.event_alerts)
            + len(self.traffic_alerts)
            + len(self.metric_alerts)
        )
        health_section_lines = []
        if self.health_alerts:
            health_section_lines.append(section_header("健康告警", len(self.health_alerts)))
            for idx, alert in enumerate(self.health_alerts[:2], start=1):
                status = self._compact_text(alert.get("status", ""))
                label = "重大" if status.lower() in {"503", "error", "critical"} else "警告"
                health_section_lines.append(f"{idx}. [{label}] {self._compact_text(alert.get('rule', '健康檢查'))}")
                health_section_lines.append(f"時間：{self._compact_text(alert.get('time', ''))}")
                health_section_lines.append(f"摘要：{self._compact_text(alert.get('details', ''))}")
                health_section_lines.append("")

        event_section_lines = []
        if self.event_alerts:
            event_section_lines.append(section_header("安全事件", len(self.event_alerts)))
            for idx, alert in enumerate(self._build_all_event_alert_payloads()[:3], start=1):
                first = alert["events"][0] if alert["events"] else {}
                event_section_lines.append(f"{idx}. [{alert['severity_label']}] {alert['rule']}")
                if first.get("event_type"):
                    event_section_lines.append(f"事件：{first['event_type']}")
                if first.get("timestamp"):
                    event_section_lines.append(f"時間：{self._compact_text(first['timestamp'])[:19]}")
                if first.get("created_by"):
                    event_section_lines.append(f"建立者：{first['created_by']}")
                if first.get("target_name"):
                    event_section_lines.append(f"對象：{first['target_name']}")
                if first.get("action", {}).get("label"):
                    event_section_lines.append(f"動作：{first['action']['label']}")
                if first.get("action", {}).get("src_ip"):
                    event_section_lines.append(f"來源 IP：{first['action']['src_ip']}")
                if first.get("resource_changes_count"):
                    event_section_lines.append(f"異動：{first['resource_changes_count']} 筆")
                if first.get("notifications_count"):
                    event_section_lines.append(f"通知：{first['notifications_count']} 筆")
                if alert.get("desc"):
                    event_section_lines.append(f"摘要：{alert['desc']}")
                if first.get("recommendation"):
                    event_section_lines.append(f"建議：{first['recommendation']}")
                if first.get("pce_link"):
                    event_section_lines.append(f"PCE：{first['pce_link']}")
                event_section_lines.append("")
            remaining = len(self.event_alerts) - 3
            if remaining > 0:
                event_section_lines.append(f"其餘 {remaining} 筆安全事件請至 Web GUI 查看完整內容。")

        traffic_section_lines = []
        if self.traffic_alerts:
            traffic_section_lines.append(section_header("流量告警", len(self.traffic_alerts)))
            for idx, alert in enumerate(self.traffic_alerts[:2], start=1):
                traffic_section_lines.append(f"{idx}. [警告] {self._compact_text(alert.get('rule', '流量告警'))}")
                if alert.get("criteria"):
                    traffic_section_lines.append(f"條件：{self._compact_text(alert.get('criteria', ''))}")
                if alert.get("count") is not None:
                    traffic_section_lines.append(f"次數：{self._compact_text(alert.get('count', ''))}")
                traffic_section_lines.append("")

        metric_section_lines = []
        if self.metric_alerts:
            metric_section_lines.append(section_header("指標告警", len(self.metric_alerts)))
            for idx, alert in enumerate(self.metric_alerts[:2], start=1):
                metric_section_lines.append(f"{idx}. [警告] {self._compact_text(alert.get('rule', '指標告警'))}")
                if alert.get("criteria"):
                    metric_section_lines.append(f"條件：{self._compact_text(alert.get('criteria', ''))}")
                if alert.get("count") is not None:
                    metric_section_lines.append(f"數值：{self._compact_text(alert.get('count', ''))}")
                metric_section_lines.append("")

        return render_alert_template(
            "line_digest.txt.tmpl",
            subject=self._compact_text(subj),
            generated_at=self._now_str(),
            total_issues=str(total_issues),
            health_count=str(len(self.health_alerts)),
            event_count=str(len(self.event_alerts)),
            traffic_count=str(len(self.traffic_alerts)),
            metric_count=str(len(self.metric_alerts)),
            health_section="\n".join(health_section_lines),
            event_section="\n".join(event_section_lines),
            traffic_section="\n".join(traffic_section_lines),
            metric_section="\n".join(metric_section_lines),
        ).strip()

    def _send_line(self, subj):
        plugin = self._get_output_plugin("line")
        if not plugin:
            return {"channel": "line", "status": "failed", "target": "", "error": "plugin unavailable"}
        return plugin.send(self, subj)

    def _send_webhook(self, subj):
        plugin = self._get_output_plugin("webhook")
        if not plugin:
            return {"channel": "webhook", "status": "failed", "target": "", "error": "plugin unavailable"}
        return plugin.send(self, subj)

    def _render_vendor_event_detail_html(self, alert: dict, esc) -> str:
        payload = self._build_event_alert_payload(alert)
        if not payload["events"]:
            return ""

        sections = []
        for event in payload["events"][:5]:
            action = event.get("action", {})
            meta_cells = []
            for label, value in (
                ("Time", event.get("timestamp")),
                ("Status", event.get("status_label")),
                ("Severity", event.get("severity_label")),
                ("Created By", event.get("created_by")),
            ):
                if value:
                    meta_cells.append(
                        f"<td style='padding:8px 10px;border:1px solid #E6E2D8;font-size:12px;vertical-align:top;'><strong style='display:block;color:#6F7274;font-size:10px;letter-spacing:0.06em;text-transform:uppercase;'>{label}</strong>{esc(value)}</td>"
                    )

            action_rows = []
            for label, value in (
                ("Endpoint", " ".join(part for part in [action.get("api_method"), action.get("api_endpoint")] if part).strip()),
                ("Source IP", action.get("src_ip")),
                ("HTTP Status", action.get("http_status_code")),
                ("Target", event.get("target_name")),
                ("Resource", event.get("resource_name")),
            ):
                if value:
                    action_rows.append(
                        f"<tr><td style='padding:6px 8px;color:#6F7274;width:26%;border-bottom:1px solid #F0ECE4;'>{label}</td><td style='padding:6px 8px;border-bottom:1px solid #F0ECE4;word-break:break-word;'>{esc(value)}</td></tr>"
                    )
            if isinstance(action.get("info"), dict):
                for key, value in list(action["info"].items())[:4]:
                    action_rows.append(
                        f"<tr><td style='padding:6px 8px;color:#6F7274;width:26%;border-bottom:1px solid #F0ECE4;'>{esc(key)}</td><td style='padding:6px 8px;border-bottom:1px solid #F0ECE4;word-break:break-word;'>{esc(value)}</td></tr>"
                    )

            change_blocks = []
            for change in event.get("resource_changes", [])[:3]:
                diff_rows = []
                for diff in change.get("changes", [])[:5]:
                    diff_rows.append(
                        f"<tr><td style='padding:4px 6px;border-bottom:1px solid #F0ECE4;color:#6F7274;'>{esc(diff.get('field', ''))}</td><td style='padding:4px 6px;border-bottom:1px solid #F0ECE4;color:#BE122F;'>{esc(diff.get('before', '')) or '—'}</td><td style='padding:4px 6px;border-bottom:1px solid #F0ECE4;color:#166644;'>{esc(diff.get('after', '')) or '—'}</td></tr>"
                    )
                diff_table = (
                    "<table style='width:100%;border-collapse:collapse;font-size:11px;margin-top:6px;'>"
                    "<tr><th style='text-align:left;padding:4px 6px;background:#F8F5EF;'>Field</th><th style='text-align:left;padding:4px 6px;background:#F8F5EF;'>Before</th><th style='text-align:left;padding:4px 6px;background:#F8F5EF;'>After</th></tr>"
                    + "".join(diff_rows)
                    + "</table>"
                ) if diff_rows else ""
                change_blocks.append(
                    f"<div style='padding:10px 12px;border:1px solid #E6E2D8;border-radius:10px;background:#FFFFFF;margin-top:8px;'>"
                    f"<div style='font-size:12px;font-weight:700;color:#24393F;'>{esc(change.get('change_type', 'update').upper())} {esc(change.get('resource_type', 'resource'))}</div>"
                    f"<div style='font-size:12px;color:#6F7274;margin-top:4px;'>{esc(change.get('resource_name', ''))}</div>"
                    f"{diff_table}</div>"
                )

            notification_blocks = []
            for notification in event.get("notifications", [])[:3]:
                notification_blocks.append(
                    f"<div style='padding:10px 12px;border:1px solid #E6E2D8;border-radius:10px;background:#FFFFFF;margin-top:8px;'>"
                    f"<div style='font-size:12px;font-weight:700;color:#24393F;'>{esc(notification.get('notification_type', 'notification'))}</div>"
                    f"<div style='font-size:12px;color:#6F7274;margin-top:4px;word-break:break-word;'>{esc(notification.get('summary', ''))}</div>"
                    f"</div>"
                )

            parser_notes = ""
            if event.get("parser_notes"):
                parser_notes = f"<div style='margin-top:10px;font-size:11px;color:#8B407A;'>Parser Notes: {esc(', '.join(event.get('parser_notes', [])))}</div>"

            pce_link = ""
            if event.get("pce_link"):
                pce_link = (
                    f"<div style='margin-top:12px;'><a href='{esc(event['pce_link'])}' "
                    f"style='display:inline-block;background:#1A2C32;color:#FFFFFF;padding:8px 14px;border-radius:8px;text-decoration:none;font-size:12px;font-weight:700;'>View on PCE</a></div>"
                )
            resource_changes_html = ""
            if event.get("resource_changes_count"):
                resource_changes_html = (
                    f"<div style='margin-top:12px;'><div style='font-size:12px;font-weight:800;color:#24393F;'>"
                    f"Resource Changes ({event.get('resource_changes_count', 0)})</div>{''.join(change_blocks)}</div>"
                )
            notifications_html = ""
            if event.get("notifications_count"):
                notifications_html = (
                    f"<div style='margin-top:12px;'><div style='font-size:12px;font-weight:800;color:#24393F;'>"
                    f"Notifications ({event.get('notifications_count', 0)})</div>{''.join(notification_blocks)}</div>"
                )

            sections.append(
                f"<div style='margin-top:14px;padding:16px;border:1px solid #E6E2D8;border-radius:16px;background:#FFFDFC;'>"
                f"<div style='padding:12px 14px;background:#1A2C32;color:#FFFFFF;border-radius:12px 12px 0 0;font-size:16px;font-weight:800;'>{esc(event.get('event_type', 'event'))}</div>"
                f"<table style='width:100%;border-collapse:collapse;background:#FFFFFF;border:1px solid #E6E2D8;border-top:none;'><tr>{''.join(meta_cells)}</tr></table>"
                f"<div style='margin-top:10px;'>"
                f"<div style='font-size:12px;font-weight:800;color:#24393F;margin-bottom:6px;'>API Action</div>"
                f"<table style='width:100%;border-collapse:collapse;background:#FFFFFF;border:1px solid #E6E2D8;border-radius:10px;overflow:hidden;'>{''.join(action_rows) or '<tr><td style=\"padding:8px 10px;color:#6F7274;\">No action details</td></tr>'}</table>"
                f"</div>"
                f"{resource_changes_html}"
                f"{notifications_html}"
                f"{parser_notes}{pce_link}</div>"
            )

        if len(payload["events"]) > 5:
            sections.append(f"<div style='margin-top:8px;font-size:11px;color:#6F7274;'>此告警另含 {len(payload['events']) - 5} 筆事件未展開。</div>")
        return "".join(sections)

    # ── Event detail renderer ────────────────────────────────────────────────

    @staticmethod
    def _render_event_detail_html(events: list, esc, parsed_events: list | None = None) -> str:
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
        parsed_map = {}
        for item in parsed_events or []:
            if isinstance(item, dict) and item.get("event_id"):
                parsed_map[item["event_id"]] = item

        for ev in events[:5]:
            parsed = parsed_map.get(ev.get("href")) or normalize_event(ev)
            event_type = parsed.get('event_type', '') or ev.get('event_type', '')
            ts = (parsed.get('timestamp', '')[:19].replace('T', ' ')) if parsed.get('timestamp') else ''
            status = ev.get('status', '')
            actor = parsed.get('actor', 'System')

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
                count = parsed.get('workloads_affected') or workloads.get('total_affected', 0)
                extras.append(f"影響工作負載: {count} 台")
            elif event_type in ('agents.unpair', 'workloads.unpair'):
                count = parsed.get('workloads_affected') or workloads.get('total_affected', 0)
                if count:
                    extras.append(f"影響工作負載: {count} 台")
                wl_name = parsed.get('target_name') or (after or before).get('hostname') or (after or before).get('name') or ''
                if wl_name:
                    extras.append(f"工作負載: {wl_name}")
            elif parsed.get('resource_name') and parsed.get('resource_name') != parsed.get('target_name'):
                extras.append(f"資源: {parsed.get('resource_name')}")
            elif verb_key == 'create' and after:
                name = after.get('name') or after.get('hostname') or ''
                if name:
                    extras.append(f"資源: {name}")
            if event_type.startswith(('user.', 'request.')) and parsed.get('target_name'):
                extras.append(f"帳號: {parsed.get('target_name')}")
            elif event_type.startswith(('agent.', 'agents.')) and parsed.get('target_name'):
                extras.append(f"工作負載: {parsed.get('target_name')}")
            if parsed.get('source_ip'):
                extras.append(f"IP: {parsed.get('source_ip')}")
            if parsed.get('action'):
                extras.append(f"動作: {parsed.get('action')}")
            if parsed.get('parser_notes'):
                extras.append("解析註記: " + ", ".join(parsed.get('parser_notes')))

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

    def _build_mail_html(self, subj):
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
        section_style = "margin-top:28px; border:1px solid #E6E2D8; border-radius:20px; overflow:hidden; background:#FFFFFF; box-shadow:0 12px 28px rgba(26,44,50,0.08);"
        header_style = "padding:16px 20px; font-size:15px; font-weight:800; font-family:'Montserrat',Arial,sans-serif; letter-spacing:0.02em;"
        table_style = "width:100%; border-collapse:collapse; table-layout:fixed;"
        th_style = "text-align:left; padding:14px 14px; background:#F8F5EF; border-bottom:1px solid #E6E2D8; font-size:11px; color:#6F7274; font-family:'Montserrat',Arial,sans-serif; text-transform:uppercase; letter-spacing:0.08em;"
        td_style = "padding:14px 14px; border-bottom:1px solid #F0ECE4; font-size:13px; color:#313638; vertical-align:top; word-break:break-word; font-family:'Montserrat',Arial,sans-serif; line-height:1.55;"
        section_note_style = "padding:0 20px 18px 20px; font-size:12px; line-height:1.6; color:#6F7274; background:#FFFFFF;"

        health_section_html = ""
        if self.health_alerts:
            rows = []
            for alert in self.health_alerts:
                rows.append(
                    f"""
            <tr>
              <td style="{td_style} font-size:11px; color:#6F7274;">{esc(alert.get('time',''))}</td>
              <td style="{td_style} font-weight:700; color:#BE122F;">{esc(alert.get('status',''))}</td>
              <td style="{td_style}">{fmt_multiline(alert.get('details',''))}</td>
            </tr>
"""
                )
            health_section_html = f"""
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
{''.join(rows)}
          </tbody>
        </table>
      </div>
"""

        event_section_html = ""
        if self.event_alerts:
            rows = []
            for alert in self.event_alerts:
                sev_color = "#BE122F" if alert.get("severity") in ["crit", "emerg", "alert", "err", "error"] else "#F97607"
                sev_label = severity_labels.get(str(alert.get("severity", "")).lower(), str(alert.get("severity", "")).upper())
                row_html = f"""
            <tr>
              <td style="{td_style} font-size:11px; color:#6F7274;">{esc(alert.get('time',''))}</td>
              <td style="{td_style}"><strong>{esc(alert.get('rule',''))}</strong><br><small style="color:#6F7274;">{esc(alert.get('desc',''))}</small></td>
              <td style="{td_style} text-align:center;"><span style="background:{sev_color}; color:#FFFFFF; padding:2px 6px; border-radius:4px; font-size:10px; font-weight:700;">{esc(sev_label)} ({esc(alert.get('count',0))})</span></td>
              <td style="{td_style}">{esc(alert.get('source',''))}</td>
            </tr>
"""
                if alert.get("raw_data"):
                    detail_html = self._render_vendor_event_detail_html(alert, esc)
                    row_html += f"<tr><td colspan='4' style='padding:14px 14px 16px; background:#FCFAF6; border-bottom:1px solid #E6E2D8;'>{detail_html}</td></tr>"
                rows.append(row_html)
            event_section_html = f"""
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
{''.join(rows)}
          </tbody>
        </table>
      </div>
"""

        traffic_section_html = ""
        if self.traffic_alerts:
            rows = []
            for alert in self.traffic_alerts:
                rows.append(
                    f"""
            <tr>
              <td style="{td_style} font-weight:700; color:#FF5500;">{esc(alert.get('rule',''))}</td>
              <td style="{td_style} text-align:center; font-weight:700; font-size:16px; color:#FF5500;">{esc(alert.get('count',0))}</td>
              <td style="{td_style} font-size:11px; color:#6F7274;">{esc(alert.get('criteria',''))}</td>
            </tr>
            <tr>
              <td colspan="3" style="{td_style} background:#FCFAF6; font-size:12px; padding:16px;">
                <div style="margin-bottom:10px; padding:12px 14px; border:1px solid #ECE7DD; border-radius:14px; background:#FFFFFF;"><strong style="color:#24393F;">{esc(t('traffic_toptalkers'))}:</strong> {fmt_multiline(alert.get('details',''))}</div>
                {self.generate_pretty_snapshot_html(alert.get('raw_data', []))}
              </td>
            </tr>
"""
                )
            traffic_section_html = f"""
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
{''.join(rows)}
          </tbody>
        </table>
      </div>
"""

        metric_section_html = ""
        if self.metric_alerts:
            rows = []
            for alert in self.metric_alerts:
                rows.append(
                    f"""
            <tr>
              <td style="{td_style} font-weight:700; color:#313638;">{esc(alert.get('rule',''))}</td>
              <td style="{td_style} text-align:center; font-weight:700; font-size:16px; color:#FF5500;">{esc(alert.get('count',0))}</td>
              <td style="{td_style} font-size:11px; color:#6F7274;">{esc(alert.get('criteria',''))}</td>
            </tr>
            <tr>
              <td colspan="3" style="{td_style} background:#FCFAF6; font-size:12px; padding:16px;">
                <div style="margin-bottom:10px; padding:12px 14px; border:1px solid #ECE7DD; border-radius:14px; background:#FFFFFF;"><strong style="color:#24393F;">{esc(t('traffic_toptalkers'))}:</strong> {fmt_multiline(alert.get('details',''))}</div>
                {self.generate_pretty_snapshot_html(alert.get('raw_data', []))}
              </td>
            </tr>
"""
                )
            metric_section_html = f"""
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
{''.join(rows)}
          </tbody>
        </table>
      </div>
"""

        return render_alert_template(
            "mail_wrapper.html.tmpl",
            subject_html=esc(subj),
            generated_at_html=esc(generated_at),
            summary_html=summary_html,
            health_section_html=health_section_html,
            event_section_html=event_section_html,
            traffic_section_html=traffic_section_html,
            metric_section_html=metric_section_html,
        )

    def _send_mail(self, subj):
        plugin = self._get_output_plugin("mail")
        if not plugin:
            return {"channel": "mail", "status": "failed", "target": "", "error": "plugin unavailable"}
        return plugin.send(self, subj)

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
