"""Rule preview (the same evaluation over recent data, nothing written) and applying the best-practice pack."""
import json

from pydantic import TypeAdapter

from illumio_ops.domain.alertpack import best_practice_rules, pack_rule_id
from illumio_ops.domain.alertrules import AlertRule
from illumio_ops.services.alerts.rules import apply_pack, preview_rule, rule_list
from illumio_ops.store import alerts as store
from tests_v6.services.alerts.test_evaluate import (
    Pce,
    _alerts,
    _blocked,
    _collect_and_evaluate,
)
from tests_v6.services.collect.conftest import NOW, configured_ctx, minutes

RULE = TypeAdapter(AlertRule)


def ruleset_rule(**kw):
    d = {"id": "d" * 32, "name": "rs", "pack_key": None, "enabled": True, "notify": True, "severity": "high",
         "cooldown_minutes": 0, "throttle": None, "type": "event", "event_types": ["rule_set.create"], "status": "all",
         "event_severity": "all", "match_fields": {}, "threshold": "immediate", "threshold_count": 1,
         "window_minutes": 10} | kw
    return RULE.validate_python(d)


def test_preview_counts_without_writing(tmp_path, monkeypatch):
    ctx = configured_ctx(tmp_path)
    pce = Pce(monkeypatch)
    for i in range(3):
        pce.event(i, "rule_set.create", NOW - minutes(50 - 10 * i))
    _collect_and_evaluate(ctx, pce, NOW)  # first run: nothing alerted
    p = preview_rule(ctx, ruleset_rule(), hours=24, now=NOW)
    assert p.would_fire == 3 and p.status == "ok" and len(p.samples) == 3
    assert _alerts(ctx) == []


def test_preview_does_not_touch_cooldown(tmp_path, monkeypatch):
    ctx = configured_ctx(tmp_path)
    pce = Pce(monkeypatch)
    pce.event(1, "rule_set.create", NOW - minutes(30))
    pce.event(2, "rule_set.create", NOW - minutes(20))
    _collect_and_evaluate(ctx, pce, NOW)
    p = preview_rule(ctx, ruleset_rule(cooldown_minutes=60), hours=24, now=NOW)
    assert p.would_fire == 1  # the second is within the cooldown, simulated in memory
    with ctx.db() as conn:
        assert store.rule_state(conn, "d" * 32, "rule_set.create") is None


def test_preview_traffic_rule(tmp_path):
    ctx = configured_ctx(tmp_path)
    _blocked(ctx, NOW - minutes(30), 30)
    rule = next(r for r in best_practice_rules(notify_new_defaults=True) if r.pack_key == "rule_high_blocked")
    p = preview_rule(ctx, rule, hours=2, now=NOW)
    assert p.would_fire == 1 and p.status == "ok"
    long = preview_rule(ctx, rule, hours=48, now=NOW)
    assert long.coverage_note == "preview_increments_kept"


def test_preview_system_not_applicable(tmp_path):
    ctx = configured_ctx(tmp_path)
    rule = next(r for r in best_practice_rules(notify_new_defaults=True) if r.type == "system")
    assert preview_rule(ctx, rule, hours=24, now=NOW).status == "not_applicable"


def test_append_missing_keeps_edits():
    pack = best_practice_rules(notify_new_defaults=True)
    edited = pack[0].model_copy(update={"cooldown_minutes": 5})
    current = (edited, ruleset_rule())
    out = apply_pack(current, mode="append_missing", notify_new_defaults=True)
    assert out[0].cooldown_minutes == 5 and out[1].id == "d" * 32 and len(out) == len(pack) + 1


def test_replace_restores_pack_keeps_custom():
    pack = best_practice_rules(notify_new_defaults=True)
    current = (pack[0].model_copy(update={"cooldown_minutes": 5}), ruleset_rule())
    out = apply_pack(current, mode="replace", notify_new_defaults=False)
    by_id = {r.id: r for r in out}
    assert by_id[pack[0].id].cooldown_minutes == pack[0].cooldown_minutes and "d" * 32 in by_id
    assert by_id[pack_rule_id("rule_lateral_fanout")].notify is False


def test_rule_list_includes_last_status(tmp_path, monkeypatch):
    from illumio_ops.services.alerts.evaluate import evaluate_traffic
    ctx = configured_ctx(tmp_path, mode="events_only")
    evaluate_traffic(ctx, now=NOW)
    items = {i.rule.id: i for i in rule_list(ctx, now=NOW)}
    hb = items[pack_rule_id("rule_high_blocked")]
    assert hb.display_name == "High Blocked Traffic" and hb.summary.last_status == "collection_off"
    assert json.dumps(hb.model_dump(mode="json"))
