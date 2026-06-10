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
    seen_per_label: dict[str, set[str]] = {}
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
            seen = seen_per_label.setdefault(href, set())
            for ip in ips:
                if ip not in seen:
                    seen.add(ip)
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

    def expand(href: str, seen: set[str]) -> list[str]:
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
        if not self.api:
            return {"rulesets": {}, "record_count": 0}
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
