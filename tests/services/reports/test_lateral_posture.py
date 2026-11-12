"""The lateral movement posture report (P5a Task 3, spec §6.5.5 flagship)."""
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.domain.conclusion import incomplete
from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.report import BarBlock, TableBlock, TextBlock
from illumio_ops.domain.values import DataOrigin, Language, ReportType
from illumio_ops.services.reports.lateral_posture import build_lateral_posture
from illumio_ops.services.reports.registry import BuildInput, ReportParams
from illumio_ops.store.flowdb import analysis, workloads
from illumio_ops.store.flowdb.analysis import DetectionWrite
from illumio_ops.store.flowdb.flows import rebuild_rollup, upsert_flows
from tests.services.collect.conftest import configured_ctx, raw_flow

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
A, B, DB = "/orgs/1/workloads/a", "/orgs/1/workloads/b", "/orgs/1/workloads/db"


def _inp(ctx, lang=Language.EN):
    return BuildInput(ctx=ctx, params=ReportParams(report_type=ReportType.LATERAL_POSTURE), start=START, end=END,
                      lang=lang, tz=UTC, now=NOW, pce_label="pce")


def _hosts(ctx):
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href=h, hostname=name, name=None, managed=1, enforcement_mode="selective", visibility_level=None,
            os_id=None, ven_version=None, ven_href=None, label_set=None, online=1, risk_exposure=None,
            risk_percent=None, risk_updated_at=None, fetched_at="x") for h, name in
            ((A, "app-01"), (B, "bak-01"), (DB, "fin-db-01"))])


def _exposure(ctx, *, at=NOW - timedelta(minutes=30), assets=True):
    result = {
        "computed_at": at.isoformat(), "observation_from": (at - timedelta(days=30)).isoformat(),
        "observation_to": at.isoformat(), "hops": 3, "nodes": 3, "edges_now": 2, "edges_enforced": 1,
        "unknown_edges": 1,
        "hosts": [{"key": A, "reach_now": 2, "reach_enforced": 0, "pivot_now": False, "pivot_enforced": False},
                  {"key": B, "reach_now": 1, "reach_enforced": 1, "pivot_now": True, "pivot_enforced": False}],
        "assets": [{"key": DB, "sources_now": 2, "sources_enforced": 1, "paths": [[A, B, DB]],
                    "cuts": [{"kind": "edge", "src": B, "dst": DB, "ports": [[3389, 6]], "before": 2, "after": 0}]}]
        if assets else [],
        "cross_env": [{"src": A, "dst": DB, "src_env": "Dev", "dst_env": "Prod", "ports": [[22, 6]],
                       "state": "allowed"}],
        "cross_env_total": 3, "footholds": [], "limits_hit": []}
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "exposure", params={}, result=result, at=at)
        conn.commit()


def _snapshot(ctx, day, **metrics):
    base = {"assets_reachable_now": 1, "pivots_now": 1, "cross_env_edges": 3, "edges_now": 2}
    with ctx.flows().connect() as conn:
        analysis.write_lateral_snapshot(conn, day, base | metrics)
        conn.commit()


def _detection(ctx, detector, first, *, severity="medium", subject=A, summary=None):
    with ctx.flows().connect() as conn:
        analysis.upsert_detections(conn, [DetectionWrite(
            detector=detector, fingerprint=f"{detector}|{subject}|{first}", subject_key=subject, severity=severity,
            first_seen=first, last_seen=first + timedelta(minutes=5), critical_asset=False,
            summary_json=json.dumps(summary or {"targets": 11, "window_minutes": 60}), segment_json="{}",
            confidence_json="{}")], dedup={detector: timedelta(minutes=1)}, late=False, at=first)


@pytest.fixture
def ctx(tmp_path):
    c = configured_ctx(tmp_path)
    c.settings.update(c.settings.current().revision,
                      lambda d: d["lateral"].update(critical_assets=[{"key": "app", "value": "Finance"}]))
    _hosts(c)
    return c


def _section(doc, sid):
    return next(s for s in doc.sections if s.id == sid)


def _texts(doc):
    out = [doc.title, *doc.data_quality, *(k.note or "" for k in doc.kpis)]
    for s in doc.sections:
        out += [s.title, s.intro]
        for b in s.blocks:
            if isinstance(b, TableBlock):
                out += [b.empty_text, b.limit_note or ""] + [str(c) for r in b.rows for c in r]
            elif isinstance(b, TextBlock):
                out += list(b.paragraphs)
            elif isinstance(b, BarBlock):
                out.append(b.empty_text)
    return "\n".join(out)


def test_kpis_from_snapshots_and_previous(ctx):
    _exposure(ctx)
    _snapshot(ctx, "2026-10-26", assets_reachable_now=2, pivots_now=4, cross_env_edges=5)
    _snapshot(ctx, "2026-10-19", assets_reachable_now=1, pivots_now=1, cross_env_edges=5)
    _detection(ctx, "fanout", datetime(2026, 10, 21, tzinfo=UTC))
    _detection(ctx, "fanout", datetime(2026, 10, 22, tzinfo=UTC), subject=B)
    _detection(ctx, "fanout", datetime(2026, 10, 15, tzinfo=UTC), subject=B)  # previous period
    from illumio_ops.domain.values import IngestSource
    from illumio_ops.store.flowdb import ingest_state
    with ctx.flows().connect() as conn:
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, START - (END - START), END)
    doc = build_lateral_posture(_inp(ctx))
    k = {x.key: x for x in doc.kpis}
    assert len(doc.kpis) == 4
    assert (k["assets_reachable"].value, k["assets_reachable"].previous) == (2, 1)
    assert (k["pivots"].value, k["pivots"].previous) == (4, 1)
    assert (k["new_detections"].value, k["new_detections"].previous) == (2, 1)
    assert (k["cross_env"].value, k["cross_env"].previous) == (5, 5)


def test_previous_none_without_snapshot(ctx):
    _exposure(ctx)
    _snapshot(ctx, "2026-10-26")
    doc = build_lateral_posture(_inp(ctx))
    k = {x.key: x for x in doc.kpis}
    assert k["pivots"].previous is None and k["assets_reachable"].previous is None


def test_value_falls_back_to_current_exposure_and_says_so(ctx):
    _exposure(ctx)
    doc = build_lateral_posture(_inp(ctx))
    k = {x.key: x for x in doc.kpis}
    assert k["pivots"].value == 1 and k["pivots"].note  # from the current exposure result, noted


def test_no_critical_assets_says_so(tmp_path):
    c = configured_ctx(tmp_path)
    _hosts(c)
    _exposure(c, assets=False)
    doc = build_lateral_posture(_inp(c))
    # 6.6.0: with no critical asset chosen, the number, the section and the column that need one are not there;
    # one data note says what is missing, what choosing them would add and where
    assert "assets_reachable" not in {x.key for x in doc.kpis}
    assert "assets" not in {s.id for s in doc.sections}
    detail = [b for b in _section(doc, "detections").blocks if isinstance(b, TableBlock)][1]
    assert "critical" not in {c.key for c in detail.columns}
    notes = [q for q in doc.data_quality if "critical asset" in q.lower()]
    assert len(notes) == 1 and "Lateral movement settings" in notes[0]
    assert not incomplete(doc)


def test_admin_groups_unset_or_stale_is_said(tmp_path):
    c = configured_ctx(tmp_path)
    _hosts(c)
    doc = build_lateral_posture(_inp(c))
    assert sum("admin group" in q.lower() for q in doc.data_quality) == 1
    c.settings.update(c.settings.current().revision,
                      lambda d: d["lateral"].update(admin_groups=[{"key": "role", "value": "NoSuchLabel"}]))
    stale = [q for q in build_lateral_posture(_inp(c)).data_quality if "admin group" in q.lower()]
    assert len(stale) == 1 and "role=NoSuchLabel" in stale[0]


def test_cut_sentence_names_hosts_and_numbers(ctx):
    _exposure(ctx)
    text = _texts(build_lateral_posture(_inp(ctx)))
    assert "bak-01" in text and "fin-db-01" in text and "3389/TCP" in text
    assert "from 2 to 0" in text


def test_cross_env_limit_disclosed(ctx):
    _exposure(ctx)
    t = next(b for b in _section(build_lateral_posture(_inp(ctx)), "cross_env").blocks if isinstance(b, TableBlock))
    assert t.total_rows == 3 and len(t.rows) == 1 and t.limit_note


def test_no_exposure_result_yet(ctx):
    """6.6.0: before the first exposure computation the sections and numbers that come from it are not there (they
    were five panels reading "not been computed"); one data note says so, and the sentence is still a sentence."""
    doc = build_lateral_posture(_inp(ctx))
    assert {s.id for s in doc.sections} == {"detections", "initiators", "directory"}
    assert {k.key for k in doc.kpis} == {"new_detections"}
    assert sum("not been computed" in q for q in doc.data_quality) == 1
    assert not incomplete(doc)


def test_stale_exposure_in_data_quality(ctx):
    _exposure(ctx, at=NOW - timedelta(hours=5))
    assert any("hours" in q or "stale" in q.lower() for q in build_lateral_posture(_inp(ctx)).data_quality)


def test_detections_section_counts_and_lists(ctx):
    _exposure(ctx)
    _detection(ctx, "fanout", datetime(2026, 10, 21, tzinfo=UTC), severity="high")
    _detection(ctx, "auth_to_non_dc", datetime(2026, 10, 23, tzinfo=UTC),
               summary={"target": "game", "port": 88, "decision": "allowed"})
    sec = _section(build_lateral_posture(_inp(ctx)), "detections")
    by_detector, detail = [b for b in sec.blocks if isinstance(b, TableBlock)]
    assert {r[0]: r[1] for r in by_detector.rows} == {"Fan-out": 1, "Authentication to a non-directory host": 1}
    assert detail.total_rows == 2 and detail.rows[0][1] == "Fan-out"  # high first


def test_findings_only_lateral_kinds_max_five(ctx):
    items = [{"kind": k, "fingerprint": f"f{i}", "severity": "high", "critical_asset": False, "confidence": "high",
              "title_key": "focus_title_pivot_host", "why_key": "focus_why_pivot", "params": {"host": f"h{i}"},
              "action": {"target": "host"}, "score": 9 - i, "first_seen": NOW.isoformat(), "new_this_week": True,
              "weeks_persisting": 0}
             for i, k in enumerate(["tamper", "pivot_host", "pivot_host", "detection", "exposure_asset", "cross_env",
                                    "pivot_host", "visibility"])]
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "focus", params={}, result={"items": items}, at=NOW)
        conn.commit()
    doc = build_lateral_posture(_inp(ctx))
    assert len(doc.findings) == 5
    assert next(f.title for f in doc.findings) == "h1 is a pivot: many management-port paths go through it"
    assert all(f.action for f in doc.findings)
    # the five findings in order: pivot, pivot, detection, exposure asset, cross-environment
    assert [f.action_code for f in doc.findings] == ["lat_pivot_host", "lat_pivot_host", "lat_detection",
                                                     "lat_exposure_asset", "lat_cross_env"]
    assert all(f.action_short and f.what == "" for f in doc.findings)  # their "why" is a reason: no fact to move
    from illumio_ops.domain.actions import group_actions
    assert [len(a.findings) for a in group_actions(doc.findings)] == [2, 1, 1, 1]


def _dir_flow(i, port, *, day, dst=DB):
    first = day + timedelta(hours=1)
    r = normalize_flow(raw_flow(i, first, first + timedelta(minutes=5), port=port))
    return replace(r, dst_href=dst, dst_ip="10.0.9.9")


def test_directory_section_marks_inferred_and_declared(ctx):
    ctx.settings.update(ctx.settings.current().revision,
                        lambda d: d["lateral"].update(directory_server_ips=["10.0.9.10"]))
    _exposure(ctx)
    with ctx.flows().connect() as conn:
        upsert_flows(conn, [_dir_flow(i, 389, day=datetime(2026, 10, 22, tzinfo=UTC)) for i in range(1, 5)],
                     origin=DataOrigin.INGEST, now=NOW)
        upsert_flows(conn, [_dir_flow(9, 389, day=datetime(2026, 10, 14, tzinfo=UTC))],
                     origin=DataOrigin.INGEST, now=NOW)
        for day in ("2026-10-14", "2026-10-22"):
            rebuild_rollup(conn, day)
    from illumio_ops.domain.values import IngestSource
    from illumio_ops.store.flowdb import ingest_state
    with ctx.flows().connect() as conn:
        ingest_state.add_coverage(conn, IngestSource.TRAFFIC, START - (END - START), END)
    sec = _section(build_lateral_posture(_inp(ctx)), "directory")
    servers, _detections, sources = [b for b in sec.blocks if isinstance(b, TableBlock)]
    rows = {r[0]: r for r in servers.rows}
    assert "fin-db-01" in rows and "Inferred" in rows["fin-db-01"][2]
    assert "10.0.9.10" in rows and "Declared" in rows["10.0.9.10"][2]
    by_src = {r[0]: r for r in sources.rows}  # sources no longer in the inventory are named as removed
    s1 = by_src["Removed workload …src-1"]
    assert s1[1] == 1 and s1[2] == 0 and "None last period" in s1[3]  # the previous period had none from it
    # each row's host key, row for row: a declared address opens the host page as ip:<address>
    assert dict(zip((r[0] for r in servers.rows), servers.host_keys["server"], strict=True))["10.0.9.10"] == "ip:10.0.9.10"
    assert all(k and k.startswith("/orgs/") for k in servers.host_keys["server"][:-1])
    assert len(sources.host_keys["source"]) == len(sources.rows) and all(sources.host_keys["source"])
    assert {b.host_section for b in (servers, sources)} == {"connections"}


def test_generated_through_the_one_path_in_both_languages(ctx):
    from illumio_ops.domain.values import ReportStatus
    from illumio_ops.services.reports import generate
    from illumio_ops.store import reports as store
    _exposure(ctx)
    _detection(ctx, "fanout", datetime(2026, 10, 25, tzinfo=UTC))
    ids = [generate.enqueue(ctx, ReportParams(report_type=ReportType.LATERAL_POSTURE, lang=lang), trigger="manual",
                            schedule_id=None, now=NOW) for lang in (Language.EN, Language.ZH_TW)]
    for _ in ids:
        generate.run_queued(ctx, now=NOW)
    with ctx.db() as conn:
        rows = [store.get(conn, i) for i in ids]
    assert [r.status for r in rows] == [ReportStatus.DONE, ReportStatus.DONE], [r.error_detail for r in rows]
    html = (ctx.paths.reports_dir / str(ids[1]) / next(f for f in rows[1].files if f.endswith(".html"))).read_text()
    assert "橫向移動態勢" in html and "rpt_" not in html


def test_detection_previous_none_when_not_collected(ctx):
    _exposure(ctx)
    k = {x.key: x for x in build_lateral_posture(_inp(ctx)).kpis}
    assert k["new_detections"].previous is None


def test_finding_params_show_addresses_without_key_prefix(ctx):
    """Lab: a detection about an unmanaged source read "ip:139.138.105.82" in the finding's title."""
    item = {"kind": "pivot_host", "fingerprint": "f", "severity": "high", "critical_asset": False,
            "confidence": "high", "title_key": "focus_title_pivot_host", "why_key": "focus_why_pivot",
            "params": {"host": "ip:139.138.105.82"}, "action": {"target": "host"}, "score": 1,
            "first_seen": NOW.isoformat(), "new_this_week": True, "weeks_persisting": 0}
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "focus", params={}, result={"items": [item]}, at=NOW)
        conn.commit()
    [f] = build_lateral_posture(_inp(ctx)).findings
    assert f.title.startswith("139.138.105.82 ")


def test_finding_params_name_hosts_not_their_href(ctx):
    # 2026-11-10 report review: a key finding read "/orgs/1/workloads/<uuid> is a pivot".
    _hosts(ctx)
    gone = "/orgs/1/workloads/0f3c9a7e-1111-2222-3333-444455556666"
    items = [{"kind": "pivot_host", "fingerprint": f"f{i}", "severity": "high", "critical_asset": False,
              "confidence": "high", "title_key": "focus_title_pivot_chain", "why_key": "focus_why_pivot",
              "params": {"host": A, "via": B, "target": target}, "action": {"target": "host"}, "score": 1,
              "first_seen": NOW.isoformat(), "new_this_week": True, "weeks_persisting": 0}
             for i, target in enumerate((DB, gone))]
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "focus", params={}, result={"items": items}, at=NOW)
        conn.commit()
    named, removed = build_lateral_posture(_inp(ctx)).findings
    assert named.title.startswith("app-01 reached fin-db-01 through bak-01;")
    assert removed.title.startswith("app-01 reached Removed workload …556666 through bak-01;")
    assert all("/orgs/" not in f.title + f.why for f in (named, removed))


def test_initiators_section_is_the_pages_ranking(ctx, monkeypatch):
    """6.5.0 B3 (spec §6.5.7): the report's users and processes section prints what the lateral movement page
    shows — both read lateral_defaults, neither keeps a copy of the segments — with the field coverage."""
    from illumio_ops.services.analysis import lateral_defaults as mod
    from illumio_ops.services.analysis.lateral_defaults import (
        Initiator,
        LateralDefaults,
    )
    from illumio_ops.services.reports import lateral_posture
    asked = []

    assert lateral_posture.lateral_defaults is mod.lateral_defaults  # the shared function, not a copy

    def fake(c, *, start, end, now):
        asked.append((start, end))
        return LateralDefaults(start=start, end=end, users=[Initiator(name="corp\\alice", destinations=7)],
                               processes=[], system_accounts=[Initiator(name="root", destinations=2)],
                               more={"users": 3}, capped={"processes": 50, "system_accounts": 1000}, flows=200,
                               with_user=50, with_process=0)
    monkeypatch.setattr(lateral_posture, "lateral_defaults", fake)
    assert lateral_posture.lateral_defaults is fake and mod.lateral_defaults is not fake
    doc = build_lateral_posture(_inp(ctx))
    sec = _section(doc, "initiators")
    assert asked == [(START, END)]
    assert "200" in sec.intro and "50 (25.0%)" in sec.intro and "0 (0.0%)" in sec.intro
    tables = [b for b in sec.blocks if isinstance(b, TableBlock)]
    assert [t.rows for t in tables] == [(("corp\\alice", 7),), (), (("root", 2),)]
    assert tables[0].total_rows == 4 and tables[0].limit_note  # three more exist and the table says so
    assert tables[1].empty_text == "No management-port flow record names a process."
    # a read that stopped at its limit never reads as "none" or as the whole list
    assert "first 50" in tables[1].limit_note and "first 1000 accounts" in tables[2].limit_note


def test_admin_groups_with_one_label_gone_still_detect(tmp_path):
    """The detector is off only when every admin-group Label is gone (services/analysis/detect.py): with one left
    the note says the detection judges by the rest, not that it did not run."""
    from illumio_ops.store.flowdb.labels import label_set_id
    c = configured_ctx(tmp_path)
    _hosts(c)
    with c.flows().connect() as conn:  # a host carries app=Finance: that Label exists
        conn.execute("UPDATE workloads SET label_set = ? WHERE href = ?", (label_set_id(conn, (("app", "Finance"),)), DB))
        conn.commit()
    c.settings.update(c.settings.current().revision, lambda d: d["lateral"].update(
        admin_groups=[{"key": "app", "value": "Finance"}, {"key": "role", "value": "NoSuchLabel"}]))
    notes = [q for q in build_lateral_posture(_inp(c)).data_quality if "admin group" in q.lower()]
    assert len(notes) == 1 and "role=NoSuchLabel" in notes[0] and "app=Finance" not in notes[0]
    assert "remaining" in notes[0] and "did not run" not in notes[0]
