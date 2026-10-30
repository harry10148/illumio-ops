"""5.x report settings and report schedules → v6 (spec §7, P5c-5). Every schedule is carried, rewritten, paused or
skipped, and the report says which and why; nothing is widened silently: a cron expression or a traffic filter v6
cannot hold keeps the schedule but pauses it, so it never runs wider or at other times than it did.

Only report.retention_days and report.output_dir were read by the 5.x scheduler; the other report.* keys were the
removed CLI's defaults."""
from __future__ import annotations

import uuid
from typing import Any

from illumio_ops.domain.values import ReportFormat, ReportType
from illumio_ops.migrate.report import MigrationItem
from illumio_ops.services.reports.registry import specs
from illumio_ops.settings.schema import Settings

# 5.x report type -> v6 (audit_summary: the .106 config's older name for the audit report)
TYPES = {"traffic": ReportType.TRAFFIC, "security_risk": ReportType.SECURITY_RISK,
         "network_inventory": ReportType.NETWORK_INVENTORY, "audit": ReportType.AUDIT,
         "audit_summary": ReportType.AUDIT, "ven_status": ReportType.VEN_STATUS,
         "policy_usage": ReportType.POLICY_USAGE, "policy_diff": ReportType.POLICY_DIFF,
         "policy_resolver": ReportType.POLICY_RESOLVER, "app_summary": ReportType.APP_SUMMARY,
         "rule_hit_count": ReportType.RULE_HIT_COUNT, "readiness": ReportType.READINESS}
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
REPORT_KEYS: dict[str, tuple[str | None, str, str]] = {  # report.<key> -> (target, action, reason)
    "retention_days": ("reports.retention_days", "carried", "migrate_carried"),
    "output_dir": (None, "dropped", "migrate_fixed_path"),
}


def _item(source: str, target: str | None, action: str, reason: str, **params: str) -> MigrationItem:
    return MigrationItem(source, target, action, reason, params)  # type: ignore[arg-type]


def _weekday(value: Any) -> int | None:
    text = str(value or "").strip().lower()
    return next((i for i, d in enumerate(WEEKDAYS) if text and d.startswith(text[:3])), None)


def _formats(v5: Any, kind: ReportType, made: tuple[ReportFormat, ...]) -> tuple[ReportFormat, ...]:
    """5.x html / xlsx / csv / all → what the v6 type makes. policy_resolver always wrote JSON and CSV."""
    if kind is ReportType.POLICY_RESOLVER:
        return made
    want: list[ReportFormat] = []
    for f in v5 if isinstance(v5, list) else [v5]:
        f = str(f).lower()
        picks = made if f == "all" else [ReportFormat.XLSX] if f == "csv" else \
            [ReportFormat(f)] if f in ("html", "xlsx") else []
        want += [p for p in picks if p in made and p not in want]
    return tuple(f for f in made if f in want) or made  # in the type's own order


def _app_filter(s: dict[str, Any]) -> dict[str, Any] | None:
    """5.x app_summary named the app (and optionally env) in the schedule: the destination side in v6."""
    app = str(s.get("app") or "").strip()
    if not app:
        return None
    labels = [{"key": "app", "values": [app]}]
    env = str(s.get("env") or "").strip()
    if env:
        labels.append({"key": "env", "values": [env]})
    return {"dst": {"labels": labels}}


def migrate_reports(raw: dict[str, Any], settings: Settings,
                    v5_timezone: str) -> tuple[dict[str, Any], list[MigrationItem]]:
    """The v6 `reports` section and a report item per report.* key, per schedule and for web_gui.public_url.
    `settings`: v6 defaults, for each type's lookback limit."""
    items: list[MigrationItem] = []
    out: dict[str, Any] = settings.reports.model_dump(mode="json")
    section = raw.get("report")
    report: dict[str, Any] = section if isinstance(section, dict) else {}
    for key in _leaves(report):
        target, action, reason = ((None, "dropped", "migrate_deprecated_in_5x") if key.startswith("attack_surface")
                                  else REPORT_KEYS.get(key.split(".")[0], (None, "unsupported", "migrate_not_in_v6")))
        items.append(_item(f"report.{key}", target, action, reason))
    if isinstance(report.get("retention_days"), int):
        out["retention_days"] = min(max(report["retention_days"], 1), 3650)
    url = (raw.get("web_gui") or {}).get("public_url") if isinstance(raw.get("web_gui"), dict) else None
    if isinstance(url, str) and url.strip():
        out["gui_external_url"] = url.strip().rstrip("/")
        items.append(_item("web_gui.public_url", "reports.gui_external_url",
                           "carried" if url == out["gui_external_url"] else "rewritten", "migrate_carried"
                           if url == out["gui_external_url"] else "migrate_normalized"))
    elif url is not None:
        items.append(_item("web_gui.public_url", "reports.gui_external_url", "carried", "migrate_empty_is_unset"))

    scheds = raw.get("report_schedules")
    if "report_schedules" in raw:
        items.append(_item("report_schedules", "reports.schedules", "rewritten" if scheds else "carried",
                           "migrate_schedules_listed" if scheds else "migrate_carried"))
    schedules: list[dict[str, Any]] = []
    for i, s in enumerate(scheds if isinstance(scheds, list) else []):
        name = str(s.get("name") or "").strip() if isinstance(s, dict) else ""
        label = f"report_schedules[{i}] {name or s.get('id', '') if isinstance(s, dict) else ''}".rstrip()
        built, item = _schedule(s, name, label, settings, v5_timezone)
        items.append(item)
        if built is not None:
            schedules.append(built)
    out["schedules"] = schedules[:100]
    return out, items


def _leaves(node: Any, prefix: str = "") -> list[str]:
    if isinstance(node, dict) and node:
        return [k for key, v in node.items() for k in _leaves(v, f"{prefix}{key}.")]
    return [prefix[:-1]] if prefix else []


def _schedule(s: Any, name: str, label: str, settings: Settings,
              v5_timezone: str) -> tuple[dict[str, Any] | None, MigrationItem]:
    if not isinstance(s, dict):
        return None, _item(label, None, "unsupported", "migrate_schedule_unreadable")
    kind = TYPES.get(str(s.get("report_type") or "traffic"))
    if kind is None:
        return None, _item(label, None, "unsupported", "migrate_schedule_type_unknown",
                           type=str(s.get("report_type")))
    spec = specs()[kind]
    changed: list[str] = []
    paused = ""
    flt = None
    if kind is ReportType.APP_SUMMARY:
        flt = _app_filter(s)
        if flt is None:  # 5.x refused to run it
            return None, _item(label, None, "unsupported", "migrate_schedule_app_missing")
    if str(s.get("report_type")) == "audit_summary":
        changed.append("report type")
    stype = str(s.get("schedule_type") or "weekly")
    frequency = stype if stype in ("daily", "weekly", "monthly") else "weekly"
    if s.get("cron_expr"):
        paused = "migrate_schedule_cron_paused"
    elif frequency != stype:
        paused = "migrate_schedule_type_paused"
    if s.get("filters") and kind is not ReportType.APP_SUMMARY:
        paused = paused or "migrate_schedule_filter_paused"
    dow = _weekday(s.get("day_of_week", "monday")) if frequency == "weekly" else None
    if frequency == "weekly" and dow is None:
        dow, paused = 0, paused or "migrate_schedule_type_paused"
    dom = min(max(int(s.get("day_of_month") or 1), 1), 31) if frequency == "monthly" else None
    lookback = int(s.get("lookback_days") or 7)
    cap = spec.max_lookback(settings) if spec.max_lookback else 90
    if not 1 <= lookback <= min(cap, 90):
        lookback = min(max(lookback, 1), cap, 90)
        changed.append("lookback")
    formats = _formats(s.get("format", ["html"]), kind, spec.formats)
    if [f.value for f in formats] != [str(f).lower() for f in (s.get("format") or ["html"])]:
        changed.append("formats")
    raw_rcpt = [str(r).strip() for r in s.get("email_recipients") or []]
    rcpt = [r for r in raw_rcpt if "@" in r and not any(c in r for c in "\r\n,; ")][:50]
    if rcpt != raw_rcpt:
        changed.append("recipients")
    keep = min(max(int(s.get("max_reports") or 30), 1), 365)
    if keep != int(s.get("max_reports") or 30):
        changed.append("keep")
    tz = str(s.get("timezone") or "local")
    if tz not in ("local", "", v5_timezone):
        changed.append("time zone")
    lang = s.get("lang") if s.get("lang") in ("en", "zh_TW") else None
    built = {"id": uuid.uuid4().hex, "name": (name or f"5.x schedule {s.get('id', '')}".strip())[:80],
             "enabled": bool(s.get("enabled", True)) and not paused, "report_type": kind.value,
             "lookback_days": lookback, "frequency": frequency, "day_of_week": dow, "day_of_month": dom,
             "hour": min(max(int(s.get("hour", 8)), 0), 23), "minute": min(max(int(s.get("minute", 0)), 0), 59),
             "formats": [f.value for f in formats], "email": bool(s.get("email_report")), "recipients": rcpt,
             "lang": lang, "keep": keep, "filter": flt}
    if paused:
        return built, _item(label, "reports.schedules", "rewritten", paused)
    if changed:
        return built, _item(label, "reports.schedules", "rewritten", "migrate_schedule_rewritten",
                            what=", ".join(changed))
    return built, _item(label, "reports.schedules", "carried", "migrate_carried")
