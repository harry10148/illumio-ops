"""Exfiltration & threat-intel analysis.

- Flag managed→unmanaged flows with high byte volume.
- Optional: join against a CSV of known-bad IPs.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

HIGH_VOLUME_THRESHOLD_BYTES = 1_000_000_000  # 1 GB


def analyze(flows_df: pd.DataFrame, *, threat_intel_csv: str | None = None) -> dict:
    if "src_managed" not in flows_df.columns or "dst_managed" not in flows_df.columns:
        return {"skipped": True, "reason": "no managed/unmanaged labels"}
    exfil = flows_df[(flows_df["src_managed"] == True) & (flows_df["dst_managed"] == False)]
    high_vol = []
    if "bytes" in exfil.columns:
        big = exfil[exfil["bytes"] >= HIGH_VOLUME_THRESHOLD_BYTES]
        high_vol = (big.groupby(["src", "dst", "port"])
                    .agg(bytes=("bytes", "sum"), flows=("dst", "count"))
                    .reset_index().sort_values("bytes", ascending=False).head(50)
                    .to_dict("records"))
    return {
        "high_volume_exfil": high_vol,
        "managed_to_unmanaged_count": int(len(exfil)),
        "threat_intel_matches": _threat_intel_join(exfil, threat_intel_csv),
    }


def _threat_intel_join(exfil_df, threat_intel_csv):
    if not threat_intel_csv:
        return []
    p = Path(threat_intel_csv)
    if not p.exists():
        return []
    bad = {}
    with p.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            bad[row["ip"].strip()] = row.get("reason", "unknown").strip()
    if not bad:
        return []
    matches = exfil_df[exfil_df["dst"].isin(bad.keys())]
    out = []
    for _, row in matches.iterrows():
        out.append({"src": row["src"], "dst": row["dst"], "port": int(row.get("port", 0)),
                    "reason": bad.get(row["dst"], "unknown")})
    return out
