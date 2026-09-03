"""One-off probe of the PCE Rule Search API against a real PCE (Phase 3A Task 4).

Run on the test appliance with the service interpreter (credentials come from
the product's own config; nothing is written except the JSON summary):

    sudo -u illumio-ops PYTHONNOUSERSITE=1 venv/bin/python tools/probe_rule_search.py [out.json]

What it settles (the plan refuses to guess these from docs):
  A/B  which of consumers/providers is the SOURCE side of a flow
  C    workload href as actor
  D    the KB doc's providers+destinations spelling
  E    pversion active vs draft
  F    ip_list href as actor (Task 5's fallback depends on it)
  G    a pair with no covering rule — the empty-result shape
  H    kubernetes_workload href as actor, and whether /workloads?managed=true
       returns k8s workloads at all

Findings are printed and dumped to the output file with hostnames/IPs masked.
The recorded responses become tests/fixtures/pce_rule_search/*.json.

RESULTS (LAB-PCE 25.2, 2026-09-03; temp draft ruleset created and deleted):
  * Field names: `consumers` / `providers` only. `sources`, `destinations`
    are rejected with 406 input_validation_error (schema
    sec_policy_rule_search_post) — the KB doc's spelling is wrong for 25.2.
  * `consumers` = the flow's SOURCE side, `providers` = DESTINATION side:
    a rule consumer=L1 provider=L2 matches {consumers:[L1],providers:[L2]}
    (1 hit) and not the swapped body (0 hits).
  * Omitting one side, or `ingress_services`, widens to "any" (still hits);
    a non-matching port yields 0 hits. `rule_types` may be omitted.
  * `pversion` active/draft are independent views (draft-only rule is
    invisible to active).
  * Actor kinds accepted: label, workload, ip_list, kubernetes_workload.
    /workloads?managed=true does NOT return kubernetes workloads.
  * Response: {counts:{sec_rules:{matched,total},...}, sec_rules:[...],
    deny_rules:[...], override_deny_rules:[...], ip_tables_rules:[...]}.
    Each sec_rules item is the full rule (href, enabled, consumers[],
    providers[] with {label:{href,key,value},exclusion}, ingress_services[],
    resolve_labels_as, update_type, ...) plus `rule_set` {href, name,
    enabled, scopes, update_type, ...}. No `provision_state` field — use
    `update_type` (null = provisioned/unchanged in that pversion).
"""
from __future__ import annotations

import json
import re
import sys

sys.path.insert(0, ".")
from src.api_client import ApiClient  # noqa: E402
from src.config import ConfigManager  # noqa: E402

RULE_TYPES = ["sec_rules", "deny_rules", "override_deny_rules"]


def _mask(obj):
    text = json.dumps(obj, ensure_ascii=False, default=str)
    text = re.sub(r"\b(\d{1,3}\.){3}\d{1,3}\b", "10.0.0.1", text)
    text = re.sub(r'"hostname": "[^"]*"', '"hostname": "host.masked"', text)
    text = re.sub(r'"name": "([^"]{0,64})"', lambda m: '"name": "%s"' % m.group(1), text)
    return json.loads(text)


_ACTOR_KINDS = ("label", "label_group", "workload", "ip_list", "virtual_service", "virtual_server", "actors")


def _actor(entry):
    """Reduce a rule actor entry to the one key Rule Search wants."""
    for k in _ACTOR_KINDS:
        if k in entry:
            v = entry[k]
            return {k: ({"href": v["href"]} if isinstance(v, dict) and "href" in v else v)}
    return None


def _first_rule_with_labels(rulesets):
    """First enabled rule with an actor on both sides and a service. Label
    actors are preferred (they make the swap test unambiguous); anything the
    lab has is accepted otherwise — the actor kinds get printed."""
    best = None
    for rs in rulesets:
        if not rs.get("enabled", True):
            continue
        for rule in rs.get("rules", []):
            if not rule.get("enabled", True):
                continue
            cons = [_actor(a) for a in rule.get("consumers", []) if _actor(a)]
            provs = [_actor(a) for a in rule.get("providers", []) if _actor(a)]
            svcs = [s for s in rule.get("ingress_services", []) if "port" in s or "href" in s or "proto" in s]
            if not (cons and provs and svcs):
                continue
            cand = (rs, rule, cons[0], provs[0], svcs[0])
            if "label" in cons[0] and "label" in provs[0]:
                return cand
            best = best or cand
    return best or (None, None, None, None, None)


def _acceptance_mode(api, findings, out_path):
    import sqlite3
    org = api.api_cfg["org_id"]
    st, labels = api._api_get(f"/orgs/{org}/labels?max_results=5")
    labels = labels or []
    l1 = {"label": {"href": labels[0]["href"]}} if labels else None
    l2 = {"label": {"href": labels[1]["href"]}} if len(labels) > 1 else l1
    iplists = api.get_ip_lists(raise_on_error=True)
    ipl = next((x for x in iplists if x.get("ip_ranges")), None)
    k8s_href = None
    try:
        c = sqlite3.connect(api.cm.models.pce_cache.db_path) if hasattr(api, "cm") else None
    except Exception:
        c = None
    try:
        from src.config import ConfigManager
        cm2 = ConfigManager(); cm2.load()
        c = sqlite3.connect(cm2.models.pce_cache.db_path)
        row = c.execute("select raw_json from pce_traffic_flows_raw where raw_json like '%kubernetes_workloads%' limit 1").fetchone()
        if row:
            m = re.search(r'/orgs/\d+/kubernetes_workloads/[0-9a-f-]+', row[0])
            k8s_href = m.group(0) if m else None
    except Exception as exc:
        findings["k8s_lookup_error"] = str(exc)
    svc = [{"port": 22, "proto": 6}]

    def run(tag, body, pversion="active"):
        status, data = api.rule_search(body, pversion=pversion)
        summary = {"status": status}
        if isinstance(data, dict):
            summary["keys"] = sorted(data.keys()); summary["sec_rules_n"] = len(data.get("sec_rules") or [])
            summary["deny_rules_n"] = len(data.get("deny_rules") or [])
        else:
            summary["body"] = data
        print(f"[{tag}] {summary}")
        findings[tag] = {"body": body, "pversion": pversion, "summary": summary, "response": _mask(data)}

    if l1:
        run("A1_consumers_providers_labels", {"consumers": [l1], "providers": [l2], "ingress_services": svc, "rule_types": RULE_TYPES})
        run("D1_providers_destinations_labels", {"providers": [l1], "destinations": [l2], "ingress_services": svc, "rule_types": RULE_TYPES})
        run("D2_sources_destinations_labels", {"sources": [l1], "destinations": [l2], "ingress_services": svc, "rule_types": RULE_TYPES})
        run("E1_draft", {"consumers": [l1], "providers": [l2], "ingress_services": svc, "rule_types": RULE_TYPES}, pversion="draft")
        run("G1_no_service", {"consumers": [l1], "providers": [l2], "rule_types": RULE_TYPES})
        run("R1_rule_types_omitted", {"consumers": [l1], "providers": [l2], "ingress_services": svc})
        run("R2_rule_types_with_ip_tables", {"consumers": [l1], "providers": [l2], "ingress_services": svc, "rule_types": RULE_TYPES + ["ip_tables_rules"]})
    if ipl and l1:
        run("F1_iplist_consumer", {"consumers": [{"ip_list": {"href": ipl["href"]}}], "providers": [l1], "ingress_services": svc, "rule_types": RULE_TYPES})
    if k8s_href and l1:
        run("H1_k8s_consumer", {"consumers": [{"kubernetes_workload": {"href": k8s_href}}], "providers": [l1], "ingress_services": svc, "rule_types": RULE_TYPES})
    else:
        findings["H1_k8s_consumer"] = "skipped: no kubernetes_workloads href found in traffic cache"
    wls = api.fetch_managed_workloads()
    findings["managed_workloads_include_k8s"] = any("kubernetes_workloads" in w.get("href", "") for w in wls)
    if wls and l1:
        run("C1_workload_consumer", {"consumers": [{"workload": {"href": wls[0]["href"]}}], "providers": [l1], "ingress_services": svc, "rule_types": RULE_TYPES})
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(findings, f, ensure_ascii=False, indent=2)
    print("written", out_path)
    return 0


def _temp_rule_mode(api, findings, out_path):
    """Create a throwaway DRAFT ruleset with one asymmetric allow rule
    (consumer label L1 -> provider label L2, 22/TCP), search it both ways to
    settle which field is the flow's source side, record the hit shape, and
    delete the ruleset again. Never provisioned. Requires explicit user consent
    (given 2026-09-03 for LAB-PCE)."""
    import datetime as _dt
    org = api.api_cfg["org_id"]
    st, labels = api._api_get(f"/orgs/{org}/labels?max_results=50")
    labels = [l for l in (labels or []) if l.get("href")]
    if len(labels) < 2:
        print("need two labels"); return 3
    # two labels with different keys make the direction test unambiguous
    l1 = labels[0]
    l2 = next((l for l in labels[1:] if l.get("key") != l1.get("key")), labels[1])
    L1 = {"label": {"href": l1["href"]}}; L2 = {"label": {"href": l2["href"]}}
    name = "illumio-ops-probe-" + _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    body = {
        "name": name, "description": "temporary Rule Search probe; safe to delete", "enabled": True,
        "scopes": [[]],
        "rules": [{
            "enabled": True,
            "consumers": [L1], "providers": [L2],
            "ingress_services": [{"port": 22, "proto": 6}],
            "resolve_labels_as": {"consumers": ["workloads"], "providers": ["workloads"]},
        }],
    }
    st, created = api._api_post(f"/orgs/{org}/sec_policy/draft/rule_sets", body)
    print("create ruleset:", st, (created or {}).get("href") if isinstance(created, dict) else created)
    if st not in (200, 201) or not isinstance(created, dict):
        # _api_post drops the error body; fetch it raw for the record
        url = f"{api.api_cfg['url']}/api/v2/orgs/{org}/sec_policy/draft/rule_sets"
        st2, raw = api._request(url, method="POST", data=body)
        print("create error body:", st2, raw[:400] if isinstance(raw, (bytes, str)) else raw)
        findings["temp_rule_create_error"] = {"status": st2, "body": str(raw)[:400]}
        return 4
    rs_href = created["href"]
    findings["temp_ruleset"] = {"name": name, "href": rs_href, "L1": l1.get("key"), "L2": l2.get("key")}
    try:
        svc = [{"port": 22, "proto": 6}]

        def run(tag, body, pversion="draft"):
            status, data = api.rule_search(body, pversion=pversion)
            summary = {"status": status}
            if isinstance(data, dict):
                summary["sec_rules_n"] = len(data.get("sec_rules") or [])
                summary["deny_rules_n"] = len(data.get("deny_rules") or [])
                summary["counts"] = data.get("counts")
            else:
                summary["body"] = data
            print(f"[{tag}] {summary}")
            findings[tag] = {"body": body, "pversion": pversion, "summary": summary, "response": _mask(data)}

        run("T_A_consumer_L1_provider_L2", {"consumers": [L1], "providers": [L2], "ingress_services": svc, "rule_types": RULE_TYPES})
        run("T_B_swapped", {"consumers": [L2], "providers": [L1], "ingress_services": svc, "rule_types": RULE_TYPES})
        run("T_C_consumer_only", {"consumers": [L1], "ingress_services": svc, "rule_types": RULE_TYPES})
        run("T_D_provider_only", {"providers": [L2], "ingress_services": svc, "rule_types": RULE_TYPES})
        run("T_E_wrong_port", {"consumers": [L1], "providers": [L2], "ingress_services": [{"port": 65000, "proto": 6}], "rule_types": RULE_TYPES})
        run("T_F_no_service", {"consumers": [L1], "providers": [L2], "rule_types": RULE_TYPES})
        run("T_G_active_sees_nothing", {"consumers": [L1], "providers": [L2], "ingress_services": svc, "rule_types": RULE_TYPES}, pversion="active")
    finally:
        url = f"{api.api_cfg['url']}/api/v2{rs_href}"
        st_del, _ = api._request(url, method="DELETE")
        print("delete ruleset:", st_del)
        findings["temp_ruleset_deleted_status"] = st_del
        st_chk, after = api._api_get(rs_href)
        print("ruleset after delete: status", st_chk)
        findings["temp_ruleset_after_delete_status"] = st_chk
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(findings, f, ensure_ascii=False, indent=2)
    print("written", out_path)
    return 0


def main(out_path: str = "tmp/rule_search_probe.json") -> int:
    cm = ConfigManager(); cm.load()
    findings = {}
    with ApiClient(cm) as api:
        if not hasattr(api, "rule_search"):
            # Appliance may run a build that predates ApiClient.rule_search; the
            # probe must not depend on deploying first.
            import orjson

            def _rule_search(body, *, pversion="active", timeout=30):
                org = api.api_cfg["org_id"]
                url = f"{api.api_cfg['url']}/api/v2/orgs/{org}/sec_policy/{pversion}/rule_search"
                status, raw = api._request(url, method="POST", data=body, timeout=timeout)
                try:
                    return status, orjson.loads(raw) if raw else None
                except Exception:
                    return status, raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            api.rule_search = _rule_search
        rulesets = api.get_active_rulesets(raise_on_error=True)
        rs, rule, c_actor, p_actor, svc = _first_rule_with_labels(rulesets)
        ref_pversion = "active"
        if rule is None:
            # Lab PCEs often keep everything in draft (2026-09-03: active had one
            # empty ruleset). Fall back to draft for the reference rule and run
            # the probes against draft; E then compares active for the same body.
            rulesets = api.get_all_rulesets(force_refresh=True, raise_on_error=True)
            rs, rule, c_actor, p_actor, svc = _first_rule_with_labels(rulesets)
            ref_pversion = "draft"
        if rule is None:
            print("no enabled allow rule in active or draft — running ACCEPTANCE mode "
                  "(field names / empty shape / actor kinds only; source-side semantics need a rule)")
            rc = _acceptance_mode(api, findings, out_path)
            if "--with-temp-rule" in sys.argv:
                rc = _temp_rule_mode(api, findings, out_path)
            return rc
        findings["reference_pversion"] = ref_pversion
        findings["active_ruleset_count"] = len(api.get_active_rulesets(raise_on_error=True))
        service = ({"href": svc["href"]} if "href" in svc
                   else {"port": svc["port"], "proto": svc.get("proto", 6),
                         **({"to_port": svc["to_port"]} if "to_port" in svc else {})})
        print("reference rule:", rs.get("name"), rule.get("href"), "consumer", c_actor, "provider", p_actor, "svc", service)
        wls = api.fetch_managed_workloads()
        wl = next((w for w in wls if w.get("href", "").startswith("/orgs/")), None)
        k8s = [w for w in wls if "kubernetes_workloads" in w.get("href", "")]
        findings["H_managed_workloads_include_k8s"] = bool(k8s)
        iplists = api.get_ip_lists(raise_on_error=True)
        ipl = next((x for x in iplists if any("ip_ranges" in x and r.get("from_ip") for r in x.get("ip_ranges", []))), None)

        def run(tag, body, pversion=None):
            pversion = pversion or ref_pversion
            status, data = api.rule_search(body, pversion=pversion)
            summary = {"status": status}
            if isinstance(data, dict):
                summary["keys"] = sorted(data.keys())
                summary["sec_rules_n"] = len(data.get("sec_rules", []) or [])
                summary["deny_rules_n"] = len(data.get("deny_rules", []) or [])
            else:
                summary["body"] = data
            print(f"[{tag}] {summary}")
            findings[tag] = {"body": body, "pversion": pversion, "summary": summary, "response": _mask(data)}
            return status, data

        base = {"ingress_services": [service], "rule_types": RULE_TYPES}
        run("A_consumers_src_providers_dst",
            {**base, "consumers": [c_actor], "providers": [p_actor]})
        run("B_swapped",
            {**base, "consumers": [p_actor], "providers": [c_actor]})
        if wl:
            run("C_workload_href_as_consumer",
                {**base, "consumers": [{"workload": {"href": wl["href"]}}], "providers": [p_actor]})
        run("D_doc_spelling_providers_destinations",
            {**base, "providers": [c_actor], "destinations": [p_actor]})
        run("E_other_pversion",
            {**base, "consumers": [c_actor], "providers": [p_actor]},
            pversion="active" if ref_pversion == "draft" else "draft")
        if ipl:
            run("F_iplist_actor",
                {**base, "consumers": [{"ip_list": {"href": ipl["href"]}}], "providers": [p_actor]})
        run("G_no_match_port",
            {"ingress_services": [{"port": 65000, "proto": 6}], "rule_types": RULE_TYPES,
             "consumers": [c_actor], "providers": [p_actor]})
        if k8s:
            run("H_k8s_actor",
                {**base, "consumers": [{"kubernetes_workload": {"href": k8s[0]["href"]}}],
                 "providers": [p_actor]})
        else:
            # try any k8s workload href from the traffic cache snapshot naming
            findings["H_k8s_actor"] = "skipped: no kubernetes_workload href available via managed workloads"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(findings, f, ensure_ascii=False, indent=2)
    print("written", out_path)
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(main(*args))
