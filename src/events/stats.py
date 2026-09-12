"""Operational stats and audit trail for event monitoring."""

from __future__ import annotations

import datetime

from src.state_store import update_state_file

from .poller import event_identity, format_utc

DEFAULT_TIMELINE_LIMIT = 100

# A connection error's diagnosis is at its END. urllib3 puts the host first,
# the request URL (long, and mostly noise) in the middle, and the only clause
# that says WHY — "(Caused by NewConnectionError… [Errno 110] …)" — last. A
# leading slice therefore keeps the least useful half: the watchdog alert used
# to stop right before the reason. Keep both ends, drop the middle, and mark
# the cut so a shortened message never reads as a complete one.
def elide_error(message: str, limit: int) -> str:
    """Shorten `message` to `limit` characters, keeping its head and its tail."""
    if message is None:
        return ""
    if len(message) <= limit:
        return message
    if limit <= 3:
        return message[:limit]
    head = max(1, limit * 2 // 5)
    tail = limit - head - 3
    if tail <= 0:
        return message[:limit - 3] + "..."
    return f"{message[:head]}...{message[-tail:]}"

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
    # 這串失敗的起點（見 record_pce_error/record_pce_success）。歸零的是
    # 「目前狀態」，last_incident 留的是「上一次事故」。
    pce_stats.setdefault("failure_run_started_at", "")
    pce_stats.setdefault("failure_run_first_error", "")
    pce_stats.setdefault("failure_run_first_stage", "")
    pce_stats.setdefault("last_incident", {})
    pce_stats.setdefault("health_probe", "")
    pce_stats.setdefault("deployment_type", "")
    pce_stats.setdefault("health_category", "unknown")
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

    def record_pce_success(
        self,
        stage: str,
        *,
        status=200,
        message: str = "",
        probe: str | None = None,
        deployment_type: str | None = None,
        category: str | None = None,
    ) -> None:
        now_str = format_utc(datetime.datetime.now(datetime.timezone.utc))
        pce_stats = self.state.setdefault("pce_stats", {})
        pce_stats["last_success"] = now_str
        # 復原＝一次事故結束。歸零之前先把它留下來：2026-09-12 使用者收到
        # 「已連續失敗 936 次」的告警，兩分鐘後查 state.json 只看到 0 / None,
        # 因為期間有一次探測成功，而這裡把計數與冷卻時戳一起清了。自癒機制
        # 不應該吃掉事後診斷能力——歸零的是「目前狀態」，last_incident 是
        # 「上一次事故」，只有真的有失敗串時才覆寫（否則健康的系統會在幾分鐘
        # 內把唯一那筆事故洗掉）。
        failures = int(pce_stats.get("consecutive_failures", 0) or 0)
        if failures > 0:
            pce_stats["last_incident"] = {
                "started_at": pce_stats.get("failure_run_started_at", ""),
                "ended_at": now_str,
                "failures": failures,
                "first_error": pce_stats.get("failure_run_first_error", ""),
                "first_stage": pce_stats.get("failure_run_first_stage", ""),
                "last_error": pce_stats.get("last_error", ""),
                "last_stage": pce_stats.get("last_error_stage", ""),
                # 在下面清掉 watchdog_last_alert_at **之前**讀——這是事後唯一
                # 能回答「這台到底有沒有發過警」的欄位。
                "alerted": bool(self.state.get("watchdog_last_alert_at")),
            }
        pce_stats["consecutive_failures"] = 0
        pce_stats["failure_run_started_at"] = ""
        pce_stats["failure_run_first_error"] = ""
        pce_stats["failure_run_first_stage"] = ""
        # A real PCE probe succeeding means any prior watchdog incident is
        # over: clear its cooldown timestamp so a fresh run of failures isn't
        # suppressed by the previous incident's alert. watchdog_last_alert_at
        # is a top-level analyzer-owned key (not part of pce_stats); self.state
        # here is always the full top-level state dict (Analyzer's own state,
        # or the scheduler's on-disk state via _record_ingest_pce_result), so
        # it is reachable from here. Set to None rather than popped: Analyzer's
        # save_state() merge overlay (self.state onto disk's existing) only
        # overwrites keys present in self.state, so a pop would leave a stale
        # on-disk value in place, but a None value overwrites it correctly.
        self.state["watchdog_last_alert_at"] = None
        if stage == "health":
            pce_stats["health_status"] = "ok"
            pce_stats["last_health_check"] = now_str
            pce_stats["health_category"] = "ok"
            if probe is not None:
                pce_stats["health_probe"] = probe
            if deployment_type is not None:
                pce_stats["deployment_type"] = deployment_type
        else:
            pce_stats["event_poll_status"] = "ok"
            pce_stats["last_event_poll"] = now_str
        self.record_timeline("pce_ok", f"{stage} ok", status=status, message=message)

    def record_local_read(self, stage: str, *, success: bool, message: str = "", error: str = "") -> None:
        """Record a LOCAL cache-read outcome for dashboard display only.

        Used by the pce_cache-ingest deployment shape's monitor cycle, which
        reads events from the local on-disk cache already populated by the
        scheduler's ingest jobs (run_events_ingest/run_traffic_ingest) — the
        code that actually talks to the live PCE on that deployment shape.
        A local cache read succeeding or failing says nothing about live PCE
        reachability, so unlike record_pce_success/record_pce_error this
        never touches pce_stats.consecutive_failures (the watchdog counter);
        it only updates the dashboard-facing event_poll_status/
        last_event_poll/last_error* fields. See
        .superpowers/sdd/watchdog-overflow-fix-report.md (C1).
        """
        now_str = format_utc(datetime.datetime.now(datetime.timezone.utc))
        pce_stats = self.state.setdefault("pce_stats", {})
        pce_stats["event_poll_status"] = "ok" if success else "error"
        pce_stats["last_event_poll"] = now_str
        if success:
            self.record_timeline("pce_ok", f"{stage} ok", status=200, message=message)
        else:
            pce_stats["last_error"] = elide_error(error, 600)
            pce_stats["last_error_stage"] = stage
            self.record_timeline("pce_error", f"{stage} failed", status=None, error=elide_error(error, 600))

    def record_pce_error(
        self,
        stage: str,
        error: str,
        *,
        status=None,
        probe: str | None = None,
        deployment_type: str | None = None,
        category: str | None = None,
    ) -> None:
        now_str = format_utc(datetime.datetime.now(datetime.timezone.utc))
        pce_stats = self.state.setdefault("pce_stats", {})
        pce_stats["last_error"] = elide_error(error, 600)
        pce_stats["last_error_status"] = "" if status is None else str(status)
        pce_stats["last_error_stage"] = stage
        failures = int(pce_stats.get("consecutive_failures", 0)) + 1
        pce_stats["consecutive_failures"] = failures
        # 只有 0→1 那一次寫起點。看門狗要引用的是**開啟**這串失敗的錯誤，不是
        # 最新的那一個：2026-09-12 的告警說 /noop 401，而當下的 last_error 是
        # /health 200 body=critical——兩者屬於不同階段，讀訊息的人無從分辨。
        if failures == 1 or not pce_stats.get("failure_run_started_at"):
            pce_stats["failure_run_started_at"] = now_str
            pce_stats["failure_run_first_error"] = elide_error(error, 600)
            pce_stats["failure_run_first_stage"] = stage
        if stage == "health":
            pce_stats["health_status"] = "error"
            pce_stats["last_health_check"] = now_str
            if category is not None:
                pce_stats["health_category"] = category
            if probe is not None:
                pce_stats["health_probe"] = probe
            if deployment_type is not None:
                pce_stats["deployment_type"] = deployment_type
        else:
            pce_stats["event_poll_status"] = "error"
            pce_stats["last_event_poll"] = now_str
        self.record_timeline("pce_error", f"{stage} failed", status=status, error=elide_error(error, 600))

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
