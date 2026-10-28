"""Read a 5.x config/config.json and produce v6 settings plus a report covering every key.

The 5.x values are first parsed the way 5.x parsed them (illumio_ops.migrate.v5_models), so
what carries over is what 5.x actually used. A value v6 cannot hold is either rewritten to
what 5.x effectively did (and reported as rewritten), or blocks the migration while the
report still lists every key. Nothing is skipped silently.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from illumio_ops.domain.netaddr import parse_ip_token
from illumio_ops.domain.values import Language
from illumio_ops.migrate.report import Action, MigrationItem, MigrationReport
from illumio_ops.migrate.v5_alerts import migrate_alerts
from illumio_ops.migrate.v5_models import V5Config
from illumio_ops.settings.schema import DisplaySettings, Settings, default_settings
from illumio_ops.settings.secrets import (
    DEFAULT_ADMIN_PASSWORD,
    hash_password,
    new_secret_key,
)
from illumio_ops.settings.store import SettingsInvalid, validate_settings

Path_ = tuple[str, ...]

DEPRECATED_PREFIXES: tuple[Path_, ...] = (("report", "attack_surface"), ("web_gui", "tls", "http_redirect_port"),
                                          ("pce_profiles",), ("active_pce_id",),
                                          ("pce_cache", "archive_review_max_days"))
PHASE_OF_SECTION = {"siem": "P7", "report": "P5", "report_schedules": "P5"}
ALERT_SECTIONS = ("alerts", "email", "smtp", "rules")  # reported by migrate_alerts, key by key
NOT_IN_V6_SECTIONS = ("rule_scheduler", "scheduler", "rule_backups")
SPECIAL: dict[Path_, tuple[Action, str, dict[str, str]]] = {
    ("api", "profile"): ("dropped", "migrate_no_profiles", {}),
    ("settings", "enable_health_check"): ("dropped", "migrate_always_on", {}),
    ("settings", "theme"): ("unsupported", "migrate_not_in_v6", {}),
    ("settings", "dashboard_queries"): ("unsupported", "migrate_not_in_v6", {}),
    ("web_gui", "public_url"): ("unsupported", "migrate_arrives_in_phase", {"phase": "P5"}),
    ("pce_cache", "db_path"): ("dropped", "migrate_fixed_path", {}),
    ("pce_cache", "archive_dir"): ("dropped", "migrate_fixed_path", {}),
    ("pce_cache", "archive_interval_hours"): ("dropped", "migrate_archive_daily", {}),
    ("pce_cache", "archive_gzip_after_days"): ("dropped", "migrate_archive_always_gzip", {}),
    ("pce_cache", "async_threshold_events"): ("dropped", "migrate_fixed_event_cap", {}),
    ("pce_cache", "cache_read_max_rows"): ("dropped", "migrate_not_in_v6", {}),
    ("pce_cache", "flow_delta_enabled"): ("dropped", "migrate_not_in_v6", {}),
    ("pce_cache", "flow_obs_retention_hours"): ("dropped", "migrate_not_in_v6", {}),
    ("pce_cache", "siem_pending_warn_rows"): ("unsupported", "migrate_arrives_in_phase", {"phase": "P7"}),
    ("logging", "json_sink"): ("unsupported", "migrate_not_in_v6", {}),
    ("logging", "rotation"): ("unsupported", "migrate_not_in_v6", {}),
    ("logging", "retention"): ("unsupported", "migrate_not_in_v6", {}),
}
# Whole subtrees dropped with one reason: v6 collects every flow, since a filtered or sampled
# store would hide exactly the lateral movement it exists to find.
DROPPED_PREFIXES: dict[Path_, str] = {("pce_cache", "traffic_filter"): "migrate_no_sampling",
                                      ("pce_cache", "traffic_sampling"): "migrate_no_sampling"}
LOG_LEVELS = ("TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL")
_HEX_KEY = re.compile(r"[0-9a-f]{64,}")
_MISSING = object()


def show(path: Path_) -> str:
    """Dotted display; a segment that itself contains a dot is bracketed so paths stay unique."""
    return ".".join(f"[{p}]" if "." in p else p for p in path)


def leaf_paths(node: Any, prefix: Path_ = ()) -> list[Path_]:
    if isinstance(node, dict) and node:
        out: list[Path_] = []
        for k, v in node.items():
            out += leaf_paths(v, (*prefix, str(k)))
        return out
    return [prefix]


def leaf_keys(node: Any) -> list[str]:
    """Display paths of every leaf; a list or an empty object counts as one leaf."""
    return [show(p) for p in leaf_paths(node)]


def _raw(raw: dict[str, Any], path: Path_) -> Any:
    node: Any = raw
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


@dataclass
class MigrationResult:
    settings: Settings | None
    report: MigrationReport
    blocking: list[tuple[str, str]] = field(default_factory=list)


def read_v5(v5_root: Path) -> dict[str, Any]:
    data = json.loads((v5_root / "config" / "config.json").read_text(encoding="utf-8"))
    known = {"api", "web_gui", "settings", "alerts", "pce_cache", "siem", "report"}
    if not (isinstance(data, dict) and known & set(data) and "schema_version" not in data):
        raise ValueError("this is not a 5.x config.json")
    return data


@dataclass(frozen=True)
class _Carry:
    target: str
    convert: Callable[[V5Config], Any]
    reason_if_changed: str | Callable[[V5Config], str] = "migrate_normalized"


def _clamped(value: int, lo: int, hi: int) -> int:
    return min(max(value, lo), hi)


def _bound_reason(value: int, lo: int, hi: int) -> str:
    return "migrate_raised_to_minimum" if value < lo else "migrate_lowered_to_maximum" if value > hi \
        else "migrate_normalized"


def _traffic_interval(v: V5Config) -> int:
    t = v.pce_cache.traffic_poll_interval_seconds
    return 600 if t == 3600 else _clamped(t, 300, 86400)  # 5.x's default hourly → v6's 10 minutes


def _traffic_interval_reason(v: V5Config) -> str:
    t = v.pce_cache.traffic_poll_interval_seconds
    return "migrate_v6_default_interval" if t == 3600 else _bound_reason(t, 300, 86400)


def _flow_days(v: V5Config) -> int:
    # "New connection" detection compares against 30 days of baseline; raw flows must outlive it.
    d = v.pce_cache.traffic_raw_retention_days
    return 35 if d < 30 else min(d, 3650)


def _rollup_days(v: V5Config) -> int:
    return min(max(v.pce_cache.traffic_agg_retention_days, _flow_days(v)), 3650)


def _archive_days(v: V5Config) -> int:
    c = v.pce_cache
    floor = max(_flow_days(v), min(c.events_retention_days, 3650))
    days = min(c.archive_retention_days, 3650)
    return floor if c.archive_enabled and 0 < days < floor else days


def _tz(v5: V5Config) -> str:
    tz = v5.settings.timezone or "local"  # 5.x: empty means local
    try:
        DisplaySettings(language=Language.EN, timezone=tz)
    except ValidationError:
        return "UTC"  # 5.x resolve_tz falls back to UTC for anything it cannot parse
    return tz


def _is_ip(value: str) -> bool:
    """5.x skipped allowlist entries it could not parse; v6 refuses them, so they are dropped."""
    try:
        parse_ip_token(value)
    except ValueError:
        return False
    return True


def _tls_mode(v5: V5Config) -> str:
    t = v5.web_gui.tls
    # 5.x (src/gui/__init__.py, launch) uses both files when given, whatever self_signed says.
    return "provided" if t.cert_file and t.key_file else "self_signed"


CARRY: dict[Path_, _Carry] = {
    ("api", "url"): _Carry("pce.url", lambda v: v.api.url.rstrip("/")),
    ("api", "key"): _Carry("pce.api_key", lambda v: v.api.key),
    ("api", "secret"): _Carry("pce.api_secret", lambda v: v.api.secret),
    ("api", "verify_ssl"): _Carry("pce.verify_tls", lambda v: v.api.verify_ssl),
    ("api", "deployment_type"): _Carry("pce.deployment_type", lambda v: v.api.deployment_type),
    ("api", "console_url"): _Carry("pce.console_url", lambda v: v.api.console_url.rstrip("/") or None,
                                   "migrate_empty_is_unset"),
    ("api", "events_timeout_seconds"): _Carry("pce.events_timeout_seconds", lambda v: v.api.events_timeout_seconds),
    ("web_gui", "username"): _Carry("web.username", lambda v: v.web_gui.username),
    ("web_gui", "allowed_ips"): _Carry("web.allowed_ips", lambda v: [ip for ip in v.web_gui.allowed_ips if _is_ip(ip)],
                                       "migrate_5x_effective_value"),
    ("web_gui", "session_lifetime_seconds"): _Carry("web.session_lifetime_seconds",
                                                    lambda v: max(60, v.web_gui.session_lifetime_seconds),
                                                    "migrate_raised_to_minimum"),
    ("web_gui", "must_change_password"): _Carry("web.must_change_password", lambda v: v.web_gui.must_change_password),
    ("web_gui", "tls", "enabled"): _Carry("web.tls.enabled", lambda v: v.web_gui.tls.enabled),
    ("web_gui", "tls", "cert_file"): _Carry("web.tls.cert_file", lambda v: v.web_gui.tls.cert_file),
    ("web_gui", "tls", "key_file"): _Carry("web.tls.key_file", lambda v: v.web_gui.tls.key_file),
    ("web_gui", "tls", "self_signed"): _Carry("web.tls.mode", _tls_mode, "migrate_tls_source"),
    ("web_gui", "tls", "auto_renew"): _Carry("web.tls.auto_renew", lambda v: v.web_gui.tls.auto_renew),
    ("web_gui", "tls", "auto_renew_days"): _Carry("web.tls.auto_renew_days", lambda v: v.web_gui.tls.auto_renew_days),
    ("web_gui", "tls", "validity_days"): _Carry("web.tls.validity_days", lambda v: v.web_gui.tls.validity_days),
    ("web_gui", "tls", "key_algorithm"): _Carry(
        "web.tls.key_algorithm",
        lambda v: v.web_gui.tls.key_algorithm if v.web_gui.tls.key_algorithm == "rsa-2048" else "ecdsa-p256",
        "migrate_5x_effective_value"),
    ("web_gui", "tls", "min_version"): _Carry(
        "web.tls.min_version",
        lambda v: v.web_gui.tls.min_version if v.web_gui.tls.min_version in ("TLSv1.2", "TLSv1.3") else "TLSv1.2",
        "migrate_5x_effective_value"),
    ("web_gui", "tls", "ciphers"): _Carry("web.tls.ciphers", lambda v: v.web_gui.tls.ciphers or None),
    ("settings", "language"): _Carry("display.language", lambda v: v.settings.language),
    ("settings", "timezone"): _Carry("display.timezone", _tz, "migrate_5x_effective_value"),
    ("logging", "level"): _Carry("logging.level",
                                 lambda v: v.logging.level.upper() if v.logging.level.upper() in LOG_LEVELS else "INFO",
                                 "migrate_5x_effective_value"),
    # pce_cache: applied only when the 5.x file has the section (never configured → v6 defaults)
    ("pce_cache", "enabled"): _Carry("collection.mode", lambda v: "full" if v.pce_cache.enabled else "lightweight",
                                     lambda v: "migrate_cache_on_full" if v.pce_cache.enabled
                                     else "migrate_cache_off_lightweight"),
    ("pce_cache", "traffic_poll_interval_seconds"): _Carry("collection.traffic_interval_seconds", _traffic_interval,
                                                           _traffic_interval_reason),
    ("pce_cache", "events_poll_interval_seconds"): _Carry(
        "collection.events_interval_seconds", lambda v: _clamped(v.pce_cache.events_poll_interval_seconds, 60, 3600),
        lambda v: _bound_reason(v.pce_cache.events_poll_interval_seconds, 60, 3600)),
    ("pce_cache", "rate_limit_per_minute"): _Carry("collection.rate_limit_per_minute",
                                                   lambda v: v.pce_cache.rate_limit_per_minute),
    ("pce_cache", "events_retention_days"): _Carry(
        "collection.retention.event_days", lambda v: min(v.pce_cache.events_retention_days, 3650),
        "migrate_lowered_to_maximum"),
    ("pce_cache", "traffic_raw_retention_days"): _Carry("collection.retention.flow_days", _flow_days,
                                                        lambda v: "migrate_raised_to_baseline"
                                                        if v.pce_cache.traffic_raw_retention_days < 30
                                                        else "migrate_lowered_to_maximum"),
    ("pce_cache", "traffic_agg_retention_days"): _Carry("collection.retention.rollup_days", _rollup_days,
                                                        lambda v: "migrate_lowered_to_maximum"
                                                        if v.pce_cache.traffic_agg_retention_days > 3650
                                                        else "migrate_raised_to_baseline"),
    ("pce_cache", "archive_enabled"): _Carry("collection.archive.enabled", lambda v: v.pce_cache.archive_enabled),
    ("pce_cache", "archive_retention_days"): _Carry("collection.archive.retention_days", _archive_days,
                                                    lambda v: "migrate_lowered_to_maximum"
                                                    if v.pce_cache.archive_retention_days > 3650
                                                    else "migrate_raised_for_archive"),
    ("pce_cache", "disk_free_warn_gb"): _Carry("collection.disk_free_warn_gb",
                                               lambda v: min(v.pce_cache.disk_free_warn_gb, 100000),
                                               "migrate_lowered_to_maximum"),
}


def _set(d: dict[str, Any], dotted: str, value: Any) -> None:
    *parents, leaf = dotted.split(".")
    for p in parents:
        d = d[p]
    d[leaf] = value


def migrate_v5(raw: dict[str, Any], *, rules: list[dict[str, Any]] | None = None,
               legacy_channels: dict[str, Any] | None = None) -> MigrationResult:
    """rules / legacy_channels: what config/alerts.json held (illumio_ops.migrate.v5_alerts.read_v5_rules)."""
    report = MigrationReport()
    add = report.items.append
    blocking: list[tuple[str, str]] = []
    try:
        v5 = V5Config.model_validate(raw)
    except ValidationError as exc:
        # A value 5.x itself would have rejected: report every key, block the write.
        bad = {tuple(str(p) for p in e["loc"]) for e in exc.errors(include_input=False)}
        blocking = [(show(p), "5.x itself would not accept this value") for p in sorted(bad)]
        for path in leaf_paths(raw):
            add(MigrationItem(show(path), None, "unsupported", "migrate_invalid_in_5x"))
        return MigrationResult(None, report, blocking)

    # password and signing key first: default_settings needs both
    pw = v5.web_gui.password
    raw_pw = _raw(raw, ("web_gui", "password"))
    if pw.startswith("$argon2"):
        password_hash = pw
        pw_item = ("carried" if raw_pw == pw else "rewritten", "migrate_carried" if raw_pw == pw else "migrate_normalized")
    elif pw:
        password_hash, pw_item = hash_password(pw), ("rewritten", "migrate_password_hashed")
    else:
        password_hash, pw_item = hash_password(DEFAULT_ADMIN_PASSWORD), ("rewritten", "migrate_password_default")
    secret_key = v5.web_gui.secret_key
    key_item = ("carried", "migrate_carried")
    if not _HEX_KEY.fullmatch(secret_key):
        secret_key, key_item = new_secret_key(), ("rewritten", "migrate_secret_key_new")

    out = default_settings(password_hash=password_hash, secret_key=secret_key).model_dump(mode="json")
    if v5.web_gui.allowed_ips and not any(_is_ip(ip) for ip in v5.web_gui.allowed_ips):
        # 5.x refused every client with such a list; an empty v6 list would allow everyone.
        blocking.append(("web_gui.allowed_ips", "no entry is an IP address or network; fix the list in 5.x first"))
    org = v5.api.org_id
    if org.isdigit():
        out["pce"]["org_id"] = org
    else:
        blocking.append(("api.org_id", "a PCE organization ID is a number"))
    for path, carry in CARRY.items():
        if path[0] == "pce_cache" and not isinstance(raw.get("pce_cache"), dict):
            continue
        _set(out, carry.target, carry.convert(v5))
    if not isinstance(raw.get("pce_cache"), dict):
        out["collection"]["mode"] = "lightweight"  # 5.x without the section kept no traffic (spec §7)

    out["alerts"], alert_items = migrate_alerts(raw, rules, legacy_channels)
    report.items.extend(alert_items)

    for path in leaf_paths(raw):
        source = show(path)
        if path[0] in ALERT_SECTIONS:
            continue
        if any(path[:len(p)] == p for p in DEPRECATED_PREFIXES):
            add(MigrationItem(source, None, "dropped", "migrate_deprecated_in_5x"))
        elif path == ("web_gui", "password"):
            add(MigrationItem(source, "web.password_hash", pw_item[0], pw_item[1]))  # type: ignore[arg-type]
        elif path == ("web_gui", "secret_key"):
            add(MigrationItem(source, "web.secret_key", key_item[0], key_item[1]))  # type: ignore[arg-type]
        elif path == ("api", "org_id"):
            if org.isdigit():
                same = _raw(raw, path) == org
                add(MigrationItem(source, "pce.org_id", "carried" if same else "rewritten",
                                  "migrate_carried" if same else "migrate_normalized"))
            else:
                add(MigrationItem(source, None, "unsupported", "migrate_org_id_not_numeric"))
        elif path in CARRY:
            carry = CARRY[path]
            value = carry.convert(v5)
            same = _raw(raw, path) == value and type(_raw(raw, path)) is type(value)
            reason = carry.reason_if_changed if isinstance(carry.reason_if_changed, str) \
                else carry.reason_if_changed(v5)
            add(MigrationItem(source, carry.target, "carried" if same else "rewritten",
                              "migrate_carried" if same else reason))
        elif path in SPECIAL:
            action, reason, params = SPECIAL[path]
            add(MigrationItem(source, None, action, reason, params))
        elif dropped := next((r for p, r in DROPPED_PREFIXES.items() if path[:len(p)] == p), None):
            add(MigrationItem(source, None, "dropped", dropped))
        elif path[0] in PHASE_OF_SECTION:
            add(MigrationItem(source, None, "unsupported", "migrate_arrives_in_phase",
                              {"phase": PHASE_OF_SECTION[path[0]]}))
        elif path[0] in NOT_IN_V6_SECTIONS:
            add(MigrationItem(source, None, "unsupported", "migrate_not_in_v6"))
        else:
            add(MigrationItem(source, None, "unsupported", "migrate_unknown_key"))

    if blocking:
        return MigrationResult(None, report, blocking)
    try:
        return MigrationResult(validate_settings(out), report)
    except SettingsInvalid as exc:
        return MigrationResult(None, report, list(exc.errors))
