"""Rule schedules (UI redesign spec §4.5; the 5.x semantics of docs/legacy-5.x/guide/automation.md §1): a weekly
window — on the listed days from start to end in the schedule's own time zone, across midnight when start is later
than end — in which an active rule or rule set is enabled (or disabled), or an expiry after which it is disabled.
Pure: what the target should be at a moment, when that next changes, and the fixed-English note the target's
description carries (it is read back by reports in either language, so it is never translated)."""
from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta, timezone, tzinfo
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# The note prefixes 5.x wrote: the calendar (weekly, GUI and CLI), the hourglass (CLI expiry), the alarm clock (GUI
# expiry). All three are removed, so a note a 5.x install left is cleared too (5.x tests/test_rule_note_tag_strip.py).
_NOTES = re.compile(r"\s*\[(?:📅|⏳|⏰)[^\]]*\]")
_FIXED = re.compile(r"^UTC([+-])(\d{2}):(\d{2})$")
NEXT_DAYS = 8


def zone(name: str) -> tzinfo:
    """An IANA zone, or a fixed offset written UTC+05:30 (5.x accepted UTC+5.5; no IANA name says it exactly)."""
    m = _FIXED.match(name)
    if m:
        minutes = int(m.group(2)) * 60 + int(m.group(3))
        if minutes > 14 * 60:
            raise ValueError("an offset beyond 14 hours")
        return timezone(timedelta(minutes=minutes if m.group(1) == "+" else -minutes))
    return ZoneInfo(name)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("timezone", check_fields=False)
    @classmethod
    def _zone(cls, v: str) -> str:
        try:
            zone(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("an IANA time zone, such as Asia/Taipei, or UTC+05:30") from None
        return v


class Weekly(_Model):
    kind: Literal["weekly"] = "weekly"
    days: tuple[Weekday, ...] = Field(min_length=1)
    start: str
    end: str
    timezone: str
    action: Literal["enable_in_window", "disable_in_window"]

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError("a time as HH:MM")
        return v

    @model_validator(mode="after")
    def _shape(self) -> Weekly:
        if len(set(self.days)) != len(self.days):
            raise ValueError("each day once")
        if self.start == self.end:
            raise ValueError("start and end must differ")
        return self


class Expiry(_Model):
    kind: Literal["expiry"] = "expiry"
    expire_at: AwareDatetime
    timezone: str


Plan = Weekly | Expiry


def _day(d: date) -> Weekday:
    return WEEKDAYS[d.weekday()]


def in_window(w: Weekly, now: datetime) -> bool:
    local = now.astimezone(zone(w.timezone))
    cur, today, yesterday = local.strftime("%H:%M"), _day(local.date()), _day(local.date() - timedelta(days=1))
    if w.start < w.end:
        return today in w.days and w.start <= cur < w.end
    return (today in w.days and cur >= w.start) or (yesterday in w.days and cur < w.end)


def desired(plan: Plan, now: datetime) -> bool | Literal["expired"]:
    """Whether the target should be enabled now; "expired": an expiry has passed (disable it, then drop the
    schedule)."""
    if isinstance(plan, Expiry):
        return "expired" if now >= plan.expire_at else True
    inside = in_window(plan, now)
    return inside if plan.action == "enable_in_window" else not inside


def _walls(d: date, hhmm: str, tz: tzinfo) -> list[datetime]:
    """That wall-clock time on that day as instants: both readings when the clock repeats it, the one-way reading when
    it is skipped (the actual flip then falls at the jump, found from the zone's transitions)."""
    h, m = (int(x) for x in hhmm.split(":"))
    return [datetime.combine(d, time(h, m), tzinfo=tz).replace(fold=f).astimezone(UTC) for f in (0, 1)]


def _transitions(start: datetime, end: datetime, tz: tzinfo) -> list[datetime]:
    """The instants the zone's offset changes between start and end, to the minute."""
    out = []
    t = start
    while t < end:
        nxt = t + timedelta(hours=1)
        if t.astimezone(tz).utcoffset() != nxt.astimezone(tz).utcoffset():
            lo, hi = t, nxt
            while hi - lo > timedelta(minutes=1):
                mid = lo + (hi - lo) / 2
                if mid.astimezone(tz).utcoffset() == lo.astimezone(tz).utcoffset():
                    lo = mid
                else:
                    hi = mid
            out.append(hi.replace(second=0, microsecond=0))
        t = nxt
    return out


def next_change(plan: Plan, now: datetime) -> datetime | None:
    """The next moment the target's desired state actually changes (a window starts or ends, an expiry falls due) —
    taken from the instants where desired() flips, so a clock jump moves it as it moves the window."""
    if isinstance(plan, Expiry):
        return plan.expire_at if plan.expire_at > now else None
    tz = zone(plan.timezone)
    first = now.astimezone(tz).date() - timedelta(days=1)
    horizon = now + timedelta(days=NEXT_DAYS + 1)
    candidates = set(_transitions(now, horizon, tz))
    for i in range(NEXT_DAYS + 2):
        d = first + timedelta(days=i)
        for hhmm in (plan.start, plan.end):
            candidates.update(_walls(d, hhmm, tz))
    step = timedelta(seconds=1)
    flips = sorted(c for c in candidates if now < c <= horizon and desired(plan, c) != desired(plan, c - step))
    return flips[0] if flips else None


def _days_text(days: tuple[Weekday, ...]) -> list[Weekday]:
    return sorted(days, key=WEEKDAYS.index)


def note(plan: Plan) -> str:
    if isinstance(plan, Expiry):
        local = plan.expire_at.astimezone(zone(plan.timezone))
        return f"[⏰ Expires: {local:%Y-%m-%d %H:%M} ({plan.timezone})]"
    days = ",".join(d.capitalize() for d in _days_text(plan.days))
    action = "Enable in window" if plan.action == "enable_in_window" else "Disable in window"
    return f"[📅 Recurring: {days} {plan.start}-{plan.end} ({plan.timezone}) {action}]"


def strip_notes(description: str) -> str:
    return _NOTES.sub("", description).strip()


def with_note(description: str, plan: Plan) -> str:
    kept = strip_notes(description)
    return f"{kept}\n{note(plan)}" if kept else note(plan)


def preview(plan: Plan) -> tuple[str, dict[str, str]]:
    """The i18n key and parameters of the sentence the page shows ("一三五 18:00 停用並佈署，隔天 09:00 啟用並佈署")."""
    if isinstance(plan, Expiry):
        local = plan.expire_at.astimezone(zone(plan.timezone))
        return "rs_preview_expiry", {"at": f"{local:%Y-%m-%d %H:%M}", "timezone": plan.timezone}
    key = "rs_preview_weekly_enable" if plan.action == "enable_in_window" else "rs_preview_weekly_disable"
    return key, {"days": ",".join(_days_text(plan.days)), "start": plan.start, "end": plan.end,
                 "next_day": "1" if plan.start > plan.end else "0"}
