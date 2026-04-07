import datetime
import email
from email import policy
from pathlib import Path

from src.config import ConfigManager
from src.i18n import set_language, t
from src.reporter import Reporter
from src.settings import FULL_EVENT_CATALOG
import src.reporter as reporter_module


CATEGORY_LABELS = {
    "General": "一般事件",
    "Agent Health": "Agent 健康",
    "Agent Security": "Agent 安全",
    "User Access": "使用者存取",
    "Agent Health Detail": "Agent 健康細節",
    "Auth & API": "認證與 API",
    "Policy": "政策",
    "System": "系統",
}


def _severity_for_event(event_type: str) -> str:
    if event_type in {
        "agent.tampering",
        "agent.clone_detected",
        "request.authentication_failed",
        "request.authorization_failed",
    }:
        return "error"
    if event_type in {
        "agent.suspend",
        "system_task.agent_missed_heartbeats_check",
        "system_task.agent_offline_check",
        "lost_agent.found",
        "agent.service_not_available",
        "pce_health",
    }:
        return "warn"
    return "info"


def _status_for_event(event_type: str) -> str:
    if event_type in {
        "request.authentication_failed",
        "request.authorization_failed",
        "agent.suspend",
        "agent.tampering",
        "agent.clone_detected",
        "pce_health",
    }:
        return "failure"
    return "success"


def _sample_event(event_type: str, idx: int) -> dict:
    now = datetime.datetime(2026, 4, 8, 10, 30) + datetime.timedelta(minutes=idx * 3)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    base = {
        "event_type": event_type,
        "timestamp": timestamp,
        "status": _status_for_event(event_type),
        "severity": _severity_for_event(event_type),
        "src_ip": f"10.10.{idx % 20}.{20 + idx}",
        "created_by": {
            "user": {"username": "harry"},
            "agent": {"hostname": f"ven-core-{idx:02d}.lab.local"},
        },
        "resource": {},
    }

    if event_type.startswith(("user.", "request.")):
        base["resource"] = {"user": {"username": f"user{idx:02d}@lab.local"}}
    elif event_type.startswith(("agent.", "agents.")):
        base["resource"] = {"agent": {"hostname": f"ven-app-{idx:02d}.lab.local"}}
        base["resource_changes"] = [
            {"field": "mode", "before": "建置", "after": "閒置"},
            {"field": "labels", "before": "env:dev", "after": "env:prod"},
        ]
    elif event_type.startswith("rule_set."):
        base["resource_changes"] = [
            {"field": "name", "before": "Legacy Ruleset", "after": "CoreServices"},
            {"field": "enabled", "before": "停用", "after": "啟用"},
        ]
    elif event_type.startswith("sec_rule."):
        base["resource_changes"] = [
            {"field": "service", "before": "TCP/22", "after": "TCP/443"},
            {"field": "consumers", "before": "role:Web", "after": "role:Web,app:Portal"},
        ]
    elif event_type == "sec_policy.create":
        base["workloads_affected"] = {"total_affected": 37}
        base["resource_changes"] = [
            {"field": "provision_status", "before": "草稿", "after": "啟用"},
            {"field": "batch_id", "before": "N/A", "after": "prov-20260408-01"},
        ]
    elif event_type == "cluster.update":
        base["resource_changes"] = [
            {"field": "fqdns", "before": "pce-old.lab.local", "after": "pce.lab.local"},
            {"field": "nodes", "before": 2, "after": 3},
        ]
    elif event_type == "pce_health":
        base["resource_changes"] = [
            {"field": "service_status", "before": "警告", "after": "正常"},
        ]

    return base


def _sample_flows(metric_mode: str) -> list:
    rows = []
    for idx, decision in enumerate(["allowed", "potentially_blocked", "blocked"], start=1):
        value = f"{2.4 * idx:.2f} Gbps" if metric_mode == "bandwidth" else f"{idx * 4200}"
        rows.append(
            {
                "_metric_fmt": value,
                "timestamp": f"2026-04-08T10:{10 + idx:02d}:00Z",
                "timestamp_range": {
                    "first_detected": f"2026-04-08T09:{50 + idx:02d}:00Z",
                    "last_detected": f"2026-04-08T10:{10 + idx:02d}:00Z",
                },
                "flow_direction": "outbound" if idx % 2 else "inbound",
                "source": {
                    "name": f"src-app-{idx}",
                    "ip": f"10.0.0.{idx}",
                    "labels": [
                        {"key": "app", "value": "CoreServices"},
                        {"key": "env", "value": "VMware"},
                    ],
                    "process": "python",
                    "user": "svc_app",
                },
                "destination": {
                    "name": f"dst-db-{idx}",
                    "ip": f"172.16.15.{100 + idx}",
                    "labels": [
                        {"key": "role", "value": "DB"},
                        {"key": "loc", "value": "TP"},
                    ],
                },
                "src": {
                    "ip": f"10.0.0.{idx}",
                    "workload": {"name": f"src-app-{idx}", "labels": []},
                },
                "dst": {
                    "ip": f"172.16.15.{100 + idx}",
                    "workload": {"name": f"dst-db-{idx}", "labels": []},
                },
                "service": {
                    "port": 443 if idx == 1 else 8443 if idx == 2 else 22,
                    "proto": 6,
                    "process_name": "nginx",
                    "user_name": "www-data",
                },
                "dst_port": 443 if idx == 1 else 8443 if idx == 2 else 22,
                "proto": 6,
                "num_connections": idx * 120,
                "count": idx * 120,
                "policy_decision": decision,
            }
        )
    return rows


def _build_reporter(cm: ConfigManager) -> Reporter:
    reporter = Reporter(cm)
    reporter.add_health_alert(
        {
            "time": "2026-04-08 09:15:00",
            "rule": "PCE 健康檢查",
            "status": "503",
            "details": "API 健康檢查於 /health 端點回傳 503。",
        }
    )
    reporter.add_health_alert(
        {
            "time": "2026-04-08 09:25:00",
            "rule": "PCE 健康檢查",
            "status": "警告",
            "details": "叢集節點延遲高於預期門檻。",
        }
    )

    idx = 0
    for category, entries in FULL_EVENT_CATALOG.items():
        for event_type, desc_key in entries.items():
            if event_type == "*":
                continue
            idx += 1
            event = _sample_event(event_type, idx)
            source = f"harry | {event.get('src_ip', '')}".strip(" |")
            reporter.add_event_alert(
                {
                    "time": event["timestamp"].replace("T", " ").replace("Z", ""),
                    "rule": f"[{CATEGORY_LABELS.get(category, category)}] {t(desc_key)}",
                    "desc": f"樣本事件類型：{event_type}",
                    "severity": event["severity"],
                    "count": 1 + (idx % 3),
                    "source": source,
                    "raw_data": [event],
                }
            )

    traffic_flows = _sample_flows("traffic")
    reporter.add_traffic_alert(
        {
            "rule": "異常連線量告警（樣本）",
            "count": "1260",
            "criteria": "門檻：> 1000，連接埠：443，判定：全部",
            "details": "src-app-1 -> dst-db-1 [443]: 420<br>src-app-2 -> dst-db-2 [8443]: 360<br>src-app-3 -> dst-db-3 [22]: 240",
            "raw_data": traffic_flows,
        }
    )

    metric_flows = _sample_flows("bandwidth")
    reporter.add_metric_alert(
        {
            "rule": "高頻寬告警（樣本）",
            "count": "7.20",
            "criteria": "門檻：> 2.0 Gbps，判定：全部",
            "details": "src-app-1 -> dst-db-1 [443]: 2.40 Gbps<br>src-app-2 -> dst-db-2 [8443]: 4.80 Gbps<br>src-app-3 -> dst-db-3 [22]: 7.20 Gbps",
            "raw_data": metric_flows,
        }
    )
    return reporter


class _CaptureSMTP:
    last_message = None

    def __init__(self, host, port):
        self.host = host
        self.port = port

    def ehlo(self):
        return None

    def starttls(self):
        return None

    def login(self, user, password):
        return None

    def sendmail(self, sender, recipients, raw_message):
        _CaptureSMTP.last_message = raw_message

    def quit(self):
        return None


def main():
    cm = ConfigManager()
    cm.config["settings"]["language"] = "zh_TW"
    set_language("zh_TW")
    reporter = _build_reporter(cm)

    output_dir = Path("reports") / "mail_samples"
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    subject = f"Illumio 告警郵件樣本（全事件） - {datetime.date.today()}"

    original_smtp = reporter_module.smtplib.SMTP
    try:
        reporter_module.smtplib.SMTP = _CaptureSMTP
        reporter._send_mail(subject)
    finally:
        reporter_module.smtplib.SMTP = original_smtp

    if not _CaptureSMTP.last_message:
        raise RuntimeError("無法擷取告警郵件樣本內容")

    raw_eml = _CaptureSMTP.last_message
    message = email.message_from_string(raw_eml, policy=policy.default)
    html_body = message.get_body(preferencelist=("html",)).get_content()

    html_path = output_dir / f"illumio_alert_mail_all_events_sample_{ts}.html"
    eml_path = output_dir / f"illumio_alert_mail_all_events_sample_{ts}.eml"
    html_path.write_text(html_body, encoding="utf-8")
    eml_path.write_text(raw_eml, encoding="utf-8")

    print(f"HTML sample: {html_path}")
    print(f"EML sample: {eml_path}")
    print(f"Event alerts: {len(reporter.event_alerts)}")


if __name__ == "__main__":
    main()
