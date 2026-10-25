"""Tamper analysis per host and the hourly summary; known causes are kept per PCE."""
import json
from datetime import timedelta

from illumio_ops.domain.events import normalize_event
from illumio_ops.domain.tamper import GUIDANCE_KEYS, TAMPER_ACTION_KEYS
from illumio_ops.domain.values import DataOrigin, Language, TamperPattern
from illumio_ops.i18n import dictionary
from illumio_ops.services.analysis.hourly import HOURLY_STEPS
from illumio_ops.services.analysis.tamper import (
    add_annotation,
    host_tamper,
    list_annotations,
    remove_annotation,
    tamper_summary,
)
from illumio_ops.store.flowdb import analysis, workloads
from illumio_ops.store.flowdb.events import upsert_events
from tests_v6.services.collect.conftest import NOW, configured_ctx

HOST, VEN = "/orgs/1/workloads/dev", "/orgs/1/vens/v-dev"


def _tamper(i, at, *, signal=False):
    info = ({"event_classification": "signal", "events": [{"timestamp": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
             "tamper_type": "firewall", "process_id": 77, "kernel_functions": ["nf_tables_newrule"],
             "process_name": "nft"}]} if signal else {"event_classification": "confirmed", "num_events": 1})
    return {"href": f"/orgs/1/events/t{i}", "event_type": "agent.tampering", "severity": "info",
            "timestamp": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "created_by": {"ven": {"href": VEN, "hostname": "dev"}},
            "notifications": [{"info": info}]}


def _ctx(tmp_path):
    ctx = configured_ctx(tmp_path)
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href=HOST, hostname="dev", name=None, managed=1, enforcement_mode="visibility_only", visibility_level=None,
            os_id="ubuntu-x86_64-noble", ven_version=None, ven_href=VEN, label_set=None, online=1, risk_exposure=None,
            risk_percent=None, risk_updated_at=None, fetched_at="x")])
        start = NOW - timedelta(hours=3)
        raws = [_tamper(i, start + timedelta(minutes=10 * i), signal=i == 3) for i in range(12)]
        raws.append({"href": "/orgs/1/events/m1", "event_type": "workload.update", "severity": "info",
                     "timestamp": (start - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "created_by": {"ven": {"href": VEN, "hostname": "dev"}}})
        raws.append({"href": "/orgs/1/events/p1", "event_type": "sec_policy.create", "severity": "info",
                     "timestamp": (start + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "created_by": {"user": {"username": "admin"}}})
        upsert_events(conn, [normalize_event(r) for r in raws], origin=DataOrigin.INGEST, now=NOW)
    return ctx


def test_host_tamper_reads_events_pattern_timeline_and_guidance(tmp_path):
    t = host_tamper(_ctx(tmp_path), HOST, now=NOW)
    assert t.pattern.kind is TamperPattern.REGULAR_CYCLE and len(t.readings) == 12
    signal = [r for r in t.readings if r.has_process_info]
    assert len(signal) == 1 and signal[0].process == "nft"
    assert [e.event_type for e in t.timeline] == ["workload.update", "sec_policy.create"]
    assert any(c.text == "nft -s list ruleset" for c in t.guidance)


def test_annotations_scoped_to_current_pce(tmp_path):
    ctx = _ctx(tmp_path)
    aid = add_annotation(ctx, host_href=HOST, pattern=TamperPattern.REGULAR_CYCLE, process=None,
                         reason="NetBird, known", by="illumio")
    assert [(a.id, a.reason) for a in list_annotations(ctx)] == [(aid, "NetBird, known")]
    t = host_tamper(ctx, HOST, now=NOW)
    assert t.explained == {aid: 12}
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update({"org_id": "2"}))
    assert list_annotations(ctx) == []  # another PCE: its hosts are not these
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update({"org_id": "1"}))
    remove_annotation(ctx, aid)
    assert list_annotations(ctx) == []


def test_summary_written_by_hourly_step(tmp_path):
    assert [name for name, _ in HOURLY_STEPS][:3] == ["exposure", "ransomware", "tamper"]
    ctx = _ctx(tmp_path)
    tamper_summary(ctx, NOW)
    with ctx.flows().connect() as conn:
        res = json.loads(analysis.read_result(conn, "tamper")["result_json"])
    [h] = res["hosts"]
    assert (h["href"], h["hostname"], h["n_60d"], h["n_7d"], h["pattern"]) == (HOST, "dev", 12, 12, "regular_cycle")
    assert h["unexplained_7d"] == 12 and h["has_signal"] is True and res["unmatched"] == 0


def test_every_guidance_key_in_both_languages():
    for lang in (Language.EN, Language.ZH_TW):
        d = dictionary(lang)
        assert all(k in d for k in [*GUIDANCE_KEYS.values(), *TAMPER_ACTION_KEYS.values()])
