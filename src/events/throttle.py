"""Alert throttling helpers inspired by illumio-pretty-cool-events."""

from __future__ import annotations

import datetime
import re

from .poller import format_utc, parse_event_timestamp

_THROTTLE_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)([smhd]?)\s*$", re.IGNORECASE)

def parse_throttle(value):
    if not value:
        return None

    if isinstance(value, dict):
        try:
            count = max(1, int(value.get("count", 0)))
        except (TypeError, ValueError):
            return None
        seconds = int(value.get("period_seconds") or 0)
        if seconds <= 0:
            minutes = value.get("period_minutes")
            try:
                seconds = max(1, int(minutes)) * 60
            except (TypeError, ValueError):
                return None
        return {
            "count": count,
            "period_seconds": seconds,
            "label": f"{count}/{seconds}s",
        }

    match = _THROTTLE_RE.match(str(value))
    if not match:
        return None

    count = max(1, int(match.group(1)))
    period = max(1, int(match.group(2)))
    unit = (match.group(3) or "m").lower()
    multiplier = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }.get(unit, 60)
    return {
        "count": count,
        "period_seconds": period * multiplier,
        "label": f"{count}/{period}{unit}",
    }

class AlertThrottler:
    def __init__(self, state: dict):
        self.state = state

    def _entry(self, rule: dict) -> dict:
        throttle_state = self.state.setdefault("throttle_state", {})
        rid = str(rule["id"])
        entry = throttle_state.setdefault(rid, {})
        entry.setdefault("rule_name", rule.get("name", rid))
        entry.setdefault("recent_dispatches", [])
        entry.setdefault("cooldown_suppressed", 0)
        entry.setdefault("throttle_suppressed", 0)
        entry.setdefault("last_suppressed_at", "")
        entry.setdefault("last_allowed_at", "")
        entry.setdefault("next_allowed_at", "")
        entry.setdefault("throttle", rule.get("throttle") or rule.get("alert_throttle") or "")
        return entry

    def prune(self, now_utc: datetime.datetime | None = None, horizon_seconds: int = 86400) -> None:
        if now_utc is None:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now_utc - datetime.timedelta(seconds=horizon_seconds)
        throttle_state = self.state.setdefault("throttle_state", {})
        stale_ids = []
        for rid, entry in throttle_state.items():
            timestamps = []
            for ts_str in entry.get("recent_dispatches", []):
                ts = parse_event_timestamp(ts_str)
                if ts and ts > cutoff:
                    timestamps.append(format_utc(ts))
            entry["recent_dispatches"] = timestamps

            last_allowed = parse_event_timestamp(entry.get("last_allowed_at"))
            last_suppressed = parse_event_timestamp(entry.get("last_suppressed_at"))
            if not timestamps and not last_allowed and not last_suppressed:
                stale_ids.append(rid)
        for rid in stale_ids:
            throttle_state.pop(rid, None)

    def record_cooldown_suppressed(
        self,
        rule: dict,
        now_utc: datetime.datetime,
        next_allowed_at: datetime.datetime | None = None,
    ) -> dict:
        entry = self._entry(rule)
        entry["cooldown_suppressed"] = int(entry.get("cooldown_suppressed", 0)) + 1
        entry["last_suppressed_at"] = format_utc(now_utc)
        if next_allowed_at:
            entry["next_allowed_at"] = format_utc(next_allowed_at)
        return dict(entry)

    def allow(self, rule: dict, now_utc: datetime.datetime | None = None):
        if now_utc is None:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
        spec = parse_throttle(rule.get("throttle") or rule.get("alert_throttle"))
        if not spec:
            return True, {}

        entry = self._entry(rule)
        cutoff = now_utc - datetime.timedelta(seconds=spec["period_seconds"])
        recent = []
        for ts_str in entry.get("recent_dispatches", []):
            ts = parse_event_timestamp(ts_str)
            if ts and ts > cutoff:
                recent.append(format_utc(ts))
        entry["recent_dispatches"] = recent
        entry["throttle"] = spec["label"]

        if len(recent) >= spec["count"]:
            oldest = parse_event_timestamp(recent[0])
            next_allowed_at = oldest + datetime.timedelta(seconds=spec["period_seconds"]) if oldest else None
            entry["throttle_suppressed"] = int(entry.get("throttle_suppressed", 0)) + 1
            entry["last_suppressed_at"] = format_utc(now_utc)
            entry["next_allowed_at"] = format_utc(next_allowed_at) if next_allowed_at else ""
            return False, {
                "count": spec["count"],
                "period_seconds": spec["period_seconds"],
                "next_allowed_at": entry.get("next_allowed_at", ""),
                "suppressed": entry["throttle_suppressed"],
                "throttle": spec["label"],
            }

        recent.append(format_utc(now_utc))
        entry["recent_dispatches"] = recent
        entry["last_allowed_at"] = format_utc(now_utc)
        entry["next_allowed_at"] = ""
        return True, {
            "count": spec["count"],
            "period_seconds": spec["period_seconds"],
            "dispatches_in_window": len(recent),
            "throttle": spec["label"],
        }
