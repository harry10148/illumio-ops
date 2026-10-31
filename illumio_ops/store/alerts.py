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
        "evidence_json, confidence_json) VALUES ((SELECT MAX(COALESCE((SELECT MAX(id) FROM alerts), 0), "
        "COALESCE((SELECT id FROM alert_id_floor), 0)) + 1), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (pce_url, org_id, trigger.rule_id, trigger.rule_type.value, rule_name, pack_key, trigger.severity.value,
         trigger.subject_key, _t(at), _t(trigger.first_seen), _t(trigger.last_seen), int(trigger.late),
         int(hold is None), trigger.grouped_annotation, trigger.message_key,
         json.dumps(trigger.params, default=str), json.dumps(trigger.facts, default=str), evidence_json(trigger),
         json.dumps(asdict(trigger.confidence), default=str)))
    alert_id = int(cur.lastrowid or 0)
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


def list_alerts(conn: sqlite3.Connection, *, pce_url: str, org_id: str, since: datetime, rule_type: str | None = None,
                severity: str | None = None, rule_id: str | None = None, limit: int,
                offset: int) -> tuple[list[sqlite3.Row], int]:
    clauses, params = ["pce_url = ?", "org_id = ?", "fired_at >= ?"], [pce_url, org_id, _t(since)]
    for column, value in (("rule_type", rule_type), ("severity", severity), ("rule_id", rule_id)):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = " AND ".join(clauses)
    rows = conn.execute(f"SELECT * FROM alerts WHERE {where} ORDER BY fired_at DESC, id DESC LIMIT ? OFFSET ?",
                        [*params, limit, offset]).fetchall()
    total = conn.execute(f"SELECT COUNT(*) FROM alerts WHERE {where}", params).fetchone()[0]
    return rows, int(total)


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


def rule_summaries(conn: sqlite3.Connection, *, pce_url: str, org_id: str, now: datetime) -> dict[str, RuleSummary]:
    fired = {r["rule_id"]: (r["last"], r["n"]) for r in conn.execute(
        "SELECT rule_id, MAX(fired_at) AS last, SUM(fired_at >= ?) AS n FROM alerts WHERE pce_url = ? AND org_id = ? "
        "GROUP BY rule_id", (_t(now - timedelta(days=7)), pce_url, org_id))}
    held = {r["rule_id"]: (r["c"], r["t"]) for r in conn.execute(
        "SELECT rule_id, SUM(suppressed_cooldown) AS c, SUM(suppressed_throttle) AS t FROM alert_rule_state "
        "GROUP BY rule_id")}
    status = {r["rule_id"]: r["status"] for r in conn.execute("SELECT rule_id, status FROM alert_rule_status")}
    out = {}
    for rule_id in set(fired) | set(held) | set(status):
        last, n = fired.get(rule_id, (None, 0))
        c, t = held.get(rule_id, (0, 0))
        out[rule_id] = RuleSummary(datetime.fromisoformat(last) if last else None, int(n or 0), int(c or 0),
                                   int(t or 0), status.get(rule_id))
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
