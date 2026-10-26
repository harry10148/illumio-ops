"""5.x alert rules and notification channels → v6 settings (spec §7). Rules come from config/alerts.json (or, in the
older layout where that file held the channel settings, from config.json "rules"). Every rule and every channel key
is accounted for in the report. A rule v6 cannot fully hold is carried disabled, with each part it lost listed; it
never blocks the rest of the migration. Values are never written into the report."""
from __future__ import annotations

import ipaddress
import json
import re
import uuid
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from illumio_ops.domain.alertpack import PACK_KEYS, best_practice_rules, pack_rule_id
from illumio_ops.domain.alertrules import AlertRule
from illumio_ops.migrate.report import Action, MigrationItem
from illumio_ops.settings.schema import AlertChannels, AlertSettings, default_alerts

_RULE: TypeAdapter[Any] = TypeAdapter(AlertRule)  # type: ignore[arg-type]  # an Annotated union
_PD = {0: "allowed", 1: "potentially_blocked", 2: "blocked"}  # -1, 3 or missing: every decision
_THROTTLE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)([smhd]?)\s*$", re.IGNORECASE)
_UNIT = {"s": 1 / 60, "m": 1, "h": 60, "d": 1440}
MAX_THROTTLE_MINUTES = 10080
MIN_FLOW_WINDOW = 10
# FilterBar keys and legacy scalar keys v6 conditions can hold (the rest are listed per rule as unsupported).
_UNSUPPORTED_FILTER_KEYS = ("src_iplists", "dst_iplists", "ex_src_iplists", "ex_dst_iplists", "any_label", "any_ip",
                            "any_iplist", "any_workload", "ex_any_label", "ex_any_ip", "ex_any_iplist",
                            "ex_any_workload", "services", "ex_services", "windows_service_name",
                            "ex_windows_service_name", "transmission", "ex_transmission", "ex_process_name",
                            "src_label_group", "dst_label_group", "ex_src_label_group", "ex_dst_label_group",
                            "src_label_groups", "dst_label_groups", "ex_src_label_groups", "ex_dst_label_groups")
_RULE_META = frozenset({"id", "type", "name", "name_key", "desc", "desc_key", "rec", "rec_key", "enabled", "filter_key"})


def read_v5_rules(v5_root: Path) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    """(the rules in config/alerts.json, or the channel settings when the file has the older layout)."""
    path = v5_root / "config" / "alerts.json"
    if not path.is_file():
        return None, None
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "rules" in data:
        return list(data.get("rules") or []), None
    if isinstance(data, dict) and data:
        return None, data
    return None, None


# ── channels ─────────────────────────────────────────────────────────────────

def _item(source: str, target: str | None, action: Action, reason: str, **params: str) -> MigrationItem:
    return MigrationItem(source, target, action, reason, dict(params))


def _channels(raw: dict[str, Any], legacy: dict[str, Any] | None) -> tuple[dict[str, Any], list[MigrationItem]]:
    def section(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    alerts = legacy if legacy is not None else section(raw.get("alerts"))
    email = section(raw.get("email"))
    smtp = section(raw.get("smtp"))
    prefix = "alerts.json" if legacy is not None else "alerts"
    out = default_alerts(notify_new_defaults=False).channels.model_dump(mode="json")
    items: list[MigrationItem] = []
    active = [str(a) for a in alerts.get("active") or [] if isinstance(a, str)]
    auth = bool(smtp.get("enable_auth"))

    def take(src: dict[str, Any], key: str, source: str, channel: str, field: str, value: Any = None,
             rewritten: str | None = None) -> None:
        if key not in src:
            return
        out[channel][field] = src[key] if value is None else value
        items.append(_item(source, f"alerts.channels.{channel}.{field}", "rewritten" if rewritten else "carried",
                           rewritten or "migrate_carried"))

    take(alerts, "line_channel_access_token", f"{prefix}.line_channel_access_token", "line", "access_token")
    take(alerts, "line_token", f"{prefix}.line_token", "line", "access_token", rewritten="migrate_alias_key")
    take(alerts, "line_target_id", f"{prefix}.line_target_id", "line", "target_id")
    take(alerts, "telegram_bot_token", f"{prefix}.telegram_bot_token", "telegram", "bot_token")
    take(alerts, "telegram_chat_id", f"{prefix}.telegram_chat_id", "telegram", "chat_id")
    take(alerts, "teams_webhook_url", f"{prefix}.teams_webhook_url", "teams", "webhook_url")
    take(alerts, "webhook_url", f"{prefix}.webhook_url", "webhook", "url")
    take(email, "sender", "email.sender", "smtp", "sender")
    listed = [str(r).strip() for r in email.get("recipients") or [] if str(r).strip()]
    valid = [r for r in listed if "@" in r and not any(c in r for c in "\r\n,; ")]
    take(email, "recipients", "email.recipients", "smtp", "recipients", value=valid,
         rewritten="migrate_recipients_filtered" if valid != listed else None)
    take(smtp, "host", "smtp.host", "smtp", "host")
    take(smtp, "port", "smtp.port", "smtp", "port")
    if "user" in smtp:
        out["smtp"]["username"] = str(smtp["user"] or "") if auth else ""
        items.append(_item("smtp.user", "alerts.channels.smtp.username", "carried" if auth else "rewritten",
                           "migrate_carried" if auth else "migrate_smtp_no_auth"))
    if "password" in smtp:
        if auth:
            out["smtp"]["password"] = str(smtp["password"] or "")
            items.append(_item("smtp.password", "alerts.channels.smtp.password", "carried", "migrate_carried"))
        else:
            items.append(_item("smtp.password", None, "dropped", "migrate_smtp_no_auth"))
    if "enable_auth" in smtp:
        items.append(_item("smtp.enable_auth", "alerts.channels.smtp.username", "rewritten", "migrate_smtp_auth_by_user"))
    if "enable_tls" in smtp:
        out["smtp"]["security"] = "starttls" if smtp.get("enable_tls") else "none"
        items.append(_item("smtp.enable_tls", "alerts.channels.smtp.security", "rewritten", "migrate_smtp_tls"))
    names = {"mail": "smtp", "line": "line", "telegram": "telegram", "teams": "teams", "webhook": "webhook"}
    for name in active:
        if name in names:
            out[names[name]]["enabled"] = True
    if "active" in alerts:
        items.append(_item(f"{prefix}.active", "alerts.channels.*.enabled", "rewritten", "migrate_active_channels"))
    known = {"active", "line_channel_access_token", "line_token", "line_target_id", "telegram_bot_token",
             "telegram_chat_id", "teams_webhook_url", "webhook_url"}
    for source, keys, seen in ((prefix, alerts, known), ("email", email, {"sender", "recipients"}),
                               ("smtp", smtp, {"host", "port", "user", "password", "enable_auth", "enable_tls"})):
        for key in keys:
            if key not in seen:
                items.append(_item(f"{source}.{key}", None, "unsupported", "migrate_unknown_key"))
    # A channel that is on but cannot work is carried off, said so, and never blocks the migration.
    for channel in list(out):
        if out[channel]["enabled"]:
            try:
                AlertChannels.model_validate(out)
            except ValidationError as exc:
                if any(e["loc"][0] == channel for e in exc.errors(include_input=False)):
                    out[channel]["enabled"] = False
                    items.append(_item(f"alerts.channels.{channel}", f"alerts.channels.{channel}.enabled", "rewritten",
                                       "migrate_channel_incomplete"))
    try:
        AlertChannels.model_validate(out)
    except ValidationError as exc:  # an http:// webhook URL even with the channel off
        for e in exc.errors(include_input=False):
            channel, field = str(e["loc"][0]), str(e["loc"][-1])
            out[channel][field] = "" if isinstance(out[channel].get(field), str) else out[channel].get(field)
            out[channel]["enabled"] = False
            items.append(_item(f"alerts.channels.{channel}.{field}", None, "dropped", "migrate_channel_invalid"))
    if out["smtp"]["enabled"] and auth:
        # 5.x let ILLUMIO_SMTP_PASSWORD override the file; v6 reads only its settings (not visible from here).
        items.append(_item("ILLUMIO_SMTP_PASSWORD", None, "unsupported", "migrate_smtp_env_password"))
    return out, items


# ── rules ────────────────────────────────────────────────────────────────────

def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _throttle(value: Any) -> tuple[dict[str, int] | None, bool]:
    """(the v6 throttle, whether it was cut to the 7-day maximum)."""
    if not value:
        return None, False
    if isinstance(value, dict):
        count = max(1, int(_num(value.get("count"), 0)))
        seconds = _num(value.get("period_seconds"), 0) or _num(value.get("period_minutes"), 0) * 60
        minutes = seconds / 60
    else:
        m = _THROTTLE.match(str(value))
        if not m:
            return None, False
        count, minutes = max(1, int(m.group(1))), max(1, int(m.group(2))) * _UNIT[(m.group(3) or "m").lower()]
    if minutes <= 0:
        return None, False
    whole = max(1, round(minutes))
    return {"count": count, "period_minutes": min(whole, MAX_THROTTLE_MINUTES)}, whole > MAX_THROTTLE_MINUTES


def _label(token: Any) -> tuple[str, str] | None:
    """5.x label filters: "key=value" or "key:value", split at whichever comes first."""
    text = str(token or "").strip()
    cuts = [i for i in (text.find("="), text.find(":")) if i > 0]
    if not cuts:
        return None
    key, value = text[:min(cuts)].strip(), text[min(cuts) + 1:].strip()
    return (key, value) if key and value else None


def _ips(token: Any) -> list[str] | None:
    """An address, a network or an IPv4 range a-b (as networks); None for anything else (an IP list name)."""
    text = str(token or "").strip()
    try:
        if "-" in text and "/" not in text:
            a, b = (ipaddress.IPv4Address(p.strip()) for p in text.split("-", 1))
            lo, hi = min(a, b), max(a, b)
            return [str(n) for n in ipaddress.summarize_address_range(lo, hi)]
        return [str(ipaddress.ip_network(text, strict=False)) if "/" in text else str(ipaddress.ip_address(text))]
    except ValueError:
        return None


def _port(token: Any, default_proto: int | None = None) -> dict[str, Any] | None:
    text = str(token).strip()
    proto: Any = default_proto
    if "/" in text:
        text, proto = text.split("/", 1)
    try:
        if "-" in text:
            a, b = (int(p) for p in text.split("-", 1))
            out: dict[str, Any] = {"port": min(a, b), "to_port": max(a, b)}
        else:
            out = {"port": int(text)}
    except ValueError:
        return None
    if isinstance(proto, str):
        proto = {"tcp": 6, "udp": 17}.get(proto.strip().lower(), int(proto) if proto.strip().isdigit() else None)
    if proto is not None:
        out["proto"] = int(proto)
    return out


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    return list(value) if isinstance(value, list | tuple) else [value]


class _Lost:
    """What one rule could not keep: each entry is (5.x key, reason key)."""

    def __init__(self) -> None:
        self.keys: list[tuple[str, str]] = []

    def add(self, key: str, reason: str) -> None:
        self.keys.append((key, reason))


def _side(rule: dict[str, Any], lost: _Lost, *, labels: tuple[str, ...], ips: tuple[str, ...],
          hrefs: tuple[str, ...]) -> dict[str, Any] | None:
    by_key: dict[str, list[str]] = {}
    out: dict[str, Any] = {}
    for k in labels:
        for token in _as_list(rule.get(k)):
            pair = _label(token)
            if pair is None:
                lost.add(k, "migrate_rule_bad_label")
            else:
                values = by_key.setdefault(pair[0], [])
                if pair[1] not in values:
                    values.append(pair[1])
    if by_key:
        out["labels"] = [{"key": k, "values": v} for k, v in by_key.items()]
    found: list[str] = []
    for k in ips:
        for token in _as_list(rule.get(k)):
            nets = _ips(token)
            if nets is None:
                lost.add(k, "migrate_rule_iplist_name")
            else:
                found += nets
    if found:
        out["ips"] = found
    refs = [str(v.get("href") if isinstance(v, dict) else v) for k in hrefs for v in _as_list(rule.get(k)) if v]
    if refs:
        out["hrefs"] = refs
    return out or None


def _condition(rule: dict[str, Any], lost: _Lost) -> dict[str, Any]:
    cond: dict[str, Any] = {}
    pd = rule.get("pd")
    try:
        pd_value = int(pd) if pd is not None and str(pd).strip() != "" else None
    except (TypeError, ValueError):
        pd_value = None
        lost.add("pd", "migrate_rule_bad_value")
    if pd_value in _PD:
        cond["decisions"] = [_PD[pd_value]]
    for name, keys in (("src", (("src_label", "src_labels"), ("src_ip_in",), ("src_workloads",))),
                       ("dst", (("dst_label", "dst_labels"), ("dst_ip_in",), ("dst_workloads",))),
                       ("src_exclude", (("ex_src_label", "ex_src_labels"), ("ex_src_ip",), ("ex_src_workloads",))),
                       ("dst_exclude", (("ex_dst_label", "ex_dst_labels"), ("ex_dst_ip",), ("ex_dst_workloads",)))):
        side = _side(rule, lost, labels=keys[0], ips=keys[1], hrefs=keys[2])
        if side:
            cond[name] = side
    proto = rule.get("proto")
    proto_value = int(proto) if isinstance(proto, int | float) or (isinstance(proto, str) and proto.isdigit()) else None
    ports = []
    for k in ("port", "ports"):
        for token in _as_list(rule.get(k)):
            p = _port(token, proto_value)
            if p is None:
                lost.add(k, "migrate_rule_bad_value")
            else:
                ports.append(p)
    if not ports and proto_value is not None:
        ports.append({"proto": proto_value})
    if ports:
        cond["ports"] = ports
    excluded = []
    for k in ("ex_port", "ex_ports"):
        for token in _as_list(rule.get(k)):
            p = _port(token)
            if p is None:
                lost.add(k, "migrate_rule_bad_value")
            else:
                excluded.append(p)
    if excluded:
        cond["exclude_ports"] = excluded
    if rule.get("process_name"):
        names = _as_list(rule["process_name"])
        cond["initiator_process"] = str(names[0])
        lost.add("process_name", "migrate_rule_process_initiator")  # rewritten, said so
        if len(names) > 1:
            lost.add("process_name", "migrate_rule_first_process_only")
    for k in _UNSUPPORTED_FILTER_KEYS:
        if _as_list(rule.get(k)):
            lost.add(k, "migrate_rule_filter_unsupported")
    return cond


_FLOW_KEYS = frozenset({"pd", "port", "proto", "ex_port", "ports", "ex_ports", "src_label", "dst_label", "ex_src_label",
                        "ex_dst_label", "src_labels", "dst_labels", "ex_src_labels", "ex_dst_labels", "src_ip_in",
                        "dst_ip_in", "ex_src_ip", "ex_dst_ip", "src_workloads", "dst_workloads", "ex_src_workloads",
                        "ex_dst_workloads", "process_name", *_UNSUPPORTED_FILTER_KEYS})
_COMMON_KEYS = frozenset({"threshold_type", "threshold_count", "threshold", "threshold_window", "cooldown_minutes",
                          "throttle", "alert_throttle"})
_EVENT_KEYS = frozenset({"filter_value", "filter_status", "filter_severity", "match_fields", "filter_match_fields"})


def _base(rule: dict[str, Any], *, rule_id: str, pack_key: str | None, enabled: bool, severity: str | None,
          lost: _Lost) -> dict[str, Any]:
    window = int(_num(rule.get("threshold_window"), 10)) or 10
    cooldown = rule.get("cooldown_minutes")
    throttle, cut = _throttle(rule.get("throttle") or rule.get("alert_throttle"))
    if cut:
        lost.add("throttle", "migrate_rule_throttle_capped")
    if (rule.get("throttle") or rule.get("alert_throttle")) and throttle is None:
        lost.add("throttle", "migrate_rule_bad_value")
    return {"id": rule_id, "name": "" if pack_key else str(rule.get("name") or rule.get("name_key") or "")[:120],
            "pack_key": pack_key, "enabled": enabled, "notify": True, "severity": severity,
            # 5.x's engine falls back to the window when cooldown_minutes is missing (analyzer _check_cooldown).
            "cooldown_minutes": int(_num(cooldown, window)) if cooldown is not None else window,
            "throttle": throttle, "_window": window}


def convert_rule(rule: dict[str, Any], *, used_ids: set[str]) -> tuple[dict[str, Any] | None, list[tuple[str, str]],
                                                                         list[str]]:
    """(the v6 rule or None, what was lost or rewritten (key, reason), keys taken as they were)."""
    lost = _Lost()
    kind = str(rule.get("type") or "")
    name_key = rule.get("name_key")
    pack_key = name_key if name_key in PACK_KEYS else None
    raw_id = str(rule.get("id") or "")
    rule_id = pack_rule_id(pack_key) if pack_key and pack_rule_id(pack_key) not in used_ids else (
        raw_id if re.fullmatch(r"[0-9a-f]{32}", raw_id) and raw_id not in used_ids else uuid.uuid4().hex)
    if rule_id != raw_id:
        lost.add("id", "migrate_rule_new_id")
    enabled = rule.get("enabled") is not False  # 5.x: only False turns a rule off
    pack = {r.pack_key: r for r in best_practice_rules(notify_new_defaults=True)}
    if kind == "event":
        base = _base(rule, rule_id=rule_id, pack_key=pack_key, enabled=enabled,
                     severity=pack[pack_key].severity if pack_key else None, lost=lost)
        count_key = "threshold_count" if "threshold_count" in rule else "threshold"
        if count_key == "threshold" and "threshold" in rule:
            lost.add("threshold", "migrate_rule_threshold_alias")
        types = [p.strip() for p in str(rule.get("filter_value") or "").split(",") if p.strip()]
        fields = rule.get("match_fields") or rule.get("filter_match_fields") or {}
        if "filter_match_fields" in rule and "match_fields" not in rule:
            lost.add("filter_match_fields", "migrate_alias_key")
        out = {**base, "type": "event", "event_types": types or ["*"], "status": str(rule.get("filter_status") or "all"),
               "event_severity": str(rule.get("filter_severity") or "all"),
               "match_fields": {str(k): str(v) for k, v in fields.items()} if isinstance(fields, dict) else {},
               "threshold": "count" if rule.get("threshold_type") == "count" else "immediate",
               "threshold_count": max(1, int(_num(rule.get(count_key), 1))), "window_minutes": min(base["_window"], 1440)}
        handled = _EVENT_KEYS | _COMMON_KEYS
    elif kind in ("traffic", "bandwidth", "volume"):
        base = _base(rule, rule_id=rule_id, pack_key=pack_key, enabled=enabled, severity="medium", lost=lost)
        window = base["_window"]
        if window < MIN_FLOW_WINDOW:
            lost.add("threshold_window", "migrate_rule_window_raised")
        threshold = _num(rule.get("threshold_count", rule.get("threshold")), 1)
        field = {"traffic": "threshold_connections", "bandwidth": "threshold_mbps", "volume": "threshold_mb"}[kind]
        out = {**base, "type": kind, "condition": _condition(rule, lost),
               field: max(1, int(threshold)) if kind == "traffic" else max(threshold, 0.001),
               "window_minutes": min(max(window, MIN_FLOW_WINDOW), 1440)}
        handled = _FLOW_KEYS | _COMMON_KEYS
        if any(r == "migrate_rule_filter_unsupported" for _, r in lost.keys):
            out["enabled"] = False
    elif kind == "system" and str(rule.get("filter_value") or "") == "pce_health":
        base = _base(rule, rule_id=rule_id, pack_key=None, enabled=enabled, severity="high", lost=lost)
        out = {**base, "type": "system", "check": "pce_health"}
        for k in ("threshold_type", "threshold_count", "threshold_window", "match_fields"):
            if k in rule:
                lost.add(k, "migrate_rule_not_read_by_5x")
        handled = _COMMON_KEYS | {"filter_value", "match_fields"}
    else:
        return None, [("type", "migrate_rule_type_unsupported")], []
    out.pop("_window")
    if not out["name"] and not out["pack_key"]:
        out["name"] = f"{kind} rule"
    try:
        _RULE.validate_python(out)
    except ValidationError as exc:
        # A pattern that does not compile, an empty event type: carried off, never blocking the rest.
        for e in exc.errors(include_input=False):
            lost.add(".".join(str(p) for p in e["loc"][1:2]) or kind, "migrate_rule_invalid")
        out["enabled"] = False
        for field in ("event_types", "status", "event_severity", "match_fields"):
            if field in out and any(field in ".".join(str(p) for p in e["loc"]) for e in exc.errors()):
                out[field] = {"event_types": ["*"], "status": "all", "event_severity": "all", "match_fields": {}}[field]
        _RULE.validate_python(out)
    used_ids.add(rule_id)
    unknown = [k for k in rule if k not in handled | _RULE_META]
    for k in unknown:
        lost.add(k, "migrate_unknown_key")
    kept = [k for k in rule if k in handled and k not in {k2 for k2, _ in lost.keys}]
    return out, lost.keys, kept


def migrate_alerts(raw: dict[str, Any], rules: list[dict[str, Any]] | None,
                   legacy_channels: dict[str, Any] | None) -> tuple[dict[str, Any], list[MigrationItem]]:
    """The alerts section of v6 settings and a report item per channel key and per rule."""
    channels, items = _channels(raw, legacy_channels)
    source_rules = rules if rules is not None else list(raw.get("rules") or [])
    where = "alerts.json rules" if rules is not None else "rules"
    if "rules" in raw:  # the config.json key itself (a list: one leaf), whose entries are listed one by one below
        items.append(_item("rules", "alerts.rules", "rewritten" if raw.get("rules") else "carried",
                           "migrate_rules_listed" if raw.get("rules") else "migrate_carried"))
    used: set[str] = set()
    out_rules: list[dict[str, Any]] = []
    for i, rule in enumerate(source_rules):
        label = f"{where}[{i}] {rule.get('name') or rule.get('name_key') or ''}".rstrip()
        if not isinstance(rule, dict):
            items.append(_item(label, None, "unsupported", "migrate_rule_type_unsupported"))
            continue
        converted, lost, _ = convert_rule(rule, used_ids=used)
        if converted is None:
            items.append(_item(label, None, "unsupported", "migrate_rule_type_unsupported"))
            continue
        out_rules.append(converted)
        target = f"alerts.rules[{converted['id'][:8]}]"
        if not lost:
            items.append(_item(label, target, "carried", "migrate_carried"))
        for key, reason in lost:
            action: Action = "unsupported" if reason in ("migrate_rule_filter_unsupported", "migrate_rule_invalid",
                                                         "migrate_rule_iplist_name", "migrate_unknown_key") else (
                "dropped" if reason == "migrate_rule_not_read_by_5x" else "rewritten")
            items.append(_item(f"{label} · {key}", target, action, reason))
        if not converted["enabled"] and rule.get("enabled") is not False:
            items.append(_item(label, target, "rewritten", "migrate_rule_disabled"))
    # The new default rules 5.x did not have: added, and the lateral-movement ones record without sending until the
    # operator turns each on (spec §7: an upgrade must not flood the channels with long-standing connections).
    have = {r["id"] for r in out_rules}
    for rule in best_practice_rules(notify_new_defaults=False):
        # Only the kinds 5.x did not have; a 5.x pack rule the customer deleted stays deleted.
        if rule.id not in have and rule.type in ("system", "lateral"):
            out_rules.append(rule.model_dump(mode="json"))
            items.append(_item(f"(new) {rule.pack_key}", f"alerts.rules[{rule.id[:8]}]", "rewritten",
                               "migrate_new_default_quiet" if rule.type == "lateral" else "migrate_new_default"))
    section = {"channels": channels, "rules": out_rules, "retention_days": 90}
    AlertSettings.model_validate(section)
    return section, items

