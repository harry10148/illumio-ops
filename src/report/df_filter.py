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
    """同 key 內 OR、跨 key AND（對齊 PCE 原生語意，spec §2.2）。"""
    def split_spec(spec: str) -> tuple[str, str] | None:
        # "=" 與 ":" 皆可為分隔符，取先出現者；無分隔符則視為無法解析
        idx = min((i for i in (spec.find("="), spec.find(":")) if i != -1), default=-1)
        if idx == -1:
            return None
        return spec[:idx].strip(), spec[idx + 1:].strip()

    def one(spec: str) -> pd.Series:
        parsed = split_spec(spec)
        if parsed is None:
            return pd.Series(False, index=df.index)
        k, v = parsed
        col = f"{side}_{k}"
        if col in df.columns:
            return df[col].astype(str) == v
        exc = f"{side}_extra_labels"  # 自訂維度 key → extra_labels dict 欄
        if exc in df.columns:
            return df[exc].apply(
                lambda d, _k=k, _v=v: isinstance(d, dict) and d.get(_k) == _v)
        return pd.Series(False, index=df.index)

    by_key: dict[str, list[str]] = {}
    for i, spec in enumerate(specs):
        parsed = split_spec(spec)
        # 無法解析的 spec 各自成一組（恆為 False），迫使跨 key AND 失敗，而非靜默略過
        key = parsed[0] if parsed else f"__pos{i}"
        by_key.setdefault(key, []).append(spec)

    m = pd.Series(True, index=df.index)
    for group in by_key.values():
        gm = pd.Series(False, index=df.index)
        for spec in group:
            gm |= one(spec)
        m &= gm
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

    def _cidrs_mask(col: str, values: list) -> pd.Series:
        gm = pd.Series(False, index=df.index)
        for v in values:
            gm |= _ip_mask(df, col, str(v))
        return gm

    for fkey, col, negate in (
        ("_src_object_cidrs", "src_ip", False),
        ("_dst_object_cidrs", "dst_ip", False),
        ("_ex_src_object_cidrs", "src_ip", True),
        ("_ex_dst_object_cidrs", "dst_ip", True),
    ):
        vals = filters.get(fkey)
        if vals and col in df.columns:
            m = _cidrs_mask(col, vals)
            mask &= ~m if negate else m

    any_cidrs = filters.get("_any_object_cidrs")
    if any_cidrs and "src_ip" in df.columns and "dst_ip" in df.columns:
        mask &= _cidrs_mask("src_ip", any_cidrs) | _cidrs_mask("dst_ip", any_cidrs)

    ex_any_cidrs = filters.get("_ex_any_object_cidrs")
    if ex_any_cidrs and "src_ip" in df.columns and "dst_ip" in df.columns:
        # either-side 排除：來源或目的命中任一 CIDR 即剔除（對稱於 _any_object_cidrs 的包含）
        mask &= ~(_cidrs_mask("src_ip", ex_any_cidrs) | _cidrs_mask("dst_ip", ex_any_cidrs))

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
