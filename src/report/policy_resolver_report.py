"""Policy Resolver report facade — fetch ACTIVE policy, build lookups, resolve.

I/O layer for the pure core in src/report/analysis/policy_resolver.py. Fetches
active rulesets + managed workloads + ip_lists + label_groups + services, builds
O(1) lookups in single passes, resolves each ruleset to flat IP rows, and exports
JSON + CSV via PolicyResolverExporter.
"""
from __future__ import annotations

from typing import Any

from loguru import logger

from src.report.analysis.policy_resolver import resolve_ruleset
from src.report.exporters.policy_resolver_exporter import PolicyResolverExporter

# 每條規則已有 _MAX_RULE_PAIRS 上限（見 analysis/policy_resolver.py），但跨 ruleset
# 的總列數仍無上限：幾百個 ruleset 各自貼著上限，就會把整個展開結果拉進記憶體再
# 寫成一份沒人能開的 JSON/CSV。這裡加總量上限，並沿用同一套揭露方式——被砍掉的
# 部分一定會在輸出裡寫明，不做靜默截斷。
_MAX_TOTAL_ROWS = 500_000


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


def build_service_to_names(services: list[dict]) -> dict[str, str]:
    """Map service href -> human-friendly name (e.g. 'HTTPS') for labelling."""
    out: dict[str, str] = {}
    for s in services:
        href, name = s.get("href"), s.get("name")
        if href and name:
            out[href] = name
    return out


def _cap_notice_row(ruleset_name: str, omitted: int) -> dict:
    """Sentinel row stating the total-row cap dropped `omitted` rows.

    刻意不是合法 IP／port，下游（第三方防火牆匯入）不會把它誤當成可套用的規則，
    但讀者在 JSON／CSV 裡一定看得到這一列。
    """
    token = f"<report row cap {_MAX_TOTAL_ROWS} reached: {omitted} rows omitted>"
    return {
        "ruleset_name": ruleset_name,
        "rule_href": "",
        "action": "",
        "src_ip": token,
        "dst_ip": token,
        "port": "",
        "protocol": "",
        "src_kind": "",
        "dst_kind": "",
        "service_name": "",
        "truncated": "total_row_cap",
    }


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
        # PCE 抓取失敗一律 raise_on_error=True：故障要讓報表往上炸失敗，
        # 不得誤把「抓取失敗」當成「規則全被移除」產出誤導性結果。
        rulesets = api.get_active_rulesets(raise_on_error=True)
        workloads = api.fetch_managed_workloads()
        ip_lists = api.get_ip_lists(raise_on_error=True)
        groups = api.get_label_groups(raise_on_error=True)
        services = api.get_services(raise_on_error=True)

        lookups = dict(
            label_to_ips=build_label_to_ips(workloads),
            iplist_to_cidrs=build_iplist_to_cidrs(ip_lists),
            label_group_to_labels=build_label_group_to_labels(groups),
            workload_to_ips=build_workload_to_ips(workloads),
            service_to_ports=build_service_to_ports(services),
            service_to_names=build_service_to_names(services),
        )

        per_ruleset: dict[str, list[dict]] = {}
        total = 0
        rows_omitted = 0
        truncated_rulesets: list[str] = []
        for rs in rulesets:
            name = rs.get("name", rs.get("href", "ruleset"))
            rows = resolve_ruleset(rs, **lookups)
            remaining = max(_MAX_TOTAL_ROWS - total, 0)
            kept = rows[:remaining]
            total += len(kept)
            if len(kept) < len(rows):
                omitted = len(rows) - len(kept)
                rows_omitted += omitted
                truncated_rulesets.append(name)
                kept = kept + [_cap_notice_row(name, omitted)]
            per_ruleset[name] = kept

        result: dict[str, Any] = {"rulesets": per_ruleset, "record_count": total}
        if rows_omitted:
            # 揭露欄位跟著結果一起進 JSON；CSV 端則靠上面每個 ruleset 尾端的
            # notice row，兩種輸出都不會讓截斷變成看不見的事。
            result["truncated"] = True
            result["row_cap"] = _MAX_TOTAL_ROWS
            result["rows_omitted"] = rows_omitted
            result["truncated_rulesets"] = truncated_rulesets
            logger.warning(
                "Policy Resolver hit the {} row cap: {} rows omitted across {} ruleset(s)",
                _MAX_TOTAL_ROWS, rows_omitted, len(truncated_rulesets))
        return result

    def run(self, output_dir: str = "reports", lang: str = "en",
            fmt: str = "all") -> list[str]:
        results = self.resolve()
        if results["record_count"] == 0:
            return []
        return PolicyResolverExporter(results, lang=lang).export(output_dir, fmt=fmt)
