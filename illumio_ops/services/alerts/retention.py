"""Alert records are kept alerts.retention_days (5.x borrowed the archive's retention for this)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from illumio_ops.services.context import AppContext
from illumio_ops.store import alerts as store


def run_alert_retention(ctx: AppContext, *, now: datetime | None = None) -> int:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    days = ctx.settings.current().alerts.retention_days
    with ctx.db() as conn:
        return store.delete_alerts_before(conn, at - timedelta(days=days))  # notes and deliveries cascade
