"""Event rule matching inspired by pretty-cool-events watcher logic."""

from __future__ import annotations

import re
from typing import Any


def _looks_like_regex(pattern: str) -> bool:
    if pattern.startswith("^") or pattern.endswith("$"):
        return True
    if any(c in pattern for c in r"*+?[](){}$\\"):
        return True
    return any(token in pattern for token in (".*", ".+", ".?"))


def _value_matches(pattern: str, value: str | None) -> bool:
    if pattern in ("*", "any", "all", ""):
        return True

    normalized = value if value is not None else ""

    if pattern.startswith("!"):
        return not _value_matches(pattern[1:], value)

    if "|" in pattern and not _looks_like_regex(pattern):
        return normalized in pattern.split("|")

    if _looks_like_regex(pattern):
        try:
            return bool(re.match(f"^{pattern}$", normalized))
        except re.error:
            return pattern == normalized

    return pattern == normalized


def _extract_nested(event: dict[str, Any], field_path: str) -> str | None:
    current: Any = event
    for part in field_path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    if current is None:
        return None
    return current if isinstance(current, str) else str(current)


def _event_type_matches(pattern: str, event_type: str) -> bool:
    if pattern in ("*", ".*", ""):
        return True
    if "|" in pattern and not _looks_like_regex(pattern):
        return event_type in pattern.split("|")
    if _looks_like_regex(pattern):
        try:
            compiled = re.compile(f"^{pattern}$" if not pattern.startswith("^") else pattern)
            return bool(compiled.match(event_type))
        except re.error:
            return pattern == event_type
    return pattern == event_type


def matches_event_rule(rule: dict[str, Any], event: dict[str, Any]) -> bool:
    event_type = str(event.get("event_type") or "")
    patterns = [p.strip() for p in str(rule.get("filter_value") or "").split(",") if p.strip()]
    if not patterns:
        return False

    if not any(_event_type_matches(pattern, event_type) for pattern in patterns):
        return False

    if not _value_matches(str(rule.get("filter_status", "all")), event.get("status")):
        return False

    if not _value_matches(str(rule.get("filter_severity", "all")), event.get("severity")):
        return False

    match_fields = rule.get("match_fields") or rule.get("filter_match_fields") or {}
    for field_path, pattern in match_fields.items():
        if not _value_matches(str(pattern), _extract_nested(event, field_path)):
            return False

    return True
