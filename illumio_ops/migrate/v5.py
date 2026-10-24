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

from illumio_ops.domain.values import Language
from illumio_ops.migrate.report import Action, MigrationItem, MigrationReport
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
PHASE_OF_SECTION = {"pce_cache": "P2", "alerts": "P3", "email": "P3", "smtp": "P3", "rules": "P3",
                    "siem": "P4", "report": "P5", "report_schedules": "P5"}
NOT_IN_V6_SECTIONS = ("rule_scheduler", "scheduler", "rule_backups")
SPECIAL: dict[Path_, tuple[Action, str, dict[str, str]]] = {
    ("api", "profile"): ("dropped", "migrate_no_profiles", {}),
    ("settings", "enable_health_check"): ("dropped", "migrate_always_on", {}),
    ("settings", "theme"): ("unsupported", "migrate_not_in_v6", {}),
    ("settings", "dashboard_queries"): ("unsupported", "migrate_not_in_v6", {}),
    ("web_gui", "public_url"): ("unsupported", "migrate_arrives_in_phase", {"phase": "P3"}),
    ("logging", "json_sink"): ("unsupported", "migrate_not_in_v6", {}),
    ("logging", "rotation"): ("unsupported", "migrate_not_in_v6", {}),
    ("logging", "retention"): ("unsupported", "migrate_not_in_v6", {}),
}
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
    reason_if_changed: str = "migrate_normalized"


def _tz(v5: V5Config) -> str:
    tz = v5.settings.timezone or "local"  # 5.x: empty means local
    try:
        DisplaySettings(language=Language.EN, timezone=tz)
    except ValidationError:
        return "UTC"  # 5.x resolve_tz falls back to UTC for anything it cannot parse
    return tz


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
    ("web_gui", "allowed_ips"): _Carry("web.allowed_ips", lambda v: list(v.web_gui.allowed_ips)),
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
}


def _set(d: dict[str, Any], dotted: str, value: Any) -> None:
    *parents, leaf = dotted.split(".")
    for p in parents:
        d = d[p]
    d[leaf] = value


def migrate_v5(raw: dict[str, Any]) -> MigrationResult:
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
    org = v5.api.org_id
    if org.isdigit():
        out["pce"]["org_id"] = org
    else:
        blocking.append(("api.org_id", "a PCE organization ID is a number"))
    for path, carry in CARRY.items():
        _set(out, carry.target, carry.convert(v5))

    for path in leaf_paths(raw):
        source = show(path)
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
            add(MigrationItem(source, carry.target, "carried" if same else "rewritten",
                              "migrate_carried" if same else carry.reason_if_changed))
        elif path in SPECIAL:
            action, reason, params = SPECIAL[path]
            add(MigrationItem(source, None, action, reason, params))
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
