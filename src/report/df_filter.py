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

from src.port_token import parse_port_token

_STD_LABEL_KEYS = ("app", "env", "loc", "role")
_PROTO_ALIAS = {"6": "TCP", "17": "UDP", "1": "ICMP", "58": "ICMPV6"}


def _name_mask(df: pd.DataFrame, column: str, values: list) -> pd.Series:
    """不分大小寫完整相等；缺欄回全 False（呼叫端決定 include/exclude 語意）。"""
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    vals = {str(v).strip().casefold() for v in values if v and str(v).strip()}
    return df[column].fillna("").astype(str).str.strip().str.casefold().isin(vals)


def _port_entries_mask(df: pd.DataFrame, entries: list) -> pd.Series:
    """parse_port_token/service 展開條目清單 → 條目間 OR 的命中 mask。"""
    m = pd.Series(False, index=df.index)
    if "port" not in df.columns:
        return m
    ports = pd.to_numeric(df["port"], errors="coerce")
    for e in entries:
        if e.get("wildcard"):
            m |= pd.Series(True, index=df.index)  # All Services：無服務限制，全命中
            continue
        em = pd.Series(True, index=df.index)
        if "port" in e:
            em &= ports.ge(e["port"]) & ports.le(e.get("to_port", e["port"]))
        if e.get("proto") is not None and "proto" in df.columns:
            want = _PROTO_ALIAS.get(str(e["proto"]), str(e["proto"])).upper()
            em &= df["proto"].astype(str).str.upper() == want
        if "port" not in e and e.get("proto") is None:
            continue  # 空條目不得全命中
        m |= em
    return m


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
    """Exact IP match, CIDR containment when value has a '/', or IP range
    containment ('a.b.c.d-a.b.c.d', from>to auto-swapped) when value has a '-'.
    Illegal CIDR/range values match everything (existing fail-open convention
    for this cache-display path)."""
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
    if "-" in value:
        left, _, right = value.partition("-")
        try:
            frm = ipaddress.IPv4Address(left.strip())
            to = ipaddress.IPv4Address(right.strip())
        except ValueError:
            return pd.Series(True, index=df.index)
        if frm > to:
            frm, to = to, frm

        def _in_range(ip):
            try:
                return frm <= ipaddress.ip_address(str(ip)) <= to
            except ValueError:
                return False

        return df[col].apply(_in_range)
    return df[col].astype(str) == value


def _scalar(filters: dict, key: str) -> str:
    v = filters.get(key)
    return v.strip() if isinstance(v, str) else (str(v) if v else "")


def _list_or_scalar(filters: dict, key: str) -> list[str]:
    """排除值正規化：FilterBar 送 list，舊前端送 scalar，皆歸一成清單（濾除空值/空白）。"""
    v = filters.get(key)
    vals = v if isinstance(v, list) else [v]
    out = []
    for item in vals:
        s = item.strip() if isinstance(item, str) else (str(item) if item else "")
        if s:
            out.append(s)
    return out


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
        if col in df.columns:
            # ex_src_ip/ex_dst_ip：FilterBar 送 list、舊前端送 scalar，皆需支援；
            # 語意同 ex_{side}_ip_in（逐值 AND-exclude）
            for exv in _list_or_scalar(filters, f"ex_{key}"):
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

    ports_raw = filters.get("ports")
    ports_list = ports_raw if isinstance(ports_raw, (list, tuple)) else [ports_raw]
    ports_inc = [s for s in ports_list if s]
    if ports_inc:
        tokens = [t for t in (parse_port_token(v) for v in ports_inc) if t]
        mask &= _port_entries_mask(df, tokens)  # 全數無法解析 → tokens 空 → mask False（fail-closed）
    ex_ports_raw = filters.get("ex_ports")
    ex_ports_list = ex_ports_raw if isinstance(ex_ports_raw, (list, tuple)) else [ex_ports_raw]
    for v in ex_ports_list:
        if v:
            t = parse_port_token(v)
            if t:
                mask &= ~_port_entries_mask(df, [t])

    svc_inc = filters.get("_svc_port_entries")
    if svc_inc:
        mask &= _port_entries_mask(df, svc_inc)
    svc_exc = filters.get("_ex_svc_port_entries")
    if svc_exc:
        mask &= ~_port_entries_mask(df, svc_exc)

    for inc_key, ex_key, col in (
        ("process_name", "ex_process_name", "process_name"),
        ("windows_service_name", "ex_windows_service_name", "windows_service_name"),
    ):
        raw = filters.get(inc_key)
        vals = [v for v in (raw if isinstance(raw, (list, tuple)) else [raw]) if v and str(v).strip()]
        if vals:
            mask &= _name_mask(df, col, vals)      # 缺欄 → 全 False（fail-closed）
        raw = filters.get(ex_key)
        vals = [v for v in (raw if isinstance(raw, (list, tuple)) else [raw]) if v and str(v).strip()]
        if vals:
            mask &= ~_name_mask(df, col, vals)     # 缺欄 → 不排除

    raw = filters.get("transmission")
    vals = [v for v in (raw if isinstance(raw, (list, tuple)) else [raw]) if v and str(v).strip()]
    if vals:
        mask &= _name_mask(df, "transmission", vals)
    raw = filters.get("ex_transmission") or filters.get("transmission_excludes")
    vals = [v for v in (raw if isinstance(raw, (list, tuple)) else [raw]) if v and str(v).strip()]
    if vals:
        mask &= ~_name_mask(df, "transmission", vals)

    # src_ip_in / dst_ip_in（FilterBar 送 list；多 IP/CIDR 取 OR）。既有 src_ip（scalar）保留相容。
    for side in ("src", "dst"):
        inc = [s for s in (filters.get(f"{side}_ip_in") or []) if s]
        if inc and f"{side}_ip" in df.columns:
            m = pd.Series(False, index=df.index)
            for v in inc:
                m |= _ip_mask(df, f"{side}_ip", v)
            mask &= m
        exi = [s for s in (filters.get(f"ex_{side}_ip_in") or []) if s]
        if exi and f"{side}_ip" in df.columns:
            for v in exi:
                mask &= ~_ip_mask(df, f"{side}_ip", v)

    # any_label / ex_any_label（either-side label：src 或 dst 命中）。用既有 _label_mask 單值。
    any_lbl = _scalar(filters, "any_label")
    if any_lbl:
        mask &= (_label_mask(df, "src", [any_lbl]) | _label_mask(df, "dst", [any_lbl]))
    ex_any_lbl = _scalar(filters, "ex_any_label")
    if ex_any_lbl:
        mask &= ~(_label_mask(df, "src", [ex_any_lbl]) | _label_mask(df, "dst", [ex_any_lbl]))

    # any_ip / ex_any_ip（either-side IP/CIDR：src 或 dst 命中）。同 any_label 樣式，
    # 並比照 _any_object_cidrs 區塊的欄位存在守衛（src_ip/dst_ip 任一不存在則略過此條件）。
    any_ip = _scalar(filters, "any_ip")
    if any_ip and "src_ip" in df.columns and "dst_ip" in df.columns:
        mask &= (_ip_mask(df, "src_ip", any_ip) | _ip_mask(df, "dst_ip", any_ip))
    ex_any_ip = _scalar(filters, "ex_any_ip")
    if ex_any_ip and "src_ip" in df.columns and "dst_ip" in df.columns:
        mask &= ~(_ip_mask(df, "src_ip", ex_any_ip) | _ip_mask(df, "dst_ip", ex_any_ip))

    proto = _scalar(filters, "proto")
    if proto and "proto" in df.columns:
        want = _PROTO_ALIAS.get(proto, proto).upper()
        mask &= df["proto"].astype(str).str.upper() == want

    return df[mask].reset_index(drop=True)
