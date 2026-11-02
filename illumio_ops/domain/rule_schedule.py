"""Rule schedules (UI redesign spec §4.5; the 5.x semantics of docs/legacy-5.x/guide/automation.md §1): a weekly
window — on the listed days from start to end in the schedule's own time zone, across midnight when start is later
than end — in which an active rule or rule set is enabled (or disabled), or an expiry after which it is disabled.
Pure: what the target should be at a moment, when that next changes, and the fixed-English note the target's
description carries (it is read back by reports in either language, so it is never translated)."""
from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
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
NEXT_DAYS = 8


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("timezone", check_fields=False)
    @classmethod
    def _zone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("an IANA time zone, such as Asia/Taipei") from None
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
    local = now.astimezone(ZoneInfo(w.timezone))
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


def _local(d: date, hhmm: str, tz: ZoneInfo) -> datetime | None:
    """That wall-clock time on that day as an instant; None when it does not exist (a spring-forward gap)."""
    h, m = (int(x) for x in hhmm.split(":"))
    wall = datetime.combine(d, time(h, m), tzinfo=tz)
    back = wall.astimezone(UTC).astimezone(tz)
    return wall.astimezone(UTC) if (back.hour, back.minute) == (h, m) else None


def next_change(plan: Plan, now: datetime) -> datetime | None:
    """The next moment the target's desired state changes (a window starts or ends, an expiry falls due)."""
    if isinstance(plan, Expiry):
        return plan.expire_at if plan.expire_at > now else None
    tz = ZoneInfo(plan.timezone)
    first = now.astimezone(tz).date() - timedelta(days=1)
    found = []
    for i in range(NEXT_DAYS + 1):
        d = first + timedelta(days=i)
        if _day(d) not in plan.days:
            continue
        end_day = d if plan.start < plan.end else d + timedelta(days=1)
        for moment in (_local(d, plan.start, tz), _local(end_day, plan.end, tz)):
            if moment is not None and moment > now:
                found.append(moment)
    return min(found, default=None)


def _days_text(days: tuple[Weekday, ...]) -> list[Weekday]:
    return sorted(days, key=WEEKDAYS.index)


def note(plan: Plan) -> str:
    if isinstance(plan, Expiry):
        local = plan.expire_at.astimezone(ZoneInfo(plan.timezone))
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
        local = plan.expire_at.astimezone(ZoneInfo(plan.timezone))
        return "rs_preview_expiry", {"at": f"{local:%Y-%m-%d %H:%M}", "timezone": plan.timezone}
    key = "rs_preview_weekly_enable" if plan.action == "enable_in_window" else "rs_preview_weekly_disable"
    return key, {"days": ",".join(_days_text(plan.days)), "start": plan.start, "end": plan.end,
                 "next_day": "1" if plan.start > plan.end else "0"}
