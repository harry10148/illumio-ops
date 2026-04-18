"""Operational stats and audit trail for event monitoring."""

from __future__ import annotations

import datetime

from src.state_store import update_state_file

from .poller import event_identity, format_utc

DEFAULT_TIMELINE_LIMIT = 100
DEFAULT_DISPATCH_LIMIT = 50

def ensure_monitoring_state(state: dict) -> dict:
    state.setdefault("dispatch_history", [])
    state.setdefault("event_timeline", [])
    state.setdefault("throttle_state", {})
    state.setdefault("pce_stats", {})
    pce_stats = state["pce_stats"]
    pce_stats.setdefault("health_status", "unknown")
    pce_stats.setdefault("event_poll_status", "unknown")
    pce_stats.setdefault("last_health_check", "")
    pce_stats.setdefault("last_event_poll", "")
    pce_stats.setdefault("last_success", "")
    pce_stats.setdefault("last_error", "")
    pce_stats.setdefault("last_error_status", "")
    pce_stats.setdefault("last_error_stage", "")
    pce_stats.setdefault("consecutive_failures", 0)
    pce_stats.setdefault("last_batch_total", 0)
    pce_stats.setdefault("last_batch_unknown", 0)
    pce_stats.setdefault("last_batch_notes", 0)
    pce_stats.setdefault("last_batch_overflow", False)
    return state

class StatsTracker:
    def __init__(
        self,
        state: dict,
        *,
        timeline_limit: int = DEFAULT_TIMELINE_LIMIT,
        dispatch_limit: int = DEFAULT_DISPATCH_LIMIT,
    ):
        self.state = ensure_monitoring_state(state)
        self.timeline_limit = timeline_limit
        self.dispatch_limit = dispatch_limit

    def prune(self, now_utc: datetime.datetime | None = None) -> None:
        if now_utc is None:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
        self.state["dispatch_history"] = list(self.state.get("dispatch_history", []))[-self.dispatch_limit:]
        self.state["event_timeline"] = list(self.state.get("event_timeline", []))[-self.timeline_limit:]

    def record_timeline(self, kind: str, title: str, **details) -> dict:
        entry = {
            "timestamp": format_utc(datetime.datetime.now(datetime.timezone.utc)),
            "kind": kind,
            "title": title,
            "details": details,
        }
        timeline = self.state.setdefault("event_timeline", [])
        timeline.append(entry)
        self.state["event_timeline"] = timeline[-self.timeline_limit:]
        return entry

    def record_pce_success(self, stage: str, *, status=200, message: str = "") -> None:
        now_str = format_utc(datetime.datetime.now(datetime.timezone.utc))
        pce_stats = self.state.setdefault("pce_stats", {})
        pce_stats["last_success"] = now_str
        pce_stats["consecutive_failures"] = 0
        if stage == "health":
            pce_stats["health_status"] = "ok"
            pce_stats["last_health_check"] = now_str
        else:
            pce_stats["event_poll_status"] = "ok"
            pce_stats["last_event_poll"] = now_str
        self.record_timeline("pce_ok", f"{stage} ok", status=status, message=message)

    def record_pce_error(self, stage: str, error: str, *, status=None) -> None:
        now_str = format_utc(datetime.datetime.now(datetime.timezone.utc))
        pce_stats = self.state.setdefault("pce_stats", {})
        pce_stats["last_error"] = error[:300]
        pce_stats["last_error_status"] = "" if status is None else str(status)
        pce_stats["last_error_stage"] = stage
        pce_stats["consecutive_failures"] = int(pce_stats.get("consecutive_failures", 0)) + 1
        if stage == "health":
            pce_stats["health_status"] = "error"
            pce_stats["last_health_check"] = now_str
        else:
            pce_stats["event_poll_status"] = "error"
            pce_stats["last_event_poll"] = now_str
        self.record_timeline("pce_error", f"{stage} failed", status=status, error=error[:300])

    def record_event_batch(self, events, *, unknown_count=0, parser_note_count=0, overflow_risk=False, query_since="", query_until="") -> None:
        pce_stats = self.state.setdefault("pce_stats", {})
        pce_stats["last_batch_total"] = len(events)
        pce_stats["last_batch_unknown"] = int(unknown_count)
        pce_stats["last_batch_notes"] = int(parser_note_count)
        pce_stats["last_batch_overflow"] = bool(overflow_risk)
        sample_ids = [event_identity(event) for event in list(events)[:5]]
        self.record_timeline(
            "event_batch",
            "event batch processed",
            total=len(events),
            unknown=unknown_count,
            parser_notes=parser_note_count,
            overflow_risk=bool(overflow_risk),
            query_since=query_since,
            query_until=query_until,
            sample_event_ids=sample_ids,
        )

    def record_rule_trigger(self, rule: dict, *, match_count=0, metric_value=None) -> None:
        details = {
            "rule_id": rule.get("id"),
            "rule_name": rule.get("name"),
            "rule_type": rule.get("type"),
            "match_count": match_count,
        }
        if metric_value is not None:
            details["metric_value"] = metric_value
        self.record_timeline("rule_trigger", rule.get("name", "unnamed rule"), **details)

    def record_suppression(self, rule: dict, reason: str, **details) -> None:
        payload = {
            "rule_id": rule.get("id"),
            "rule_name": rule.get("name"),
            "reason": reason,
        }
        payload.update(details)
        self.record_timeline("suppressed", rule.get("name", "unnamed rule"), **payload)

    def record_dispatch(self, result: dict, *, subject: str = "", counts: dict | None = None, force_test: bool = False) -> None:
        entry = {
            "timestamp": format_utc(datetime.datetime.now(datetime.timezone.utc)),
            "channel": result.get("channel", "unknown"),
            "status": result.get("status", "unknown"),
            "subject": subject,
            "target": result.get("target", ""),
            "error": result.get("error", ""),
            "force_test": bool(force_test),
            "counts": counts or {},
        }
        history = self.state.setdefault("dispatch_history", [])
        history.append(entry)
        self.state["dispatch_history"] = history[-self.dispatch_limit:]
        self.record_timeline(
            "dispatch",
            f"dispatch {entry['channel']} {entry['status']}",
            channel=entry["channel"],
            status=entry["status"],
            target=entry["target"],
            error=entry["error"],
            force_test=bool(force_test),
        )

def persist_dispatch_results(
    state_file: str,
    results,
    *,
    subject: str = "",
    counts: dict | None = None,
    force_test: bool = False,
) -> dict:
    def _merge(existing: dict) -> dict:
        tracker = StatsTracker(existing)
        for result in results:
            tracker.record_dispatch(result, subject=subject, counts=counts, force_test=force_test)
        tracker.prune()
        return tracker.state

    return update_state_file(state_file, _merge)
