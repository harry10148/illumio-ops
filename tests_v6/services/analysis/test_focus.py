"""build_focus: the hourly step that derives, persists and ranks the focus list."""
import json
from datetime import timedelta

from illumio_ops.domain.values import IngestSource, Language
from illumio_ops.i18n import dictionary
from illumio_ops.services.analysis.focus import build_focus
from illumio_ops.services.analysis.hourly import HOURLY_STEPS
from illumio_ops.store.flowdb import analysis, ingest_state
from illumio_ops.store.flowdb.analysis import DetectionWrite
from tests_v6.services.collect.conftest import NOW, configured_ctx


def _result(ctx):
    with ctx.flows().connect() as conn:
        return json.loads(analysis.read_result(conn, "focus")["result_json"])


def test_focus_is_the_last_hourly_step():
    assert HOURLY_STEPS[-1][0] == "focus"


def test_missing_source_reported_in_status(tmp_path):
    ctx = configured_ctx(tmp_path)
    build_focus(ctx, NOW)
    res = _result(ctx)
    assert res["sources_status"]["exposure"] == "missing" and res["sources_status"]["detections"] == "ok"
    assert {i["title_key"] for i in res["items"]} >= {"focus_title_setup_critical", "focus_title_setup_admin"}


def test_first_seen_persists_across_runs(tmp_path):
    ctx = configured_ctx(tmp_path)
    with ctx.flows().connect() as conn:
        analysis.upsert_detections(conn, [DetectionWrite(
            detector="fanout", fingerprint="fanout|/w/a", subject_key="/w/a", severity="high",
            first_seen=NOW - timedelta(minutes=30), last_seen=NOW - timedelta(minutes=5), critical_asset=False,
            summary_json=json.dumps({"targets": 12, "window_minutes": 60}), segment_json='{"view": "detail"}',
            confidence_json="{}")], dedup={"fanout": timedelta(hours=1)}, late=False, at=NOW)
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, NOW - timedelta(hours=2), NOW - timedelta(hours=1),
                                "failed", "x", NOW)
    build_focus(ctx, NOW)
    first = {i["fingerprint"]: i for i in _result(ctx)["items"]}
    assert first["det|fanout|/w/a"]["new_this_week"] is True and "gaps" in first
    build_focus(ctx, NOW + timedelta(days=9))  # the detection is older than 7 days by now: gone from the list
    later = {i["fingerprint"]: i for i in _result(ctx)["items"]}
    assert "det|fanout|/w/a" not in later
    assert later["setup|critical"]["first_seen"] == first["setup|critical"]["first_seen"]
    assert later["setup|critical"]["new_this_week"] is False and later["setup|critical"]["weeks_persisting"] == 1


def test_events_only_mode_lists_only_the_mode(tmp_path):
    ctx = configured_ctx(tmp_path, mode="events_only")
    build_focus(ctx, NOW)
    assert [i["title_key"] for i in _result(ctx)["items"]] == ["focus_title_events_only"]


def test_every_focus_key_in_both_languages():
    from illumio_ops.domain.focus import FOCUS_KEYS
    for lang in (Language.EN, Language.ZH_TW):
        assert all(k in dictionary(lang) for k in FOCUS_KEYS.values())
