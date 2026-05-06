from __future__ import annotations

import datetime
import json
import html
from typing import Any, Callable
from loguru import logger
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from src.alerts import build_output_plugin, get_output_registry, render_alert_template
from src.events import normalize_event, persist_dispatch_results
from src.i18n import t

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(PKG_DIR)
STATE_FILE = os.path.join(ROOT_DIR, "logs", "state.json")

class Reporter:
    def __init__(self, config_manager: Any) -> None:
        self.cm = config_manager
        self.health_alerts: list[dict[str, Any]] = []
        self.event_alerts: list[dict[str, Any]] = []
        self.traffic_alerts: list[dict[str, Any]] = []
        self.metric_alerts: list[dict[str, Any]] = []
        self.last_dispatch_results: list[dict[str, Any]] = []

    def _now_str(self) -> str:
        """Return current time formatted in the configured timezone."""
        tz_str = self.cm.config.get('settings', {}).get('timezone', 'local')
        try:
            if not tz_str or tz_str == 'local':
                offset = datetime.datetime.now(datetime.timezone.utc).astimezone().utcoffset()
                tz = datetime.timezone(offset)  # type: ignore[arg-type]
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
            sign_ch = offset_s[0]; hh = offset_s[1:3]; mm = offset_s[3:5]
            tz_label = f"UTC{sign_ch}{hh}:{mm}" if mm != '00' else f"UTC{sign_ch}{hh}"
            return now.strftime('%Y-%m-%d %H:%M') + f' ({tz_label})'
        except Exception:
            return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')  # intentional fallback: return UTC time if timezone offset calculation fails

    def add_health_alert(self, alert: dict[str, Any]) -> None:
        self.health_alerts.append(alert)

    def add_event_alert(self, alert: dict[str, Any]) -> None:
        self.event_alerts.append(alert)

    def add_traffic_alert(self, alert: dict[str, Any]) -> None:
        self.traffic_alerts.append(alert)

    def add_metric_alert(self, alert: dict[str, Any]) -> None:
        self.metric_alerts.append(alert)

    def _get_output_plugin(self, name: str) -> Any:
        try:
            return build_output_plugin(name, self.cm)
        except KeyError:
            logger.warning("Unknown alert output plugin requested: {}", name)
            return None

    def _active_pce_url(self) -> str:
        active_id = self.cm.config.get("active_pce_id")
        if active_id is not None:
            for profile in self.cm.config.get("pce_profiles", []):
                if profile.get("id") == active_id and profile.get("url"):
                    return str(profile.get("url")).strip()
        return str(self.cm.config.get("api", {}).get("url", "")).strip()

    @staticmethod
    def _clean_text(value: Any) -> str:
        return re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", str(value or ""))

    @classmethod
    def _compact_text(cls, value: Any) -> str:
        return re.sub(r"\s+", " ", cls._clean_text(value)).strip()

    # ------------------------------------------------------------------ #
    # i18n-backed label helpers. Each dict maps a domain value (severity /
    # status / event_type) to an i18n key; `t()` resolves it lang-aware.
    # Everything flows through here so alert emails match the user's
    # language setting instead of being hardcoded zh_TW.
    # ------------------------------------------------------------------ #

    _SEVERITY_I18N_KEYS: dict[str, str] = {
        "crit":     "alert_sev_critical",
        "critical": "alert_sev_critical",
        "emerg":    "alert_sev_critical",
        "alert":    "alert_sev_high",
        "err":      "alert_sev_error",
        "error":    "alert_sev_error",
        "warn":     "alert_sev_warning",
        "warning":  "alert_sev_warning",
        "info":     "alert_sev_info",
    }

    _STATUS_I18N_KEYS: dict[str, str] = {
        "success": "alert_status_success",
        "failure": "alert_status_failure",
        "warning": "alert_status_warning",
        "warn":    "alert_status_warning",
        "error":   "alert_status_error",
        "info":    "alert_status_info",
    }

    # event_type → recommendation i18n key
    _REC_I18N_KEYS: dict[str, str] = {
        "agent.tampering":                          "alert_rec_agent_tampering",
        "agent.clone_detected":                     "alert_rec_agent_clone_detected",
        "agent.suspend":                            "alert_rec_agent_suspend",
        "agent.service_not_available":              "alert_rec_agent_service_not_available",
        "system_task.agent_missed_heartbeats_check":"alert_rec_agent_missed_heartbeats_check",
        "system_task.agent_offline_check":          "alert_rec_agent_offline_check",
        "request.authentication_failed":            "alert_rec_request_authentication_failed",
        "request.authorization_failed":             "alert_rec_request_authorization_failed",
        "sec_policy.create":                        "alert_rec_sec_policy_create",
    }

    @classmethod
    def _severity_label(cls, value: str) -> str:
        key = cls._SEVERITY_I18N_KEYS.get(str(value or "").lower())
        if key:
            return t(key)
        return str(value or "").upper() or t("alert_sev_info")

    @classmethod
    def _status_label(cls, value: str) -> str:
        key = cls._STATUS_I18N_KEYS.get(str(value or "").lower())
        if key:
            return t(key)
        return str(value or "") or "N/A"

    @classmethod
    def _event_recommendation(cls, event_type: str) -> str:
        key = cls._REC_I18N_KEYS.get(event_type)
        return t(key) if key else t("alert_rec_default")

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
    def _summarize_notification_info(info: Any) -> str:
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

    def generate_pretty_snapshot_html(self, data_list: list[dict[str, Any]]) -> str:
        import re

        def clean_ansi(text: Any) -> str:
            return re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", str(text))

        def esc(text: Any) -> str:
            return html.escape(clean_ansi(text), quote=True)

        # Snapshot column labels resolved via i18n so alert emails follow
        # the user's language setting.
        snapshot_labels = {
            "value":        t("alert_snap_col_value"),
            "first_seen":   t("alert_snap_col_first_seen"),
            "last_seen":    t("alert_snap_col_last_seen"),
            "direction":    t("alert_snap_col_direction"),
            "source":       t("alert_snap_col_source"),
            "destination":  t("alert_snap_col_destination"),
            "service":      t("alert_snap_col_service"),
            "connections":  t("alert_snap_col_connections"),
            "decision":     t("alert_snap_col_decision"),
        }

        if not data_list:
            no_data = esc(t("alert_snap_no_data"))
            return f"<div style='padding:10px 12px; color:#6b7280; font-size:12px;'>{no_data}</div>"

        def actor_view(item: dict[str, Any], is_source: bool = True) -> str:
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
            proc_label = esc(t("alert_snap_process"))
            user_label = esc(t("alert_snap_user"))
            proc_line = (
                f"<div style='font-size:10px; color:#313638; margin-top:4px;'><strong>{proc_label}:</strong> {esc(proc)}</div>"
                if proc
                else ""
            )
            user_line = (
                f"<div style='font-size:10px; color:#6F7274;'><strong>{user_label}:</strong> {esc(user)}</div>"
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

    def _build_plain_text_report(self) -> str:
        import re

        def clean_ansi(text: Any) -> str:
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
            desc_label = t("alert_field_desc")
            for a in self.event_alerts:
                body += clean_ansi(
                    f"[{a['time']}] {a['rule']} ({a.get('severity', '').upper()} x{a['count']})\n"
                )
                body += clean_ansi(f"{desc_label}: {a['desc']}\n")
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

    @staticmethod
    def _highest_severity(issues: list[dict]) -> str:
        """Pick highest severity from a list of issue dicts; returns 'critical', 'warning', or 'info'."""
        # Map raw severity values to canonical three-level labels used by mail_severity_* i18n keys
        _rank = {'critical': 3, 'crit': 3, 'emerg': 3, 'alert': 2, 'err': 2, 'error': 2, 'warning': 2, 'warn': 2, 'info': 1}
        _canonical = {'critical': 'critical', 'crit': 'critical', 'emerg': 'critical',
                      'alert': 'warning', 'err': 'warning', 'error': 'warning', 'warning': 'warning', 'warn': 'warning',
                      'info': 'info'}
        cur = 0
        out = 'info'
        for issue in issues:
            sev = (issue.get('severity') or 'info').lower()
            rank = _rank.get(sev, 0)
            if rank > cur:
                cur = rank
                out = _canonical.get(sev, 'info')
        return out

    @staticmethod
    def _build_preheader_text(issues_list, max_chars=90):
        """Build a 50-90 char standalone preview shown in inbox.

        Picks first 1-2 issues and joins their summaries; truncates with
        ellipsis if over budget. HTML-escapes the result before returning
        so it's safe to interpolate into the template via string.Template.
        """
        import html as _html
        if not issues_list:
            return ''
        parts = []
        for i in issues_list[:2]:
            s = (i.get('summary') or i.get('action') or i.get('desc')
                 or i.get('rule') or i.get('source') or '')
            if s:
                parts.append(str(s))
        text = ' • '.join(parts)
        if len(text) > max_chars:
            text = text[:max_chars - 1].rsplit(' ', 1)[0] + '…'
        return _html.escape(text)

    def send_alerts(self, force_test: bool = False, channels: list[str] | None = None) -> list[dict[str, Any]]:
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
        if force_test:
            subj = t("mail_subject_test")
        elif total_issues > 0:
            all_issues = (
                self.health_alerts
                + self.event_alerts
                + self.traffic_alerts
                + self.metric_alerts
            )
            sev = self._highest_severity(all_issues)
            sev_label = t(f"mail_severity_{sev}")
            primary = all_issues[0] if all_issues else {}
            obj = (
                primary.get("source")
                or primary.get("resource_name")
                or primary.get("rule")
                or t("mail_object_default")
            )
            action = primary.get("action") or primary.get("desc") or t("mail_action_default")
            subj = t("mail_subject_structured", severity=sev_label, object=obj, action=action)
        else:
            subj = t("mail_subject", count=total_issues)
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
                logger.warning("Configured alert channel has no registered plugin: {}", channel)
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
                logger.exception("Alert plugin {} failed during send", channel)
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
            logger.warning("Failed to persist dispatch history: {}", exc)
        return results

    def _build_line_message(self, subj: str) -> str:
        """Build a LINE-friendly alert digest aligned to the vendor event content baseline."""
        records: str = t("alert_field_records")

        def section_header(title: str, count: int) -> str:
            return f"\n【{title}】{count} {records}"

        total_issues = (
            len(self.health_alerts)
            + len(self.event_alerts)
            + len(self.traffic_alerts)
            + len(self.metric_alerts)
        )
        # Pre-resolve labels once per call so each section loop stays compact.
        time_lbl       = t("alert_field_time")
        summary_lbl    = t("alert_field_summary")
        event_lbl      = t("alert_field_event")
        created_by_lbl = t("alert_field_created_by")
        target_lbl     = t("alert_field_target")
        action_lbl     = t("alert_field_action")
        src_ip_lbl     = t("alert_field_src_ip")
        changes_lbl    = t("alert_field_changes")
        notif_lbl      = t("alert_field_notifications")
        rec_lbl        = t("alert_field_recommendation")
        cond_lbl       = t("alert_field_condition")
        count_lbl      = t("alert_field_count")
        value_lbl      = t("alert_field_metric_value")
        sev_crit       = t("alert_sev_critical")
        sev_warn       = t("alert_sev_warning")

        health_section_lines = []
        if self.health_alerts:
            health_section_lines.append(section_header(t("alert_sec_health"), len(self.health_alerts)))
            rule_fallback = t("alert_field_health_rule_fallback")
            for idx, alert in enumerate(self.health_alerts[:2], start=1):
                status = self._compact_text(alert.get("status", ""))
                label = sev_crit if status.lower() in {"503", "error", "critical"} else sev_warn
                health_section_lines.append(f"{idx}. [{label}] {self._compact_text(alert.get('rule', rule_fallback))}")
                health_section_lines.append(f"{time_lbl}：{self._compact_text(alert.get('time', ''))}")
                health_section_lines.append(f"{summary_lbl}：{self._compact_text(alert.get('details', ''))}")
                health_section_lines.append("")

        event_section_lines = []
        if self.event_alerts:
            event_section_lines.append(section_header(t("alert_sec_event"), len(self.event_alerts)))
            for idx, alert in enumerate(self._build_all_event_alert_payloads()[:3], start=1):
                first = alert["events"][0] if alert["events"] else {}
                event_section_lines.append(f"{idx}. [{alert['severity_label']}] {alert['rule']}")
                if first.get("event_type"):
                    event_section_lines.append(f"{event_lbl}：{first['event_type']}")
                if first.get("timestamp"):
                    event_section_lines.append(f"{time_lbl}：{self._compact_text(first['timestamp'])[:19]}")
                if first.get("created_by"):
                    event_section_lines.append(f"{created_by_lbl}：{first['created_by']}")
                if first.get("target_name"):
                    event_section_lines.append(f"{target_lbl}：{first['target_name']}")
                if first.get("action", {}).get("label"):
                    event_section_lines.append(f"{action_lbl}：{first['action']['label']}")
                if first.get("action", {}).get("src_ip"):
                    event_section_lines.append(f"{src_ip_lbl}：{first['action']['src_ip']}")
                if first.get("resource_changes_count"):
                    event_section_lines.append(f"{changes_lbl}：{first['resource_changes_count']} {records}")
                if first.get("notifications_count"):
                    event_section_lines.append(f"{notif_lbl}：{first['notifications_count']} {records}")
                if alert.get("desc"):
                    event_section_lines.append(f"{summary_lbl}：{alert['desc']}")
                if first.get("recommendation"):
                    event_section_lines.append(f"{rec_lbl}：{first['recommendation']}")
                if first.get("pce_link"):
                    event_section_lines.append(f"PCE：{first['pce_link']}")
                event_section_lines.append("")
            remaining = len(self.event_alerts) - 3
            if remaining > 0:
                event_section_lines.append(
                    t("alert_field_remaining_events", count=remaining)
                )

        traffic_section_lines = []
        if self.traffic_alerts:
            traffic_section_lines.append(section_header(t("alert_sec_traffic"), len(self.traffic_alerts)))
            traffic_fallback = t("alert_field_traffic_rule_fallback")
            for idx, alert in enumerate(self.traffic_alerts[:2], start=1):
                traffic_section_lines.append(f"{idx}. [{sev_warn}] {self._compact_text(alert.get('rule', traffic_fallback))}")
                if alert.get("criteria"):
                    traffic_section_lines.append(f"{cond_lbl}：{self._compact_text(alert.get('criteria', ''))}")
                if alert.get("count") is not None:
                    traffic_section_lines.append(f"{count_lbl}：{self._compact_text(alert.get('count', ''))}")
                traffic_section_lines.append("")

        metric_section_lines = []
        if self.metric_alerts:
            metric_section_lines.append(section_header(t("alert_sec_metric"), len(self.metric_alerts)))
            metric_fallback = t("alert_field_metric_rule_fallback")
            for idx, alert in enumerate(self.metric_alerts[:2], start=1):
                metric_section_lines.append(f"{idx}. [{sev_warn}] {self._compact_text(alert.get('rule', metric_fallback))}")
                if alert.get("criteria"):
                    metric_section_lines.append(f"{cond_lbl}：{self._compact_text(alert.get('criteria', ''))}")
                if alert.get("count") is not None:
                    metric_section_lines.append(f"{value_lbl}：{self._compact_text(alert.get('count', ''))}")
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

    def _send_line(self, subj: str) -> dict[str, Any]:
        plugin = self._get_output_plugin("line")
        if not plugin:
            return {"channel": "line", "status": "failed", "target": "", "error": "plugin unavailable"}
        return plugin.send(self, subj)

    def _send_webhook(self, subj: str) -> dict[str, Any]:
        plugin = self._get_output_plugin("webhook")
        if not plugin:
            return {"channel": "webhook", "status": "failed", "target": "", "error": "plugin unavailable"}
        return plugin.send(self, subj)

    def _render_vendor_event_detail_html(self, alert: dict, esc: Callable[[Any], str]) -> str:
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

            action_rows_html = "".join(action_rows)
            if not action_rows_html:
                action_rows_html = '<tr><td style="padding:8px 10px;color:#6F7274;">No action details</td></tr>'
            sections.append(
                f"<div style='margin-top:14px;padding:16px;border:1px solid #E6E2D8;border-radius:16px;background:#FFFDFC;'>"
                f"<div style='padding:12px 14px;background:#1A2C32;color:#FFFFFF;border-radius:12px 12px 0 0;font-size:16px;font-weight:800;'>{esc(event.get('event_type', 'event'))}</div>"
                f"<table style='width:100%;border-collapse:collapse;background:#FFFFFF;border:1px solid #E6E2D8;border-top:none;'><tr>{''.join(meta_cells)}</tr></table>"
                f"<div style='margin-top:10px;'>"
                f"<div style='font-size:12px;font-weight:800;color:#24393F;margin-bottom:6px;'>API Action</div>"
                f"<table style='width:100%;border-collapse:collapse;background:#FFFFFF;border:1px solid #E6E2D8;border-radius:10px;overflow:hidden;'>{action_rows_html}</table>"
                f"</div>"
                f"{resource_changes_html}"
                f"{notifications_html}"
                f"{parser_notes}{pce_link}</div>"
            )

        if len(payload["events"]) > 5:
            tail = esc(t("alert_field_event_tail", count=len(payload["events"]) - 5))
            sections.append(
                f"<div style='margin-top:8px;font-size:11px;color:#6F7274;'>{tail}</div>"
            )
        return "".join(sections)

    # ── Event detail renderer ────────────────────────────────────────────────

    @staticmethod
    def _render_event_detail_html(events: list, esc: Callable[[Any], str], parsed_events: list | None = None) -> str:
        """Convert raw Illumio event list into structured human-readable HTML cards."""
        if not events:
            return ""

        # i18n keys for resource types → category labels (lang-aware).
        _RESOURCE_I18N = {
            'sec_rule': 'Security Rule',           # Illumio term, stays English
            'rule_set': 'Ruleset',
            'sec_policy': 'Policy Provision',
            'user':        ('alert_cat_user',),
            'request':     ('alert_cat_request',),
            'authz_csrf':  ('alert_cat_authz_csrf',),
            'agent': 'VEN Agent',
            'agents': 'VEN Agents',
            'workload':    ('alert_cat_workload',),
            'workloads':   ('alert_cat_workloads',),
            'system_task': ('alert_cat_system_task',),
            'lost_agent': 'Lost Agent',
            'cluster':     ('alert_cat_cluster',),
            'api_key': 'API Key',
            'pce_health':  ('alert_cat_pce_health',),
            'label':       ('alert_cat_label',),
            'ip_list':     ('alert_cat_ip_list',),
            'service':     ('alert_cat_service',),
            'ven': 'VEN',
            'pairing_profile':         ('alert_cat_pairing_profile',),
            'authentication_settings': ('alert_cat_authentication_settings',),
            'firewall_settings':       ('alert_cat_firewall_settings',),
        }
        _RESOURCE_LABELS = {
            k: (t(v[0]) if isinstance(v, tuple) else v)
            for k, v in _RESOURCE_I18N.items()
        }

        # verb → (label, fg color, bg color); label resolved via i18n key.
        _VERB_META = {
            'create':                       ('alert_verb_create',                   '#166644', '#D1FAE5'),
            'update':                       ('alert_verb_update',                   '#F97607', '#FFF3CD'),
            'delete':                       ('alert_verb_delete',                   '#BE122F', '#FEE2E2'),
            'sign_in':                      ('alert_verb_sign_in',                  '#325158', '#E0F2FE'),
            'sign_out':                     ('alert_verb_sign_out',                 '#325158', '#E0F2FE'),
            'authentication_failed':        ('alert_verb_authentication_failed',    '#BE122F', '#FEE2E2'),
            'tampering':                    ('alert_verb_tampering',                '#BE122F', '#FEE2E2'),
            'suspend':                      ('alert_verb_suspend',                  '#F97607', '#FFF3CD'),
            'clone_detected':               ('alert_verb_clone_detected',           '#BE122F', '#FEE2E2'),
            'csrf_validation_failure':      ('alert_verb_csrf_validation_failure',  '#BE122F', '#FEE2E2'),
            'unpair':                       ('alert_verb_unpair',                   '#BE122F', '#FEE2E2'),
            'deactivate':                   ('alert_verb_deactivate',               '#F97607', '#FFF3CD'),
            'activate':                     ('alert_verb_activate',                 '#166644', '#D1FAE5'),
            'goodbye':                      ('alert_verb_goodbye',                  '#325158', '#E0F2FE'),
            'refresh_policy':               ('alert_verb_refresh_policy',           '#325158', '#E0F2FE'),
            'agent_missed_heartbeats_check':('alert_verb_missed_heartbeats_check',  '#F97607', '#FFF3CD'),
            'agent_offline_check':          ('alert_verb_offline_check',            '#F97607', '#FFF3CD'),
            'missed_heartbeats_check':      ('alert_verb_missed_heartbeats_check',  '#F97607', '#FFF3CD'),
            'offline_check':                ('alert_verb_offline_check',            '#F97607', '#FFF3CD'),
            'found':                        ('alert_verb_found',                    '#166644', '#D1FAE5'),
            'service_not_available':        ('alert_verb_service_not_available',    '#BE122F', '#FEE2E2'),
            'authenticate':                 ('alert_verb_authenticate',             '#166644', '#D1FAE5'),
            'login_session_terminated':     ('alert_verb_login_session_terminated', '#F97607', '#FFF3CD'),
            'pce_session_terminated':       ('alert_verb_pce_session_terminated',   '#F97607', '#FFF3CD'),
            'authorization_failed':         ('alert_verb_authorization_failed',     '#BE122F', '#FEE2E2'),
            'pce_health':                   ('alert_verb_pce_health',               '#F97607', '#FFF3CD'),
        }
        _VERB_STYLE = {
            verb: (t(key), fg, bg) for verb, (key, fg, bg) in _VERB_META.items()
        }

        _STATUS_LABELS = {
            'success': t('alert_status_success'),
            'failure': t('alert_status_failure'),
            'warn':    t('alert_status_warning'),
            'warning': t('alert_status_warning'),
            'error':   t('alert_status_error'),
            'info':    t('alert_status_info'),
        }
        _FIELD_LABELS = {
            'labels':           t('alert_rfield_labels'),
            'mode':             t('alert_rfield_mode'),
            'name':             t('alert_rfield_name'),
            'enabled':          t('alert_rfield_enabled'),
            'service':          t('alert_rfield_service'),
            'consumers':        t('alert_rfield_consumers'),
            'provision_status': t('alert_rfield_provision_status'),
            'batch_id':         t('alert_rfield_batch_id'),
            'fqdns':            'FQDN',
            'nodes':            t('alert_rfield_nodes'),
            'service_status':   t('alert_rfield_service_status'),
        }

        _CHANGE_NONE = t('alert_change_none')
        _CHANGE_EMPTY = t('alert_change_empty')
        _COL_FIELD  = t('alert_change_col_field')
        _COL_BEFORE = t('alert_change_col_before')
        _COL_AFTER  = t('alert_change_col_after')
        _EVT_FALLBACK = t('alert_verb_event_fallback')

        def _fmt_val(v: Any) -> str:
            if v is None:
                return _CHANGE_NONE
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
                    return _CHANGE_EMPTY
                first = v[0]
                label = (first.get('name') or first.get('value') or str(first))[:40] if isinstance(first, dict) else str(first)[:40]
                suffix = t('alert_change_more_rows', count=len(v) - 1) if len(v) > 1 else ''
                return f"{label}{suffix}"
            return str(v)[:120]

        def _diff_rows(before: dict[str, Any] | None, after: dict[str, Any] | None) -> str:
            if not (before and after):
                return ''
            skip = {'href', 'updated_at', 'created_at', 'created_by', 'update_type'}
            all_keys = sorted(set(list(before.keys()) + list(after.keys())) - skip)
            changes = [(k, before.get(k), after.get(k)) for k in all_keys if before.get(k) != after.get(k)]
            if not changes:
                return ''
            rows = "<table style='width:100%; border-collapse:collapse; margin-top:6px; font-size:10px;'>"
            rows += ("<tr>"
                     f"<th style='text-align:left; padding:3px 6px; background:#24393F; color:#D6D7D7; width:24%;'>{esc(_COL_FIELD)}</th>"
                     f"<th style='text-align:left; padding:3px 6px; background:#24393F; color:#D6D7D7; width:38%;'>{esc(_COL_BEFORE)}</th>"
                     f"<th style='text-align:left; padding:3px 6px; background:#24393F; color:#D6D7D7; width:38%;'>{esc(_COL_AFTER)}</th>"
                     "</tr>")
            for k, bv, av in changes[:5]:
                field_label = _FIELD_LABELS.get(k, k)
                rows += (f"<tr>"
                         f"<td style='padding:3px 6px; border-bottom:1px solid #E3D8C5; color:#989A9B;'>{esc(field_label)}</td>"
                         f"<td style='padding:3px 6px; border-bottom:1px solid #E3D8C5; color:#BE122F; word-break:break-word;'>{esc(_fmt_val(bv))}</td>"
                         f"<td style='padding:3px 6px; border-bottom:1px solid #E3D8C5; color:#166644; word-break:break-word;'>{esc(_fmt_val(av))}</td>"
                         f"</tr>")
            if len(changes) > 5:
                overflow = esc(t('alert_field_changes_overflow', count=len(changes) - 5))
                rows += f"<tr><td colspan='3' style='padding:3px 6px; color:#989A9B;'>{overflow}</td></tr>"
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
            verb_label, verb_color, verb_bg = _VERB_STYLE.get(
                verb_key,
                (verb_key.replace('_', ' ').title() or _EVT_FALLBACK, '#325158', '#E0F2FE'),
            )

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
                extras.append(t('alert_ext_workloads_affected', count=count))
            elif event_type in ('agents.unpair', 'workloads.unpair'):
                count = parsed.get('workloads_affected') or workloads.get('total_affected', 0)
                if count:
                    extras.append(t('alert_ext_workloads_affected', count=count))
                wl_name = parsed.get('target_name') or (after or before).get('hostname') or (after or before).get('name') or ''
                if wl_name:
                    extras.append(t('alert_ext_workload_affected_one', name=wl_name))
            elif parsed.get('resource_name') and parsed.get('resource_name') != parsed.get('target_name'):
                extras.append(t('alert_ext_resource', name=parsed.get('resource_name')))
            elif verb_key == 'create' and after:
                name = after.get('name') or after.get('hostname') or ''
                if name:
                    extras.append(t('alert_ext_resource', name=name))
            if event_type.startswith(('user.', 'request.')) and parsed.get('target_name'):
                extras.append(t('alert_ext_account', name=parsed.get('target_name')))
            elif event_type.startswith(('agent.', 'agents.')) and parsed.get('target_name'):
                extras.append(t('alert_ext_workload_affected_one', name=parsed.get('target_name')))
            if parsed.get('source_ip'):
                extras.append(f"IP: {parsed.get('source_ip')}")
            if parsed.get('action'):
                extras.append(t('alert_ext_action', name=parsed.get('action')))
            if parsed.get('parser_notes'):
                extras.append(t('alert_ext_parser_notes', notes=", ".join(parsed.get('parser_notes'))))  # type: ignore[arg-type]

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
                f"<div style='font-size:11px; color:#313638;'>{esc(t('alert_ext_source', source=actor))}"
            )
            if extras:
                card += f"&nbsp; &bull; &nbsp;{esc(' | '.join(extras))}"
            card += "</div>"
            if diff_html:
                card += diff_html
            card += "</div>"
            cards.append(card)

        if len(events) > 5:
            tail_short = esc(t('alert_field_event_tail_short', count=len(events) - 5))
            cards.append(
                f"<div style='font-size:10px; color:#989A9B; padding:2px 6px;'>{tail_short}</div>"
            )

        return "".join(cards)

    # ── Mail sender ──────────────────────────────────────────────────────────

    def _build_mail_plain(self, subject: str) -> str:
        """Render a plain-text version of the alert email.

        Reuses _build_line_message which already renders line_digest.txt.tmpl
        from the same alert lists, ensuring parity with LINE channel content.
        """
        return self._build_line_message(subject)

    def _build_mail_html(self, subj: str) -> str:
        def esc(text: Any) -> str:
            return html.escape(str(text), quote=True)

        def fmt_multiline(text: Any) -> str:
            normalized = str(text).replace("<br>", "\n")
            return esc(normalized).replace("\n", "<br>")

        generated_at = self._now_str()
        summary_items = [
            (t("alert_sec_health"),  len(self.health_alerts), "#FDECEC", "#BE122F"),
            (t("alert_sec_event"),   len(self.event_alerts),  "#E5F2F9", "#1A2C32"),
            (t("alert_sec_traffic"), len(self.traffic_alerts),"#FFF0E3", "#FF5500"),
            (t("alert_sec_metric"),  len(self.metric_alerts), "#FFF5E8", "#F97607"),
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
        # Severity labels re-resolved here since the HTML body may be built
        # independently of `_severity_label()` callers.
        severity_labels = {
            "crit":     t("alert_sev_critical"),
            "critical": t("alert_sev_critical"),
            "emerg":    t("alert_sev_emerg"),
            "alert":    t("alert_sev_high"),
            "err":      t("alert_sev_error"),
            "error":    t("alert_sev_error"),
            "warn":     t("alert_sev_warning"),
            "warning":  t("alert_sev_warning"),
            "info":     t("alert_sev_info"),
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
        <div style="{section_note_style} border-bottom:1px solid #F0ECE4;">{esc(t('alert_note_health'))}</div>
        <table style="{table_style}">
          <thead>
            <tr>
              <th style="{th_style} width:140px;">{esc(t('health_time'))}</th>
              <th style="{th_style}">{esc(t('health_status'))}</th>
              <th style="{th_style}">{esc(t('health_details'))}</th>
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
        <div style="{section_note_style} border-bottom:1px solid #F0ECE4;">{esc(t('alert_note_event'))}</div>
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
        <div style="{section_note_style} border-bottom:1px solid #F0ECE4;">{esc(t('alert_note_traffic'))}</div>
        <table style="{table_style}">
          <thead>
            <tr>
              <th style="{th_style}">{esc(t('traffic_rule'))}</th>
              <th style="{th_style} width:80px; text-align:center;">{esc(t('traffic_count'))}</th>
              <th style="{th_style}">{esc(t('alert_field_condition'))}</th>
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
        <div style="{section_note_style} border-bottom:1px solid #F0ECE4;">{esc(t('alert_note_metric'))}</div>
        <table style="{table_style}">
          <thead>
            <tr>
              <th style="{th_style}">{esc(t('traffic_rule'))}</th>
              <th style="{th_style} width:100px; text-align:center;">{esc(t('alert_field_metric_value'))}</th>
              <th style="{th_style}">{esc(t('alert_field_condition'))}</th>
            </tr>
          </thead>
          <tbody>
{''.join(rows)}
          </tbody>
        </table>
      </div>
"""

        all_issues = (
            self.health_alerts
            + self.event_alerts
            + self.traffic_alerts
            + self.metric_alerts
        )
        preheader = self._build_preheader_text(all_issues)

        body_html = f"""
<div style="margin-bottom:20px;">
  <div style="background:#FF5500;color:#FFFFFF;display:inline-block;padding:6px 14px;border-radius:999px;font-weight:800;font-size:14px;letter-spacing:0.02em;margin-bottom:8px;">Illumio PCE Ops</div>
  <div style="font-size:12px;color:#6F7274;letter-spacing:0.08em;text-transform:uppercase;margin-bottom:6px;">{esc(t('alert_tpl_summary'))}</div>
  <div style="font-size:12px;color:#8C8E8F;margin-bottom:8px;">{esc(t('alert_tpl_aggregated_blurb'))}</div>
  <div style="font-size:12px;color:#6F7274;margin-bottom:4px;">{esc(t('alert_tpl_generated_at'))}: <strong>{esc(generated_at)}</strong></div>
</div>
{summary_html}
{health_section_html}
{event_section_html}
{traffic_section_html}
{metric_section_html}
<div style="margin-top:32px;padding:20px 0 4px;border-top:1px solid #ECE7DD;text-align:center;">
  <p style="color:#8C8E8F;font-size:11px;line-height:1.8;margin:0;">
    {esc(t('alert_tpl_auto_generated'))}<br>
    {esc(t('alert_tpl_act_per_runbook'))}
  </p>
</div>
"""

        return render_alert_template(
            "mail_wrapper.html.tmpl",
            title=esc(subj),
            body_html=body_html,
            preheader=preheader,
        )

    def _send_mail(self, subj: str) -> dict[str, Any]:
        plugin = self._get_output_plugin("mail")
        if not plugin:
            return {"channel": "mail", "status": "failed", "target": "", "error": "plugin unavailable"}
        return plugin.send(self, subj)

    def send_scheduled_report_email(self, subject: str, html_body: str, attachment_paths: list[str] | None = None,
                                     custom_recipients: list[str] | None = None) -> bool:
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
        import io, zipfile
        from email.mime.base import MIMEBase
        from email import encoders

        _MAX_ATTACH_BYTES = 10 * 1024 * 1024  # 10 MB per attachment

        cfg = self.cm.config["email"]
        recipients = (
            [r.strip() for r in custom_recipients if r.strip()]
            if custom_recipients
            else cfg.get("recipients", [])
        )
        if not recipients:
            logger.warning(t('no_recipients'))
            return False

        # Zip non-.zip files in-memory; skip files that exceed the size limit
        attach_parts = []
        skipped = []
        for path in (attachment_paths or []):
            if not path or not os.path.exists(path):
                continue
            fname = os.path.basename(path)
            try:
                if fname.lower().endswith('.zip'):
                    with open(path, 'rb') as f:
                        data = f.read()
                    attach_name = fname
                else:
                    buf = io.BytesIO()
                    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
                        zf.write(path, fname)
                    data = buf.getvalue()
                    attach_name = fname + '.zip'

                if len(data) > _MAX_ATTACH_BYTES:
                    skipped.append(fname)
                    logger.warning(
                        f"[Email] Skipping {fname}: "
                        f"{len(data) / 1024 / 1024:.1f} MB exceeds "
                        f"{_MAX_ATTACH_BYTES // 1024 // 1024} MB limit"
                    )
                    continue

                part = MIMEBase("application", "zip")
                part.set_payload(data)
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f'attachment; filename="{attach_name}"')
                attach_parts.append(part)
            except (IOError, OSError) as e:
                logger.warning(f"Warning: could not attach {path}: {e}")

        if skipped:
            limit_mb = _MAX_ATTACH_BYTES // 1024 // 1024
            warning_text = t("rpt_email_attach_too_large",
                             limit_mb=limit_mb, files=", ".join(skipped))
            warning_html = (
                "<div style='background:#FFF3CD;border:1px solid #F0AD4E;border-radius:8px;"
                "padding:12px;margin:8px 16px;font-family:Arial,sans-serif;"
                f"font-size:12px;color:#856404;'>⚠ {html.escape(warning_text)}</div>"
            )
            html_body = html_body.replace('</body></html>', warning_html + '</body></html>', 1)

        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"] = cfg["sender"]
        msg["To"] = ",".join(recipients)
        msg.attach(MIMEText(html_body, "html"))
        for part in attach_parts:
            msg.attach(part)

        try:
            smtp_conf = self.cm.config.get("smtp", {})
            host = smtp_conf.get("host", "localhost")
            port = int(smtp_conf.get("port", 25))
            s = smtplib.SMTP(host, port, timeout=30)
            s.ehlo()
            if smtp_conf.get("enable_tls"):
                import ssl as _ssl
                _tls_ctx = _ssl.create_default_context()
                s.starttls(context=_tls_ctx)
                s.ehlo()
            if smtp_conf.get("enable_auth"):
                s.login(smtp_conf.get("user"), smtp_conf.get("password"))
            s.sendmail(cfg["sender"], recipients, msg.as_string())
            s.quit()
            logger.info(t('mail_sent', host=host, port=port))
            return True
        except Exception as e:
            logger.error(t('mail_failed', error=e))
            return False

    def send_report_email(self, subject: str, html_body: str, attachment_path: str | None = None) -> bool:
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
            logger.warning(t('no_recipients'))
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
                logger.warning(f"Warning: could not attach file {attachment_path}: {e}")

        try:
            smtp_conf = self.cm.config.get("smtp", {})
            host = smtp_conf.get("host", "localhost")
            port = int(smtp_conf.get("port", 25))
            s = smtplib.SMTP(host, port, timeout=30)
            s.ehlo()
            if smtp_conf.get("enable_tls"):
                import ssl as _ssl
                _tls_ctx = _ssl.create_default_context()
                s.starttls(context=_tls_ctx)
                s.ehlo()
            if smtp_conf.get("enable_auth"):
                s.login(smtp_conf.get("user"), smtp_conf.get("password"))
            s.sendmail(cfg["sender"], cfg["recipients"], msg.as_string())
            s.quit()
            logger.info(t('mail_sent', host=host, port=port))
            return True
        except Exception as e:
            logger.error(t('mail_failed', error=e))
            return False
