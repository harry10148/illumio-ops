"""Port token 解析（純函式、零依賴）。

消費者：labels 的 native payload 組裝、report/df_filter 的 cache 路徑比對、
CLI object_picker 的手動輸入驗證。語法：'80'、'443/tcp'、'1000-2000'、
'1000-2000/tcp'、'80-90:6'（舊 : 分隔僅限範圍）；proto 收數字或別名。
"""
from __future__ import annotations

PROTO_NAME_TO_NUM = {"tcp": 6, "udp": 17, "icmp": 1, "icmpv6": 58}


def _coerce_proto(proto):
    if proto in (None, ""):
        return None, True
    if isinstance(proto, str) and proto.strip().lower() in PROTO_NAME_TO_NUM:
        return PROTO_NAME_TO_NUM[proto.strip().lower()], True
    try:
        return int(proto), True
    except (TypeError, ValueError):
        return None, False


def parse_port_token(value, default_proto=None):
    """token -> services.include/exclude 條目 dict；無法解析回 None。

    回傳形狀：{"port": n}、{"port": n, "proto": p}、
    {"port": n, "to_port": m[, "proto": p]}。port 界限 1-65535。
    """
    proto = default_proto
    if isinstance(value, (list, tuple)):
        if len(value) == 2:
            start, end = value
        elif len(value) == 3:
            start, end, proto = value
        else:
            return None
    else:
        text = str(value).strip()
        if not text:
            return None
        range_part = text
        if "/" in text:
            range_part, proto_part = text.split("/", 1)
            proto = proto_part
        elif ":" in text and text.count(":") == 1 and "-" in text:
            range_part, proto_part = text.split(":", 1)
            proto = proto_part
        if "-" in range_part:
            start, end = [part.strip() for part in range_part.split("-", 1)]
        else:
            start = end = range_part.strip()  # 單一 port（'80'、'443/tcp'）
    try:
        start = int(start)
        end = int(end)
    except (TypeError, ValueError):
        return None
    if start > end:
        start, end = end, start
    if not (1 <= start <= 65535 and 1 <= end <= 65535):
        return None
    entry = {"port": start} if start == end else {"port": start, "to_port": end}
    proto_num, ok = _coerce_proto(proto)
    if not ok:
        return None
    if proto_num is not None:
        entry["proto"] = proto_num
    return entry
