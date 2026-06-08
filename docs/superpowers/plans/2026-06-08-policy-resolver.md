# Policy Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve abstract label-based ACTIVE policy into a flat list of concrete `src_ip / dst_ip / port / protocol` firewall entries (one resolved list per ruleset), exportable as JSON + CSV, runnable via CLI `report` and wired into the scheduler like security_risk / network_inventory (commit ff93df9).

**Architecture:** A PURE resolution core (`src/report/analysis/policy_resolver.py::resolve_ruleset`) consumes pre-built lookups (label→IPs, ip_list→CIDRs, label_group→labels, workload→IPs) and emits flat rows — zero I/O, fully unit-testable with synthetic dicts. An I/O facade (`src/report/policy_resolver_report.py`) fetches active rulesets + workloads + ip_lists + label_groups, builds the lookups in a single O(N) pass, calls the core, and hands `module_results` to a JSON+CSV exporter. CLI + scheduler wiring mirrors the existing traffic-profile reports.

**Tech Stack:** Python 3.10+, pytest, click (CLI), pandas (CSV via existing CsvExporter), stdlib json, JSON i18n (EN + ZH_TW).

**Spec:** `docs/superpowers/specs/2026-06-08-policy-resolver-design.md`

**Deliberate refinements to the spec (disclosed):**
1. `get_ip_lists()` / `get_label_groups()` fetch the **draft** policy (matching existing `labels.py:208-209` cache population, where object definitions are stable), while rulesets are fetched **active** per the locked decision. Justification: object *definitions* (CIDRs, group members) live identically in draft; active vs draft only matters for the *ruleset graph*, which we take active.
2. Port ranges (`to_port`) are NOT exploded into one row per port; a single row carries `port` (from) + `port_to` (to). Prevents row explosion. (YAGNI for per-port expansion.)
3. `actors:"ams"` (All Managed) and empty actors resolve to a single `"ANY"` sentinel IP with `kind="any"` rather than the full estate, avoiding a cartesian blow-up.
4. Named services (`{"href": ...}`) are resolved via an injected `service_to_ports` lookup; the facade builds it from a new `get_services()` only if the existing client lacks one (Task 1 covers it conditionally).

---

### Task 1: Add `get_ip_lists` / `get_label_groups` / `get_services` to ApiClient

**Files:**
- Modify: `src/api_client.py` (near `get_active_rulesets`, ~748)
- Test: `tests/test_policy_resolver_api.py`

> Rationale: The repo only populates href→name caches from `/sec_policy/draft/ip_lists` and `/label_groups` (see `src/api/labels.py:208-236`); it does NOT expose `ip_ranges` or group members. We add three thin GET wrappers that mirror `get_active_rulesets`' shape.

- [ ] **Step 1: Write the failing test**

Create `tests/test_policy_resolver_api.py`:

```python
"""Tests for the policy-resolver API fetch wrappers (mocked _api_get)."""
from __future__ import annotations

from unittest.mock import MagicMock

from src.api_client import ApiClient


def _client():
    c = ApiClient.__new__(ApiClient)          # bypass __init__/network
    c.api_cfg = {"org_id": "1"}
    return c


def test_get_ip_lists_returns_definitions():
    c = _client()
    payload = [{"href": "/orgs/1/sec_policy/draft/ip_lists/5", "name": "DC-Nets",
                "ip_ranges": [{"from_ip": "10.0.0.0", "to_ip": "10.0.255.255"}]}]
    c._api_get = MagicMock(return_value=(200, payload))
    out = c.get_ip_lists()
    assert out == payload
    c._api_get.assert_called_once_with(
        "/orgs/1/sec_policy/draft/ip_lists?max_results=10000")


def test_get_label_groups_returns_members():
    c = _client()
    payload = [{"href": "/orgs/1/sec_policy/draft/label_groups/9", "name": "Prod-Apps",
                "labels": [{"href": "/orgs/1/labels/3"}], "sub_groups": []}]
    c._api_get = MagicMock(return_value=(200, payload))
    out = c.get_label_groups()
    assert out == payload
    c._api_get.assert_called_once_with(
        "/orgs/1/sec_policy/draft/label_groups?max_results=10000")


def test_get_services_returns_definitions():
    c = _client()
    payload = [{"href": "/orgs/1/sec_policy/draft/services/2", "name": "HTTPS",
                "service_ports": [{"port": 443, "proto": 6}]}]
    c._api_get = MagicMock(return_value=(200, payload))
    out = c.get_services()
    assert out == payload


def test_get_ip_lists_empty_on_error():
    c = _client()
    c._api_get = MagicMock(return_value=(403, None))
    assert c.get_ip_lists() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_resolver_api.py -v`
Expected: FAIL with `AttributeError: 'ApiClient' object has no attribute 'get_ip_lists'`.

- [ ] **Step 3: Add the three wrappers**

In `src/api_client.py`, immediately AFTER `get_active_rulesets` (ends ~757), insert:

```python
    def get_ip_lists(self) -> list[dict[str, Any]]:
        """Get all IP Lists with their ip_ranges/fqdns (draft definitions)."""
        org = self.api_cfg['org_id']
        status, data = self._api_get(
            f"/orgs/{org}/sec_policy/draft/ip_lists?max_results=10000"
        )
        if status == 200 and data:
            return data
        logger.warning(f"get_ip_lists: status={status}, returned empty list")
        return []

    def get_label_groups(self) -> list[dict[str, Any]]:
        """Get all Label Groups with their member labels + sub_groups (draft)."""
        org = self.api_cfg['org_id']
        status, data = self._api_get(
            f"/orgs/{org}/sec_policy/draft/label_groups?max_results=10000"
        )
        if status == 200 and data:
            return data
        logger.warning(f"get_label_groups: status={status}, returned empty list")
        return []

    def get_services(self) -> list[dict[str, Any]]:
        """Get all Service definitions with their service_ports (draft)."""
        org = self.api_cfg['org_id']
        status, data = self._api_get(
            f"/orgs/{org}/sec_policy/draft/services?max_results=10000"
        )
        if status == 200 and data:
            return data
        logger.warning(f"get_services: status={status}, returned empty list")
        return []
```

(`logger` and `Any` are already imported in `api_client.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_resolver_api.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/api_client.py tests/test_policy_resolver_api.py
git commit -m "feat(api): add get_ip_lists/get_label_groups/get_services fetch wrappers"
```

---

### Task 2: Pure resolution core — `resolve_ruleset`

**Files:**
- Create: `src/report/analysis/policy_resolver.py`
- Test: `tests/test_policy_resolver_core.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_policy_resolver_core.py`:

```python
"""Tests for the PURE policy resolution core (synthetic lookups, zero I/O)."""
from __future__ import annotations

from src.report.analysis.policy_resolver import resolve_ruleset


# Shared synthetic lookups -------------------------------------------------
LABEL_TO_IPS = {
    "/labels/web": ["10.0.1.5", "10.0.1.6"],
    "/labels/db": ["10.0.2.7"],
}
IPLIST_TO_CIDRS = {"/ip_lists/dc": ["10.9.0.0/16"]}
LABELGROUP_TO_LABELS = {"/lg/apps": ["/labels/web", "/labels/db"]}
WORKLOAD_TO_IPS = {"/wl/jump": ["172.16.0.10"]}


def _lookups():
    return dict(
        label_to_ips=LABEL_TO_IPS,
        iplist_to_cidrs=IPLIST_TO_CIDRS,
        label_group_to_labels=LABELGROUP_TO_LABELS,
        workload_to_ips=WORKLOAD_TO_IPS,
    )


def _ruleset(rules, name="App-Tier", scopes=None):
    return {"name": name, "scopes": scopes or [], "rules": rules}


def test_label_to_label_cartesian_with_port():
    rs = _ruleset([{
        "href": "/sec_rules/1",
        "consumers": [{"label": {"href": "/labels/web"}}],
        "providers": [{"label": {"href": "/labels/db"}}],
        "ingress_services": [{"port": 443, "proto": 6}],
    }])
    rows = resolve_ruleset(rs, **_lookups())
    pairs = {(r["src_ip"], r["dst_ip"], r["port"], r["protocol"]) for r in rows}
    assert pairs == {
        ("10.0.1.5", "10.0.2.7", 443, "TCP"),
        ("10.0.1.6", "10.0.2.7", 443, "TCP"),
    }
    assert all(r["ruleset_name"] == "App-Tier" for r in rows)
    assert all(r["src_kind"] == "label" and r["dst_kind"] == "label" for r in rows)


def test_udp_proto_17():
    rs = _ruleset([{
        "href": "/sec_rules/2",
        "consumers": [{"workload": {"href": "/wl/jump"}}],
        "providers": [{"label": {"href": "/labels/db"}}],
        "ingress_services": [{"port": 53, "proto": 17}],
    }])
    rows = resolve_ruleset(rs, **_lookups())
    assert rows[0]["protocol"] == "UDP"
    assert rows[0]["src_ip"] == "172.16.0.10"
    assert rows[0]["src_kind"] == "workload"


def test_label_group_expands_recursively():
    rs = _ruleset([{
        "href": "/sec_rules/3",
        "consumers": [{"ip_list": {"href": "/ip_lists/dc"}}],
        "providers": [{"label_group": {"href": "/lg/apps"}}],
        "ingress_services": [{"port": 22, "proto": 6}],
    }])
    rows = resolve_ruleset(rs, **_lookups())
    dsts = {r["dst_ip"] for r in rows}
    assert dsts == {"10.0.1.5", "10.0.1.6", "10.0.2.7"}
    assert all(r["src_ip"] == "10.9.0.0/16" for r in rows)
    assert all(r["src_kind"] == "ip_list" and r["dst_kind"] == "label_group" for r in rows)


def test_ip_address_literal_and_ams_sentinel():
    rs = _ruleset([{
        "href": "/sec_rules/4",
        "consumers": [{"actors": "ams"}],
        "providers": [{"ip_address": {"value": "8.8.8.8"}}],
        "ingress_services": [{"port": 443, "proto": 6}],
    }])
    rows = resolve_ruleset(rs, **_lookups())
    assert rows[0]["src_ip"] == "ANY"
    assert rows[0]["src_kind"] == "any"
    assert rows[0]["dst_ip"] == "8.8.8.8"


def test_port_range_kept_as_from_to():
    rs = _ruleset([{
        "href": "/sec_rules/5",
        "consumers": [{"workload": {"href": "/wl/jump"}}],
        "providers": [{"label": {"href": "/labels/db"}}],
        "ingress_services": [{"port": 8000, "to_port": 8100, "proto": 6}],
    }])
    rows = resolve_ruleset(rs, **_lookups())
    assert rows[0]["port"] == 8000
    assert rows[0]["port_to"] == 8100


def test_named_service_via_lookup():
    rs = _ruleset([{
        "href": "/sec_rules/6",
        "consumers": [{"workload": {"href": "/wl/jump"}}],
        "providers": [{"label": {"href": "/labels/db"}}],
        "ingress_services": [{"href": "/services/https"}],
    }])
    rows = resolve_ruleset(
        rs, **_lookups(),
        service_to_ports={"/services/https": [{"port": 443, "proto": 6}]},
    )
    assert rows[0]["port"] == 443
    assert rows[0]["service_name"] == "/services/https"


def test_missing_label_yields_no_rows_no_error():
    rs = _ruleset([{
        "href": "/sec_rules/7",
        "consumers": [{"label": {"href": "/labels/UNKNOWN"}}],
        "providers": [{"label": {"href": "/labels/db"}}],
        "ingress_services": [{"port": 443, "proto": 6}],
    }])
    rows = resolve_ruleset(rs, **_lookups())
    assert rows == []


def test_dedup_identical_rows():
    rs = _ruleset([{
        "href": "/sec_rules/8",
        "consumers": [{"label": {"href": "/labels/db"}},
                      {"label": {"href": "/labels/db"}}],
        "providers": [{"label": {"href": "/labels/db"}}],
        "ingress_services": [{"port": 443, "proto": 6}],
    }])
    rows = resolve_ruleset(rs, **_lookups())
    assert len(rows) == 1


def test_scope_narrows_providers():
    # provider label /labels/web; scope restricts to /labels/db only → no rows.
    rs = _ruleset(
        [{
            "href": "/sec_rules/9",
            "consumers": [{"workload": {"href": "/wl/jump"}}],
            "providers": [{"label": {"href": "/labels/web"}}],
            "ingress_services": [{"port": 443, "proto": 6}],
        }],
        scopes=[[{"label": {"href": "/labels/db"}}]],
    )
    rows = resolve_ruleset(rs, **_lookups())
    assert rows == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_resolver_core.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.report.analysis.policy_resolver'`.

- [ ] **Step 3: Write the implementation**

Create `src/report/analysis/policy_resolver.py`:

```python
"""PURE policy resolution core.

Expands one Illumio ACTIVE ruleset into flat src_ip/dst_ip/port/protocol rows
ready for third-party firewall implementation. Zero I/O: it consumes
pre-built lookups (label→IPs, ip_list→CIDRs, label_group→member labels,
workload→IPs, optional service→ports) and returns a list of dict rows.

Resolution per rule:
  consumers → src IP set, providers → dst IP set (scope-narrowed), and
  ingress_services → (port, protocol) set; the cartesian product of those,
  deduplicated, becomes the rows.
"""
from __future__ import annotations

from typing import Any

_ANY = "ANY"


def _proto_name(proto: Any) -> str:
    return "UDP" if proto == 17 else "TCP"


def _actor_ips(
    actor: dict,
    *,
    label_to_ips: dict[str, list[str]],
    iplist_to_cidrs: dict[str, list[str]],
    label_group_to_labels: dict[str, list[str]],
    workload_to_ips: dict[str, list[str]],
) -> tuple[list[str], str]:
    """Return (ip_values, kind) for one actor; unknown refs → ([], kind)."""
    if actor.get("actors") == "ams":
        return [_ANY], "any"
    if "label" in actor:
        href = actor["label"].get("href", "")
        return list(label_to_ips.get(href, [])), "label"
    if "label_group" in actor:
        href = actor["label_group"].get("href", "")
        ips: list[str] = []
        for lh in label_group_to_labels.get(href, []):
            ips.extend(label_to_ips.get(lh, []))
        return ips, "label_group"
    if "ip_list" in actor:
        href = actor["ip_list"].get("href", "")
        return list(iplist_to_cidrs.get(href, [])), "ip_list"
    if "workload" in actor:
        href = actor["workload"].get("href", "")
        return list(workload_to_ips.get(href, [])), "workload"
    if "ip_address" in actor:
        val = actor["ip_address"].get("value")
        return ([val], "ip_address") if val else ([], "ip_address")
    return [], "unknown"


def _scope_label_hrefs(scopes: list) -> set[str]:
    """Flatten a ruleset's scopes into the set of label hrefs they require."""
    hrefs: set[str] = set()
    for scope in scopes or []:
        for entry in scope or []:
            if "label" in entry:
                hrefs.add(entry["label"].get("href", ""))
    return hrefs


def _side_ips(
    actors: list[dict],
    lookups: dict[str, Any],
    *,
    scope_hrefs: set[str] | None = None,
) -> tuple[list[str], str]:
    """Resolve a consumer/provider actor list to (deduped IPs, kind).

    When scope_hrefs is given (providers side), an actor is only included if
    it is a label/label_group whose label href intersects the scope, an
    explicit IP source (ip_list/workload/ip_address), or ANY.
    """
    out: list[str] = []
    kind = "any"
    seen: set[str] = set()
    for actor in actors or []:
        if scope_hrefs:
            lbl = actor.get("label", {}).get("href") if "label" in actor else None
            if lbl is not None and lbl not in scope_hrefs:
                continue
        ips, k = _actor_ips(actor, **lookups)
        kind = k
        for ip in ips:
            if ip not in seen:
                seen.add(ip)
                out.append(ip)
    if not out:
        return [_ANY], "any"
    return out, kind


def _services(rule: dict, service_to_ports: dict[str, list[dict]]) -> list[dict]:
    """Resolve ingress_services to a list of {port, port_to?, protocol, name}."""
    out: list[dict] = []
    svcs = rule.get("ingress_services") or []
    if not svcs:
        out.append({"port": _ANY, "protocol": _ANY, "name": ""})
        return out
    for s in svcs:
        if "port" in s:
            entry = {"port": s["port"], "protocol": _proto_name(s.get("proto")),
                     "name": ""}
            if s.get("to_port"):
                entry["port_to"] = s["to_port"]
            out.append(entry)
        elif "href" in s:
            href = s["href"]
            ports = service_to_ports.get(href, [])
            if not ports:
                out.append({"port": _ANY, "protocol": _ANY, "name": href})
            for p in ports:
                entry = {"port": p.get("port", _ANY),
                         "protocol": _proto_name(p.get("proto")), "name": href}
                if p.get("to_port"):
                    entry["port_to"] = p["to_port"]
                out.append(entry)
    return out


def resolve_ruleset(
    ruleset: dict,
    *,
    label_to_ips: dict[str, list[str]],
    iplist_to_cidrs: dict[str, list[str]],
    label_group_to_labels: dict[str, list[str]],
    workload_to_ips: dict[str, list[str]],
    service_to_ports: dict[str, list[dict]] | None = None,
) -> list[dict]:
    """Expand a single ruleset's rules into flat src/dst/port/proto rows."""
    lookups = dict(
        label_to_ips=label_to_ips,
        iplist_to_cidrs=iplist_to_cidrs,
        label_group_to_labels=label_group_to_labels,
        workload_to_ips=workload_to_ips,
    )
    service_to_ports = service_to_ports or {}
    rs_name = ruleset.get("name", "")
    scope_hrefs = _scope_label_hrefs(ruleset.get("scopes") or [])

    rows: list[dict] = []
    seen: set[tuple] = set()
    for rule in ruleset.get("rules") or []:
        rule_href = rule.get("href", "")
        srcs, src_kind = _side_ips(rule.get("consumers") or [], lookups)
        dsts, dst_kind = _side_ips(rule.get("providers") or [], lookups,
                                   scope_hrefs=scope_hrefs or None)
        # If a side resolved to ANY only because every concrete actor was
        # scoped out / unknown, and there WERE concrete actors, drop the rule.
        if scope_hrefs and dsts == [_ANY] and (rule.get("providers")):
            if any("label" in a or "label_group" in a for a in rule["providers"]):
                continue
        for svc in _services(rule, service_to_ports):
            for s_ip in srcs:
                for d_ip in dsts:
                    key = (rule_href, s_ip, d_ip, svc["port"],
                           svc.get("port_to"), svc["protocol"])
                    if key in seen:
                        continue
                    seen.add(key)
                    row = {
                        "ruleset_name": rs_name,
                        "rule_href": rule_href,
                        "src_ip": s_ip,
                        "dst_ip": d_ip,
                        "port": svc["port"],
                        "protocol": svc["protocol"],
                        "src_kind": src_kind,
                        "dst_kind": dst_kind,
                        "service_name": svc["name"],
                    }
                    if "port_to" in svc:
                        row["port_to"] = svc["port_to"]
                    rows.append(row)
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_resolver_core.py -v`
Expected: PASS (9 tests).

> If `test_scope_narrows_providers` fails, re-check: the provider `/labels/web` is not in `scope_hrefs={/labels/db}`, so `_side_ips` skips it → returns `([_ANY], "any")`; the guard then drops the rule because it had a concrete label provider. Confirm the guard branch matches.

- [ ] **Step 5: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/report/analysis/policy_resolver.py tests/test_policy_resolver_core.py
git commit -m "feat(report): add pure policy resolution core (ruleset → flat IP rows)"
```

---

### Task 3: Lookup builders + report facade

**Files:**
- Create: `src/report/policy_resolver_report.py`
- Test: `tests/test_policy_resolver_facade.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_policy_resolver_facade.py`:

```python
"""Tests for the policy-resolver facade: lookup builders + run()."""
from __future__ import annotations

from unittest.mock import MagicMock

from src.report.policy_resolver_report import (
    build_workload_to_ips,
    build_label_to_ips,
    build_iplist_to_cidrs,
    build_label_group_to_labels,
    build_service_to_ports,
    PolicyResolverReport,
)


def test_build_workload_to_ips_skips_missing_address():
    wls = [{"href": "/wl/1", "interfaces": [
        {"address": "10.0.0.1"}, {"name": "eth1"}, {"address": "10.0.0.2"}]}]
    assert build_workload_to_ips(wls) == {"/wl/1": ["10.0.0.1", "10.0.0.2"]}


def test_build_label_to_ips_single_pass_groups_by_label():
    wls = [
        {"href": "/wl/1", "interfaces": [{"address": "10.0.0.1"}],
         "labels": [{"href": "/labels/web"}, {"href": "/labels/prod"}]},
        {"href": "/wl/2", "interfaces": [{"address": "10.0.0.2"}],
         "labels": [{"href": "/labels/web"}]},
    ]
    out = build_label_to_ips(wls)
    assert set(out["/labels/web"]) == {"10.0.0.1", "10.0.0.2"}
    assert out["/labels/prod"] == ["10.0.0.1"]


def test_build_iplist_to_cidrs_ranges_and_fqdn():
    ipls = [{"href": "/ip_lists/5",
             "ip_ranges": [{"from_ip": "10.0.0.0", "to_ip": "10.0.255.255"},
                           {"from_ip": "192.168.1.1"}],
             "fqdns": [{"fqdn": "db.corp.local"}]}]
    out = build_iplist_to_cidrs(ipls)
    assert out["/ip_lists/5"] == ["10.0.0.0-10.0.255.255", "192.168.1.1",
                                  "db.corp.local"]


def test_build_label_group_to_labels_recursive():
    groups = [
        {"href": "/lg/outer", "labels": [{"href": "/labels/a"}],
         "sub_groups": [{"href": "/lg/inner"}]},
        {"href": "/lg/inner", "labels": [{"href": "/labels/b"}], "sub_groups": []},
    ]
    out = build_label_group_to_labels(groups)
    assert set(out["/lg/outer"]) == {"/labels/a", "/labels/b"}
    assert out["/lg/inner"] == ["/labels/b"]


def test_build_service_to_ports():
    svcs = [{"href": "/services/2", "service_ports": [{"port": 443, "proto": 6}]}]
    assert build_service_to_ports(svcs) == {"/services/2": [{"port": 443, "proto": 6}]}


def test_run_produces_module_results_per_ruleset():
    api = MagicMock()
    api.get_active_rulesets.return_value = [{
        "name": "App-Tier",
        "scopes": [],
        "rules": [{
            "href": "/sec_rules/1",
            "consumers": [{"label": {"href": "/labels/web"}}],
            "providers": [{"label": {"href": "/labels/db"}}],
            "ingress_services": [{"port": 443, "proto": 6}],
        }],
    }]
    api.fetch_managed_workloads.return_value = [
        {"href": "/wl/1", "interfaces": [{"address": "10.0.1.5"}],
         "labels": [{"href": "/labels/web"}]},
        {"href": "/wl/2", "interfaces": [{"address": "10.0.2.7"}],
         "labels": [{"href": "/labels/db"}]},
    ]
    api.get_ip_lists.return_value = []
    api.get_label_groups.return_value = []
    api.get_services.return_value = []

    rep = PolicyResolverReport(cm=MagicMock(), api_client=api)
    results = rep.resolve()                      # build lookups + resolve, no export
    rows = results["rulesets"]["App-Tier"]
    assert {(r["src_ip"], r["dst_ip"], r["port"]) for r in rows} == {
        ("10.0.1.5", "10.0.2.7", 443)}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_resolver_facade.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.report.policy_resolver_report'`.

- [ ] **Step 3: Write the facade**

Create `src/report/policy_resolver_report.py`:

```python
"""Policy Resolver report facade — fetch ACTIVE policy, build lookups, resolve.

I/O layer for the pure core in src/report/analysis/policy_resolver.py. Fetches
active rulesets + managed workloads + ip_lists + label_groups + services, builds
O(1) lookups in single passes, resolves each ruleset to flat IP rows, and exports
JSON + CSV via PolicyResolverExporter.
"""
from __future__ import annotations

from typing import Any

from src.report.analysis.policy_resolver import resolve_ruleset
from src.report.exporters.policy_resolver_exporter import PolicyResolverExporter


def build_workload_to_ips(workloads: list[dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for wl in workloads:
        href = wl.get("href")
        if not href:
            continue
        ips = [i["address"] for i in (wl.get("interfaces") or [])
               if i.get("address")]
        if ips:
            out[href] = ips
    return out


def build_label_to_ips(workloads: list[dict]) -> dict[str, list[str]]:
    """Single O(N) pass: attribute each workload's IPs to each of its labels."""
    out: dict[str, list[str]] = {}
    for wl in workloads:
        ips = [i["address"] for i in (wl.get("interfaces") or [])
               if i.get("address")]
        if not ips:
            continue
        for lbl in wl.get("labels") or []:
            href = lbl.get("href")
            if not href:
                continue
            bucket = out.setdefault(href, [])
            for ip in ips:
                if ip not in bucket:
                    bucket.append(ip)
    return out


def build_iplist_to_cidrs(ip_lists: list[dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for ipl in ip_lists:
        href = ipl.get("href")
        if not href:
            continue
        vals: list[str] = []
        for r in ipl.get("ip_ranges") or []:
            frm, to = r.get("from_ip"), r.get("to_ip")
            if frm and to:
                vals.append(f"{frm}-{to}")
            elif frm:
                vals.append(frm)
        for f in ipl.get("fqdns") or []:
            fq = f.get("fqdn")
            if fq:
                vals.append(fq)
        if vals:
            out[href] = vals
    return out


def build_label_group_to_labels(groups: list[dict]) -> dict[str, list[str]]:
    """Recursively flatten each group to its full set of member label hrefs."""
    by_href = {g.get("href"): g for g in groups if g.get("href")}
    memo: dict[str, list[str]] = {}

    def expand(href: str, seen: set[str]) -> list[str]:
        if href in memo:
            return memo[href]
        if href in seen:
            return []
        seen.add(href)
        g = by_href.get(href, {})
        labels = [l.get("href") for l in (g.get("labels") or []) if l.get("href")]
        for sg in g.get("sub_groups") or []:
            sgh = sg.get("href")
            if sgh:
                labels.extend(expand(sgh, seen))
        # de-dup preserving order
        out, s = [], set()
        for lh in labels:
            if lh not in s:
                s.add(lh)
                out.append(lh)
        memo[href] = out
        return out

    return {h: expand(h, set()) for h in by_href}


def build_service_to_ports(services: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for s in services:
        href = s.get("href")
        if href:
            out[href] = s.get("service_ports") or []
    return out


class PolicyResolverReport:
    def __init__(self, cm, api_client=None, config_dir: str = "config",
                 cache_reader=None):
        self.cm = cm
        self.api = api_client
        self.config_dir = config_dir
        self.cache_reader = cache_reader

    def resolve(self) -> dict[str, Any]:
        """Fetch + build lookups + resolve every active ruleset. No export."""
        api = self.api
        rulesets = api.get_active_rulesets()
        workloads = api.fetch_managed_workloads()
        ip_lists = api.get_ip_lists()
        groups = api.get_label_groups()
        services = api.get_services()

        lookups = dict(
            label_to_ips=build_label_to_ips(workloads),
            iplist_to_cidrs=build_iplist_to_cidrs(ip_lists),
            label_group_to_labels=build_label_group_to_labels(groups),
            workload_to_ips=build_workload_to_ips(workloads),
            service_to_ports=build_service_to_ports(services),
        )

        per_ruleset: dict[str, list[dict]] = {}
        total = 0
        for rs in rulesets:
            rows = resolve_ruleset(rs, **lookups)
            per_ruleset[rs.get("name", rs.get("href", "ruleset"))] = rows
            total += len(rows)
        return {"rulesets": per_ruleset, "record_count": total}

    def run(self, output_dir: str = "reports", lang: str = "en") -> str:
        results = self.resolve()
        if results["record_count"] == 0:
            return ""
        return PolicyResolverExporter(results, lang=lang).export(output_dir)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_resolver_facade.py -v`
Expected: FAIL on import of `PolicyResolverExporter` (created in Task 4) — that's expected; the lookup-builder + `resolve()` tests cannot run until Task 4 provides the exporter import. Proceed to Task 4, then re-run.

> Note: if you prefer green-at-each-task, temporarily stub the exporter import; Task 4 replaces it. The plan keeps them as one logical unit and re-runs at Task 4 Step 4.

- [ ] **Step 5: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/report/policy_resolver_report.py tests/test_policy_resolver_facade.py
git commit -m "feat(report): add policy-resolver facade with O(1) lookup builders"
```

---

### Task 4: JSON + CSV exporter

**Files:**
- Create: `src/report/exporters/policy_resolver_exporter.py`
- Test: `tests/test_policy_resolver_exporter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_policy_resolver_exporter.py`:

```python
"""Tests for the policy-resolver JSON + CSV exporter."""
from __future__ import annotations

import json
import os
import zipfile

from src.report.exporters.policy_resolver_exporter import PolicyResolverExporter


def _results():
    return {
        "rulesets": {
            "App-Tier": [
                {"ruleset_name": "App-Tier", "rule_href": "/sec_rules/1",
                 "src_ip": "10.0.1.5", "dst_ip": "10.0.2.7", "port": 443,
                 "protocol": "TCP", "src_kind": "label", "dst_kind": "label",
                 "service_name": ""},
            ],
        },
        "record_count": 1,
    }


def test_json_export_writes_per_ruleset_list(tmp_path):
    out = PolicyResolverExporter(_results(), lang="en").export_json(str(tmp_path))
    assert os.path.exists(out)
    data = json.load(open(out))
    assert data["rulesets"]["App-Tier"][0]["dst_ip"] == "10.0.2.7"


def test_csv_export_writes_zip_with_rows(tmp_path):
    out = PolicyResolverExporter(_results(), lang="en").export_csv(str(tmp_path))
    assert out.endswith(".zip")
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert any(n.endswith(".csv") for n in names)
        body = zf.read(names[0]).decode()
        assert "10.0.2.7" in body and "443" in body


def test_export_default_returns_both(tmp_path):
    paths = PolicyResolverExporter(_results(), lang="en").export(str(tmp_path))
    # export() returns the JSON path (primary); CSV alongside.
    assert os.path.exists(paths)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_resolver_exporter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.report.exporters.policy_resolver_exporter'`.

- [ ] **Step 3: Write the exporter**

Create `src/report/exporters/policy_resolver_exporter.py`:

```python
"""Policy Resolver exporter — JSON + CSV.

JSON: one document with a per-ruleset map of resolved rows.
CSV : reuses the generic CsvExporter (writes one CSV per ruleset into a ZIP).
"""
from __future__ import annotations

import datetime
import json
import os

from loguru import logger

import pandas as pd

from src.report.exporters.csv_exporter import CsvExporter


class PolicyResolverExporter:
    def __init__(self, results: dict, lang: str = "en"):
        self._r = results
        self._lang = lang

    def export_json(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        path = os.path.join(output_dir, f"Illumio_Policy_Resolver_{ts}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._r, f, ensure_ascii=False, indent=2)
        logger.info(f"[PolicyResolverExporter] Wrote JSON → {path}")
        return path

    def export_csv(self, output_dir: str = "reports") -> str:
        # Shape into module_results the generic CsvExporter understands:
        # {ruleset_name: DataFrame(rows)}.
        module_results = {
            name: pd.DataFrame(rows)
            for name, rows in (self._r.get("rulesets") or {}).items()
            if rows
        }
        return CsvExporter(module_results, report_label="Policy_Resolver").export(
            output_dir)

    def export(self, output_dir: str = "reports") -> str:
        self.export_csv(output_dir)
        return self.export_json(output_dir)
```

- [ ] **Step 4: Run exporter + facade tests**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_resolver_exporter.py tests/test_policy_resolver_facade.py -v`
Expected: PASS (exporter 3 tests + facade tests now that the import resolves).

- [ ] **Step 5: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/report/exporters/policy_resolver_exporter.py tests/test_policy_resolver_exporter.py
git commit -m "feat(report): add policy-resolver JSON+CSV exporter"
```

---

### Task 5: CLI `report resolve` command

**Files:**
- Modify: `src/cli/report.py` (add generator fn + `report resolve` command)
- Test: `tests/test_cli_policy_resolver.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_policy_resolver.py`:

```python
"""Tests for the `report resolve` CLI command."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from src.cli.report import report_group


def test_report_resolve_invokes_generator(tmp_path):
    runner = CliRunner()
    with patch("src.cli.report.generate_policy_resolver_report") as gen:
        gen.return_value = [str(tmp_path / "out.json")]
        (tmp_path / "out.json").write_text("{}")
        result = runner.invoke(
            report_group,
            ["resolve", "--format", "json", "--output-dir", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output
    gen.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_cli_policy_resolver.py -v`
Expected: FAIL — `report_group` has no `resolve` command (non-zero exit / "No such command").

- [ ] **Step 3: Add the generator function**

In `src/cli/report.py`, after `generate_policy_usage_report` (~165-213), add:

```python
def generate_policy_resolver_report(
    *,
    fmt: str = "json",
    output_dir: str | None = None,
    email: bool = False,
    ctx: click.Context | None = None,
) -> list[str]:
    """Resolve ACTIVE policy into IP-level rows; export JSON + CSV."""
    from src.config_manager import ConfigManager
    from src.api_client import ApiClient
    from src.report.policy_resolver_report import PolicyResolverReport

    root_dir, config_dir = _resolve_paths(output_dir)
    cm = ConfigManager(config_dir=config_dir)
    out_dir = _resolve_output_dir(cm, output_dir)
    lang = _resolve_lang(cm)

    api = ApiClient(cm.config)
    report = PolicyResolverReport(cm, api_client=api, config_dir=config_dir)
    path = report.run(output_dir=out_dir, lang=lang)
    return [path] if path else []
```

> Verify `ConfigManager` / `ApiClient` construction matches the existing generators in this file (Step: `grep -n "ConfigManager(\|ApiClient(" src/cli/report.py` and mirror the exact call used by `generate_security_report`'s path). Adjust the two constructor lines to match if they differ.

- [ ] **Step 4: Add the `resolve` command**

In `src/cli/report.py`, after `report_inventory` (~314-350), add:

```python
@report_group.command("resolve")
@click.option("--format", "fmt", type=click.Choice(["json", "csv", "all"]),
              default="json")
@click.option("--output-dir", type=click.Path(), default=None)
@click.option("--email", is_flag=True)
@click.pass_context
def report_resolve(ctx: click.Context, fmt: str, output_dir, email: bool) -> None:
    """Resolve ACTIVE label-based Policy into IP-level firewall rules."""
    try:
        paths = generate_policy_resolver_report(
            fmt=fmt, output_dir=output_dir, email=email, ctx=ctx,
        )
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, f"Connection failed: {exc}")
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except Exception as exc:
        log.exception("policy resolver report failed")
        echo_error(ctx, f"Unexpected error: {exc}")
        ctx.exit(EXIT_SOFTWARE)
        return
    _emit_paths(ctx, paths, fmt)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_cli_policy_resolver.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/cli/report.py tests/test_cli_policy_resolver.py
git commit -m "feat(cli): add 'report resolve' policy-resolver command"
```

---

### Task 6: Scheduler wiring (mirror ff93df9)

**Files:**
- Modify: `src/report_scheduler.py` (`_generate_report` ~247-307; email subject map ~322-327; `_REPORT_PREFIXES` ~471-476)
- Test: `tests/test_policy_resolver_scheduler.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_policy_resolver_scheduler.py`:

```python
"""Scheduler must recognise the policy_resolver report type (prune + subject)."""
from __future__ import annotations

import os

from src.report_scheduler import ReportScheduler


def test_prefix_registered():
    assert ReportScheduler._REPORT_PREFIXES["policy_resolver"] == \
        "Illumio_Policy_Resolver_"


def test_prune_by_count_handles_policy_resolver(tmp_path):
    # Create 3 matching files; keep 1.
    for i in range(3):
        (tmp_path / f"Illumio_Policy_Resolver_2026-06-0{i}_0900.json").write_text("{}")
    sched = ReportScheduler.__new__(ReportScheduler)
    sched._prune_by_count(str(tmp_path), "policy_resolver", 1)
    remaining = [f for f in os.listdir(tmp_path)
                 if f.startswith("Illumio_Policy_Resolver_")]
    assert len(remaining) == 1
```

> Confirm `_prune_by_count`'s signature/behaviour by reading `src/report_scheduler.py:480-500` before relying on the second test; if it needs an instance with attrs, adapt the construction exactly as `tests/test_traffic_report_split.py::test_scheduler_prune_by_count_handles_new_types` does.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_resolver_scheduler.py -v`
Expected: FAIL with `KeyError: 'policy_resolver'`.

- [ ] **Step 3: Register the prefix**

In `src/report_scheduler.py`, in `_REPORT_PREFIXES` (~471-476), add the entry:

```python
    _REPORT_PREFIXES = {
        "traffic":           "Illumio_Traffic_Report_",
        "security_risk":     "Illumio_Traffic_Report_SecurityRisk_",
        "network_inventory": "Illumio_Traffic_Report_NetworkInventory_",
        "policy_resolver":   "Illumio_Policy_Resolver_",
        "audit":             "illumio_audit_report_",
        "ven_status":        "illumio_ven_status_",
        "policy_usage":      "illumio_policy_usage_report_",
    }
```

- [ ] **Step 4: Add the email subject + dispatch branch**

In the email subject `type_label` map (~322-327), add:

```python
                      "policy_resolver": t("rpt_policy_resolver_title", lang=lang),
```

In `_generate_report` (~247-307), add a branch (after the `security_risk/network_inventory` block, before `audit`):

```python
        elif report_type == "policy_resolver":
            from src.report.policy_resolver_report import PolicyResolverReport
            report = PolicyResolverReport(self.cm, api_client=api,
                                          config_dir=self.config_dir)
            return report.run(output_dir=output_dir, lang=lang)
```

> Verify the exact local names available in `_generate_report` (`self.cm`, `self.config_dir`, `api`, `output_dir`, `lang`) by reading `src/report_scheduler.py:247-272`; mirror how the `security_risk` branch constructs its report object and adapt the constructor args to match.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_policy_resolver_scheduler.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/report_scheduler.py tests/test_policy_resolver_scheduler.py
git commit -m "feat(scheduler): wire policy_resolver into dispatch + prune + email subject"
```

---

### Task 7: i18n keys (EN + ZH_TW)

**Files:**
- Modify: `src/i18n_en.json`
- Modify: `src/i18n_zh_TW.json`

- [ ] **Step 1: Add keys to `src/i18n_en.json`**

Insert in alphabetical position within the existing `rpt_*` block (the report-title / column area). All use the strict `rpt_` prefix:

```json
  "rpt_email_pr_subject": "Policy Resolver Report",
  "rpt_policy_resolver_title": "Policy Resolver Report",
  "rpt_pr_col_dst_ip": "Destination IP",
  "rpt_pr_col_port": "Port",
  "rpt_pr_col_protocol": "Protocol",
  "rpt_pr_col_ruleset": "Ruleset",
  "rpt_pr_col_service": "Service",
  "rpt_pr_col_src_ip": "Source IP",
```

- [ ] **Step 2: Add the SAME keys to `src/i18n_zh_TW.json`**

Insert in the same alphabetical position. Glossary preserve-list keeps **Ruleset / Service / Port / Policy / IP List** in English per `src/i18n/data/glossary.json`:

```json
  "rpt_email_pr_subject": "Policy Resolver 報表",
  "rpt_policy_resolver_title": "Policy Resolver 報表",
  "rpt_pr_col_dst_ip": "目的 IP",
  "rpt_pr_col_port": "Port",
  "rpt_pr_col_protocol": "通訊協定",
  "rpt_pr_col_ruleset": "Ruleset",
  "rpt_pr_col_service": "Service",
  "rpt_pr_col_src_ip": "來源 IP",
```

- [ ] **Step 3: Verify i18n parity + glossary**

Run: `cd /home/harry/rd/illumio-ops && python scripts/audit_i18n_usage.py`
Expected: no NEW parity (Cat I) or glossary (Cat E) failures for the `rpt_policy_resolver_title` / `rpt_pr_*` / `rpt_email_pr_subject` keys. If a glossary violation is flagged, edit the ZH_TW value to preserve the flagged English term, then re-run.

- [ ] **Step 4: Run the i18n test suite**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_i18n_audit.py tests/test_i18n_glossary.py -v`
Expected: PASS (no new failures introduced by the added keys).

- [ ] **Step 5: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/i18n_en.json src/i18n_zh_TW.json
git commit -m "i18n(report): add policy-resolver report strings (EN/ZH_TW)"
```

---

## Final Verification

- [ ] **Run the full policy-resolver test scope**

Run:
```bash
cd /home/harry/rd/illumio-ops && python -m pytest \
  tests/test_policy_resolver_api.py \
  tests/test_policy_resolver_core.py \
  tests/test_policy_resolver_facade.py \
  tests/test_policy_resolver_exporter.py \
  tests/test_cli_policy_resolver.py \
  tests/test_policy_resolver_scheduler.py \
  tests/test_i18n_audit.py tests/test_i18n_glossary.py -v
```
Expected: all PASS.

- [ ] **Confirm separation of concerns**

The pure core (`src/report/analysis/policy_resolver.py::resolve_ruleset`) does zero I/O — verified by `test_policy_resolver_core.py` running entirely on synthetic dicts. The facade owns all fetches + lookup building. The exporter owns JSON+CSV. CLI + scheduler only dispatch.

- [ ] **Smoke-run the CLI against a live PCE (optional, manual)**

```bash
cd /home/harry/rd/illumio-ops && python illumio-ops.py report resolve --format all --output-dir reports
```
Verify a `Illumio_Policy_Resolver_*.json` (per-ruleset map) and a `Illumio_Policy_Resolver_Report_*_raw.zip` (one CSV per ruleset) appear in `reports/`, with `src_ip/dst_ip/port/protocol` columns.

---

## Self-Review Notes (author)

- **Spec coverage:** locked sources (label/label_group→workload→IP, ip_list→CIDR, workload→IP) → Task 2 core + Task 3 builders; JSON+CSV via exporter pipeline → Task 4; ACTIVE policy → `get_active_rulesets` in Task 3 facade; CLI `report` + scheduler wiring (ff93df9 shape) → Tasks 5+6; i18n EN/ZH_TW + glossary → Task 7; pure-vs-IO separation → Task 2 (pure) vs Task 3 (IO). All spec sections mapped.
- **Missing-API encoding:** the repo had NO public `get_ip_lists`/`get_label_groups`/`get_services` (only href-name caches in `labels.py:208-236`). Added as explicit Task 1 with complete code + endpoint-asserting tests, mirroring `get_active_rulesets`' draft/active + status-200 pattern.
- **Type consistency:** core row shape (`ruleset_name/rule_href/src_ip/dst_ip/port/protocol/src_kind/dst_kind/service_name[/port_to]`) is produced in Task 2, consumed unchanged by Task 4 exporter (DataFrame columns, JSON keys) and Task 3 facade (`record_count` sums rows). Lookup dict shapes match `resolve_ruleset`'s keyword params exactly.
- **Verified against real code:** workload `interfaces[].address` (`gui/routes/actions.py:150-153`); rule `consumers/providers/ingress_services` (`rule_scheduler.py:135-136`); actor shapes + `proto==17→UDP` (`api/labels.py:302-327,422`); CLI click template + `_REPORT_FORMATS`/`_emit_paths` (`cli/report.py`); scheduler dispatch + `_REPORT_PREFIXES` + subject map (`report_scheduler.py:247-327,471-476`); CsvExporter DataFrame walk (`exporters/csv_exporter.py`).
- **Placeholders:** none — every code/step has concrete content. Three steps include a "verify the exact local names / constructor" instruction because `ConfigManager`/`ApiClient` construction and `_prune_by_count`/`_generate_report` locals were not fully read line-by-line; the implementer is told to mirror the adjacent existing branch.
- **DRY/YAGNI:** reuses CsvExporter (no new CSV walker); no per-port range explosion; ams→ANY sentinel (no full-estate expansion); HTML/xlsx deliberately out of scope (JSON+CSV per locked decision).
