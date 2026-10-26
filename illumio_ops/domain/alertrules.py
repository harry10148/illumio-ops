"""Alert rules: six types in one discriminated union, stored in the settings file and validated when written.

Event matching keeps the semantics 5.x users wrote their rules against (src/events/matcher.py, 5.x 035f7519):
comma-separated event types, each an exact name, `a|b` alternatives or a regular expression; status and
severity patterns with `all` / `*` / `any` / empty meaning anything, a leading `!` negating, and the PCE's
`err` matching a rule's `error`. One deliberate change: a pattern that looks like a regular expression must
compile when the rule is saved (5.x silently fell back to an exact match, so a typo matched nothing).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from illumio_ops.domain.filter import FlowCondition
from illumio_ops.domain.values import DetectorKind, Severity, SystemCheck, ThresholdType

_ID = re.compile(r"[0-9a-f]{32}")
_ANY = ("*", "any", "all", "")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _looks_like_regex(pattern: str) -> bool:
    if pattern.startswith("^") or pattern.endswith("$"):
        return True
    if any(c in pattern for c in r"*+?[](){}$\\"):
        return True
    return any(token in pattern for token in (".*", ".+", ".?"))


def _check_pattern(pattern: str) -> str:
    """A pattern that looks like a regular expression must compile (the message never repeats it)."""
    body = pattern.removeprefix("!")
    if body not in _ANY and _looks_like_regex(body):
        try:
            re.compile(f"^{body}$")  # as the matcher runs it: a flag group that must lead fails only once anchored
        except re.error:
            raise ValueError("not a valid regular expression") from None
    return pattern


class Throttle(_Model):
    count: int = Field(ge=1, le=1000)
    period_minutes: int = Field(ge=1, le=10080)


class RuleBase(_Model):
    """What every rule has. name "" means: show the pack rule's translated name (pack_key)."""
    id: str
    name: str = Field(max_length=120)
    pack_key: str | None
    enabled: bool
    notify: bool  # false: alerts are recorded, never sent (spec §7: new default rules on an upgraded install)
    severity: Severity | None  # None: as the event (event rules) or as the detection (lateral rules)
    cooldown_minutes: int = Field(ge=0, le=10080)
    throttle: Throttle | None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _ID.fullmatch(v):
            raise ValueError("must be 32 lowercase hexadecimal characters")
        return v

    @model_validator(mode="after")
    def _named(self) -> RuleBase:
        if not self.name and not self.pack_key:
            raise ValueError("a rule needs a name")
        return self


class _NeedsSeverity(RuleBase):
    @model_validator(mode="after")
    def _severity(self) -> _NeedsSeverity:
        if self.severity is None:
            raise ValueError("severity is required")
        return self


class EventRule(RuleBase):
    type: Literal["event"]
    event_types: tuple[str, ...] = Field(min_length=1)
    status: str
    event_severity: str
    match_fields: dict[str, str]
    threshold: ThresholdType
    threshold_count: int = Field(ge=1)
    window_minutes: int = Field(ge=1, le=1440)

    @field_validator("event_types")
    @classmethod
    def _types(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        out = tuple(p.strip() for p in v)
        if any(not p for p in out):
            raise ValueError("an event type cannot be empty")
        for p in out:
            _check_pattern(p)
        return out

    @field_validator("status", "event_severity")
    @classmethod
    def _value_pattern(cls, v: str) -> str:
        return _check_pattern(v.strip())

    @field_validator("match_fields")
    @classmethod
    def _fields(cls, v: dict[str, str]) -> dict[str, str]:
        for path, pattern in v.items():
            if not path.strip():
                raise ValueError("a field path cannot be empty")
            _check_pattern(pattern)
        return v


class _FlowRule(_NeedsSeverity):
    condition: FlowCondition
    window_minutes: int = Field(ge=10, le=1440)  # shorter than the fastest traffic collection means nothing


class TrafficRule(_FlowRule):
    type: Literal["traffic"]
    threshold_connections: int = Field(ge=1)


class BandwidthRule(_FlowRule):
    type: Literal["bandwidth"]
    threshold_mbps: float = Field(gt=0)


class VolumeRule(_FlowRule):
    type: Literal["volume"]
    threshold_mb: float = Field(gt=0)


class SystemRule(_NeedsSeverity):
    type: Literal["system"]
    check: SystemCheck


class LateralRule(RuleBase):
    """severity None: each alert takes its detection's severity (precursor weighting included)."""
    type: Literal["lateral"]
    detectors: tuple[DetectorKind, ...] = Field(min_length=1)
    min_severity: Severity
    critical_assets_only: bool


AlertRule = Annotated[EventRule | TrafficRule | BandwidthRule | VolumeRule | SystemRule | LateralRule,
                      Field(discriminator="type")]


# ── matching (5.x src/events/matcher.py) ─────────────────────────────────────

def _regex_match(anchored: str, text: str) -> bool:
    """A pattern stored before validation compiled it anchored cannot match, and never stops an evaluation."""
    try:
        return re.match(anchored, text) is not None
    except re.error:
        return False


def _value_matches(pattern: str, value: str | None) -> bool:
    if pattern in _ANY:
        return True
    normalized = value if value is not None else ""
    if pattern.startswith("!"):
        return not _value_matches(pattern[1:], value)
    if "|" in pattern and not _looks_like_regex(pattern):
        return normalized in pattern.split("|")
    if _looks_like_regex(pattern):
        return _regex_match(f"^{pattern}$", normalized)
    return pattern == normalized


# The PCE sends "err"; 5.x's GUI and CLI stored "error". Both sides are normalised before comparing.
_SEVERITY_ALIASES = {"error": "err"}


def _canon_severity(value: str | None) -> str:
    text = str(value if value is not None else "").strip().lower()
    return _SEVERITY_ALIASES.get(text, text)


def _severity_matches(pattern: str, value: str | None) -> bool:
    pattern = pattern.strip()
    if pattern.startswith("!"):
        return not _severity_matches(pattern[1:], value)
    if _looks_like_regex(pattern):
        return _value_matches(pattern, value) or _value_matches(pattern, _canon_severity(value))
    canon = "|".join(_canon_severity(p) for p in pattern.split("|"))
    return _value_matches(canon, _canon_severity(value))


def _extract(event: Mapping[str, Any], path: str) -> str | None:
    current: Any = event
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return None
    if current is None:
        return None
    return current if isinstance(current, str) else str(current)


def _type_matches(pattern: str, event_type: str) -> bool:
    if pattern in ("*", ".*", ""):
        return True
    if "|" in pattern and not _looks_like_regex(pattern):
        return event_type in pattern.split("|")
    if _looks_like_regex(pattern):
        return _regex_match(f"^{pattern}$" if not pattern.startswith("^") else pattern, event_type)
    return pattern == event_type


def event_matches(rule: EventRule, event: Mapping[str, Any]) -> bool:
    """Whether one PCE event (its raw JSON) matches an event rule."""
    event_type = str(event.get("event_type") or "")
    if not any(_type_matches(p, event_type) for p in rule.event_types):
        return False
    if not _value_matches(rule.status, event.get("status")):
        return False
    if not _severity_matches(rule.event_severity, event.get("severity")):
        return False
    for path, pattern in rule.match_fields.items():
        if path == "notification_type":
            notifications = event.get("notifications")
            values = [str(n.get("notification_type") or "") for n in notifications
                      if isinstance(n, Mapping)] if isinstance(notifications, list) else []
            if not any(_value_matches(pattern, v) for v in values):
                return False
            continue
        if not _value_matches(pattern, _extract(event, path)):
            return False
    return True


def uses_regex(rule: EventRule) -> bool:
    """Whether matching needs the whole window of events, not just those of the named types."""
    return any(p in ("*", ".*", "") or _looks_like_regex(p) for p in rule.event_types)


def exact_types(rule: EventRule) -> tuple[str, ...]:
    """The event types an exact-pattern rule can match (alternatives split)."""
    return tuple(t for p in rule.event_types for t in p.split("|"))
