"""Sending alerts: every minute, the deliveries that are due, one message per channel. A failure is retried after
1 and then 5 minutes and is final after the third attempt; a channel that failed three times in a row rests for
5 minutes, and resting costs no attempt (5.x LINE, 2026-07-24 review B2). Every outcome stays on the alert —
5.x's alert retry queue had no reader at all."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from loguru import logger
from pydantic import BaseModel

from illumio_ops.domain.values import ChannelKind, DeliveryStatus, Language, Severity
from illumio_ops.services.alerts.channels import SendResult, enabled_channels, send
from illumio_ops.services.alerts.messages import (
    AlertView,
    alert_view,
    console_url,
    display_zone,
    render,
)
from illumio_ops.services.context import AppContext
from illumio_ops.settings.schema import AlertChannels
from illumio_ops.store import alerts as store

DUE_LIMIT = 200
ATTEMPTS = 3
BACKOFF = (timedelta(minutes=1), timedelta(minutes=5))
CHANNEL_STRIKES = 3
CHANNEL_REST = timedelta(minutes=5)


class DispatchRun(BaseModel):
    sent: int
    failed: int
    waiting: int


def run_dispatch(ctx: AppContext, *, now: datetime | None = None) -> DispatchRun:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    s = ctx.settings.current()
    enabled = set(enabled_channels(s.alerts.channels))
    with ctx.db() as conn:
        due = store.due_deliveries(conn, at, limit=DUE_LIMIT)
        states = store.channel_state(conn)
        by_channel: dict[str, list[tuple[int, int, int]]] = defaultdict(list)  # channel -> (delivery, alert, attempts)
        for d in due:
            by_channel[d["channel"]].append((d["id"], d["alert_id"], d["attempts"]))
        rows = {r["id"]: r for r in store.alerts_by_id(conn, sorted({d["alert_id"] for d in due}))}
    out = DispatchRun(sent=0, failed=0, waiting=0)
    lang, link = s.display.language, console_url(s.pce)
    tz, label = display_zone(s.display)
    for channel, items in sorted(by_channel.items()):
        ids = [i for i, _, _ in items]
        if channel not in enabled:
            with ctx.db() as conn:
                store.mark_deliveries(conn, ids, status=DeliveryStatus.FAILED, attempts_add=0, next_attempt_at=None,
                                      sent_at=None, error="channel_disabled")
            out.failed += len(ids)
            continue
        state = states.get(channel)
        if state is not None and state["cooldown_until"] and datetime.fromisoformat(state["cooldown_until"]) > at:
            out.waiting += len(ids)
            continue
        views = [alert_view(rows[a]) for _, a, _ in items]
        rendered = render(views, ChannelKind(channel), lang=lang, tz=tz, tz_label=label, console_url=link)
        result = send(ChannelKind(channel), s.alerts.channels, rendered)
        _record(ctx, channel, items, result, at, state["consecutive_failures"] if state is not None else 0)
        if result.ok:
            out.sent += len(ids)
        else:
            logger.warning("alert channel {} failed: {}", channel, result.error)
            out.failed += len(ids)
    return out


def _record(ctx: AppContext, channel: str, items: list[tuple[int, int, int]], result: SendResult, at: datetime,
            strikes: int) -> None:
    with ctx.db() as conn:
        if result.ok:
            store.mark_deliveries(conn, [i for i, _, _ in items], status=DeliveryStatus.SENT, attempts_add=1,
                                  next_attempt_at=None, sent_at=at, error=None)
            store.save_channel_state(conn, channel, consecutive_failures=0, cooldown_until=None, last_error=None,
                                     last_ok_at=at)
            return
        by_attempts: dict[int, list[int]] = defaultdict(list)
        for delivery, _, attempts in items:
            by_attempts[attempts + 1].append(delivery)
        for attempts, ids in by_attempts.items():
            final = attempts >= ATTEMPTS
            store.mark_deliveries(conn, ids, status=DeliveryStatus.FAILED if final else DeliveryStatus.PENDING,
                                  attempts_add=1, next_attempt_at=None if final else at + BACKOFF[attempts - 1],
                                  sent_at=None, error=result.error)
        strikes += 1
        store.save_channel_state(conn, channel, consecutive_failures=strikes,
                                 cooldown_until=at + CHANNEL_REST if strikes >= CHANNEL_STRIKES else None,
                                 last_error=result.error, last_ok_at=None)


def send_test(ctx: AppContext, channel: ChannelKind, *, cfg: AlertChannels | None = None) -> SendResult:
    """A fixed test message to one channel, with these (possibly unsaved) settings; nothing is recorded."""
    s = ctx.settings.current()
    channels = cfg or s.alerts.channels
    lang: Language = s.display.language
    view = AlertView(id=0, rule_name="", pack_key="alert_test_rule", severity=Severity.LOW, subject_key="test",
                     fired_at=datetime.now(UTC), late=False, message_key="alert_test_message", params={}, facts={},
                     confidence={})
    tz, label = display_zone(s.display)
    return send(channel, channels, render([view], channel, lang=lang, tz=tz, tz_label=label, console_url=None))
