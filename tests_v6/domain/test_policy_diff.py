"""Policy diff engine (P5c-3): Draft against active, ported from 5.x policy_diff (diff_engine, object_diff, risk)."""
from illumio_ops.domain.policy_diff import (
    diff_objects,
    diff_rule_sets,
    grade,
    object_refs,
)

D = "/orgs/1/sec_policy/draft"
A = "/orgs/1/sec_policy/active"
LBL = {"label": {"href": "/orgs/1/labels/1"}}
LBL2 = {"label": {"href": "/orgs/1/labels/2"}}
NAMES = {"/orgs/1/labels/1": "app:Web", "/orgs/1/labels/2": "app:DB"}


def rule(v, n, *, coll="sec_rules", enabled=True, providers=(LBL,), consumers=(LBL2,), services=(), **kw):
    return {"href": f"{v}/rule_sets/1/{coll}/{n}", "enabled": enabled, "providers": list(providers),
            "consumers": list(consumers), "ingress_services": list(services), **kw}


def rs(v, n=1, *, name="Web", enabled=True, rules=(), deny=(), **kw):
    return {"href": f"{v}/rule_sets/{n}", "name": name, "enabled": enabled, "description": "", "rules": list(rules),
            "deny_rules": list(deny), **kw}


def _rows(changes, kind=None):
    return [(c.kind, c.change, c.ref, c.field) for c in changes if kind is None or c.kind == kind]


# ── rule sets and rules ──────────────────────────────────────────────────────

def test_added_and_removed_rulesets():
    ch = diff_rule_sets([rs(D, 1), rs(D, 2, name="New")], [rs(A, 1), rs(A, 3, name="Old")], NAMES)
    assert ("rule_set", "added", "2", "*") in _rows(ch) and ("rule_set", "removed", "3", "*") in _rows(ch)


def test_added_ruleset_rule_count():
    """Review Focus 5: the rules a new ruleset brings are counted, though not listed one by one."""
    [c] = diff_rule_sets([rs(D, 2, rules=[rule(D, 1), rule(D, 2)], deny=[rule(D, 3, coll="deny_rules")])], [], NAMES)
    assert c.change == "added" and c.rule_count == 3


def test_modified_ruleset_field_level():
    ch = diff_rule_sets([rs(D, name="Web2", description="x")], [rs(A)], NAMES)
    assert {c.field for c in ch if c.kind == "rule_set"} == {"name", "description"}


def test_modified_rule_provider_change():
    ch = diff_rule_sets([rs(D, rules=[rule(D, 1, providers=(LBL2,))])], [rs(A, rules=[rule(A, 1)])], NAMES)
    [c] = [c for c in ch if c.kind == "rule"]
    assert (c.change, c.field, c.draft, c.active) == ("modified", "providers", "label:app:DB", "label:app:Web")


def test_provider_order_is_not_a_false_diff():
    ch = diff_rule_sets([rs(D, rules=[rule(D, 1, providers=(LBL, LBL2))])],
                        [rs(A, rules=[rule(A, 1, providers=(LBL2, LBL))])], NAMES)
    assert ch == []


def test_empty_inputs():
    assert diff_rule_sets([], [], {}) == []


def test_names_fall_back_to_href():
    ch = diff_rule_sets([rs(D, rules=[rule(D, 1, providers=({"label": {"href": "/orgs/1/labels/9"}},))])],
                        [rs(A, rules=[rule(A, 1)])], {})
    assert "/orgs/1/labels/9" in next(c for c in ch if c.kind == "rule").draft


def test_deny_rules_diffed():
    """Review Focus 2: Deny Rules and Override Deny are diffed, not only allow rules."""
    added = diff_rule_sets([rs(D, deny=[rule(D, 5, coll="deny_rules", override=True)])], [rs(A)], NAMES)
    assert [(c.change, c.rule_type) for c in added if c.kind == "rule"] == [("added", "override_deny")]
    removed = diff_rule_sets([rs(D)], [rs(A, deny=[rule(A, 5, coll="deny_rules")])], NAMES)
    assert [(c.change, c.rule_type) for c in removed if c.kind == "rule"] == [("removed", "deny")]
    promoted = diff_rule_sets([rs(D, deny=[rule(D, 5, coll="deny_rules", override=True)])],
                              [rs(A, deny=[rule(A, 5, coll="deny_rules", override=False)])], NAMES)
    assert ("rule", "modified", "deny_rules/5", "rule_type") in _rows(promoted)


def test_rule_keys_namespaced():
    """sec_rules/3 and deny_rules/3 are different rules."""
    ch = diff_rule_sets([rs(D, rules=[rule(D, 3)])], [rs(A, deny=[rule(A, 3, coll="deny_rules")])], NAMES)
    assert {(c.change, c.ref) for c in ch if c.kind == "rule"} == {("added", "sec_rules/3"),
                                                                     ("removed", "deny_rules/3")}


def test_rule_count_includes_deny_rules():
    ch = diff_rule_sets([rs(D, rules=[rule(D, 1)], deny=[rule(D, 2, coll="deny_rules")])],
                        [rs(A, rules=[rule(A, 1)])], NAMES)
    assert ("rule_set", "modified", "1", "rule_count") in _rows(ch)


def test_sec_rules_and_rules_keys_deduped():
    r = rule(D, 1)
    ch = diff_rule_sets([rs(D, rules=[r], sec_rules=[r])], [rs(A, rules=[rule(A, 1)])], NAMES)
    assert ch == []


# ── policy objects ───────────────────────────────────────────────────────────

IPL = ["ip_ranges", "fqdns", "description"]


def ipl(v, n=1, ranges=("10.0.0.0/24",), **kw):
    return {"href": f"{v}/ip_lists/{n}", "name": f"L{n}", "ip_ranges": [{"from_ip": r} for r in ranges], **kw}


def test_object_added_removed():
    ch = diff_objects([ipl(D, 2)], [ipl(A, 3)], kind="ip_list", fields=IPL, names={})
    assert {(c.change, c.ref) for c in ch} == {("added", "2"), ("removed", "3")}


def test_expansion_flagged_shrink_not():
    grow = diff_objects([ipl(D, ranges=("10.0.0.0/24", "10.9.0.0/16"))], [ipl(A)], kind="ip_list", fields=IPL, names={})
    shrink = diff_objects([ipl(D, ranges=())], [ipl(A)], kind="ip_list", fields=IPL, names={})
    assert grow[0].scope_expanded and not shrink[0].scope_expanded


def test_member_order_ignored():
    ch = diff_objects([ipl(D, ranges=("b", "a"))], [ipl(A, ranges=("a", "b"))], kind="ip_list", fields=IPL, names={})
    assert ch == []


def test_description_change_not_expansion():
    ch = diff_objects([ipl(D, description="x")], [ipl(A)], kind="ip_list", fields=IPL, names={})
    assert [(c.field, c.scope_expanded) for c in ch] == [("description", False)]


def test_service_ports_summary():
    svc = ["service_ports", "windows_services", "description"]
    ch = diff_objects([{"href": f"{D}/services/1", "name": "S", "service_ports": [{"proto": 6, "port": 80, "to_port": 90}]}],
                      [{"href": f"{A}/services/1", "name": "S", "service_ports": [{"proto": 6, "port": 80}]}],
                      kind="service", fields=svc, names={})
    assert ch[0].draft == "6/80-90" and ch[0].scope_expanded


def test_label_group_members_named():
    lg = ["labels", "sub_groups", "description"]
    ch = diff_objects([{"href": f"{D}/label_groups/1", "name": "G", "labels": [{"href": "/orgs/1/labels/1"}]}],
                      [{"href": f"{A}/label_groups/1", "name": "G", "labels": []}], kind="label_group", fields=lg,
                      names=NAMES)
    assert ch[0].draft == "app:Web"


def test_object_refs_counts_enabled_allow_rules():
    sets = [rs(A, rules=[rule(A, 1, consumers=({"ip_list": {"href": f"{A}/ip_lists/1"}},),
                              services=({"href": f"{A}/services/7"},)),
                         rule(A, 2, enabled=False, consumers=({"ip_list": {"href": f"{A}/ip_lists/2"}},))]),
            rs(A, 2, enabled=False, rules=[rule(A, 3, consumers=({"ip_list": {"href": f"{A}/ip_lists/3"}},))])]
    assert object_refs(sets) == {"ip_list:1": 1, "service:7": 1}


# ── risk ─────────────────────────────────────────────────────────────────────

def test_disabling_is_high_risk():
    """Review Focus 3: e.g. disabling a Quarantine ruleset removes containment once provisioned."""
    ch = grade(diff_rule_sets([rs(D, enabled=False)], [rs(A)], NAMES), {})
    assert [c.risk for c in ch] == ["high"]


def test_reenabling_and_removed_are_medium():
    on = grade(diff_rule_sets([rs(D, rules=[rule(D, 1)])], [rs(A, rules=[rule(A, 1, enabled=False)])], NAMES), {})
    gone = grade(diff_rule_sets([rs(D)], [rs(A, rules=[rule(A, 1)])], NAMES), {})
    assert [c.risk for c in on if c.kind == "rule"] == ["medium"] and [c.risk for c in gone if c.kind == "rule"] == ["medium"]


def test_plain_modification_no_risk():
    ch = grade(diff_rule_sets([rs(D, description="x")], [rs(A)], NAMES), {})
    assert [c.risk for c in ch] == [""]


def test_expanded_referenced_object_high():
    grow = diff_objects([ipl(D, ranges=("a", "b"))], [ipl(A, ranges=("a",))], kind="ip_list", fields=IPL, names={})
    assert grade(grow, {"ip_list:1": 2})[0].risk == "high"
    assert grade(grow, {})[0].risk == ""
    shrink = diff_objects([ipl(D, ranges=())], [ipl(A)], kind="ip_list", fields=IPL, names={})
    assert grade(shrink, {"ip_list:1": 2})[0].risk == ""


def test_removed_object_medium_added_blank():
    ch = grade(diff_objects([ipl(D, 2)], [ipl(A, 3)], kind="ip_list", fields=IPL, names={}), {})
    assert {(c.change, c.risk) for c in ch} == {("added", ""), ("removed", "medium")}
