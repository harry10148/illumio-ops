"""Alert records are kept alerts.retention_days (5.x borrowed the archive's retention for this)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from illumio_ops.services.context import AppContext
from illumio_ops.services.siem import guard as siem_guard
from illumio_ops.store import alerts as store


def run_alert_retention(ctx: AppContext, *, now: datetime | None = None) -> int:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    days = ctx.settings.current().alerts.retention_days
    cutoff = at - timedelta(days=days)
    pce = ctx.settings.current().pce

    def unsent(after_id: int) -> int:
        with ctx.db() as conn:
            return store.count_notified_alerts_before(conn, cutoff, pce_url=pce.url, org_id=pce.org_id,
                                                      after_id=after_id)
    dropped = siem_guard.expiring(ctx, "alerts", unsent)
    with ctx.db() as conn:
        n = store.delete_alerts_before(conn, cutoff)  # notes and deliveries cascade
    siem_guard.record_dropped(ctx, dropped)
    return n
