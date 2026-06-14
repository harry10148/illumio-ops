"""Post-fetch DataFrame filtering for cache-served traffic reports.

The live PCE API applies the report's filters server-side; the cache read does
not (only policy_decisions + workload-href scoping are pushed to SQL). This
re-applies the remaining filters (labels, ip, port, proto + exclusions) on the
cache-derived DataFrame so a filtered report served from cache returns the same
rows it would from the API. Honours query_operator ('or' => src OR dst match,
as App Summary uses; default 'and').

Standard label keys (app/env/loc/role) map to df columns; custom keys fall back
to the src/dst_extra_labels dict columns.
"""
from __future__ import annotations

import ipaddress

import pandas as pd

_STD_LABEL_KEYS = ("app", "env", "loc", "role")
_PROTO_ALIAS = {"6": "TCP", "17": "UDP", "1": "ICMP", "58": "ICMPV6"}


def _label_mask(df: pd.DataFrame, side: str, specs: list[str]) -> pd.Series:
    """AND of each "key=value" spec for one side (src/dst)."""
    m = pd.Series(True, index=df.index)
    for spec in specs:
        if "=" not in spec:
            continue
        k, v = spec.split("=", 1)
        k, v = k.strip(), v.strip()
        col = f"{side}_{k}"
        if col in df.columns:
            m &= df[col].astype(str) == v
        else:  # custom label key → extra_labels dict column
            exc = f"{side}_extra_labels"
            if exc in df.columns:
                m &= df[exc].apply(
                    lambda d, _k=k, _v=v: isinstance(d, dict) and d.get(_k) == _v
                )
            else:
                m &= False
    return m


def _ip_mask(df: pd.DataFrame, col: str, value: str) -> pd.Series:
    """Exact IP match, or CIDR containment when value has a '/'."""
    if "/" in value:
        try:
            net = ipaddress.ip_network(value, strict=False)
        except ValueError:
            return pd.Series(True, index=df.index)

        def _in(ip):
            try:
                return ipaddress.ip_address(str(ip)) in net
            except ValueError:
                return False

        return df[col].apply(_in)
    return df[col].astype(str) == value


def _scalar(filters: dict, key: str) -> str:
    v = filters.get(key)
    return v.strip() if isinstance(v, str) else (str(v) if v else "")


def apply_df_traffic_filters(df: pd.DataFrame, filters: dict | None) -> pd.DataFrame:
    """Return df filtered by the report's traffic filters (labels/ip/port/proto
    + exclusions). policy_decisions is intentionally skipped — it is pushed to
    SQL in read_flows_df. Empty/absent filters → df unchanged."""
    if df is None or df.empty or not filters:
        return df

    mask = pd.Series(True, index=df.index)

    src_inc = [s for s in (filters.get("src_labels") or []) if s]
    dst_inc = [s for s in (filters.get("dst_labels") or []) if s]
    op = (filters.get("query_operator") or "and").lower()
    if op == "or" and src_inc and dst_inc:
        mask &= _label_mask(df, "src", src_inc) | _label_mask(df, "dst", dst_inc)
    else:
        if src_inc:
            mask &= _label_mask(df, "src", src_inc)
        if dst_inc:
            mask &= _label_mask(df, "dst", dst_inc)

    for side in ("src", "dst"):
        ex = [s for s in (filters.get(f"ex_{side}_labels") or []) if s]
        if ex:
            mask &= ~_label_mask(df, side, ex)

    for key, col in (("src_ip", "src_ip"), ("dst_ip", "dst_ip")):
        v = _scalar(filters, key)
        if v and col in df.columns:
            mask &= _ip_mask(df, col, v)
        exv = _scalar(filters, f"ex_{key}")
        if exv and col in df.columns:
            mask &= ~_ip_mask(df, col, exv)

    port = _scalar(filters, "port")
    if port and "port" in df.columns:
        try:
            mask &= df["port"] == int(port)
        except (ValueError, TypeError):
            pass
    ex_port = _scalar(filters, "ex_port")
    if ex_port and "port" in df.columns:
        try:
            mask &= df["port"] != int(ex_port)
        except (ValueError, TypeError):
            pass

    proto = _scalar(filters, "proto")
    if proto and "proto" in df.columns:
        want = _PROTO_ALIAS.get(proto, proto).upper()
        mask &= df["proto"].astype(str).str.upper() == want

    return df[mask].reset_index(drop=True)
