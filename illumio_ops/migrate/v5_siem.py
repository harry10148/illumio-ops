"""5.x SIEM forwarding → v6 (spec §7, P7). Every destination is carried, rewritten, paused or dropped, and the report
says which and why. 5.x forwarded traffic records; v6 does not (they are daily running totals a SIEM would add up),
so a traffic source becomes the new-connection source with the same decision filter. A destination v6 would refuse
as it stands (on but missing its host or its HEC token) is carried paused, never dropped silently or widened."""
from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from illumio_ops.domain.values import (
    CollectionMode,
    PolicyDecision,
    SiemFormat,
    SiemTransport,
)
from illumio_ops.migrate.report import MigrationItem
from illumio_ops.settings.schema import SiemDestination, default_siem

MAX_DESTINATIONS = 20
DEST_KEYS = {"name", "enabled", "transport", "format", "host", "port", "endpoint", "profile", "tls_verify",
             "tls_ca_bundle", "framing", "hec_token", "batch_size", "source_types", "traffic_pd", "max_retries",
             "mask_pii"}
SECTION_KEYS = {"enabled", "destinations", "dlq_max_per_dest", "dispatch_tick_seconds"}


def _item(source: str, target: str | None, action: str, reason: str, **params: str) -> MigrationItem:
    return MigrationItem(source, target, action, reason, params)  # type: ignore[arg-type]


def _clamp(value: Any, lo: int, hi: int, default: int) -> int:
    return min(max(value, lo), hi) if isinstance(value, int) and not isinstance(value, bool) else default


def _host_port(d: dict[str, Any], transport: str) -> tuple[str, int]:
    """5.x's legacy `endpoint` ("host:port", or a HEC URL) when host is not set (config_models._migrate_endpoint)."""
    host, port = str(d.get("host") or "").strip(), d.get("port")
    endpoint = str(d.get("endpoint") or "").strip()
    if endpoint and not host:
        if transport == "hec":
            parsed = urlparse(endpoint)
            host, port = parsed.hostname or endpoint, parsed.port or 8088
        else:
            h, _, p = endpoint.rpartition(":")
            host, port = (h, int(p)) if h and p.isdigit() else (h or endpoint, port)
    return host, port if isinstance(port, int) and 1 <= port <= 65535 else 514


def _destination(i: int, d: dict[str, Any], names: set[str], mode: CollectionMode,
                 items: list[MigrationItem]) -> dict[str, Any] | None:
    label = f"siem.destinations[{i}]"
    name = str(d.get("name") or "").strip()[:64] or f"siem-{i + 1}"
    base = name
    n = 2
    while name.casefold() in names:
        name = f"{base[:58]} ({n})"
        n += 1
    names.add(name.casefold())
    if name != str(d.get("name") or "").strip():
        items.append(_item(f"{label}.name", f"siem.destinations.{name}.name", "rewritten", "migrate_siem_renamed"))
    target = f"siem.destinations.{name}"
    transport = str(d.get("transport") or "udp").lower()
    fmt = str(d.get("format") or "cef")
    if transport not in {t.value for t in SiemTransport} or fmt not in {f.value for f in SiemFormat}:
        items.append(_item(label, None, "unsupported", "migrate_siem_unknown_transport"))
        return None
    host, port = _host_port(d, transport)
    if d.get("endpoint") and not d.get("host"):
        items.append(_item(f"{label}.endpoint", f"{target}.host", "rewritten", "migrate_alias_key"))
    verify: bool | str = d.get("tls_verify") is not False
    bundle = d.get("tls_ca_bundle")
    if verify and isinstance(bundle, str) and bundle.strip():
        if bundle.strip().startswith("/"):
            verify = bundle.strip()
        else:
            items.append(_item(f"{label}.tls_ca_bundle", None, "unsupported", "migrate_siem_ca_relative"))
    if "profile" in d:
        items.append(_item(f"{label}.profile", None, "dropped", "migrate_siem_profile_dropped"))
    if verify is False:
        items.append(_item(f"{label}.tls_verify", f"{target}.verify_tls", "carried", "migrate_siem_tls_unverified"))
    types = d.get("source_types")
    types = ["audit", "traffic"] if types is None else [str(t) for t in types] if isinstance(types, list) else []
    sources: list[str] = []
    for t in types:
        if t == "audit" and "audit" not in sources:
            sources.append("audit")
        elif t == "traffic" and "new_connections" not in sources:
            sources.append("new_connections")
            items.append(_item(f"{label}.source_types.traffic", f"{target}.sources.new_connections", "rewritten",
                               "migrate_siem_traffic_to_new_connections"))
            if mode is CollectionMode.LIGHTWEIGHT:
                items.append(_item(f"{label}.source_types.traffic", f"{target}.sources.new_connections", "rewritten",
                                   "migrate_siem_needs_alert_mode"))
        elif t not in ("audit", "traffic"):
            items.append(_item(f"{label}.source_types.{t}", None, "unsupported", "migrate_siem_source_unknown"))
    decisions = [str(x) for x in d.get("traffic_pd") or [] if str(x) in {p.value for p in PolicyDecision}]
    if "new_connections" not in sources:
        decisions = []
    elif d.get("traffic_pd"):
        items.append(_item(f"{label}.traffic_pd", f"{target}.new_connection_decisions", "carried", "migrate_carried"))
    retries = d.get("max_retries", 10)
    if isinstance(retries, int) and retries < 1:
        items.append(_item(f"{label}.max_retries", f"{target}.max_retries", "rewritten", "migrate_siem_retries_raised"))
    out: dict[str, Any] = {
        "id": hashlib.md5(f"siem|{i}|{name}".encode(), usedforsecurity=False).hexdigest(), "name": name,
        "enabled": d.get("enabled", True) is not False, "transport": transport, "format": fmt, "host": host,
        "port": port, "framing": "octet_counting" if d.get("framing") == "octet_counting" else "lf",
        "verify_tls": verify, "hec_token": str(d.get("hec_token") or ""),
        "batch_size": _clamp(d.get("batch_size"), 1, 10_000, 100), "max_retries": _clamp(retries, 1, 100, 10),
        "sources": sources or ["audit"], "new_connection_decisions": decisions, "mask_pii": bool(d.get("mask_pii"))}
    if not sources:
        items.append(_item(f"{label}.source_types", f"{target}.sources", "rewritten", "migrate_siem_no_source"))
    for key in sorted(set(d) - DEST_KEYS):
        items.append(_item(f"{label}.{key}", None, "unsupported", "migrate_unknown_key"))
    try:
        SiemDestination.model_validate(out)
    except ValidationError:
        out["enabled"] = False  # on but incomplete (no host, a HEC destination without its token): carried paused
        try:
            SiemDestination.model_validate(out)
        except ValidationError:
            items.append(_item(label, None, "unsupported", "migrate_siem_unreadable"))
            return None
        items.append(_item(label, target, "rewritten", "migrate_siem_paused_incomplete"))
        return out
    items.append(_item(label, target, "carried", "migrate_carried"))
    return out


def migrate_siem(raw: dict[str, Any], *, mode: CollectionMode) -> tuple[dict[str, Any], list[MigrationItem]]:
    """The v6 `siem` section and an item per 5.x siem key (and pce_cache.siem_pending_warn_rows). Values never appear
    in the report — a HEC token is listed by its key only."""
    items: list[MigrationItem] = []
    out: dict[str, Any] = default_siem().model_dump(mode="json")
    section = raw.get("siem") if isinstance(raw.get("siem"), dict) else {}
    assert isinstance(section, dict)
    if "enabled" in section:
        out["enabled"] = section["enabled"] is True
        items.append(_item("siem.enabled", "siem.enabled", "carried", "migrate_carried"))
    for key, target, lo, hi in (("dlq_max_per_dest", "dlq_max_per_dest", 100, 1_000_000),
                                ("dispatch_tick_seconds", "tick_seconds", 10, 600)):
        if key in section:
            value = section[key]
            out[target] = _clamp(value, lo, hi, out[target])
            same = value == out[target]
            items.append(_item(f"siem.{key}", f"siem.{target}", "carried" if same else "rewritten",
                               "migrate_carried" if same else "migrate_raised_to_minimum" if isinstance(value, int)
                               and value < lo else "migrate_lowered_to_maximum"))
    cache = raw.get("pce_cache") if isinstance(raw.get("pce_cache"), dict) else {}
    assert isinstance(cache, dict)
    if "siem_pending_warn_rows" in cache:
        value = cache["siem_pending_warn_rows"]
        out["backlog_warn_rows"] = _clamp(value, 1_000, 10_000_000, out["backlog_warn_rows"])
        items.append(_item("pce_cache.siem_pending_warn_rows", "siem.backlog_warn_rows",
                           "carried" if value == out["backlog_warn_rows"] else "rewritten",
                           "migrate_carried" if value == out["backlog_warn_rows"] else "migrate_normalized"))
    for key in sorted(set(section) - SECTION_KEYS):
        items.append(_item(f"siem.{key}", None, "unsupported", "migrate_unknown_key"))
    dests = section.get("destinations") if isinstance(section.get("destinations"), list) else []
    assert isinstance(dests, list)
    names: set[str] = set()
    carried: list[dict[str, Any]] = []
    for i, d in enumerate(dests):
        if not isinstance(d, dict):
            items.append(_item(f"siem.destinations[{i}]", None, "unsupported", "migrate_siem_unreadable"))
            continue
        if len(carried) >= MAX_DESTINATIONS:
            items.append(_item(f"siem.destinations[{i}]", None, "unsupported", "migrate_siem_too_many"))
            continue
        made = _destination(i, d, names, mode, items)
        if made is not None:
            carried.append(made)
    out["destinations"] = carried
    if "destinations" in section:  # the list as one key; each destination is listed below it
        items.append(_item("siem.destinations", "siem.destinations", "rewritten" if dests else "carried",
                           "migrate_siem_destinations_listed" if dests else "migrate_carried"))
    return out, items
