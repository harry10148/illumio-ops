"""Vulnerability-scan CSV ingest for the V-E lite report section.

Accepts generic exports plus common Qualys/Tenable column names via alias
matching (case-insensitive). Required: an IP column and a CVE column.
Output schema: DataFrame[ip, cve_id, severity, cvss].
"""
from __future__ import annotations

import pandas as pd

_ALIASES = {
    "ip": ("ip", "ip address", "ip_address", "asset ip", "host ip", "ipv4"),
    "cve_id": ("cve_id", "cve", "cve id", "cveid", "vulnerability id"),
    "severity": ("severity", "risk", "risk factor", "vuln severity"),
    "cvss": ("cvss", "cvss v3 base score", "cvss3 base score", "cvss base score", "cvss_score"),
}


def _pick(columns: list[str], aliases: tuple[str, ...]) -> str | None:
    lowered = {c.lower().strip(): c for c in columns}
    for a in aliases:
        if a in lowered:
            return lowered[a]
    return None


def load_vulns(path: str) -> pd.DataFrame:
    raw = pd.read_csv(path, dtype=str)
    cols = list(raw.columns)
    picked = {std: _pick(cols, aliases) for std, aliases in _ALIASES.items()}
    for required in ("ip", "cve_id"):
        if picked[required] is None:
            raise ValueError(f"vuln CSV missing a recognizable '{required}' column "
                             f"(accepted: {', '.join(_ALIASES[required])})")
    n = len(raw)
    out = pd.DataFrame({
        "ip": raw[picked["ip"]].fillna("").str.strip(),
        "cve_id": raw[picked["cve_id"]].fillna("").str.strip(),
        "severity": raw[picked["severity"]].fillna("") if picked["severity"] else pd.Series([""] * n),
        "cvss": (pd.to_numeric(raw[picked["cvss"]], errors="coerce")
                 if picked["cvss"] else pd.Series([float("nan")] * n)),
    })
    out = out[(out["ip"] != "") & (out["cve_id"] != "")].reset_index(drop=True)
    return out
