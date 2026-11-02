"""Rule test on the alert rules page (UI redesign spec §5.1): a recent detection or event against every rule of its
kind, saying which would alert and where it would be sent — nothing written, nothing sent."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.domain.alerting import RuleState
from illumio_ops.domain.events import normalize_event
from illumio_ops.domain.values import DataOrigin
from illumio_ops.services.alerts import rule_test
from illumio_ops.store import alerts as store
from illumio_ops.store.flowdb import analysis
from illumio_ops.store.flowdb.analysis import DetectionWrite
from illumio_ops.store.flowdb.events import upsert_events
from tests.services.collect.conftest import configured_ctx

NOW = datetime.now(UTC).replace(microsecond=0)
WEB = "/orgs/1/workloads/web"


def _rule(i, **kw):
    base = {"id": f"{i:032x}", "name": f"rule {i}", "pack_key": None, "enabled": True, "notify": True,
            "severity": None, "cooldown_minutes": 0, "throttle": None}
    return base | kw


LATERAL = {"type": "lateral", "min_severity": "medium", "critical_assets_only": False, "exclude": None}
EVENT = {"type": "event", "status": "", "event_severity": "", "match_fields": {}, "threshold": "immediate",
         "threshold_count": 1, "window_minutes": 10}


@pytest.fixture
def ctx(tmp_path):
    c = configured_ctx(tmp_path, mode="full")

    def rules(d):
        d["alerts"]["rules"] = [
            _rule(1, **LATERAL, detectors=["fanout"]),
            _rule(2, **LATERAL, detectors=["new_process"]),
            _rule(3, **(LATERAL | {"critical_assets_only": True}), detectors=["fanout"]),
            _rule(4, **(LATERAL | {"min_severity": "critical"}), detectors=["fanout"]),
            _rule(5, **LATERAL, detectors=["fanout"], notify=False),
            _rule(6, **LATERAL, detectors=["fanout"], enabled=False),
            _rule(7, **LATERAL, detectors=["fanout"], cooldown_minutes=60),
            _rule(8, **EVENT, event_types=["agent.tampering"]),
            _rule(9, **(EVENT | {"threshold": "count", "threshold_count": 5}), event_types=["agent.*"]),
            _rule(10, **EVENT, event_types=["user.login"]),
        ]
        d["alerts"]["channels"]["line"].update(enabled=True, access_token="t", target_id="U1")
    c.settings.update(c.settings.current().revision, rules)
    with c.flows().connect() as conn:
        analysis.upsert_detections(conn, [DetectionWrite(
            detector="fanout", fingerprint=f"fanout|{WEB}", subject_key=WEB, severity="high",
            first_seen=NOW - timedelta(minutes=30), last_seen=NOW - timedelta(minutes=5), critical_asset=False,
            summary_json=json.dumps({"targets": 9}), segment_json='{"filter": {"start": "2026-11-03T00:00:00Z", '
            '"end": "2026-11-03T01:00:00Z"}, "view": "detail", "limit": 50}', confidence_json="{}")],
            dedup={"fanout": timedelta(hours=1)}, late=False, at=NOW)
        upsert_events(conn, [normalize_event({"href": "/orgs/1/events/e1", "event_type": "agent.tampering",
                                              "status": "success", "severity": "warning",
                                              "timestamp": (NOW - timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                              "created_by": {"agent": {"href": "/orgs/1/agents/1", "hostname": "web"}},
                                              "resource_changes": [], "notifications": []})],
                      origin=DataOrigin.INGEST, now=NOW)
        conn.commit()
    return c


def _detection_id(ctx):
    with ctx.flows().connect() as conn:
        return int(conn.execute("SELECT id FROM detections").fetchone()[0])


def _event_id(ctx):
    with ctx.flows().connect() as conn:
        return int(conn.execute("SELECT id FROM events").fetchone()[0])


def _by_rule(result):
    return {m.rule_name.split()[-1]: m for m in result.items}


def test_detection_against_lateral_rules(ctx):
    r = _by_rule(rule_test.run(ctx, "detection", _detection_id(ctx), now=NOW))
    assert set(r) == {"1", "2", "3", "4", "5", "6", "7"}  # lateral rules only
    assert r["1"].would_alert and r["1"].channels == ["line"] and r["1"].reason_key is None
    assert (r["2"].would_alert, r["2"].reason_key) == (False, "rule_test_other_detector")
    assert r["3"].reason_key == "rule_test_not_critical"
    assert r["4"].reason_key == "rule_test_below_severity"
    assert r["5"].would_alert and r["5"].channels == [] and r["5"].reason_key == "rule_test_record_only"
    assert (r["6"].would_alert, r["6"].reason_key) == (False, "rule_test_disabled")


def test_cooldown_reported(ctx):
    with ctx.db() as conn:
        store.save_rule_state(conn, f"{7:032x}", f"fanout|{WEB}", RuleState(last_fired_at=NOW - timedelta(minutes=10),
                                                                             recent=()), suppressed=None)
        conn.commit()
    r = _by_rule(rule_test.run(ctx, "detection", _detection_id(ctx), now=NOW))
    assert (r["7"].would_alert, r["7"].reason_key) == (False, "rule_test_cooldown")
    assert r["1"].would_alert  # no state for rule 1


def test_event_against_event_rules(ctx):
    r = _by_rule(rule_test.run(ctx, "event", _event_id(ctx), now=NOW))
    assert set(r) == {"8", "9", "10"}
    assert r["8"].would_alert and r["8"].channels == ["line"]
    assert (r["9"].would_alert, r["9"].reason_key) == (False, "rule_test_needs_count")
    assert r["9"].params == {"count": "5", "minutes": "10"}
    assert (r["10"].would_alert, r["10"].reason_key) == (False, "rule_test_no_match")


def test_writes_nothing(ctx):
    def counts():
        with ctx.db() as conn:
            return [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("alerts", "alert_rule_state", "alert_deliveries")]
    before = counts()
    rule_test.run(ctx, "detection", _detection_id(ctx), now=NOW)
    rule_test.run(ctx, "event", _event_id(ctx), now=NOW)
    assert counts() == before


def test_unknown_record(ctx):
    with pytest.raises(LookupError):
        rule_test.run(ctx, "detection", 999, now=NOW)


def test_candidates_recent_first(ctx):
    c = rule_test.candidates(ctx)
    assert [x.source for x in c.items] == ["detection", "event"] or [x.source for x in c.items] == ["event",
                                                                                                    "detection"]
    assert all(x.title and "{" not in x.title for x in c.items)
