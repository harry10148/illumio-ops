"""The data note of a report that counts traffic over days that are not UTC days (the PCE keeps traffic by UTC day,
services/collect/windows.py): every such report says it, and none whose period is whole UTC days."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from illumio_ops.domain.values import Language, ReportStatus, ReportType
from illumio_ops.services.reports.common import utc_days_note
from tests.services.collect.conftest import configured_ctx
from tests.services.reports import test_ondemand_reports as od

pce = od.pce  # the fixture: a PCE that answers the pull
NOTE = "Traffic counts use whole UTC days"
TAIPEI = timezone(timedelta(hours=8))


def test_said_only_when_an_end_of_the_period_is_not_a_utc_midnight():
    day = datetime(2026, 11, 5, tzinfo=UTC)
    assert utc_days_note(day, day + timedelta(days=7), Language.EN) == ()
    local = datetime(2026, 11, 5, tzinfo=TAIPEI)  # 16:00 UTC the day before
    said = utc_days_note(local, local + timedelta(days=7), Language.EN)
    assert len(said) == 1 and said[0].startswith(NOTE)
    assert utc_days_note(day, local + timedelta(days=7), Language.EN) == said  # one end is enough
    assert utc_days_note(local, local + timedelta(days=7), Language.ZH_TW)[0].startswith("流量數字以 UTC 整日彙總")


def _zone(ctx, name):
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["display"].update(timezone=name))
    return ctx


def test_every_report_that_counts_traffic_says_it_in_a_zone_that_is_not_utc(tmp_path, pce):
    ctx = _zone(configured_ctx(tmp_path, mode="lightweight"), "Asia/Taipei")
    for rtype in (ReportType.TRAFFIC, ReportType.SECURITY_RISK, ReportType.NETWORK_INVENTORY,
                  ReportType.UNMANAGED_ENDPOINTS, ReportType.WEEKLY_OVERVIEW):
        row = od._run(ctx, rtype)
        assert row.status is ReportStatus.DONE, (rtype, row.error_key)
        assert od._html(ctx, row).count(NOTE) == 1, rtype  # once: a builder's own and the generator's are one


def test_not_said_in_utc_nor_by_a_report_that_counts_no_traffic(tmp_path, pce):
    ctx = _zone(configured_ctx(tmp_path / "utc", mode="lightweight"), "UTC")
    row = od._run(ctx, ReportType.TRAFFIC)
    assert row.status is ReportStatus.DONE and NOTE not in od._html(ctx, row)
    ctx = _zone(configured_ctx(tmp_path / "tpe", mode="lightweight"), "Asia/Taipei")
    row = od._run(ctx, ReportType.VEN_STATUS)
    assert row.status is ReportStatus.DONE and NOTE not in od._html(ctx, row)
