"""Alert records and their bookkeeping in data/app.sqlite (owner of alerts, alert_deliveries, alert_notes,
alert_rule_state, alert_rule_status, alert_eval_state and channel_state). The services decide; this module
only stores."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from illumio_ops.domain.alert_devices import (
    Device,
    capped,
    devices_of_detection,
    devices_of_events,
)
from illumio_ops.domain.alertcategory import CATEGORIES, category_filter
from illumio_ops.domain.alerting import RuleState, Trigger
from illumio_ops.domain.segment import EventSegment
from illumio_ops.domain.values import DeliveryStatus

NOT_SENT = "-"  # the channel of the one delivery row of an alert that is not sent


def _t(value: datetime) -> str:
    return value.isoformat()


def evidence_json(trigger: Trigger) -> str | None:
    if trigger.evidence is None:
        return None
    kind = "event" if isinstance(trigger.evidence, EventSegment) else "flow"
    return json.dumps({"kind": kind, "segment": trigger.evidence.model_dump(mode="json")})


def insert_alert(conn: sqlite3.Connection, *, pce_url: str, org_id: str, rule_name: str, pack_key: str | None,
                 trigger: Trigger, at: datetime, channels: Sequence[str], hold: DeliveryStatus | None) -> int:
    """One alert and its delivery rows: a pending row per channel; with hold (not_notified, grouped) one row
    saying so; with no channel enabled one no_channel row. An alert is never stored without a delivery row.
    The caller commits (the evaluation records a batch's alerts, rule states and watermark together)."""
    # Above every id ever used (alert_id_floor): the SIEM reads alerts after the last id it sent, so a deleted newest
    # alert's id is never given again (0012).
    cur = conn.execute(
        "INSERT INTO alerts (id, pce_url, org_id, rule_id, rule_type, rule_name, pack_key, severity, subject_key, "
        "fired_at, first_seen, last_seen, late, notify, grouped_annotation, message_key, params_json, facts_json, "
        "evidence_json, confidence_json, devices_more) VALUES ((SELECT MAX(COALESCE((SELECT MAX(id) FROM alerts), 0), "
        "COALESCE((SELECT id FROM alert_id_floor), 0)) + 1), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (pce_url, org_id, trigger.rule_id, trigger.rule_type.value, rule_name, pack_key, trigger.severity.value,
         trigger.subject_key, _t(at), _t(trigger.first_seen), _t(trigger.last_seen), int(trigger.late),
         int(hold is None), trigger.grouped_annotation, trigger.message_key,
         json.dumps(trigger.params, default=str), json.dumps(trigger.facts, default=str), evidence_json(trigger),
         json.dumps(asdict(trigger.confidence), default=str), trigger.devices_more))
    alert_id = int(cur.lastrowid or 0)
    _write_devices(conn, alert_id, trigger.devices)
    rows: list[tuple[int, str, str, int, str | None]]
    if hold is not None:
        rows = [(alert_id, NOT_SENT, hold.value, 0, None)]
    elif not channels:
        rows = [(alert_id, NOT_SENT, DeliveryStatus.NO_CHANNEL.value, 0, None)]
    else:
        rows = [(alert_id, c, DeliveryStatus.PENDING.value, 0, _t(at)) for c in channels]
    conn.executemany("INSERT INTO alert_deliveries (alert_id, channel, status, attempts, next_attempt_at) "
                     "VALUES (?, ?, ?, ?, ?)", rows)
    return alert_id


def _write_devices(conn: sqlite3.Connection, alert_id: int, found: Sequence[Device]) -> None:
    conn.executemany("INSERT OR IGNORE INTO alert_devices (alert_id, key, role) VALUES (?, ?, ?)",
                     [(alert_id, d.key, d.role) for d in found])


def devices(conn: sqlite3.Connection, alert_ids: Sequence[int]) -> dict[int, list[Device]]:
    """The hosts each alert is about, in the order they were stored; an alert about none is absent."""
    out: dict[int, list[Device]] = {}
    for chunk in (alert_ids[i:i + 500] for i in range(0, len(alert_ids), 500)):
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(f"SELECT alert_id, key, role FROM alert_devices WHERE alert_id IN ({marks}) "
                              "ORDER BY alert_id, rowid", list(chunk)):
            out.setdefault(int(r["alert_id"]), []).append(Device(r["key"], r["role"]))
    return out


def backfill_devices(conn: sqlite3.Connection) -> int:
    """Alerts stored before hosts were recorded (0018) are given theirs, once: a detection's from its fingerprint (the
    alert's subject), an event rule's when its subject is the host. What names no host is left as it is — and is not
    looked at again, as nothing about it changes. Returns how many alerts were given hosts."""
    rows = conn.execute(
        "SELECT id, rule_type, subject_key FROM alerts WHERE rule_type IN ('lateral', 'event') "
        "AND NOT EXISTS (SELECT 1 FROM alert_devices d WHERE d.alert_id = alerts.id)").fetchall()
    given = 0
    with conn:
        for r in rows:
            found = (devices_of_detection(r["subject_key"]) if r["rule_type"] == "lateral"
                     else devices_of_events([r["subject_key"]]))
            kept, more = capped(found)
            if not kept:
                continue
            _write_devices(conn, int(r["id"]), kept)
            if more:
                conn.execute("UPDATE alerts SET devices_more = ? WHERE id = ?", (more, int(r["id"])))
            given += 1
    return given


def _where(*, pce_url: str, org_id: str, since: datetime, rule_types: Sequence[str] | None = None,
           severity: str | None = None, rule_id: str | None = None, detectors_in: Sequence[str] | None = None,
           detectors_not_in: Sequence[str] | None = None, ungrouped_only: bool = False,
           device: str | None = None, fired_after: datetime | None = None,
           until: datetime | None = None) -> tuple[str, list[Any]]:
    clauses, params = ["pce_url = ?", "org_id = ?", "fired_at >= ?"], [pce_url, org_id, _t(since)]
    if until is not None:  # a period's end, not included
        clauses.append("fired_at < ?")
        params.append(_t(until))
    for column, value in (("severity", severity), ("rule_id", rule_id)):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if rule_types:
        clauses.append(f"rule_type IN ({','.join('?' * len(rule_types))})")
        params.extend(rule_types)
    detector = "json_extract(params_json, '$.detector')"
    if detectors_in:
        clauses.append(f"{detector} IN ({','.join('?' * len(detectors_in))})")
        params.extend(detectors_in)
    if detectors_not_in:
        clauses.append(f"({detector} IS NULL OR {detector} NOT IN ({','.join('?' * len(detectors_not_in))}))")
        params.extend(detectors_not_in)
    if ungrouped_only:
        clauses.append("grouped_annotation IS NULL")
    if device:
        clauses.append("id IN (SELECT alert_id FROM alert_devices WHERE key = ?)")
        params.append(device)
    if fired_after is not None:
        clauses.append("fired_at > ?")
        params.append(_t(fired_after))
    return " AND ".join(clauses), params


def set_grouped(conn: sqlite3.Connection, alert_id: int, annotation_id: int, *, pce_url: str, org_id: str) -> None:
    """An alert an operator marked known: grouped under that mark from now on (an alert already grouped keeps the
    mark that grouped it)."""
    conn.execute("UPDATE alerts SET grouped_annotation = ? WHERE id = ? AND pce_url = ? AND org_id = ? "
                 "AND grouped_annotation IS NULL", (annotation_id, alert_id, pce_url, org_id))


def list_alerts(conn: sqlite3.Connection, *, pce_url: str, org_id: str, since: datetime, rule_type: str | None = None,
                severity: str | None = None, rule_id: str | None = None, rule_types: Sequence[str] | None = None,
                detectors_in: Sequence[str] | None = None, detectors_not_in: Sequence[str] | None = None,
                ungrouped_only: bool = False, device: str | None = None, fired_after: datetime | None = None,
                limit: int, offset: int) -> tuple[list[sqlite3.Row], int]:
    """rule_types / detectors_in / detectors_not_in: a category's filter (domain/alertcategory.py); detectors are the
    lateral alert's `detector` parameter. device: only the alerts about this host (its key)."""
    types = rule_types if rule_types else ((rule_type,) if rule_type else None)
    where, params = _where(pce_url=pce_url, org_id=org_id, since=since, rule_types=types, severity=severity,
                           rule_id=rule_id, detectors_in=detectors_in, detectors_not_in=detectors_not_in,
                           ungrouped_only=ungrouped_only, device=device, fired_after=fired_after)
    rows = conn.execute(f"SELECT * FROM alerts WHERE {where} ORDER BY fired_at DESC, id DESC LIMIT ? OFFSET ?",
                        [*params, limit, offset]).fetchall()
    total = conn.execute(f"SELECT COUNT(*) FROM alerts WHERE {where}", params).fetchone()[0]
    return rows, int(total)


def period_counts(conn: sqlite3.Connection, *, pce_url: str, org_id: str, since: datetime,
                  until: datetime | None = None) -> dict[str, int]:
    """Alerts fired since `since` (and before `until`, when given) per severity, and how many were marked as known
    (`grouped`: a count across the severities, not one more of them)."""
    where, params = _where(pce_url=pce_url, org_id=org_id, since=since, until=until)
    out = {r[0]: int(r[1]) for r in conn.execute(
        f"SELECT severity, COUNT(*) FROM alerts WHERE {where} GROUP BY severity", params)}
    out["grouped"] = int(conn.execute(f"SELECT COUNT(*) FROM alerts WHERE {where} AND grouped_annotation IS NOT NULL",
                                      params).fetchone()[0])
    return out


def counts_by_category(conn: sqlite3.Connection, *, pce_url: str, org_id: str, since: datetime,
                       until: datetime) -> dict[str, int]:
    """Alerts fired in [since, until) per category of the alerts page (domain/alertcategory.py CATEGORIES, each
    counted with the filter the page lists it by)."""
    out: dict[str, int] = {}
    for cat in CATEGORIES:
        types, must, must_not = category_filter(cat)
        out[cat] = count_alerts(conn, pce_url=pce_url, org_id=org_id, since=since, until=until, rule_types=types,
                                detectors_in=must, detectors_not_in=must_not)
    return out


def first_fired_at(conn: sqlite3.Connection, *, pce_url: str, org_id: str) -> datetime | None:
    """When the oldest alert of this PCE still kept was raised; None when it has none."""
    row = conn.execute("SELECT MIN(fired_at) FROM alerts WHERE pce_url = ? AND org_id = ?", (pce_url, org_id)).fetchone()
    return datetime.fromisoformat(row[0]) if row[0] else None


def alerted_devices(conn: sqlite3.Connection, *, pce_url: str, org_id: str, since: datetime,
                    until: datetime | None = None) -> list[sqlite3.Row]:
    """The hosts the period's alerts are about: key, how many alerts (n), the highest severity among them (rank: 3
    critical … 0 low) and the latest (last) — most alerted first, then most recent. until: the period's end, not
    included (None: up to now)."""
    before, more = ("AND a.fired_at < ? ", (_t(until),)) if until is not None else ("", ())
    return conn.execute(
        "SELECT d.key AS key, COUNT(DISTINCT a.id) AS n, MAX(a.fired_at) AS last, "
        "MAX(CASE a.severity WHEN 'critical' THEN 3 WHEN 'high' THEN 2 WHEN 'medium' THEN 1 ELSE 0 END) AS rank "
        "FROM alert_devices d JOIN alerts a ON a.id = d.alert_id "
        f"WHERE a.pce_url = ? AND a.org_id = ? AND a.fired_at >= ? {before}"
        "GROUP BY d.key ORDER BY n DESC, last DESC, d.key", (pce_url, org_id, _t(since), *more)).fetchall()


def devices_recorded_since(conn: sqlite3.Connection, *, pce_url: str, org_id: str) -> datetime | None:
    """Since when alerts record their hosts (0020): before it, "the alerts about this host" cannot be complete —
    earlier alerts were given hosts only where those could be read back. None when no alert of this PCE is older."""
    since = datetime.fromisoformat(conn.execute("SELECT at FROM alert_devices_since WHERE id = 1").fetchone()[0])
    older = conn.execute("SELECT 1 FROM alerts WHERE pce_url = ? AND org_id = ? AND fired_at < ? LIMIT 1",
                         (pce_url, org_id, _t(since))).fetchone()
    return since if older else None


def seen_at(conn: sqlite3.Connection) -> datetime:
    """When the alerts page was last opened (0019 gives every installation a first time)."""
    return datetime.fromisoformat(conn.execute("SELECT seen_at FROM alerts_seen WHERE id = 1").fetchone()[0])


def mark_seen(conn: sqlite3.Connection, at: datetime) -> datetime:
    """The alerts page was opened at `at`; answers when it was opened before."""
    before = seen_at(conn)
    with conn:
        conn.execute("UPDATE alerts_seen SET seen_at = ? WHERE id = 1", (_t(at),))
    return before


def count_new(conn: sqlite3.Connection, *, pce_url: str, org_id: str, after: datetime, since: datetime | None = None) -> int:
    """Alerts fired after `after` (and, when given, since `since`): what the page has not shown yet."""
    row = conn.execute("SELECT COUNT(*) FROM alerts WHERE pce_url = ? AND org_id = ? AND fired_at > ? AND fired_at >= ?",
                       (pce_url, org_id, _t(after), _t(since) if since else "")).fetchone()
    return int(row[0])


def count_alerts(conn: sqlite3.Connection, *, pce_url: str, org_id: str, since: datetime,
                 rule_types: Sequence[str] | None = None, severity: str | None = None, rule_id: str | None = None,
                 detectors_in: Sequence[str] | None = None, detectors_not_in: Sequence[str] | None = None,
                 ungrouped_only: bool = False, device: str | None = None, fired_after: datetime | None = None,
                 until: datetime | None = None) -> int:
    """How many alerts the same filters as list_alerts match; until: only those fired before it."""
    where, params = _where(pce_url=pce_url, org_id=org_id, since=since, rule_types=rule_types, severity=severity,
                           rule_id=rule_id, detectors_in=detectors_in, detectors_not_in=detectors_not_in,
                           ungrouped_only=ungrouped_only, device=device, fired_after=fired_after, until=until)
    return int(conn.execute(f"SELECT COUNT(*) FROM alerts WHERE {where}", params).fetchone()[0])


def count_ungrouped(conn: sqlite3.Connection, *, pce_url: str, org_id: str, since: datetime) -> int:
    """Alerts fired since `since` that nobody marked as known (no grouped annotation): the shell's unprocessed count."""
    row = conn.execute("SELECT COUNT(*) FROM alerts WHERE pce_url = ? AND org_id = ? AND fired_at >= ? "
                       "AND grouped_annotation IS NULL", (pce_url, org_id, _t(since))).fetchone()
    return int(row[0])


def get_alert(conn: sqlite3.Connection, alert_id: int, *, pce_url: str, org_id: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute("SELECT * FROM alerts WHERE id = ? AND pce_url = ? AND org_id = ?",
                                           (alert_id, pce_url, org_id)).fetchone()
    return row


def alerts_by_id(conn: sqlite3.Connection, ids: Sequence[int]) -> list[sqlite3.Row]:
    if not ids:
        return []
    return conn.execute(f"SELECT * FROM alerts WHERE id IN ({','.join('?' * len(ids))}) ORDER BY id", list(ids)).fetchall()


def deliveries(conn: sqlite3.Connection, alert_ids: Sequence[int]) -> list[sqlite3.Row]:
    if not alert_ids:
        return []
    return conn.execute(f"SELECT * FROM alert_deliveries WHERE alert_id IN ({','.join('?' * len(alert_ids))}) "
                        "ORDER BY alert_id, channel", list(alert_ids)).fetchall()


def last_alert(conn: sqlite3.Connection, rule_id: str, subject_key: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM alerts WHERE rule_id = ? AND subject_key = ? ORDER BY fired_at DESC, id DESC LIMIT 1",
        (rule_id, subject_key)).fetchone()
    return row


def add_note(conn: sqlite3.Connection, alert_id: int, *, body: str, created_by: str, at: datetime) -> int:
    with conn:
        cur = conn.execute("INSERT INTO alert_notes (alert_id, body, created_by, created_at) VALUES (?, ?, ?, ?)",
                           (alert_id, body, created_by, _t(at)))
    return int(cur.lastrowid or 0)


def notes(conn: sqlite3.Connection, alert_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM alert_notes WHERE alert_id = ? ORDER BY id", (alert_id,)).fetchall()


# ── rule state ───────────────────────────────────────────────────────────────

def rule_state(conn: sqlite3.Connection, rule_id: str, subject_key: str) -> RuleState | None:
    row = conn.execute("SELECT last_fired_at, recent_json FROM alert_rule_state WHERE rule_id = ? AND subject_key = ?",
                       (rule_id, subject_key)).fetchone()
    if row is None:
        return None
    return RuleState(datetime.fromisoformat(row["last_fired_at"]) if row["last_fired_at"] else None,
                     tuple(datetime.fromisoformat(t) for t in json.loads(row["recent_json"])))


def save_rule_state(conn: sqlite3.Connection, rule_id: str, subject_key: str, state: RuleState, *,
                    suppressed: Literal["cooldown", "throttle"] | None) -> None:
    last = _t(state.last_fired_at) if state.last_fired_at else None
    recent = json.dumps([_t(t) for t in state.recent])
    conn.execute(
        "INSERT INTO alert_rule_state (rule_id, subject_key, last_fired_at, recent_json, suppressed_cooldown, "
        "suppressed_throttle) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(rule_id, subject_key) DO UPDATE SET "
        "last_fired_at = excluded.last_fired_at, recent_json = excluded.recent_json, "
        "suppressed_cooldown = suppressed_cooldown + excluded.suppressed_cooldown, "
        "suppressed_throttle = suppressed_throttle + excluded.suppressed_throttle",
        (rule_id, subject_key, last, recent, int(suppressed == "cooldown"), int(suppressed == "throttle")))


def rule_states(conn: sqlite3.Connection) -> dict[str, list[RuleState]]:
    """Every rule's cooldown / throttle state, one per subject it alerted on."""
    out: dict[str, list[RuleState]] = {}
    for r in conn.execute("SELECT rule_id, last_fired_at, recent_json FROM alert_rule_state"):
        out.setdefault(r["rule_id"], []).append(RuleState(
            datetime.fromisoformat(r["last_fired_at"]) if r["last_fired_at"] else None,
            tuple(datetime.fromisoformat(t) for t in json.loads(r["recent_json"]))))
    return out


def reset_rule_state(conn: sqlite3.Connection, rule_id: str) -> None:
    """Forget when the rule last let an alert through (its cooldown and throttle start over). What it has seen stays:
    seen_severity keeps a detection already alerted on from alerting again, and the evaluation watermarks keep
    history from being alerted (spec §6.5.2); the suppressed counts are history too."""
    with conn:
        conn.execute("UPDATE alert_rule_state SET last_fired_at = NULL, recent_json = '[]' WHERE rule_id = ?",
                     (rule_id,))


def seen_severity(conn: sqlite3.Connection, rule_id: str, subject_key: str) -> str | None:
    row = conn.execute("SELECT seen_severity FROM alert_rule_state WHERE rule_id = ? AND subject_key = ?",
                       (rule_id, subject_key)).fetchone()
    return None if row is None else row["seen_severity"]


def set_seen_severity(conn: sqlite3.Connection, rule_id: str, subject_key: str, severity: str) -> None:
    """The detection's severity as this rule last evaluated it (the caller commits)."""
    conn.execute("INSERT INTO alert_rule_state (rule_id, subject_key, last_fired_at, recent_json, seen_severity) "
                 "VALUES (?, ?, NULL, '[]', ?) ON CONFLICT(rule_id, subject_key) DO UPDATE SET "
                 "seen_severity = excluded.seen_severity", (rule_id, subject_key, severity))


def set_rule_status(conn: sqlite3.Connection, rule_id: str, status: str, at: datetime) -> None:
    with conn:
        conn.execute("INSERT INTO alert_rule_status (rule_id, status, evaluated_at) VALUES (?, ?, ?) "
                     "ON CONFLICT(rule_id) DO UPDATE SET status = excluded.status, evaluated_at = excluded.evaluated_at",
                     (rule_id, status, _t(at)))


@dataclass(frozen=True)
class RuleSummary:
    last_fired_at: datetime | None
    fired_7d: int
    suppressed_cooldown: int
    suppressed_throttle: int
    last_status: str | None
    known_7d: int = 0  # of the 7 days' alerts, those marked as known (grouped)


def rule_summaries(conn: sqlite3.Connection, *, pce_url: str, org_id: str, now: datetime) -> dict[str, RuleSummary]:
    week = _t(now - timedelta(days=7))
    fired = {r["rule_id"]: (r["last"], r["n"], r["k"]) for r in conn.execute(
        "SELECT rule_id, MAX(fired_at) AS last, SUM(fired_at >= ?) AS n, "
        "SUM(fired_at >= ? AND grouped_annotation IS NOT NULL) AS k FROM alerts WHERE pce_url = ? AND org_id = ? "
        "GROUP BY rule_id", (week, week, pce_url, org_id))}
    held = {r["rule_id"]: (r["c"], r["t"]) for r in conn.execute(
        "SELECT rule_id, SUM(suppressed_cooldown) AS c, SUM(suppressed_throttle) AS t FROM alert_rule_state "
        "GROUP BY rule_id")}
    status = {r["rule_id"]: r["status"] for r in conn.execute("SELECT rule_id, status FROM alert_rule_status")}
    out = {}
    for rule_id in set(fired) | set(held) | set(status):
        last, n, k = fired.get(rule_id, (None, 0, 0))
        c, t = held.get(rule_id, (0, 0))
        out[rule_id] = RuleSummary(datetime.fromisoformat(last) if last else None, int(n or 0), int(c or 0),
                                   int(t or 0), status.get(rule_id), int(k or 0))
    return out


# ── evaluation watermarks ────────────────────────────────────────────────────

def eval_watermark(conn: sqlite3.Connection, source: str, *, pce_url: str, org_id: str) -> str | None:
    """Where an evaluation got to — None when it was about another PCE (a switch starts over from now)."""
    row = conn.execute("SELECT pce_url, org_id, watermark FROM alert_eval_state WHERE source = ?", (source,)).fetchone()
    if row is None or (row["pce_url"], row["org_id"]) != (pce_url, org_id):
        return None
    return str(row["watermark"])


def set_eval_watermark(conn: sqlite3.Connection, source: str, value: str, *, pce_url: str, org_id: str) -> None:
    conn.execute("INSERT INTO alert_eval_state (source, pce_url, org_id, watermark) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT(source) DO UPDATE SET pce_url = excluded.pce_url, org_id = excluded.org_id, "
                 "watermark = excluded.watermark", (source, pce_url, org_id, value))


def clear_eval_state(conn: sqlite3.Connection) -> None:
    """Forget every evaluation watermark: they point into a flow database that a PCE switch has just cleared."""
    with conn:
        conn.execute("DELETE FROM alert_eval_state")


# ── deliveries and channels ──────────────────────────────────────────────────

def due_deliveries(conn: sqlite3.Connection, now: datetime, *, limit: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM alert_deliveries WHERE status = ? AND next_attempt_at <= ? "
                        "ORDER BY next_attempt_at, id LIMIT ?",
                        (DeliveryStatus.PENDING.value, _t(now), limit)).fetchall()


def mark_deliveries(conn: sqlite3.Connection, ids: Sequence[int], *, status: DeliveryStatus, attempts_add: int,
                    next_attempt_at: datetime | None, sent_at: datetime | None, error: str | None) -> None:
    if not ids:
        return
    with conn:
        conn.execute(f"UPDATE alert_deliveries SET status = ?, attempts = attempts + ?, next_attempt_at = ?, "
                     f"sent_at = COALESCE(?, sent_at), last_error = ? WHERE id IN ({','.join('?' * len(ids))})",
                     [status.value, attempts_add, _t(next_attempt_at) if next_attempt_at else None,
                      _t(sent_at) if sent_at else None, error, *ids])


def channel_state(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {r["channel"]: r for r in conn.execute("SELECT * FROM channel_state")}


def save_channel_state(conn: sqlite3.Connection, channel: str, *, consecutive_failures: int,
                       cooldown_until: datetime | None, last_error: str | None, last_ok_at: datetime | None) -> None:
    with conn:
        conn.execute("INSERT INTO channel_state (channel, consecutive_failures, cooldown_until, last_error, last_ok_at) "
                     "VALUES (?, ?, ?, ?, ?) ON CONFLICT(channel) DO UPDATE SET "
                     "consecutive_failures = excluded.consecutive_failures, cooldown_until = excluded.cooldown_until, "
                     "last_error = excluded.last_error, last_ok_at = COALESCE(excluded.last_ok_at, last_ok_at)",
                     (channel, consecutive_failures, _t(cooldown_until) if cooldown_until else None, last_error,
                      _t(last_ok_at) if last_ok_at else None))


def count_notified_alerts_before(conn: sqlite3.Connection, cutoff: datetime, *, pce_url: str, org_id: str,
                                after_id: int) -> int:
    """Alerts the SIEM sends that delete_alerts_before would delete with an id above after_id (P7)."""
    return int(conn.execute("SELECT COUNT(*) FROM alerts WHERE id > ? AND notify = 1 AND pce_url = ? AND org_id = ? "
                            "AND fired_at < ?", (after_id, pce_url, org_id, _t(cutoff))).fetchone()[0])


def delete_alerts_before(conn: sqlite3.Connection, cutoff: datetime) -> int:
    with conn:
        return conn.execute("DELETE FROM alerts WHERE fired_at < ?", (_t(cutoff),)).rowcount


def row_params(row: sqlite3.Row) -> dict[str, Any]:
    params: dict[str, Any] = json.loads(row["params_json"])
    return params


def move_pce(conn: sqlite3.Connection, *, old_url: str, new_url: str, org_id: str) -> int:
    """The same PCE moved to a new address (System › PCE connection, decision D3): its rows follow it."""
    n = conn.execute("UPDATE alerts SET pce_url = ? WHERE pce_url = ? AND org_id = ?",
                     (new_url, old_url, org_id)).rowcount
    conn.execute("UPDATE alert_eval_state SET pce_url = ? WHERE pce_url = ? AND org_id = ?", (new_url, old_url, org_id))
    return int(n)
