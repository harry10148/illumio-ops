"""V-E lite — vulnerable assets that are actually reachable east-west.

Joins a vulnerability-scan CSV (ip, cve_id, severity, cvss) against observed
traffic: a vuln is "exposed" when its IP appears as the DESTINATION of any
non-blocked flow in the report window. Pure function; ranking favours
severity (cvss) and inbound source breadth — the analyst's patch-first list.
"""
from __future__ import annotations

import pandas as pd

from src.i18n import t

_SEV_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def vuln_exposure(df: pd.DataFrame, vulns: pd.DataFrame | None, top_n: int = 25,
                  lang: str = "en") -> dict:
    if vulns is None or vulns.empty:
        return {"available": False}

    reach = pd.DataFrame(columns=["dst_ip", "dst_app", "Inbound Sources", "Inbound Connections", "Top Ports"])
    if df is not None and not df.empty:
        nb = df[df["policy_decision"].astype(str) != "blocked"]
        if not nb.empty:
            grp = nb.groupby("dst_ip")
            reach = pd.DataFrame({
                "dst_ip": grp.size().index,
                "dst_app": grp["dst_app"].first().values,
                "Inbound Sources": grp["src_ip"].nunique().values,
                "Inbound Connections": grp["num_connections"].sum().values,
                "Top Ports": grp["port"].apply(
                    lambda s: ", ".join(str(p) for p in s.value_counts().head(3).index)).values,
            })

    joined = vulns.merge(reach, left_on="ip", right_on="dst_ip", how="left")
    exposed = joined[joined["dst_ip"].notna()].copy()
    exposed["_sev"] = exposed["severity"].astype(str).str.lower().map(_SEV_RANK).fillna(0)
    exposed["_cvss"] = pd.to_numeric(exposed["cvss"], errors="coerce").fillna(0)
    exposed = exposed.sort_values(["_sev", "_cvss", "Inbound Sources"], ascending=False)

    table = pd.DataFrame({
        "IP": exposed["ip"], "CVE": exposed["cve_id"], "Severity": exposed["severity"],
        "CVSS": exposed["cvss"], "Dst App": exposed["dst_app"].fillna(""),
        "Inbound Sources": exposed["Inbound Sources"].astype(int),
        "Inbound Connections": exposed["Inbound Connections"].astype(int),
        "Top Ports": exposed["Top Ports"],
    }).head(top_n).reset_index(drop=True)

    return {
        "available": True,
        "total_vulns": int(len(vulns)),
        "exposed_count": len(exposed),
        "unreached_count": int(len(vulns) - len(exposed)),
        "exposed": table,
        "chart_spec": {
            "type": "bar",
            "title_key": "rpt_vuln_chart_title",
            "title": t("rpt_vuln_chart_title", default="Exposed vs Unreached Vulnerabilities", lang=lang),
            "data": {"labels": [t("rpt_vuln_chart_exposed", default="Exposed", lang=lang),
                                t("rpt_vuln_chart_unreached", default="Unreached", lang=lang)],
                     "values": [int(len(exposed)), int(len(vulns) - len(exposed))]},
        },
    }
