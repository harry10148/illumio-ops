"""Regression tests for ReportScheduler._prune_by_count (MEDIUM finding).

Two bugs are pinned here:

1. Prefix collision: the 'traffic' retention prefix ``Illumio_Traffic_Report_``
   was a strict prefix of BOTH ``Illumio_Traffic_Report_SecurityRisk_`` and
   ``Illumio_Traffic_Report_NetworkInventory_``, so pruning a 'traffic'
   schedule's old reports could delete SecurityRisk/NetworkInventory reports
   produced by OTHER schedules sharing the output dir (cross-type loss).

2. File-vs-report counting: each report emits an HTML file PLUS a
   ``.html.metadata.json`` sidecar, and the old code counted every file
   independently, so ``max_reports`` effectively kept ~half as many reports.
"""
import datetime
import json
import os

from src.report_scheduler import ReportScheduler, _now_in_schedule_tz


def _make_report(directory, kind, ts, mtime):
    """Create a report unit: <stem>.html + <stem>.html.metadata.json sidecar."""
    stem = f"Illumio_Traffic_Report_{kind}_{ts}"
    html = directory / f"{stem}.html"
    meta = directory / f"{stem}.html.metadata.json"
    html.write_text("x")
    meta.write_text("{}")
    for f in (html, meta):
        os.utime(f, (mtime, mtime))
    return html, meta


def test_prune_security_risk_groups_metadata_and_spares_other_kinds(tmp_path):
    """KEY: prune('security_risk') must (1) never delete NetworkInventory
    reports and (2) count a report + its .html.metadata.json sidecar as ONE
    report."""
    sr = [_make_report(tmp_path, "SecurityRisk", f"2026-06-0{i + 1}_0000", 1_000_000 + i)
          for i in range(3)]
    # Two NetworkInventory reports from a sibling schedule in the same dir.
    ni = [_make_report(tmp_path, "NetworkInventory", f"2026-06-0{i + 1}_0000", 2_000_000 + i)
          for i in range(2)]

    sched = ReportScheduler.__new__(ReportScheduler)
    sched._prune_by_count(str(tmp_path), "security_risk", max_reports=2)

    names = {p.name for p in tmp_path.iterdir()}

    # (1) Cross-type: every NetworkInventory file survives, even though they are
    #     the newest files on disk (would be the first deleted under the old
    #     shared-prefix pooling once the count is exceeded).
    for html, meta in ni:
        assert html.name in names, f"NetworkInventory report wrongly pruned: {html.name}"
        assert meta.name in names, f"NetworkInventory sidecar wrongly pruned: {meta.name}"

    # (2) By-unit: exactly 2 SecurityRisk reports kept = 2 html + 2 metadata.
    sr_files = {n for n in names if "SecurityRisk" in n}
    assert len(sr_files) == 4, f"expected 2 SR reports (4 files), got: {sorted(sr_files)}"
    # Newest two SR reports kept (i=1,2); oldest (i=0) + its sidecar deleted.
    assert sr[0][0].name not in names and sr[0][1].name not in names
    assert sr[1][0].name in names and sr[1][1].name in names
    assert sr[2][0].name in names and sr[2][1].name in names


def test_prune_counts_reports_not_files(tmp_path):
    """max_reports limits REPORTS, not files: 4 reports (8 files) pruned to 2
    must leave 2 html + 2 sidecars (4 files), not 2 files."""
    reports = [_make_report(tmp_path, "SecurityRisk", f"2026-06-0{i + 1}_0000", 1_000_000 + i)
               for i in range(4)]

    sched = ReportScheduler.__new__(ReportScheduler)
    sched._prune_by_count(str(tmp_path), "security_risk", max_reports=2)

    names = {p.name for p in tmp_path.iterdir()}
    assert len(names) == 4, f"expected 2 reports = 4 files, got {len(names)}: {sorted(names)}"
    # Each surviving report retains BOTH its html and its sidecar.
    for html, meta in reports[2:]:
        assert html.name in names and meta.name in names
    for html, meta in reports[:2]:
        assert html.name not in names and meta.name not in names


def test_prune_traffic_does_not_touch_network_inventory_when_only_kind_present(tmp_path):
    """A 'traffic' prune in a dir that holds ONLY NetworkInventory reports must
    delete nothing (precise prefix no longer matches the other kind)."""
    ni = [_make_report(tmp_path, "NetworkInventory", f"2026-06-0{i + 1}_0000", 1_000_000 + i)
          for i in range(5)]

    sched = ReportScheduler.__new__(ReportScheduler)
    sched._prune_by_count(str(tmp_path), "traffic", max_reports=1)

    names = {p.name for p in tmp_path.iterdir()}
    for html, meta in ni:
        assert html.name in names and meta.name in names


def test_prune_traffic_matches_only_unsuffixed_timestamp_filename(tmp_path):
    """'traffic' now emits UNSUFFIXED filenames (TrafficFlowsHtmlExporter
    ._filename: 'Illumio_Traffic_Report_<ts>.html', no kind suffix). Retention
    for 'traffic' must match ONLY that unsuffixed pattern, and 'security_risk'
    must keep matching ONLY its own SecurityRisk-suffixed filename -- neither
    may cross-match the other's (or NetworkInventory's) files sharing the dir.
    """
    ts_old, ts_new = "2026-07-01_0100", "2026-07-03_0202"
    # Two 'traffic' reports (over the max_reports=1 cap) plus one SecurityRisk
    # and one NetworkInventory report from sibling schedules in the same dir.
    traffic_old = tmp_path / f"Illumio_Traffic_Report_{ts_old}.html"
    traffic_new = tmp_path / f"Illumio_Traffic_Report_{ts_new}.html"
    sr = tmp_path / f"Illumio_Traffic_Report_SecurityRisk_{ts_new}.html"
    ni = tmp_path / f"Illumio_Traffic_Report_NetworkInventory_{ts_new}.html"
    for f, mtime in ((traffic_old, 1_000_000), (traffic_new, 2_000_000),
                     (sr, 3_000_000), (ni, 4_000_000)):
        f.write_text("x")
        os.utime(f, (mtime, mtime))

    sched = ReportScheduler.__new__(ReportScheduler)

    # A 'traffic' prune with room for only one report must: (a) actually match
    # and prune the oldest traffic report -- proving the matcher isn't blind to
    # the new unsuffixed filename -- and (b) never touch the
    # SecurityRisk/NetworkInventory files, which share the literal prefix.
    sched._prune_by_count(str(tmp_path), "traffic", max_reports=1)
    names = {p.name for p in tmp_path.iterdir()}
    assert traffic_old.name not in names, "oldest traffic report should have been pruned"
    assert traffic_new.name in names, "newest traffic report wrongly pruned"
    assert sr.name in names, "SecurityRisk report wrongly matched by 'traffic' prune"
    assert ni.name in names, "NetworkInventory report wrongly matched by 'traffic' prune"

    # A 'security_risk' prune must likewise only ever touch its own file.
    sched._prune_by_count(str(tmp_path), "security_risk", max_reports=1)
    names = {p.name for p in tmp_path.iterdir()}
    assert traffic_new.name in names
    assert sr.name in names, "own SecurityRisk report wrongly pruned"
    assert ni.name in names


# ─── M4: retention scoped per schedule_id (shared report_type + dir) ───────────

def _make_report_for(directory, kind, ts, mtime, schedule_id):
    """A report unit whose sidecar records which schedule produced it."""
    stem = f"Illumio_Traffic_Report_{kind}_{ts}"
    html = directory / f"{stem}.html"
    meta = directory / f"{stem}.html.metadata.json"
    html.write_text("x")
    meta.write_text(json.dumps({"schedule_id": schedule_id}))
    for f in (html, meta):
        os.utime(f, (mtime, mtime))
    return html, meta


def test_prune_scoped_to_schedule_spares_sibling_schedule(tmp_path):
    """Two schedules of the SAME report_type in the SAME dir must not prune each
    other: a scoped prune(schedule_id=1) trims only schedule 1's reports and
    leaves every report produced by schedule 2 untouched."""
    s1 = [_make_report_for(tmp_path, "SecurityRisk", f"2026-06-0{i + 1}_0000",
                           1_000_000 + i, schedule_id=1) for i in range(3)]
    s2 = [_make_report_for(tmp_path, "SecurityRisk", f"2026-06-1{i + 1}_0000",
                           2_000_000 + i, schedule_id=2) for i in range(3)]

    sched = ReportScheduler.__new__(ReportScheduler)
    sched._prune_by_count(str(tmp_path), "security_risk", max_reports=2, schedule_id=1)

    names = {p.name for p in tmp_path.iterdir()}
    # Schedule 2's three reports (6 files) all survive.
    for html, meta in s2:
        assert html.name in names and meta.name in names, "sibling schedule wrongly pruned"
    # Schedule 1 trimmed to its 2 newest reports.
    assert s1[0][0].name not in names and s1[0][1].name not in names
    assert s1[1][0].name in names and s1[2][0].name in names


def test_scoped_prune_ignores_legacy_files_without_schedule_id(tmp_path):
    """Legacy reports (sidecar has no schedule_id) predate stamping; a scoped
    prune must leave them for the age-based sweep rather than count-pruning
    them against a schedule they cannot be attributed to."""
    legacy = [_make_report(tmp_path, "SecurityRisk", f"2026-05-0{i + 1}_0000",
                          500_000 + i) for i in range(4)]  # meta = "{}", no schedule_id

    sched = ReportScheduler.__new__(ReportScheduler)
    sched._prune_by_count(str(tmp_path), "security_risk", max_reports=1, schedule_id=1)

    names = {p.name for p in tmp_path.iterdir()}
    for html, meta in legacy:
        assert html.name in names and meta.name in names, "legacy report wrongly count-pruned"


def test_unscoped_prune_preserves_pool_behavior(tmp_path):
    """Backward compatibility: without schedule_id the prune keeps its original
    report_type-pool semantics (used by manual runs and existing callers)."""
    reports = [_make_report_for(tmp_path, "SecurityRisk", f"2026-06-0{i + 1}_0000",
                               1_000_000 + i, schedule_id=i) for i in range(4)]

    sched = ReportScheduler.__new__(ReportScheduler)
    sched._prune_by_count(str(tmp_path), "security_risk", max_reports=2)

    names = {p.name for p in tmp_path.iterdir()}
    assert len([n for n in names if n.endswith(".html")]) == 2
    for html, meta in reports[2:]:
        assert html.name in names and meta.name in names


# ─── Finding #6: schedule timezone 'local'/unset semantics ────────────────────

def test_local_and_unset_tz_documented_as_utc():
    """Pin the documented semantics of _now_in_schedule_tz: tz='local'/unset
    resolve to UTC (aware), NOT server-local time. A schedule's hour/minute
    therefore matches UTC wall-clock. This makes the intentional choice (shared
    with rule_scheduler._now_in_tz) explicit so it cannot silently regress.
    """
    utc = datetime.datetime.now(datetime.timezone.utc)
    for tz in ("local", ""):
        now = _now_in_schedule_tz(tz)
        assert now.tzinfo is not None, f"{tz!r} must stay tz-aware"
        # Same instant as UTC now (within a minute) — i.e. UTC, not shifted to a
        # server-local offset.
        assert abs((now - utc).total_seconds()) < 60


def test_local_schedule_fires_on_utc_wall_clock():
    """A daily schedule under tz='local' is due when its hour/minute equal the
    current UTC hour/minute (documented UTC semantics), confirming the gap-guard
    normalisation does not raise for the aware 'local' now."""
    now = _now_in_schedule_tz("local")  # aware UTC
    sched = {"id": 7, "enabled": True, "schedule_type": "daily",
             "hour": now.hour, "minute": now.minute}
    scheduler = ReportScheduler.__new__(ReportScheduler)
    # last_run_str=None → skip the rerun-gap branch; pure due-time evaluation.
    assert scheduler.should_run(sched, now, last_run_str=None) is True
