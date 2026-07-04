"""泛用 named-object diff：IP List / Service / Label Group 三種物件共用。

DRAFT relative to ACTIVE，語義與 diff_engine 一致：
added = 只在 draft、removed = 只在 active、modified = 白名單欄位值不同。
純函式，無 I/O。
"""

from __future__ import annotations

import pandas as pd

_OBJECT_COLS = [
    "change_type", "object_kind", "name", "object_id", "field",
    "draft_value", "active_value", "scope_expanded",
    "last_actor", "last_changed", "last_event",
]

# 值為成員清單、且新增成員等於擴大防護面的欄位
_EXPANSION_FIELDS = {"ip_ranges", "fqdns", "service_ports", "labels", "sub_groups"}


def _id_from_href(href: str) -> str:
    return str(href or "").rstrip("/").split("/")[-1]


def _fmt_ip_range(it: dict) -> str:
    base = str(it.get("from_ip", ""))
    if it.get("to_ip"):
        base += f"-{it['to_ip']}"
    if it.get("exclusion"):
        base = "!" + base
    return base


def _fmt_service_port(it: dict) -> str:
    proto = str(it.get("proto", ""))
    port = it.get("port")
    if port is None:
        return f"proto:{proto}"
    s = f"{proto}/{port}"
    if it.get("to_port") is not None:
        s += f"-{it['to_port']}"
    return s


def _fmt_windows_service(it: dict) -> str:
    return str(it.get("service_name") or it.get("process_name") or sorted(it.items()))


def _member_tokens(field: str, value, names: dict[str, str]) -> list[str]:
    """把清單欄位轉成穩定 token 清單（順序無關）。"""
    items = value if isinstance(value, list) else []
    tokens = []
    for it in items:
        if not isinstance(it, dict):
            tokens.append(str(it))
        elif field == "ip_ranges":
            tokens.append(_fmt_ip_range(it))
        elif field == "fqdns":
            tokens.append(str(it.get("fqdn", "")))
        elif field == "service_ports":
            tokens.append(_fmt_service_port(it))
        elif field == "windows_services":
            tokens.append(_fmt_windows_service(it))
        elif field in ("labels", "sub_groups"):
            href = str(it.get("href", "")).replace("/active/", "/draft/")
            tokens.append(names.get(href, names.get(str(it.get("href", "")), str(it.get("href", "")))))
        else:
            tokens.append(str(sorted(it.items())))
    return tokens


def _field_view(field: str, obj: dict, names: dict[str, str]) -> tuple[str, frozenset]:
    """回傳 (顯示摘要, 比對用 token set)。純量欄位 token set 為單元素。"""
    value = obj.get(field)
    if field in _EXPANSION_FIELDS or field == "windows_services":
        tokens = _member_tokens(field, value, names)
        return ", ".join(sorted(tokens)), frozenset(tokens)
    text = str(value or "").strip()
    return text, frozenset([text])


def _blank() -> dict:
    return {"last_actor": "", "last_changed": "", "last_event": ""}


def _index(objs: list[dict]) -> dict[str, dict]:
    out = {}
    for o in objs or []:
        if isinstance(o, dict) and o.get("href"):
            out[_id_from_href(o["href"])] = o
    return out


def diff_objects(draft: list[dict], active: list[dict], *, kind: str,
                 fields: list[str], names: dict[str, str] | None = None) -> pd.DataFrame:
    names = names or {}
    d_idx, a_idx = _index(draft), _index(active)
    rows: list[dict] = []

    for oid, obj in d_idx.items():
        if oid not in a_idx:
            rows.append({"change_type": "added", "object_kind": kind,
                         "name": str(obj.get("name", "")), "object_id": oid,
                         "field": "*", "draft_value": str(obj.get("name", "")),
                         "active_value": "", "scope_expanded": False, **_blank()})
    for oid, obj in a_idx.items():
        if oid not in d_idx:
            rows.append({"change_type": "removed", "object_kind": kind,
                         "name": str(obj.get("name", "")), "object_id": oid,
                         "field": "*", "draft_value": "",
                         "active_value": str(obj.get("name", "")),
                         "scope_expanded": False, **_blank()})
    for oid in d_idx.keys() & a_idx.keys():
        d_obj, a_obj = d_idx[oid], a_idx[oid]
        for field in fields:
            d_text, d_set = _field_view(field, d_obj, names)
            a_text, a_set = _field_view(field, a_obj, names)
            if d_text == a_text:
                continue
            expanded = field in _EXPANSION_FIELDS and bool(d_set - a_set)
            rows.append({"change_type": "modified", "object_kind": kind,
                         "name": str(d_obj.get("name", "")), "object_id": oid,
                         "field": field, "draft_value": d_text,
                         "active_value": a_text, "scope_expanded": expanded,
                         **_blank()})

    df = pd.DataFrame(rows, columns=_OBJECT_COLS)
    if not df.empty:
        df = df.sort_values(["change_type", "name", "field"], ignore_index=True)
    return df


def object_change_counts(df: pd.DataFrame) -> tuple[int, int, int]:
    """(added, removed, modified)；modified 以物件數計，非變動列數。"""
    if df is None or df.empty:
        return 0, 0, 0
    added = int((df["change_type"] == "added").sum())
    removed = int((df["change_type"] == "removed").sum())
    modified = int(df.loc[df["change_type"] == "modified", "object_id"].nunique())
    return added, removed, modified
