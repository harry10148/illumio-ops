"""Read a 5.x config/config.json and produce v6 settings plus a report covering every key.

P1 carries the PCE connection, web UI (incl. TLS), display and logging level. Every other
key is reported, never silently skipped: either "not migrated yet" with the v6 phase that
brings it, "not in v6", or dropped with a reason.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from illumio_ops.migrate.report import Action, MigrationItem, MigrationReport
from illumio_ops.settings.schema import Settings, default_settings
from illumio_ops.settings.secrets import (
    DEFAULT_ADMIN_PASSWORD,
    hash_password,
    new_secret_key,
)
from illumio_ops.settings.store import validate_settings

# Keys 5.x itself had already removed (src/config.py _DEPRECATED_KEY_PATHS at v5.0.0); a prefix
# covers everything under it.
DEPRECATED_PREFIXES = ("report.attack_surface", "web_gui.tls.http_redirect_port", "pce_profiles",
                       "active_pce_id", "pce_cache.archive_review_max_days")
# Whole 5.x sections that later v6 phases migrate (roadmap).
PHASE_OF_SECTION = {"pce_cache": "P2", "alerts": "P3", "email": "P3", "smtp": "P3", "rules": "P3",
                    "siem": "P4", "report": "P5", "report_schedules": "P5"}
NOT_IN_V6_SECTIONS = ("rule_scheduler", "scheduler", "rule_backups")

# 5.x leaf -> v6 settings path, value carried unchanged
DIRECT: dict[str, str] = {
    "api.url": "pce.url",
    "api.org_id": "pce.org_id",
    "api.key": "pce.api_key",
    "api.secret": "pce.api_secret",
    "api.verify_ssl": "pce.verify_tls",
    "api.deployment_type": "pce.deployment_type",
    "api.events_timeout_seconds": "pce.events_timeout_seconds",
    "web_gui.username": "web.username",
    "web_gui.allowed_ips": "web.allowed_ips",
    "web_gui.session_lifetime_seconds": "web.session_lifetime_seconds",
    "web_gui.must_change_password": "web.must_change_password",
    "settings.language": "display.language",
    "settings.timezone": "display.timezone",
    "logging.level": "logging.level",
    **{f"web_gui.tls.{k}": f"web.tls.{k}" for k in (
        "enabled", "cert_file", "key_file", "auto_renew", "auto_renew_days", "validity_days",
        "key_algorithm", "min_version", "ciphers")},
}
# 5.x leaf -> (action, reason key, params): reported, not carried
SPECIAL: dict[str, tuple[Action, str, dict[str, str]]] = {
    "api.profile": ("dropped", "migrate_no_profiles", {}),
    "settings.enable_health_check": ("dropped", "migrate_always_on", {}),
    "settings.theme": ("unsupported", "migrate_not_in_v6", {}),
    "settings.dashboard_queries": ("unsupported", "migrate_not_in_v6", {}),
    "web_gui.public_url": ("unsupported", "migrate_arrives_in_phase", {"phase": "P3"}),
    "logging.json_sink": ("unsupported", "migrate_not_in_v6", {}),
    "logging.rotation": ("unsupported", "migrate_not_in_v6", {}),
    "logging.retention": ("unsupported", "migrate_not_in_v6", {}),
}
_HEX_KEY = re.compile(r"[0-9a-f]{64,}")


def leaf_keys(node: Any, prefix: str = "") -> list[str]:
    """Dotted paths of every leaf; a list or an empty object counts as one leaf."""
    if isinstance(node, dict) and node:
        out: list[str] = []
        for k, v in node.items():
            out += leaf_keys(v, f"{prefix}.{k}" if prefix else str(k))
        return out
    return [prefix]


def _get(raw: dict[str, Any], path: str) -> Any:
    node: Any = raw
    for part in path.split("."):
        node = node[part]
    return node


def _set(d: dict[str, Any], path: str, value: Any) -> None:
    *parents, leaf = path.split(".")
    for p in parents:
        d = d[p]
    d[leaf] = value


def read_v5(v5_root: Path) -> dict[str, Any]:
    data = json.loads((v5_root / "config" / "config.json").read_text(encoding="utf-8"))
    if not (isinstance(data, dict) and isinstance(data.get("api"), dict) and isinstance(data.get("web_gui"), dict)
            and "schema_version" not in data):
        raise ValueError("this is not a 5.x config.json (no api / web_gui sections)")
    return data


def migrate_v5(raw: dict[str, Any]) -> tuple[Settings, MigrationReport]:
    report = MigrationReport()
    add = report.items.append
    password = raw.get("web_gui", {}).get("password") or ""
    if password.startswith("$argon2"):
        password_hash, pw_item = password, MigrationItem("web_gui.password", "web.password_hash", "carried",
                                                         "migrate_carried")
    elif password:
        password_hash, pw_item = hash_password(password), MigrationItem(
            "web_gui.password", "web.password_hash", "rewritten", "migrate_password_hashed")
    else:
        password_hash, pw_item = hash_password(DEFAULT_ADMIN_PASSWORD), MigrationItem(
            "web_gui.password", "web.password_hash", "rewritten", "migrate_password_default")
    secret_key = raw.get("web_gui", {}).get("secret_key") or ""
    if _HEX_KEY.fullmatch(secret_key):
        key_item = MigrationItem("web_gui.secret_key", "web.secret_key", "carried", "migrate_carried")
    else:
        secret_key = new_secret_key()
        key_item = MigrationItem("web_gui.secret_key", "web.secret_key", "rewritten", "migrate_secret_key_new")

    out = default_settings(password_hash=password_hash, secret_key=secret_key).model_dump(mode="json")
    for source in leaf_keys(raw):
        section = source.split(".", 1)[0]
        if any(source == p or source.startswith(p + ".") for p in DEPRECATED_PREFIXES):
            add(MigrationItem(source, None, "dropped", "migrate_deprecated_in_5x"))
        elif source == "web_gui.password":
            add(pw_item)
        elif source == "web_gui.secret_key":
            add(key_item)
        elif source in DIRECT:
            value = _get(raw, source)
            if source == "api.org_id":
                value = str(value)
            _set(out, DIRECT[source], value)
            add(MigrationItem(source, DIRECT[source], "carried", "migrate_carried"))
        elif source == "api.console_url":
            value = _get(raw, source) or None
            _set(out, "pce.console_url", value)
            add(MigrationItem(source, "pce.console_url", "carried" if value else "rewritten",
                              "migrate_carried" if value else "migrate_empty_is_unset"))
        elif source == "web_gui.tls.self_signed":
            mode = "self_signed" if _get(raw, source) else "provided"
            _set(out, "web.tls.mode", mode)
            add(MigrationItem(source, "web.tls.mode", "rewritten", "migrate_tls_source"))
        elif source in SPECIAL:
            action, reason, params = SPECIAL[source]
            add(MigrationItem(source, None, action, reason, params))
        elif section in PHASE_OF_SECTION:
            add(MigrationItem(source, None, "unsupported", "migrate_arrives_in_phase",
                              {"phase": PHASE_OF_SECTION[section]}))
        elif section in NOT_IN_V6_SECTIONS:
            add(MigrationItem(source, None, "unsupported", "migrate_not_in_v6"))
        else:
            add(MigrationItem(source, None, "unsupported", "migrate_unknown_key"))
    return validate_settings(out), report
