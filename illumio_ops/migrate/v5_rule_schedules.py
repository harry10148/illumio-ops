"""5.x rule schedules (config/rule_schedules.json) → v6 (UI redesign spec §4.5). Every schedule that can be read is
carried **paused**: the operator turns each on (as report schedules and new alert rules arrive on an upgrade). The
upgrade does not reach the PCE, so it does not check the targets; a schedule whose target is gone is marked deleted
at its first check once turned on. An entry that cannot be read is reported with the reason and left out."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from illumio_ops.domain.rule_schedule import WEEKDAYS, Expiry, Plan, Weekly
from illumio_ops.migrate.report import MigrationItem
from illumio_ops.store import rule_schedules as store

FILE = "config/rule_schedules.json"
_TARGET = re.compile(r"^/orgs/\d+/sec_policy/(active|draft)/rule_sets/\d+(/(sec_rules|deny_rules)/\d+)?$")
_OFFSET = re.compile(r"^UTC([+-])(\d{1,2})(?:\.(\d+))?$")
DISABLING = ("block", "disable", "deny")


@dataclass(frozen=True)
class Converted:
    href: str
    is_ruleset: bool
    name: str
    ruleset_name: str
    summary: str
    plan: Plan


def _zone(value: Any, local_zone: str | None) -> tuple[str, bool]:
    """(an IANA zone, whether it had to fall back to UTC). 5.x wrote "local" (the host's zone), an IANA name, or
    "UTC+8" (its note format)."""
    text = str(value or "local").strip()
    if text.lower() == "local":
        return (local_zone, False) if local_zone else ("UTC", True)
    m = _OFFSET.match(text)
    if m and not m.group(3):  # Etc/GMT signs are inverted: UTC+8 is Etc/GMT-8
        return f"Etc/GMT{'-' if m.group(1) == '+' else '+'}{int(m.group(2))}", False
    if m:  # 5.x accepted UTC+5.5 and UTC+5.75: kept as the fixed offset (no IANA name says it exactly)
        minutes = round(float(f"0.{m.group(3)}") * 60)
        return f"UTC{m.group(1)}{int(m.group(2)):02d}:{minutes:02d}", False
    try:
        ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"unknown time zone {text!r}") from None
    return text, False


def _days(raw: Any) -> tuple[str, ...]:
    out = []
    for d in raw or []:
        short = str(d).strip().lower()[:3]
        if short not in WEEKDAYS:
            raise ValueError(f"unknown day {d!r}")
        if short not in out:
            out.append(short)
    return tuple(out)


def _plan(entry: dict[str, Any], zone: str) -> Plan:
    kind = entry.get("type")
    if kind == "recurring":
        action = "disable_in_window" if str(entry.get("action", "allow")).lower() in DISABLING else "enable_in_window"
        return Weekly.model_validate({"days": _days(entry.get("days")), "start": str(entry.get("start", "")),
                                      "end": str(entry.get("end", "")), "timezone": zone, "action": action})
    if kind == "one_time":
        at = datetime.fromisoformat(str(entry.get("expire_at", "")))
        if at.tzinfo is None:  # 5.x compared the wall clock in the schedule's zone
            at = at.replace(tzinfo=ZoneInfo(zone))
        return Expiry(expire_at=at, timezone=zone)
    raise ValueError(f"unknown schedule type {kind!r}")


def convert(raw: dict[str, Any] | None, *, local_zone: str | None) -> tuple[list[Converted], list[MigrationItem]]:
    if not raw:
        return [], [MigrationItem(FILE, None, "dropped", "migrate_rule_schedule_none")]
    done: list[Converted] = []
    items: list[MigrationItem] = []
    for href, entry in raw.items():
        source = f"{FILE}: {href}"
        known = entry if isinstance(entry, dict) else {}
        name = str(known.get("detail_name") or known.get("name") or href)
        try:
            if not _TARGET.match(str(href)) or not isinstance(entry, dict):
                raise ValueError("not a rule or rule set")
            zone, utc = _zone(entry.get("timezone"), local_zone)
            plan = _plan(entry, zone)
        except (ValueError, ValidationError) as exc:
            why = str(exc).splitlines()[0][:200]
            items.append(MigrationItem(source, None, "dropped", "migrate_rule_schedule_unreadable",
                                       {"name": name, "why": why}))
            continue
        parts = [str(entry.get(k) or "") for k in ("detail_src", "detail_dst", "detail_svc")]
        summary = f"{parts[0]} → {parts[1]}: {parts[2]}" if any(parts) else ""
        done.append(Converted(href=str(href).replace("/sec_policy/draft/", "/sec_policy/active/"),
                              is_ruleset="/sec_rules/" not in str(href) and "/deny_rules/" not in str(href), name=name,
                              ruleset_name=str(entry.get("detail_rs") or ""), summary=summary, plan=plan))
        items.append(MigrationItem(source, "rule_schedules", "rewritten",
                                   "migrate_rule_schedule_paused_utc" if utc else "migrate_rule_schedule_paused",
                                   {"name": name}))
    return done, items


def write(conn: sqlite3.Connection, converted: list[Converted], *, pce_url: str, org_id: str, now: datetime) -> None:
    for c in converted:
        store.create(conn, pce_url=pce_url, org_id=org_id, href=c.href, is_ruleset=c.is_ruleset, name=c.name,
                     ruleset_name=c.ruleset_name, summary=c.summary, plan_json=c.plan.model_dump_json(), paused=True,
                     pce_status="unknown", by="migrated-5.x", at=now)


def host_zone() -> str | None:
    """The host's own IANA zone ("local" in 5.x), from /etc/localtime; None when it cannot be told."""
    try:
        from pathlib import Path
        target = Path("/etc/localtime").resolve()
        parts = target.parts
        if "zoneinfo" in parts:
            name = "/".join(parts[parts.index("zoneinfo") + 1:])
            ZoneInfo(name)
            return name
    except (OSError, ZoneInfoNotFoundError, ValueError):
        pass
    return None
