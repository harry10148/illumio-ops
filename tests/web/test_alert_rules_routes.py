"""Alert rules API: list with status, create / update / delete through the settings file, preview, pack."""
from illumio_ops.domain.alertpack import pack_rule_id

from .conftest import LOCAL, csrf, login, post

CUSTOM = {"id": "0" * 32, "name": "SSH to prod", "pack_key": "ignored", "enabled": True, "notify": True,
          "severity": "high", "cooldown_minutes": 30, "throttle": None, "type": "traffic",
          "condition": {"ports": [{"port": 22, "proto": 6}], "decisions": ["blocked"]}, "threshold_connections": 5,
          "window_minutes": 10}


def rules(client):
    return client.get("/api/alert-rules", environ_overrides=LOCAL).get_json()["data"]


def put(client, url, body):
    return client.open(url, method="PUT", json=body, environ_overrides=LOCAL, headers={"X-CSRFToken": csrf(client)})


def delete(client, url, body):
    return client.open(url, method="DELETE", json=body, environ_overrides=LOCAL, headers={"X-CSRFToken": csrf(client)})


def test_list_has_pack_with_names(client):
    login(client)
    data = rules(client)
    names = {i["rule"]["id"]: i["display_name"] for i in data["items"]}
    assert names[pack_rule_id("rule_agent_tampering")] == "Agent Tampering Detected" and data["pack_missing"] == 0


def test_create_assigns_id(client):
    login(client)
    rev = rules(client)["revision"]
    r = post(client, "/api/alert-rules", {"revision": rev, "rule": CUSTOM})
    data = r.get_json()["data"]
    mine = [i["rule"] for i in data["items"] if i["rule"]["name"] == "SSH to prod"]
    assert r.status_code == 200 and len(mine) == 1
    assert mine[0]["id"] != "0" * 32 and len(mine[0]["id"]) == 32 and mine[0]["pack_key"] is None


def test_update_keeps_id_and_pack_key(client):
    login(client)
    data = rules(client)
    rid = pack_rule_id("rule_agent_tampering")
    rule = next(i["rule"] for i in data["items"] if i["rule"]["id"] == rid)
    changed = rule | {"id": "f" * 32, "pack_key": None, "name": "Tamper", "cooldown_minutes": 5}
    out = put(client, f"/api/alert-rules/{rid}", {"revision": data["revision"], "rule": changed}).get_json()["data"]
    saved = next(i["rule"] for i in out["items"] if i["rule"]["id"] == rid)
    assert saved["cooldown_minutes"] == 5 and saved["pack_key"] == "rule_agent_tampering"


def test_update_unknown_rule_404(client):
    login(client)
    data = rules(client)
    r = put(client, f"/api/alert-rules/{'e' * 32}", {"revision": data["revision"], "rule": CUSTOM})
    assert r.status_code == 404


def test_delete(client):
    login(client)
    data = rules(client)
    rid = pack_rule_id("rule_agent_clone")
    out = delete(client, f"/api/alert-rules/{rid}", {"revision": data["revision"]}).get_json()["data"]
    assert rid not in {i["rule"]["id"] for i in out["items"]} and out["pack_missing"] == 1


def test_invalid_regex_400_with_field(client):
    login(client)
    bad = CUSTOM | {"type": "event", "event_types": ["agent.(x"], "status": "all", "event_severity": "all",
                    "match_fields": {}, "threshold": "immediate", "threshold_count": 1, "window_minutes": 10}
    for k in ("condition", "threshold_connections"):
        del bad[k]
    r = post(client, "/api/alert-rules", {"revision": rules(client)["revision"], "rule": bad})
    err = r.get_json()["error"]
    assert r.status_code == 400 and err["code"] == "invalid_input" and "event_types" in err["field"]
    assert "agent.(x" not in r.get_data(as_text=True)


def test_stale_revision_409(client):
    login(client)
    r = post(client, "/api/alert-rules", {"revision": 9999, "rule": CUSTOM})
    assert r.status_code == 409


def test_preview_route(client):
    login(client)
    r = post(client, "/api/alert-rules/preview", {"rule": CUSTOM, "hours": 24})
    data = r.get_json()["data"]
    assert r.status_code == 200 and data["status"] == "ok" and data["would_fire"] == 0


def test_pack_modes(client):
    login(client)
    data = rules(client)
    rid = pack_rule_id("rule_agent_clone")
    data = delete(client, f"/api/alert-rules/{rid}", {"revision": data["revision"]}).get_json()["data"]
    out = post(client, "/api/alert-rules/pack", {"revision": data["revision"], "mode": "append_missing"})
    assert rid in {i["rule"]["id"] for i in out.get_json()["data"]["items"]}
    bad = post(client, "/api/alert-rules/pack", {"revision": out.get_json()["data"]["revision"], "mode": "everything"})
    assert bad.status_code == 400


def test_rule_test_routes(client, ctx):
    from .conftest import post
    assert client.get("/api/alert-rules/test-candidates", environ_overrides=LOCAL).status_code == 401
    login(client)
    assert client.get("/api/alert-rules/test-candidates", environ_overrides=LOCAL).get_json()["data"] == {"items": []}
    r = post(client, "/api/alert-rules/test", {"source": "detection", "id": 99})
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "not_found"
    assert post(client, "/api/alert-rules/test", {"source": "alert", "id": 1}).status_code == 400


def test_condition_choices_offer_labels_and_the_pce_objects(client, ctx):
    """5.x parity 2026-11-06: a condition can name label groups and services; the editor offers what the inventory read."""
    from datetime import UTC, datetime

    from illumio_ops.store.flowdb import ip_lists, policy_objects
    from illumio_ops.store.flowdb.db import transaction
    at = datetime(2026, 11, 6, tzinfo=UTC)
    with ctx.flows().connect() as conn, transaction(conn):
        ip_lists.replace_all(conn, [ip_lists.IpListRow("/orgs/1/sec_policy/active/ip_lists/1", "Scanners", ())], at=at)
        policy_objects.replace_services(conn, [policy_objects.ServiceRow("/orgs/1/sec_policy/active/services/2", "Web",
                                                                         ((443, None, 6),))], at=at)
        policy_objects.replace_label_groups(conn, [policy_objects.LabelGroupRow(
            "/orgs/1/sec_policy/active/label_groups/3", "Live", "env", ("Prod",))], at=at)
    login(client)
    data = client.get("/api/alert-rules/condition-choices", environ_overrides=LOCAL).get_json()["data"]
    assert data["ip_lists"] == [{"href": "/orgs/1/sec_policy/active/ip_lists/1", "name": "Scanners"}]
    assert data["services"] == [{"href": "/orgs/1/sec_policy/active/services/2", "name": "Web"}]
    assert data["label_groups"] == [{"href": "/orgs/1/sec_policy/active/label_groups/3", "name": "Live", "key": "env"}]
    assert data["labels"] == []


def test_rule_with_the_new_conditions_round_trips(client):
    login(client)
    rev = rules(client)["revision"]
    cond = {"either": {"ips": ["10.0.0.9"]}, "services": ["/orgs/1/sec_policy/active/services/2"],
            "src": {"label_groups": ["/orgs/1/sec_policy/active/label_groups/3"]},
            "windows_services": ["wuauserv"], "exclude_transmissions": ["broadcast", "multicast"],
            "exclude_processes": ["svchost.exe"]}
    r = post(client, "/api/alert-rules", {"revision": rev, "rule": CUSTOM | {"name": "Parity", "condition": cond}})
    saved = next(i["rule"] for i in r.get_json()["data"]["items"] if i["rule"]["name"] == "Parity")
    for k, v in cond.items():
        got = saved["condition"][k]
        assert (got if not isinstance(v, dict) else {kk: got[kk] for kk in v}) == v, k


def test_event_catalog_lists_categories_with_their_events(client):
    login(client)
    data = client.get("/api/alert-rules/event-catalog", environ_overrides=LOCAL).get_json()["data"]
    cats = {c["id"]: c for c in data["categories"]}
    assert data["categories"][0]["id"] == "general" and cats["agent_security"]["label_key"] == "evcat_agent_security"
    tamper = next(e for e in cats["agent_security"]["events"] if e["event_type"] == "agent.tampering")
    assert tamper == {"event_type": "agent.tampering", "description_key": "evdesc_agent_tampering",
                      "vendor_documented": True, "status_filter": False, "severity_filter": False}
    sign_in = next(e for c in data["categories"] for e in c["events"] if e["event_type"] == "user.sign_in")
    assert sign_in["status_filter"] and sign_in["severity_filter"]


# ── 5.x parity 2026-11-06: cooldown shown and reset, retention 0 = forever, evaluate now ──

def _held_state(ctx, rule_id, *, minutes_ago=5):
    from datetime import UTC, datetime, timedelta

    from illumio_ops.domain.alerting import RuleState
    from illumio_ops.store import alerts as store
    fired = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    with ctx.db() as conn:
        store.save_rule_state(conn, rule_id, "host-a", RuleState(fired, ()), suppressed="cooldown")
        store.set_seen_severity(conn, rule_id, "host-a", "high")
        conn.commit()
    return fired


def test_rules_list_says_how_long_a_rule_is_held(client, ctx):
    from datetime import timedelta
    rid = pack_rule_id("rule_agent_tampering")  # cooldown 30 minutes
    fired = _held_state(ctx, rid)
    login(client)
    item = next(i for i in rules(client)["items"] if i["rule"]["id"] == rid)
    assert item["held"]["reason"] == "cooldown" and item["held"]["subjects"] == 1
    assert item["held"]["until"].startswith((fired + timedelta(minutes=30)).isoformat()[:16])
    other = next(i for i in rules(client)["items"] if i["rule"]["id"] == pack_rule_id("rule_agent_suspend"))
    assert other["held"] is None


def test_reset_clears_cooldown_and_throttle_but_not_what_was_seen(client, ctx):
    from illumio_ops.store import alerts as store
    rid = pack_rule_id("rule_agent_tampering")
    _held_state(ctx, rid)
    login(client)
    r = post(client, f"/api/alert-rules/{rid}/reset-state", None)
    item = next(i for i in r.get_json()["data"]["items"] if i["rule"]["id"] == rid)
    assert item["held"] is None
    with ctx.db() as conn:
        assert store.rule_state(conn, rid, "host-a").last_fired_at is None
        assert store.seen_severity(conn, rid, "host-a") == "high"  # a detection seen before still does not re-alert
    assert post(client, f"/api/alert-rules/{'e' * 32}/reset-state", None).status_code == 404


def test_alert_retention_zero_keeps_alerts_forever(client, ctx):
    from datetime import UTC, datetime, timedelta

    from illumio_ops.services.alerts.retention import run_alert_retention
    login(client)
    data = rules(client)
    r = put(client, "/api/alert-rules/retention", {"revision": data["revision"], "retention_days": 0})
    assert r.status_code == 200 and r.get_json()["data"]["retention_days"] == 0
    assert ctx.settings.current().alerts.retention_days == 0
    with ctx.db() as conn:
        conn.execute("INSERT INTO alerts (id, pce_url, org_id, rule_id, rule_type, rule_name, pack_key, severity, "
                     "subject_key, fired_at, first_seen, last_seen, late, notify, message_key, params_json, facts_json, "
                     "confidence_json) VALUES (1, 'u', '1', 'r', 'event', 'n', NULL, 'low', 's', ?, ?, ?, 0, 1, 'm', "
                     "'{}', '{}', '{}')",
                     ((datetime.now(UTC) - timedelta(days=4000)).isoformat(),) * 3)
        conn.commit()
    assert run_alert_retention(ctx) == 0
    with ctx.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 1
    bad = put(client, "/api/alert-rules/retention", {"revision": rules(client)["revision"], "retention_days": -1})
    assert bad.status_code == 400


def test_evaluate_now_asks_the_existing_jobs_to_run(client, ctx):
    from datetime import UTC, datetime

    from illumio_ops.jobs.scheduler import build_scheduler
    login(client)
    assert post(client, "/api/alert-rules/evaluate-now", None).status_code == 503  # nothing scheduled: said so
    ctx.scheduler = build_scheduler(ctx)
    try:
        before = datetime.now(UTC)
        r = post(client, "/api/alert-rules/evaluate-now", None)
        assert r.status_code == 200
        jobs = r.get_json()["data"]["jobs"]
        assert jobs == ["collect_events", "collect_traffic", "alerts_system", "pce_probe"]
        for job_id in jobs:
            assert ctx.scheduler.get_job(job_id).next_run_time <= datetime.now(UTC)
            assert ctx.scheduler.get_job(job_id).next_run_time >= before.replace(microsecond=0)
        assert len(ctx.scheduler.get_jobs()) == len(set(j.id for j in ctx.scheduler.get_jobs()))  # no new job
    finally:
        ctx.scheduler = None
