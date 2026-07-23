from __future__ import annotations

import datetime
import functools
import json
import html
from typing import Any, Callable
from loguru import logger
import os
import re
import smtplib
import socket
import weakref
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from src.alerts import build_output_plugin, get_output_registry, render_alert_template
from src.events import normalize_event, persist_dispatch_results
from src.events.poller import format_utc
from src.i18n import t
from src.state_store import update_state_file

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(PKG_DIR)
STATE_FILE = os.path.join(ROOT_DIR, "logs", "state.json")

# D.3 signal palette — used by _render_cta for cross-surface consistent CTA color.
SIGNAL_HEX = {
    'success': '#16a34a',
    'warning': '#d97706',
    'danger':  '#dc2626',
    'info':    '#2563eb',
}

# Alert output plugins are cached per ConfigManager (not per Reporter): the daemon
# builds a fresh Reporter every monitor cycle but reuses one long-lived
# ConfigManager, so stateful plugins (e.g. LineAlertPlugin's 3-strike cooldown)
# must hang off cm to keep their counters across dispatches. Keyed weakly so the
# cache does not pin a ConfigManager alive.
_PLUGIN_CACHE: "weakref.WeakKeyDictionary[Any, dict[str, Any]]" = weakref.WeakKeyDictionary()

class Reporter:
    def __init__(self, config_manager: Any) -> None:
        self.cm = config_manager
        self._lang: str = (config_manager.config.get("settings", {}).get("language", "en") or "en")
        # Per-dispatch language override. send_alerts() sets this (try/finally)
        # so the channel builders — which the alert plugins invoke without a
        # lang argument — still render the recipient-visible content in the
        # language requested for that dispatch instead of the process-global one.
        self._dispatch_lang: str | None = None
        self.health_alerts: list[dict[str, Any]] = []
        self.event_alerts: list[dict[str, Any]] = []
        self.traffic_alerts: list[dict[str, Any]] = []
        self.metric_alerts: list[dict[str, Any]] = []
        self.last_dispatch_results: list[dict[str, Any]] = []

    @staticmethod
    def _lang_t(lang: str) -> Callable[..., str]:
        """Return ``t()`` pre-bound to ``lang``.

        A content builder binds the module-level ``t`` to its dispatch language
        via ``t = self._lang_t(_lang)``; every existing ``t(...)`` call in that
        builder then localizes to ``lang`` (instead of the process-global
        language) with no per-call-site changes.
        """
        return functools.partial(t, lang=lang)

    def _resolve_tz(self) -> tuple[datetime.tzinfo, str]:
        """Return (tzinfo, label) for the configured timezone (settings.timezone)."""
        from src.tz_utils import resolve_tz
        tz_str = self.cm.config.get('settings', {}).get('timezone', 'local')
        tz = resolve_tz(tz_str)
        offset_s = datetime.datetime.now(tz).strftime('%z')
        sign_ch = offset_s[0]; hh = offset_s[1:3]; mm = offset_s[3:5]
        label = f"UTC{sign_ch}{hh}:{mm}" if mm != '00' else f"UTC{sign_ch}{hh}"
        return tz, label

    def _now_str(self) -> str:
        """Return current time formatted in the configured timezone."""
        try:
            tz, label = self._resolve_tz()
            return datetime.datetime.now(tz).strftime('%Y-%m-%d %H:%M') + f' ({label})'
        except Exception:
            return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')  # intentional fallback: return UTC time if timezone offset calculation fails

    def _fmt_event_ts(self, raw: str) -> str:
        """Format a PCE event timestamp (UTC ISO-8601, e.g. '2026-06-19T13:17:43.552Z')
        in the configured timezone. Returns the original string unchanged if it
        can't be parsed, so non-timestamp values pass through harmlessly."""
        if not raw or not isinstance(raw, str):
            return raw or ""
        try:
            dt = datetime.datetime.fromisoformat(raw.strip().replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            tz, label = self._resolve_tz()
            return dt.astimezone(tz).strftime('%Y-%m-%d %H:%M') + f' ({label})'
        except Exception:
            return raw

    def add_health_alert(self, alert: dict[str, Any]) -> None:
        self.health_alerts.append(alert)

    def add_event_alert(self, alert: dict[str, Any]) -> None:
        # Map the PCE event_type to its runbook *response* (remediation steps) so
        # the event-alert render surfaces it. The runbook_url links were dropped
        # (the vendored docs.illumio.com deep-links are stale); the response text
        # is the durable, version-independent value. An explicit runbook_response
        # set by the caller always wins.
        if not alert.get("runbook_response"):
            resp = self._runbook_response_for_alert(alert)
            if resp:
                alert["runbook_response"] = resp
        self.event_alerts.append(alert)

    @staticmethod
    def _runbook_response_for_alert(alert: dict) -> str:
        """Resolve the runbook remediation response from the alert's event_type ('' if none)."""
        events = alert.get("raw_data") or []
        event_type = ""
        if events and isinstance(events[0], dict):
            event_type = str(events[0].get("event_type") or "")
        if not event_type:
            return ""
        from src.events.runbooks import runbook_for
        return str((runbook_for(event_type) or {}).get("response") or "")

    def add_traffic_alert(self, alert: dict[str, Any]) -> None:
        self.traffic_alerts.append(alert)

    def add_metric_alert(self, alert: dict[str, Any]) -> None:
        self.metric_alerts.append(alert)

    def _get_output_plugin(self, name: str) -> Any:
        # Reuse a cached plugin instance keyed by the long-lived ConfigManager so
        # stateful plugins keep their state across dispatch cycles (see
        # _PLUGIN_CACHE). A per-Reporter or per-call instance would reset
        # LineAlertPlugin's cooldown counters on every dispatch.
        try:
            cache = _PLUGIN_CACHE.get(self.cm)
            if cache is None:
                cache = {}
                _PLUGIN_CACHE[self.cm] = cache
        except TypeError:
            cache = None  # cm not hashable/weak-referenceable: fall back to per-call build
        if cache is not None and name in cache:
            return cache[name]
        try:
            plugin = build_output_plugin(name, self.cm)
        except KeyError:
            logger.warning("Unknown alert output plugin requested: {}", name)
            return None
        if cache is not None:
            cache[name] = plugin
        return plugin

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
        "notice":   "alert_sev_notice",
        "debug":    "alert_sev_debug",
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
        # Best-practice rules whose recommendation was previously falling back
        # to alert_rec_default — see Telegram report 2026-05-08:
        "lost_agent.found":                         "alert_rec_lost_agent_found",
        "user.sign_in":                             "alert_rec_login_failed",
        "user.login":                               "alert_rec_login_failed",
        "agent.refresh_policy":                     "alert_rec_policy_fail",
        "rule_set.create":                          "alert_rec_ruleset_change",
        "rule_set.update":                          "alert_rec_ruleset_change",
        "rule_set.delete":                          "alert_rec_ruleset_change",
        "sec_rule.create":                          "alert_rec_sec_rule_change",
        "sec_rule.update":                          "alert_rec_sec_rule_change",
        "sec_rule.delete":                          "alert_rec_sec_rule_change",
        "api_key.create":                           "alert_rec_api_key_change",
        "api_key.delete":                           "alert_rec_api_key_change",
        "workloads.unpair":                         "alert_rec_bulk_unpair",
        "agents.unpair":                            "alert_rec_bulk_unpair",
        "authentication_settings.update":           "alert_rec_auth_settings_change",
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
        base = self._console_base(base)
        if "/orgs/" in href:
            _, _, tail = href.partition("/orgs/")
            _, _, href = tail.partition("/")
            href = "/" + href if href else ""
        return f"{base}/#{href}" if href else base

    @staticmethod
    def _console_base(api_base: str) -> str:
        """Web-console base for the event deep-link.

        On-prem the API host also serves the web console, so the API base is
        correct. Illumio SaaS serves the API from a regional SCP cluster
        (e.g. *.ap-scp1.illumio.com) but the web console is the region-agnostic
        console.illum.io — a different host — so the API base would 404. Map any
        SaaS SCP API host to console.illum.io.
        """
        from urllib.parse import urlparse
        host = (urlparse(api_base).hostname or "").lower()
        if host.endswith("illumio.com") and "scp" in host:
            return "https://console.illum.io"
        return api_base

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

    def _build_teams_card(self, subj: str, *, lang: str | None = None) -> dict:
        """Build a Power-Automate Adaptive Card (v1.4) POST body for Teams.

        Mirrors _build_webhook_payload's template-driven assembly but emits the
        `attachments`-wrapped Adaptive Card shape Power Automate Workflows
        expect. Pure data assembly (no I/O). Values go into TextBlock/FactSet
        elements as plain text; everything is injected via *_json tokens so the
        rendered template is valid JSON.
        """
        _lang = lang or self._dispatch_lang or self._lang
        t = self._lang_t(_lang)
        total_issues = (
            len(self.health_alerts) + len(self.event_alerts)
            + len(self.traffic_alerts) + len(self.metric_alerts)
        )

        facts = [
            {"title": t("alert_sec_health"), "value": str(len(self.health_alerts))},
            {"title": t("alert_sec_event"), "value": str(len(self.event_alerts))},
            {"title": t("alert_sec_traffic"), "value": str(len(self.traffic_alerts))},
            {"title": t("alert_sec_metric"), "value": str(len(self.metric_alerts))},
            {"title": t("alert_field_time"), "value": self._now_str()},
        ]

        # Compact one-line summaries of the first few issues (plain text).
        lines: list[str] = []
        for alert in self.health_alerts[:5]:
            lines.append(
                f"• {self._compact_text(alert.get('rule', ''))}"
                f" — {self._compact_text(alert.get('details', ''))}"
            )
        for payload in self._build_all_event_alert_payloads()[:5]:
            lines.append(f"• {self._compact_text(payload.get('rule', ''))}")
        summary = "\n".join(lines) if lines else t("mail_subject", count=total_issues)

        actions_fragment = ""
        # Resolve the deep-link base the same way the mail CTAs do
        # (web_gui.public_url, else stripped PCE URL). The old flat 'gui_base_url'
        # config key is defined nowhere in production, so the Teams action never
        # rendered even when web_gui.public_url was configured.
        base_url = self._gui_base_url()
        if base_url:
            action = {
                "type": "Action.OpenUrl",
                "title": t("alert_tpl_see_web_for_details"),
                "url": base_url,
            }
            actions_fragment = ',\n        "actions": ' + json.dumps([action], ensure_ascii=False)

        rendered = render_alert_template(
            "teams_card.json.tmpl",
            title_json=json.dumps(t("alert_tpl_teams_title"), ensure_ascii=False),
            subject_json=json.dumps(subj, ensure_ascii=False),
            facts_json=json.dumps(facts, ensure_ascii=False),
            summary_json=json.dumps(summary, ensure_ascii=False),
            actions_fragment=actions_fragment,
        )
        return json.loads(rendered)

    def generate_pretty_snapshot_html(self, data_list: list[dict[str, Any]], *, lang: str | None = None) -> str:
        import re
        _lang = lang or self._dispatch_lang or self._lang
        t = self._lang_t(_lang)

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
                    f"<span style='display:inline-block; background:#fafafa; color:#6f6f6f; padding:2px 5px; border-radius:4px; font-size:10px; margin:2px 3px 0 0; border:1px solid #e5e5e5;'>{esc(l.get('key'))}:{esc(l.get('value'))}</span>"
                    for l in labels
                ]
            )
            proc_label = esc(t("alert_snap_process"))
            user_label = esc(t("alert_snap_user"))
            proc_line = (
                f"<div style='font-size:10px; color:#0a0a0a; margin-top:4px;'><strong>{proc_label}:</strong> {esc(proc)}</div>"
                if proc
                else ""
            )
            user_line = (
                f"<div style='font-size:10px; color:#6f6f6f;'><strong>{user_label}:</strong> {esc(user)}</div>"
                if user
                else ""
            )
            return (
                f"<strong style='color:#0a0a0a;'>{esc(name)}</strong><br><small style='color:#6f6f6f;'>{esc(ip)}</small>"
                f"{proc_line}{user_line}<div style='margin-top:2px;'>{badges}</div>"
            )

        table_html = "<table style='width:100%; border-collapse:collapse; font-family:Inter,-apple-system,BlinkMacSystemFont,\"Segoe UI\",Roboto,Arial,sans-serif; font-size:12px; border:1px solid #e5e5e5;'>"
        table_html += "<tr style='background-color:#fafafa; color:#0a0a0a; text-align:left; border-bottom:1px solid #e5e5e5;'>"
        table_html += f"<th style='padding:10px 8px; border:1px solid #e5e5e5; width:96px; font-size:11px; text-transform:uppercase; letter-spacing:0.06em; color:#6f6f6f;'>{snapshot_labels['value']}</th>"
        table_html += f"<th style='padding:10px 8px; border:1px solid #e5e5e5; width:132px; font-size:11px; text-transform:uppercase; letter-spacing:0.06em; color:#6f6f6f;'>{snapshot_labels['first_seen']} /<br>{snapshot_labels['last_seen']}</th>"
        table_html += f"<th style='padding:10px 6px; border:1px solid #e5e5e5; width:72px; text-align:center; font-size:11px; text-transform:uppercase; letter-spacing:0.06em; color:#6f6f6f;'>{snapshot_labels['direction']}</th>"
        table_html += f"<th style='padding:10px 8px; border:1px solid #e5e5e5; font-size:11px; text-transform:uppercase; letter-spacing:0.06em; color:#6f6f6f;'>{snapshot_labels['source']}</th>"
        table_html += f"<th style='padding:10px 8px; border:1px solid #e5e5e5; font-size:11px; text-transform:uppercase; letter-spacing:0.06em; color:#6f6f6f;'>{snapshot_labels['destination']}</th>"
        table_html += f"<th style='padding:10px 8px; border:1px solid #e5e5e5; width:88px; font-size:11px; text-transform:uppercase; letter-spacing:0.06em; color:#6f6f6f;'>{snapshot_labels['service']}</th>"
        table_html += f"<th style='padding:10px 8px; border:1px solid #e5e5e5; width:74px; text-align:center; font-size:11px; text-transform:uppercase; letter-spacing:0.06em; color:#6f6f6f;'>{snapshot_labels['connections']}</th>"
        table_html += f"<th style='padding:10px 8px; border:1px solid #e5e5e5; width:88px; font-size:11px; text-transform:uppercase; letter-spacing:0.06em; color:#6f6f6f;'>{snapshot_labels['decision']}</th>"
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
                t("alert_snap_dir_inbound")
                if d.get("flow_direction") == "inbound"
                else t("alert_snap_dir_outbound")
                if d.get("flow_direction") == "outbound"
                else d.get("flow_direction", "-")
            )
            svc = d.get("service", {})
            port = d.get("dst_port") or svc.get("port") or "-"
            proto = d.get("proto") or svc.get("proto") or "-"
            proto_str = "TCP" if proto == 6 else "UDP" if proto == 17 else str(proto)
            count = d.get("num_connections") or d.get("count") or 1
            pd_map = {
                "blocked": f"<span style='display:inline-block; color:#6f6f6f; background:#fafafa; padding:2px 8px; border-radius:4px; font-weight:600; font-size:10px; border:1px solid #e5e5e5;'><span style='display:inline-block;width:6px;height:6px;background:#dc2626;border-radius:50%;margin-right:4px;vertical-align:middle;'></span>{t('alert_snap_decision_blocked')}</span>",
                "potentially_blocked": f"<span style='display:inline-block; color:#6f6f6f; background:#fafafa; padding:2px 8px; border-radius:4px; font-weight:600; font-size:10px; border:1px solid #e5e5e5;'><span style='display:inline-block;width:6px;height:6px;background:#d97706;border-radius:50%;margin-right:4px;vertical-align:middle;'></span>{t('alert_snap_decision_potential')}</span>",
                "allowed": f"<span style='display:inline-block; color:#6f6f6f; background:#fafafa; padding:2px 8px; border-radius:4px; font-weight:600; font-size:10px; border:1px solid #e5e5e5;'><span style='display:inline-block;width:6px;height:6px;background:#16a34a;border-radius:50%;margin-right:4px;vertical-align:middle;'></span>{t('alert_snap_decision_allowed')}</span>",
            }
            decision = str(d.get("policy_decision")).lower()
            decision_html = pd_map.get(decision, esc(decision))
            table_html += f"<tr style='background:{row_bg};'>"
            table_html += f"<td style='padding:10px 8px; border:1px solid #e5e5e5; font-weight:600; color:#0a0a0a;'>{val_str}</td>"
            table_html += f"<td style='padding:10px 8px; border:1px solid #e5e5e5; white-space:nowrap; font-size:10px; color:#6f6f6f;'>{t_first}<br>{t_last}</td>"
            table_html += f"<td style='padding:10px 6px; border:1px solid #e5e5e5; text-align:center; font-weight:600; color:#0a0a0a;'>{esc(direction)}</td>"
            table_html += f"<td style='padding:10px; border:1px solid #e5e5e5; word-break:break-word;'>{actor_view(d, True)}</td>"
            table_html += f"<td style='padding:10px; border:1px solid #e5e5e5; word-break:break-word;'>{actor_view(d, False)}</td>"
            table_html += f"<td style='padding:10px 6px; border:1px solid #e5e5e5; text-align:center; color:#0a0a0a;'>{esc(port)} / {esc(proto_str)}</td>"
            table_html += f"<td style='padding:10px 8px; border:1px solid #e5e5e5; text-align:center; color:#0a0a0a;'><strong>{esc(count)}</strong></td>"
            table_html += f"<td style='padding:10px 8px; border:1px solid #e5e5e5;'>{decision_html}</td>"
            table_html += "</tr>"

        table_html += "</table>"
        return table_html

    @staticmethod
    def _highest_severity(issues: list[dict]) -> str:
        """Pick highest severity from a list of issue dicts; returns 'critical', 'warning', or 'info'."""
        # Map raw severity values to canonical three-level labels used by mail_severity_* i18n keys
        _rank = {'critical': 3, 'crit': 3, 'emerg': 3, 'alert': 2, 'err': 2, 'error': 2, 'warning': 2, 'warn': 2, 'info': 1, 'notice': 1, 'debug': 1}
        _canonical = {'critical': 'critical', 'crit': 'critical', 'emerg': 'critical',
                      'alert': 'warning', 'err': 'warning', 'error': 'warning', 'warning': 'warning', 'warn': 'warning',
                      'info': 'info', 'notice': 'info', 'debug': 'info'}
        cur = 0
        out = 'info'
        for issue in issues:
            sev = (issue.get('severity') or 'info').lower()
            rank = _rank.get(sev, 0)
            if rank > cur:
                cur = rank
                out = _canonical.get(sev, 'info')
        return out

    def _gui_base_url(self) -> str:
        """Return the PCE web console base URL for CTA deep links.

        Resolution order:
        1. web_gui.public_url (explicit GUI base, no stripping needed)
        2. active PCE API URL with /api/v2 (and v1) suffixes stripped

        Returns '' if no URL is configured — callers must treat '' as "skip CTA".
        """
        web_gui_url = str(self.cm.config.get("web_gui", {}).get("public_url", "")).strip()
        if web_gui_url:
            return web_gui_url.rstrip("/")
        raw = self._active_pce_url().rstrip("/")
        if not raw:
            return ""
        for suffix in ("/api/v2", "/api/v1", "/api"):
            if raw.endswith(suffix):
                raw = raw[: -len(suffix)]
                break
        return raw

    @staticmethod
    def _render_cta(label: str, url: str, severity: str = 'info') -> str:
        """Render a bulletproof CTA button (MSO/VML wrap + table fallback).

        Outlook (Word HTML engine) receives a v:roundrect via the MSO
        conditional comment; all other clients receive the table-based
        fallback. Both branches use the same SIGNAL_HEX-derived background
        color so severity coloring stays consistent.

        Both label and url are HTML-escaped inside this helper.
        Callers must urlencode any dynamic id values in url query strings
        before passing url here.

        severity: one of 'success', 'warning', 'danger', 'info' (default 'info').
        Picks bg color from SIGNAL_HEX dict.
        """
        import html as _html
        label_html = _html.escape(label)
        url_html = _html.escape(url, quote=True)
        return (
            # MSO (Outlook) — VML rounded rectangle
            f'<!--[if mso]>'
            f'<v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" '
            f'xmlns:w="urn:schemas-microsoft-com:office:word" '
            f'href="{url_html}" '
            f'style="height:40px;v-text-anchor:middle;width:200px;" '
            f'arcsize="10%" stroke="t" strokecolor="#e5e5e5" fillcolor="#ffffff">'
            f'<w:anchorlock/>'
            f'<center style="color:#0a0a0a;font-family:Arial,sans-serif;'
            f'font-size:14px;font-weight:600;">{label_html}</center>'
            f'</v:roundrect>'
            f'<![endif]-->'
            # Non-MSO fallback — table-based
            f'<!--[if !mso]><!-- -->'
            f'<table role="presentation" border="0" cellpadding="0" cellspacing="0" '
            f'style="margin:16px 0;">'
            f'<tr><td bgcolor="#ffffff" style="border-radius:4px;background:#ffffff;border:1px solid #e5e5e5;">'
            f'<a href="{url_html}" '
            f'style="display:inline-block;padding:10px 20px;color:#0a0a0a;'
            f'text-decoration:none;font-weight:600;font-family:Arial,sans-serif;">'
            f'{label_html}</a>'
            f'</td></tr></table>'
            f'<!--<![endif]-->'
        )

    @staticmethod
    def _render_severity_badge(severity: str) -> str:
        """Render an inline severity badge — small colored pill with a 4-letter
        label (CRIT / HIGH / WARN / OK / INFO).

        Uses inline `bgcolor` attr + `style=background:` dual-write so Outlook
        renders the color correctly. Defaults to 'INFO' on unknown input.
        """
        import html as _html
        sev_norm = (severity or '').lower().strip()
        mapping = {
            'critical': ('CRIT', SIGNAL_HEX['danger']),
            'crit':     ('CRIT', SIGNAL_HEX['danger']),
            'danger':   ('CRIT', SIGNAL_HEX['danger']),
            'high':     ('HIGH', SIGNAL_HEX['danger']),
            'emerg':    ('CRIT', SIGNAL_HEX['danger']),
            'alert':    ('HIGH', SIGNAL_HEX['danger']),
            'err':      ('HIGH', SIGNAL_HEX['danger']),
            'error':    ('HIGH', SIGNAL_HEX['danger']),
            'warning':  ('WARN', SIGNAL_HEX['warning']),
            'warn':     ('WARN', SIGNAL_HEX['warning']),
            'medium':   ('WARN', SIGNAL_HEX['warning']),
            'success':  ('OK',   SIGNAL_HEX['success']),
            'ok':       ('OK',   SIGNAL_HEX['success']),
            'info':     ('INFO', SIGNAL_HEX['info']),
            'low':      ('INFO', SIGNAL_HEX['info']),
        }
        label, dot_color = mapping.get(sev_norm, mapping['info'])
        label_html = _html.escape(label)
        return (
            f'<span style="display:inline-block;padding:2px 6px;margin-right:6px;'
            f'background:#fafafa;color:#6f6f6f;font-size:11px;font-weight:600;'
            f'font-family:Arial,sans-serif;border-radius:3px;letter-spacing:0.5px;'
            f'border:1px solid #e5e5e5;">'
            f'<span style="display:inline-block;width:6px;height:6px;background:{dot_color};'
            f'border-radius:50%;margin-right:5px;vertical-align:middle;"></span>'
            f'{label_html}</span>'
        )

    @staticmethod
    def _render_runbook_link(runbook_url: str | None) -> str:
        """Render an inline runbook link, or empty string if no URL provided.

        Returns a small info-blue anchor styled to sit inline next to issue
        summary text. URL is HTML-escaped (quote=True) to prevent injection.
        """
        if not runbook_url:
            return ''
        import html as _html
        url_html = _html.escape(str(runbook_url), quote=True)
        return (
            f' <a href="{url_html}" '
            f'style="color:#2563eb;text-decoration:underline;font-size:12px;'
            f'font-family:Arial,sans-serif;">Runbook ↗</a>'
        )

    @staticmethod
    def _render_runbook_response(response: str | None) -> str:
        """Render the runbook remediation steps as an inline note, or '' if none.

        Multi-line text is HTML-escaped and newlines become <br>; styled as a
        left-bordered info note to sit under the event-alert summary.
        """
        if not response:
            return ''
        import html as _html
        body = _html.escape(str(response).strip()).replace("\n", "<br>")
        return (
            '<div style="margin-top:6px;padding:6px 10px;border-left:3px solid #2563eb;'
            'background:#f0f6ff;font-size:12px;line-height:1.5;color:#1e3a5f;'
            f'font-family:Arial,sans-serif;"><strong>Runbook</strong><br>{body}</div>'
        )

    @staticmethod
    def _build_preheader_text(issues_list: list[dict[str, Any]], max_chars: int = 90) -> str:
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

    ALERT_DLQ_MAX_ATTEMPTS = 3
    # 全 skipped（無可用通道）時 DLQ 會逐 cycle 累積新告警——單 bucket 上限
    # 防無界成長，超出裁掉最舊（2026-07-24 審查 B1 配套）
    ALERT_DLQ_BUCKET_CAP = 100

    def _pop_alert_dlq(self) -> list[dict[str, Any]]:
        """Atomically take all pending DLQ entries from the state file."""
        popped: list[dict[str, Any]] = []

        def _take(existing: dict) -> dict:
            nonlocal popped
            popped = list(existing.get("alert_dlq", []))
            out = dict(existing)
            out["alert_dlq"] = []
            return out

        try:
            update_state_file(STATE_FILE, _take)
        except Exception as exc:
            logger.warning("Failed to read alert DLQ: {}", exc)
            return []
        return popped

    def _push_alert_dlq(self, buckets: dict[str, list], attempts: int, first_failed_at: str) -> None:
        capped = {}
        for name, items in buckets.items():
            if len(items) > self.ALERT_DLQ_BUCKET_CAP:
                logger.warning(
                    "Alert DLQ: {} bucket exceeds cap ({} > {}), keeping newest",
                    name, len(items), self.ALERT_DLQ_BUCKET_CAP,
                )
                items = items[-self.ALERT_DLQ_BUCKET_CAP:]
            capped[name] = items
        entry = {"buckets": capped, "attempts": attempts, "first_failed_at": first_failed_at}

        def _append(existing: dict) -> dict:
            out = dict(existing)
            out["alert_dlq"] = list(existing.get("alert_dlq", [])) + [entry]
            return out

        try:
            update_state_file(STATE_FILE, _append)
        except Exception as exc:
            logger.error("Failed to persist alert DLQ (alerts lost): {}", exc)

    def send_alerts(self, force_test: bool = False, channels: list[str] | None = None, *, lang: str | None = None) -> list[dict[str, Any]]:
        """派送四個 bucket 到全部啟用通道。

        DLQ 為 **all-or-nothing**：任一通道成功即視為已遞送、不重試其餘
        失敗通道（部分失敗只記 dispatch_history）；全數未遞送才整批入列
        重試（真嘗試過才消耗 3 次額度）。per-channel 重試是刻意不做的
        取捨——見 docs/guide/monitoring-alerts.md（2026-07-24 審查 B3）。
        """
        _lang = lang or self._lang
        # Bind the subject's t() to the dispatch language; _dispatch_lang (set
        # around the plugin loop below) carries the same language into the
        # body builders the plugins invoke without a lang argument.
        t = self._lang_t(_lang)
        replayed_attempts = 0
        replayed_first_failed_at = ""
        _replayed_attempt_values: list[int] = []
        if not force_test:
            for entry in self._pop_alert_dlq():
                buckets = entry.get("buckets", {})
                self.health_alerts.extend(buckets.get("health", []))
                self.event_alerts.extend(buckets.get("event", []))
                self.traffic_alerts.extend(buckets.get("traffic", []))
                self.metric_alerts.extend(buckets.get("metric", []))
                _replayed_attempt_values.append(int(entry.get("attempts", 0)))
                replayed_first_failed_at = replayed_first_failed_at or entry.get("first_failed_at", "")
            # 多筆合併取 min：以最年輕條目計次，避免較新告警被提早丟棄
            # （2026-07-24 審查 B4；常態單筆時 min == 該筆值）
            replayed_attempts = min(_replayed_attempt_values, default=0)
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

        # Localize event timestamps to the configured timezone (settings.timezone)
        # once, before any channel renders them. PCE returns event times in UTC;
        # without this the alert shows raw UTC instead of the operator's local time.
        for _bucket in (self.health_alerts, self.event_alerts, self.traffic_alerts, self.metric_alerts):
            for _a in _bucket:
                if isinstance(_a, dict) and _a.get("time"):
                    _a["time"] = self._fmt_event_ts(_a["time"])

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
            # Lead the subject with the human-meaningful rule/event name (e.g.
            # "Agent Suspended") rather than the raw event actor + API action, so
            # the recipient sees WHAT happened at a glance. Actor/source becomes
            # the secondary detail.
            obj = (
                primary.get("rule")
                or primary.get("source")
                or primary.get("resource_name")
                or t("mail_object_default")
            )
            detail = (
                primary.get("source")
                or primary.get("desc")
                or primary.get("action")
                or t("mail_action_default")
            )
            if detail == obj:
                detail = primary.get("desc") or primary.get("action") or t("mail_action_default")
            subj = t("mail_subject_structured", severity=sev_label, object=obj, action=detail)
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

        # Publish the dispatch language so the plugins' calls into the content
        # builders (which pass no lang) still render the body in _lang.
        prev_dispatch_lang = self._dispatch_lang
        self._dispatch_lang = _lang
        try:
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
                    results.append(plugin.send(self, subj, lang=_lang))
                except Exception as exc:
                    logger.exception("Alert plugin {} failed during send", channel)
                    results.append({
                        "channel": channel,
                        "status": "failed",
                        "target": "",
                        "error": str(exc),
                    })
        finally:
            self._dispatch_lang = prev_dispatch_lang

        self.last_dispatch_results = results
        counts = {
            "health": len(self.health_alerts),
            "events": len(self.event_alerts),
            "traffic": len(self.traffic_alerts),
            "metrics": len(self.metric_alerts),
        }

        attempted = [r for r in results if r.get("status") != "skipped"]
        delivered = any(r.get("status") == "success" for r in results)
        if not delivered and not force_test:
            # 全 skipped（設定缺失/通道冷卻）也要入列——抽乾後不回寫等於
            # 永久遺失；但只有真的嘗試過遞送才消耗重試額度
            # （2026-07-24 審查 B1/B2）
            attempts = replayed_attempts + (1 if attempted else 0)
            first_failed_at = replayed_first_failed_at or format_utc(
                datetime.datetime.now(datetime.timezone.utc)
            )
            buckets = {
                "health": list(self.health_alerts),
                "event": list(self.event_alerts),
                "traffic": list(self.traffic_alerts),
                "metric": list(self.metric_alerts),
            }
            if any(buckets.values()):
                if attempted and attempts >= self.ALERT_DLQ_MAX_ATTEMPTS:
                    logger.error(
                        "Alert DLQ: dropping {} alert bucket(s) after {} failed dispatch attempts",
                        sum(len(v) for v in buckets.values()), attempts,
                    )
                    results.append({"channel": "dlq", "status": "dropped", "target": "",
                                    "error": f"dropped after {attempts} attempts"})
                else:
                    logger.warning(
                        "Alert DLQ: no delivery ({} attempted), queuing for retry (attempt {})",
                        len(attempted), attempts,
                    )
                    self._push_alert_dlq(buckets, attempts, first_failed_at)

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

    _LINE_MESSAGE_CAP = 4500  # LINE push API 實際上限 ~5000，留 buffer（spec §C）

    def _build_line_message(self, subj: str, *, lang: str | None = None,
                            cap: "int | None" = _LINE_MESSAGE_CAP) -> str:
        """Build a LINE-friendly alert digest aligned to the vendor event content baseline."""
        _lang = lang or self._dispatch_lang or self._lang
        t = self._lang_t(_lang)
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
            if len(self.health_alerts) > 2:
                health_section_lines.append(t('line_section_more', more=len(self.health_alerts) - 2))

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
            if len(self.traffic_alerts) > 2:
                traffic_section_lines.append(t('line_section_more', more=len(self.traffic_alerts) - 2))

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
            if len(self.metric_alerts) > 2:
                metric_section_lines.append(t('line_section_more', more=len(self.metric_alerts) - 2))

        message = render_alert_template(
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

        if cap is not None and len(message) > cap:
            footer = t("line_message_truncated")
            message = message[: cap - len(footer) - 1].rstrip() + "\n" + footer
        return message

    def _build_telegram_message(self, subj: str, *, lang: str | None = None) -> str:
        """Build an HTML-formatted alert digest for Telegram (parse_mode=HTML).

        Mirrors _build_line_message's section structure but produces Telegram-flavored
        HTML — <b>, <code>, <a href> — and escapes every dynamic value with
        html.escape(value, quote=False). Output is capped at 3500 chars (Telegram's
        hard limit is 4096) with a translated footer announcing how many entries got
        truncated.
        """
        _lang = lang or self._dispatch_lang or self._lang
        t = self._lang_t(_lang)

        def esc(value: object) -> str:
            return html.escape(self._compact_text(value), quote=False)

        records: str = t("alert_field_records")

        def section_header(title: str, count: int) -> str:
            return f"\n<b>{html.escape(title)}</b> · {count} {records}"

        total_issues = (
            len(self.health_alerts) + len(self.event_alerts)
            + len(self.traffic_alerts) + len(self.metric_alerts)
        )
        time_lbl = t("alert_field_time")
        summary_lbl = t("alert_field_summary")
        sev_crit = t("alert_sev_critical")
        sev_warn = t("alert_sev_warning")

        kept_total = 0

        health_lines = []
        if self.health_alerts:
            health_lines.append(section_header(t("alert_sec_health"), len(self.health_alerts)))
            for idx, alert in enumerate(self.health_alerts, start=1):
                status = self._compact_text(alert.get("status", ""))
                label = sev_crit if status.lower() in {"503", "error", "critical"} else sev_warn
                health_lines.append(f"{idx}. [<b>{html.escape(label)}</b>] {esc(alert.get('rule', t('alert_field_health_rule_fallback')))}")
                health_lines.append(f"{time_lbl}：{esc(alert.get('time', ''))}")
                health_lines.append(f"{summary_lbl}：{esc(alert.get('details', ''))}")
                health_lines.append("")
                kept_total += 1

        event_lines = []
        if self.event_alerts:
            event_lines.append(section_header(t("alert_sec_event"), len(self.event_alerts)))
            for payload in self._build_all_event_alert_payloads():
                first = payload["events"][0] if payload["events"] else {}
                event_lines.append(f"[<b>{html.escape(payload['severity_label'])}</b>] {esc(payload['rule'])}")
                if first.get("event_type"):
                    event_lines.append(f"<code>{html.escape(first['event_type'])}</code>")
                if first.get("pce_link"):
                    event_lines.append(f"<a href=\"{html.escape(first['pce_link'], quote=True)}\">PCE</a>")
                event_lines.append("")
                kept_total += 1

        traffic_lines = []
        if self.traffic_alerts:
            traffic_lines.append(section_header(t("alert_sec_traffic"), len(self.traffic_alerts)))
            for alert in self.traffic_alerts:
                traffic_lines.append(f"• {esc(alert.get('summary', ''))}")
                kept_total += 1
            traffic_lines.append("")

        metric_lines = []
        if self.metric_alerts:
            metric_lines.append(section_header(t("alert_sec_metric"), len(self.metric_alerts)))
            for alert in self.metric_alerts:
                metric_lines.append(f"• {esc(alert.get('summary', ''))}")
                kept_total += 1
            metric_lines.append("")

        body = render_alert_template(
            "telegram_digest.html.tmpl",
            subject=html.escape(subj),
            generated_at=html.escape(self._now_str()),
            total_issues=total_issues,
            health_count=len(self.health_alerts),
            event_count=len(self.event_alerts),
            traffic_count=len(self.traffic_alerts),
            metric_count=len(self.metric_alerts),
            health_section="\n".join(health_lines),
            event_section="\n".join(event_lines),
            traffic_section="\n".join(traffic_lines),
            metric_section="\n".join(metric_lines),
        )

        if len(body) > 3500:
            # Cut on a line boundary so we never split an HTML tag or entity:
            # Telegram sendMessage(parse_mode=HTML) rejects unbalanced/partial
            # markup with HTTP 400 and drops the whole digest. Every digest line
            # is self-contained (its <b>/<code>/<a> open and close on the same
            # line), so truncating at the last newline keeps all markup balanced.
            cut = body[:3300]
            nl = cut.rfind("\n")
            if nl != -1:
                cut = cut[:nl]
            cut = cut.rstrip()
            more = total_issues - kept_total
            footer = t("telegram_truncated_footer").format(more=max(more, 0))
            body = f"{cut}\n\n{footer}"
        return body

    def _send_line(self, subj: str, *, lang: str | None = None) -> dict[str, Any]:
        plugin = self._get_output_plugin("line")
        if not plugin:
            return {"channel": "line", "status": "failed", "target": "", "error": "plugin unavailable"}
        return plugin.send(self, subj, lang=lang or self._lang)

    def _send_webhook(self, subj: str, *, lang: str | None = None) -> dict[str, Any]:
        plugin = self._get_output_plugin("webhook")
        if not plugin:
            return {"channel": "webhook", "status": "failed", "target": "", "error": "plugin unavailable"}
        return plugin.send(self, subj, lang=lang or self._lang)

    def _render_vendor_event_detail_html(self, alert: dict, esc: Callable[[Any], str], *, lang: str | None = None) -> str:
        _lang = lang or self._dispatch_lang or self._lang
        t = self._lang_t(_lang)
        payload = self._build_event_alert_payload(alert)
        if not payload["events"]:
            return ""

        sections = []
        for event in payload["events"][:5]:
            action = event.get("action", {})
            meta_cells = []
            for label, value in (
                (t("alert_field_time"), event.get("timestamp")),
                (t("alert_field_status"), event.get("status_label")),
                (t("alert_field_severity"), event.get("severity_label")),
                (t("alert_field_created_by"), event.get("created_by")),
            ):
                if value:
                    meta_cells.append(
                        f"<td style='padding:8px 10px;border:1px solid #e5e5e5;font-size:12px;vertical-align:top;'><strong style='display:block;color:#6f6f6f;font-size:10px;letter-spacing:0.06em;text-transform:uppercase;'>{label}</strong>{esc(value)}</td>"
                    )

            action_rows = []
            for label, value in (
                (t("alert_field_endpoint"), " ".join(part for part in [action.get("api_method"), action.get("api_endpoint")] if part).strip()),
                (t("alert_field_src_ip"), action.get("src_ip")),
                (t("alert_field_http_status"), action.get("http_status_code")),
                (t("alert_field_target"), event.get("target_name")),
                (t("alert_field_resource"), event.get("resource_name")),
            ):
                if value:
                    action_rows.append(
                        f"<tr><td style='padding:6px 8px;color:#6f6f6f;width:26%;border-bottom:1px solid #f0f0f0;'>{label}</td><td style='padding:6px 8px;border-bottom:1px solid #f0f0f0;word-break:break-word;'>{esc(value)}</td></tr>"
                    )
            if isinstance(action.get("info"), dict):
                for key, value in list(action["info"].items())[:4]:
                    action_rows.append(
                        f"<tr><td style='padding:6px 8px;color:#6f6f6f;width:26%;border-bottom:1px solid #f0f0f0;'>{esc(key)}</td><td style='padding:6px 8px;border-bottom:1px solid #f0f0f0;word-break:break-word;'>{esc(value)}</td></tr>"
                    )

            change_blocks = []
            for change in event.get("resource_changes", [])[:3]:
                diff_rows = []
                for diff in change.get("changes", [])[:5]:
                    diff_rows.append(
                        f"<tr><td style='padding:4px 6px;border-bottom:1px solid #f0f0f0;color:#6f6f6f;'>{esc(diff.get('field', ''))}</td><td style='padding:4px 6px;border-bottom:1px solid #f0f0f0;color:#dc2626;'>{esc(diff.get('before', '')) or '—'}</td><td style='padding:4px 6px;border-bottom:1px solid #f0f0f0;color:#16a34a;'>{esc(diff.get('after', '')) or '—'}</td></tr>"
                    )
                diff_table = (
                    "<table style='width:100%;border-collapse:collapse;font-size:11px;margin-top:6px;'>"
                    f"<tr><th style='text-align:left;padding:4px 6px;background:#fafafa;'>{t('alert_change_col_field')}</th><th style='text-align:left;padding:4px 6px;background:#fafafa;'>{t('alert_change_col_before')}</th><th style='text-align:left;padding:4px 6px;background:#fafafa;'>{t('alert_change_col_after')}</th></tr>"
                    + "".join(diff_rows)
                    + "</table>"
                ) if diff_rows else ""
                change_blocks.append(
                    f"<div style='padding:10px 12px;border:1px solid #e5e5e5;border-radius:6px;background:#FFFFFF;margin-top:8px;'>"
                    f"<div style='font-size:12px;font-weight:600;color:#0a0a0a;'>{esc(change.get('change_type', 'update').upper())} {esc(change.get('resource_type', 'resource'))}</div>"
                    f"<div style='font-size:12px;color:#6f6f6f;margin-top:4px;'>{esc(change.get('resource_name', ''))}</div>"
                    f"{diff_table}</div>"
                )

            notification_blocks = []
            for notification in event.get("notifications", [])[:3]:
                notification_blocks.append(
                    f"<div style='padding:10px 12px;border:1px solid #e5e5e5;border-radius:6px;background:#FFFFFF;margin-top:8px;'>"
                    f"<div style='font-size:12px;font-weight:600;color:#0a0a0a;'>{esc(notification.get('notification_type', 'notification'))}</div>"
                    f"<div style='font-size:12px;color:#6f6f6f;margin-top:4px;word-break:break-word;'>{esc(notification.get('summary', ''))}</div>"
                    f"</div>"
                )

            parser_notes = ""
            if event.get("parser_notes"):
                parser_notes = f"<div style='margin-top:10px;font-size:11px;color:#7c3aed;'>{t('alert_field_parser_notes')}: {esc(', '.join(event.get('parser_notes', [])))}</div>"

            pce_link = ""
            if event.get("pce_link"):
                pce_link = (
                    f"<div style='margin-top:12px;'><a href='{esc(event['pce_link'])}' "
                    f"style='display:inline-block;background:#ffffff;color:#0a0a0a;padding:8px 14px;border-radius:6px;text-decoration:none;font-size:12px;font-weight:600;border:1px solid #e5e5e5;'>{t('alert_field_view_on_pce')}</a></div>"
                )
            resource_changes_html = ""
            if event.get("resource_changes_count"):
                resource_changes_html = (
                    f"<div style='margin-top:12px;'><div style='font-size:12px;font-weight:600;color:#0a0a0a;'>"
                    f"{t('alert_field_resource_changes')} ({event.get('resource_changes_count', 0)})</div>{''.join(change_blocks)}</div>"
                )
            notifications_html = ""
            if event.get("notifications_count"):
                notifications_html = (
                    f"<div style='margin-top:12px;'><div style='font-size:12px;font-weight:600;color:#0a0a0a;'>"
                    f"{t('alert_field_notifications')} ({event.get('notifications_count', 0)})</div>{''.join(notification_blocks)}</div>"
                )

            action_rows_html = "".join(action_rows)
            if not action_rows_html:
                action_rows_html = f'<tr><td style="padding:8px 10px;color:#6f6f6f;">{t("alert_field_no_action_details")}</td></tr>'
            sections.append(
                f"<div style='margin-top:14px;padding:16px;border:1px solid #e5e5e5;border-radius:8px;background:#FFFFFF;'>"
                f"<div style='padding:12px 14px;background:#fafafa;color:#0a0a0a;border-radius:6px 6px 0 0;font-size:14px;font-weight:600;border-left:3px solid #2563eb;'>{esc(event.get('event_type', 'event'))}</div>"
                f"<table style='width:100%;border-collapse:collapse;background:#FFFFFF;border:1px solid #e5e5e5;border-top:none;'><tr>{''.join(meta_cells)}</tr></table>"
                f"<div style='margin-top:10px;'>"
                f"<div style='font-size:12px;font-weight:600;color:#0a0a0a;margin-bottom:6px;'>{t('alert_field_api_action')}</div>"
                f"<table style='width:100%;border-collapse:collapse;background:#FFFFFF;border:1px solid #e5e5e5;border-radius:6px;overflow:hidden;'>{action_rows_html}</table>"
                f"</div>"
                f"{resource_changes_html}"
                f"{notifications_html}"
                f"{parser_notes}{pce_link}</div>"
            )

        if len(payload["events"]) > 5:
            tail = esc(t("alert_field_event_tail", count=len(payload["events"]) - 5))
            sections.append(
                f"<div style='margin-top:8px;font-size:11px;color:#6f6f6f;'>{tail}</div>"
            )
        return "".join(sections)

    # ── Mail sender ──────────────────────────────────────────────────────────

    def _build_mail_plain(self, subject: str, *, lang: str | None = None) -> str:
        """Render a plain-text version of the alert email.

        Reuses _build_line_message which already renders line_digest.txt.tmpl
        from the same alert lists, ensuring parity with LINE channel content.
        Email 無長度上限，cap=None 解除 LINE 的 4500 字截斷
        （2026-07-24 審查 B5）。
        """
        return self._build_line_message(
            subject, lang=lang or self._dispatch_lang or self._lang, cap=None)

    def _build_mail_html(self, subj: str, *, lang: str | None = None) -> str:
        _lang = lang or self._dispatch_lang or self._lang
        t = self._lang_t(_lang)

        def esc(text: Any) -> str:
            return html.escape(str(text), quote=True)

        def fmt_multiline(text: Any) -> str:
            normalized = str(text).replace("<br>", "\n")
            return esc(normalized).replace("\n", "<br>")

        generated_at = self._now_str()
        summary_items = [
            (t("alert_sec_health"),  len(self.health_alerts), "#dc2626"),
            (t("alert_sec_event"),   len(self.event_alerts),  "#2563eb"),
            (t("alert_sec_traffic"), len(self.traffic_alerts),"#d97706"),
            (t("alert_sec_metric"),  len(self.metric_alerts), "#d97706"),
        ]
        summary_html = "".join(
            f"""
        <div style="display:inline-block; width:44%; min-width:170px; margin:0 12px 12px 0; vertical-align:top; background:#ffffff; border:1px solid #e5e5e5; border-left:3px solid {stripe}; border-radius:6px; padding:16px 18px; box-sizing:border-box;">
          <div style="font-size:11px; letter-spacing:0.08em; text-transform:uppercase; color:#6f6f6f; margin-bottom:8px;">{label}</div>
          <div style="font-size:28px; line-height:1; font-weight:600; color:#0a0a0a;">{count}</div>
        </div>
"""
            for label, count, stripe in summary_items
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
        section_style = "margin-top:28px; border:1px solid #e5e5e5; border-radius:8px; overflow:hidden; background:#FFFFFF; box-shadow:0 1px 2px rgba(0,0,0,0.04);"
        header_style = "padding:16px 20px; font-size:14px; font-weight:600; font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif; letter-spacing:0.02em;"
        table_style = "width:100%; border-collapse:collapse; table-layout:fixed;"
        th_style = "text-align:left; padding:14px 14px; background:#fafafa; border-bottom:1px solid #e5e5e5; font-size:11px; color:#6f6f6f; font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif; text-transform:uppercase; letter-spacing:0.08em;"
        td_style = "padding:14px 14px; border-bottom:1px solid #f0f0f0; font-size:13px; color:#0a0a0a; vertical-align:top; word-break:break-word; font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif; line-height:1.55;"
        section_note_style = "padding:0 20px 18px 20px; font-size:12px; line-height:1.6; color:#6f6f6f; background:#FFFFFF;"

        gui_base = self._gui_base_url()
        if not gui_base:
            logger.debug("_build_mail_html: no gui_base_url resolved — CTAs suppressed")

        health_section_html = ""
        if self.health_alerts:
            rows = []
            for alert in self.health_alerts:
                sev_badge = self._render_severity_badge(alert.get('severity', alert.get('status', 'info')))
                runbook = self._render_runbook_link(alert.get('runbook_url'))
                rows.append(
                    f"""
            <tr>
              <td style="{td_style} font-size:11px; color:#6f6f6f;">{esc(alert.get('time',''))}</td>
              <td style="{td_style} font-weight:600; color:#0a0a0a;">{sev_badge}{esc(alert.get('status',''))}{runbook}</td>
              <td style="{td_style}">{fmt_multiline(alert.get('details',''))}</td>
            </tr>
"""
                )
            health_cta = (
                self._render_cta(t('mail_cta_view_health'), f'{gui_base}/dashboard?tab=health', severity='success')
                if gui_base else ""
            )
            health_section_html = f"""
      <div style="{section_style}">
        <div style="{header_style} background:#fafafa; border:1px solid #e5e5e5; border-left:3px solid #dc2626; color:#0a0a0a;">{esc(t('health_alerts_header'))}</div>
        <div style="{section_note_style} border-bottom:1px solid #f0f0f0;">{esc(t('alert_note_health'))}</div>
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
        {f'<div style="padding:0 20px 16px 20px;">{health_cta}</div>' if health_cta else ''}
      </div>
"""

        event_section_html = ""
        if self.event_alerts:
            rows = []
            for alert in self.event_alerts:
                sev_badge = self._render_severity_badge(alert.get('severity', 'info'))
                runbook = self._render_runbook_link(alert.get('runbook_url'))
                runbook_resp = self._render_runbook_response(alert.get('runbook_response'))
                row_html = f"""
            <tr>
              <td style="{td_style} font-size:11px; color:#6f6f6f;">{esc(alert.get('time',''))}</td>
              <td style="{td_style}"><strong>{esc(alert.get('rule',''))}</strong>{runbook}<br><small style="color:#6f6f6f;">{esc(alert.get('desc',''))}</small>{runbook_resp}</td>
              <td style="{td_style} text-align:center;">{sev_badge}<small>({esc(alert.get('count',0))})</small></td>
              <td style="{td_style}">{esc(alert.get('source',''))}</td>
            </tr>
"""
                if alert.get("raw_data"):
                    detail_html = self._render_vendor_event_detail_html(alert, esc, lang=_lang)
                    row_html += f"<tr><td colspan='4' style='padding:14px 14px 16px; background:#fafafa; border-bottom:1px solid #e5e5e5;'>{detail_html}</td></tr>"
                rows.append(row_html)
            event_cta = (
                self._render_cta(t('mail_cta_view_event'), f'{gui_base}/dashboard?tab=events', severity='danger')
                if gui_base else ""
            )
            event_section_html = f"""
      <div style="{section_style}">
        <div style="{header_style} background:#fafafa; border:1px solid #e5e5e5; border-left:3px solid #2563eb; color:#0a0a0a;">{esc(t('security_events_header'))}</div>
        <div style="{section_note_style} border-bottom:1px solid #f0f0f0;">{esc(t('alert_note_event'))}</div>
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
        {f'<div style="padding:0 20px 16px 20px;">{event_cta}</div>' if event_cta else ''}
      </div>
"""

        traffic_section_html = ""
        if self.traffic_alerts:
            rows = []
            for alert in self.traffic_alerts:
                sev_badge = self._render_severity_badge(alert.get('severity', 'warning'))
                runbook = self._render_runbook_link(alert.get('runbook_url'))
                rows.append(
                    f"""
            <tr>
              <td style="{td_style} font-weight:600; color:#0a0a0a;">{sev_badge}{esc(alert.get('rule',''))}{runbook}</td>
              <td style="{td_style} text-align:center; font-weight:600; font-size:16px; color:#0a0a0a;">{esc(alert.get('count',0))}</td>
              <td style="{td_style} font-size:11px; color:#6f6f6f;">{esc(alert.get('criteria',''))}</td>
            </tr>
            <tr>
              <td colspan="3" style="{td_style} background:#fafafa; font-size:12px; padding:16px;">
                <div style="margin-bottom:10px; padding:12px 14px; border:1px solid #e5e5e5; border-radius:6px; background:#FFFFFF;"><strong style="color:#0a0a0a;">{esc(t('traffic_toptalkers'))}:</strong> {fmt_multiline(alert.get('details',''))}</div>
                {self.generate_pretty_snapshot_html(alert.get('raw_data', []), lang=_lang)}
              </td>
            </tr>
"""
                )
            traffic_cta = (
                self._render_cta(t('mail_cta_view_traffic'), f'{gui_base}/traffic', severity='warning')
                if gui_base else ""
            )
            traffic_section_html = f"""
      <div style="{section_style}">
        <div style="{header_style} background:#fafafa; border:1px solid #e5e5e5; border-left:3px solid #d97706; color:#0a0a0a;">{esc(t('traffic_alerts_header'))}</div>
        <div style="{section_note_style} border-bottom:1px solid #f0f0f0;">{esc(t('alert_note_traffic'))}</div>
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
        {f'<div style="padding:0 20px 16px 20px;">{traffic_cta}</div>' if traffic_cta else ''}
      </div>
"""

        metric_section_html = ""
        if self.metric_alerts:
            rows = []
            for alert in self.metric_alerts:
                sev_badge = self._render_severity_badge(alert.get('severity', 'info'))
                runbook = self._render_runbook_link(alert.get('runbook_url'))
                rows.append(
                    f"""
            <tr>
              <td style="{td_style} font-weight:600; color:#0a0a0a;">{sev_badge}{esc(alert.get('rule',''))}{runbook}</td>
              <td style="{td_style} text-align:center; font-weight:600; font-size:16px; color:#0a0a0a;">{esc(alert.get('count',0))}</td>
              <td style="{td_style} font-size:11px; color:#6f6f6f;">{esc(alert.get('criteria',''))}</td>
            </tr>
            <tr>
              <td colspan="3" style="{td_style} background:#fafafa; font-size:12px; padding:16px;">
                <div style="margin-bottom:10px; padding:12px 14px; border:1px solid #e5e5e5; border-radius:6px; background:#FFFFFF;"><strong style="color:#0a0a0a;">{esc(t('traffic_toptalkers'))}:</strong> {fmt_multiline(alert.get('details',''))}</div>
                {self.generate_pretty_snapshot_html(alert.get('raw_data', []), lang=_lang)}
              </td>
            </tr>
"""
                )
            metric_cta = (
                self._render_cta(t('mail_cta_view_metric'), f'{gui_base}/dashboard?tab=metrics', severity='info')
                if gui_base else ""
            )
            metric_section_html = f"""
      <div style="{section_style}">
        <div style="{header_style} background:#fafafa; border:1px solid #e5e5e5; border-left:3px solid #d97706; color:#0a0a0a;">{esc(t('metric_alerts_header'))}</div>
        <div style="{section_note_style} border-bottom:1px solid #f0f0f0;">{esc(t('alert_note_metric'))}</div>
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
        {f'<div style="padding:0 20px 16px 20px;">{metric_cta}</div>' if metric_cta else ''}
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
  <div style="background:#FF5500;color:#FFFFFF;display:inline-block;padding:6px 14px;border-radius:999px;font-weight:600;font-size:14px;letter-spacing:0.02em;margin-bottom:8px;">Illumio PCE Ops</div>
  <div style="font-size:12px;color:#6f6f6f;letter-spacing:0.08em;text-transform:uppercase;margin-bottom:6px;">{esc(t('alert_tpl_summary'))}</div>
  <div style="font-size:12px;color:#a8a8a8;margin-bottom:8px;">{esc(t('alert_tpl_aggregated_blurb'))}</div>
  <div style="font-size:12px;color:#6f6f6f;margin-bottom:4px;">{esc(t('alert_tpl_generated_at'))}: <strong>{esc(generated_at)}</strong></div>
</div>
{summary_html}
{health_section_html}
{event_section_html}
{traffic_section_html}
{metric_section_html}
<div style="margin-top:32px;padding:20px 0 4px;border-top:1px solid #e5e5e5;text-align:center;">
  <p style="color:#a8a8a8;font-size:11px;line-height:1.8;margin:0;">
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

    def _send_mail(self, subj: str, *, lang: str | None = None) -> dict[str, Any]:
        plugin = self._get_output_plugin("mail")
        if not plugin:
            return {"channel": "mail", "status": "failed", "target": "", "error": "plugin unavailable"}
        return plugin.send(self, subj, lang=lang or self._lang)

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

        plain_body = self._build_line_message(subject)

        if attach_parts:
            msg = MIMEMultipart('mixed')
            body = MIMEMultipart('alternative')
            body.attach(MIMEText(plain_body, 'plain', _charset='utf-8'))
            body.attach(MIMEText(html_body, 'html', _charset='utf-8'))
            msg.attach(body)
            for part in attach_parts:
                msg.attach(part)
        else:
            msg = MIMEMultipart('alternative')
            msg.attach(MIMEText(plain_body, 'plain', _charset='utf-8'))
            msg.attach(MIMEText(html_body, 'html', _charset='utf-8'))

        msg["Subject"] = subject
        msg["From"] = cfg["sender"]
        msg["To"] = ",".join(recipients)

        try:
            smtp_conf = self.cm.config.get("smtp", {})
            host = smtp_conf.get("host", "localhost")
            port = int(smtp_conf.get("port", 25))
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.ehlo()
                if smtp_conf.get("enable_tls"):
                    import ssl as _ssl
                    _tls_ctx = _ssl.create_default_context()
                    s.starttls(context=_tls_ctx)
                    s.ehlo()
                if smtp_conf.get("enable_auth"):
                    s.login(smtp_conf.get("user"), smtp_conf.get("password"))
                s.sendmail(cfg["sender"], recipients, msg.as_string())
            logger.info(t('mail_sent', host=host, port=port))
            return True
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP auth failed (config error, not retrying): {e}")
            return False
        except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, ConnectionError, OSError, socket.timeout) as e:
            logger.warning(f"SMTP transient failure: {e}")
            return False
        except smtplib.SMTPException as e:
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

        import re as _re
        plain_body = _re.sub(r'<[^>]+>', '', html_body)
        plain_body = _re.sub(r'\s+', ' ', plain_body).strip()

        if attachment_path and os.path.exists(attachment_path):
            msg = MIMEMultipart('mixed')
            body = MIMEMultipart('alternative')
            body.attach(MIMEText(plain_body, 'plain', _charset='utf-8'))
            body.attach(MIMEText(html_body, 'html', _charset='utf-8'))
            msg.attach(body)
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
        else:
            msg = MIMEMultipart('alternative')
            msg.attach(MIMEText(plain_body, 'plain', _charset='utf-8'))
            msg.attach(MIMEText(html_body, 'html', _charset='utf-8'))

        msg["Subject"] = subject
        msg["From"] = cfg["sender"]
        msg["To"] = ",".join(cfg["recipients"])

        try:
            smtp_conf = self.cm.config.get("smtp", {})
            host = smtp_conf.get("host", "localhost")
            port = int(smtp_conf.get("port", 25))
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.ehlo()
                if smtp_conf.get("enable_tls"):
                    import ssl as _ssl
                    _tls_ctx = _ssl.create_default_context()
                    s.starttls(context=_tls_ctx)
                    s.ehlo()
                if smtp_conf.get("enable_auth"):
                    s.login(smtp_conf.get("user"), smtp_conf.get("password"))
                s.sendmail(cfg["sender"], cfg["recipients"], msg.as_string())
            logger.info(t('mail_sent', host=host, port=port))
            return True
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP auth failed (config error, not retrying): {e}")
            return False
        except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, ConnectionError, OSError, socket.timeout) as e:
            logger.warning(f"SMTP transient failure: {e}")
            return False
        except smtplib.SMTPException as e:
            logger.error(t('mail_failed', error=e))
            return False
