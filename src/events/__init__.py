"""Event monitoring primitives inspired by illumio-pretty-cool-events."""

from .catalog import KNOWN_EVENT_TYPES, is_known_event_type
from .matcher import matches_event_rule
from .normalizer import normalize_event
from .poller import EventBatch, EventPoller, event_identity, format_utc, parse_event_timestamp
from .shadow import compare_event_rules, matches_event_rule_legacy
from .stats import (
    DEFAULT_DISPATCH_LIMIT,
    DEFAULT_TIMELINE_LIMIT,
    StatsTracker,
    ensure_monitoring_state,
    persist_dispatch_results,
)
from .throttle import AlertThrottler, parse_throttle

__all__ = [
    "AlertThrottler",
    "DEFAULT_DISPATCH_LIMIT",
    "DEFAULT_TIMELINE_LIMIT",
    "KNOWN_EVENT_TYPES",
    "is_known_event_type",
    "matches_event_rule",
    "matches_event_rule_legacy",
    "compare_event_rules",
    "ensure_monitoring_state",
    "normalize_event",
    "EventBatch",
    "EventPoller",
    "parse_throttle",
    "persist_dispatch_results",
    "event_identity",
    "format_utc",
    "parse_event_timestamp",
    "StatsTracker",
]
