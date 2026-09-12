#!/usr/bin/env python3
"""Join ops (Graylog input illumio-ops, CEF-parsed fields) against the PCE's own
CEF lines (input illumio, raw syslog text) on event_href and diff field by field.

    OP_TOKEN="$(op read op://Lab/garylog/credential)" python3 tools/siem_cef_diff.py --hours 2

Graylog's CEF codec keeps only parsed fields (csN/cnN resolved to their labels,
rt to epoch ms), so the PCE side is parsed here the same way before comparing.
Tolerated (documented in docs/guide/siem.md): device_version, dst, dvchost,
and rt's zone suffix.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

G = "http://172.16.15.105:9000"
TOLERATED = {"dst", "dvchost", "device_version"}


def get(tok, path, **q):
    r = urllib.request.Request(
        G + path + "?" + urllib.parse.urlencode(q),
        headers={"Authorization": "Basic " + base64.b64encode(f"{tok}:token".encode()).decode(),
                 "Accept": "application/json", "X-Requested-By": "cli"})
    return json.load(urllib.request.urlopen(r, timeout=90))


def parse_pce(line: str) -> dict:
    """Raw CEF line -> the field dict Graylog's codec would produce."""
    line = line[line.index("CEF:"):]
    head = line.split("|", 7)
    ext = head[7]
    keys = re.findall(r"(?:^| )([A-Za-z0-9_-]+)=", ext)
    raw: dict[str, str] = {}
    pos = 0
    for i, k in enumerate(keys):
        start = ext.index(f"{k}=", pos) + len(k) + 1
        end = ext.index(f" {keys[i + 1]}=", start) if i + 1 < len(keys) else len(ext)
        raw[k] = ext[start:end]
        pos = end
    out = {"device_version": head[3], "event_class_id": head[4], "name": head[5], "severity": head[6]}
    for k, v in raw.items():
        if k.endswith("Label"):
            continue
        label = raw.get(k + "Label")
        if label and re.fullmatch(r"c[sn]\d", k):
            if v != "":
                out[label] = v
            continue
        if k == "rt":
            m = re.match(r"(\w{3} \d\d \d{4} \d\d:\d\d:\d\d)(?:\.(\d{3}))?(?: \+0000)?$", v)
            if m:
                dt = datetime.strptime(m.group(1), "%b %d %Y %H:%M:%S").replace(tzinfo=timezone.utc)
                out["rt"] = int(dt.timestamp() * 1000) + int(m.group(2) or 0)
            else:
                out["rt"] = v
            continue
        if v != "":
            out[k] = v
    return out


def norm(v):
    return str(v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=2)
    a = ap.parse_args()
    tok = os.environ["OP_TOKEN"]
    ins = {i["title"]: i["id"] for i in get(tok, "/api/system/inputs")["inputs"]}
    ops = get(tok, "/api/search/universal/relative",
              query=f'gl2_source_input:{ins["illumio-ops"]} AND cat:audit_events',
              range=a.hours * 3600, limit=3000)["messages"]
    pce = get(tok, "/api/search/universal/relative",
              query=f'gl2_source_input:{ins["illumio"]} AND message:audit_events',
              range=(a.hours + 2) * 3600, limit=5000)["messages"]
    # The PCE emits some events twice (one line with request/requestMethod/
    # reason, one without); keep the richer line per href.
    by_href: dict[str, dict] = {}
    for m in pce:
        p = parse_pce(m["message"]["message"])
        href = p.get("event_href", "")
        if len(p) > len(by_href.get(href, {})):
            by_href[href] = p
    joined = mismatched = 0
    kinds: dict[str, int] = {}
    for m in ops:
        o = {k: v for k, v in m["message"].items()
             if not k.startswith("gl2_") and k not in ("streams", "_id", "source", "timestamp", "message", "device_vendor", "device_product")}
        p = by_href.get(o.get("event_href", ""))
        if not p:
            continue
        joined += 1
        diffs = []
        for k in sorted(set(o) | set(p)):
            if k in TOLERATED:
                continue
            if norm(o.get(k)) != norm(p.get(k)):
                diffs.append((k, o.get(k), p.get(k)))
                kinds[k] = kinds.get(k, 0) + 1
        if diffs:
            mismatched += 1
            if mismatched <= 10:
                print("MISMATCH", o.get("event_href"))
                for d in diffs:
                    print("   ", d[0], "| ops:", str(d[1])[:120], "| pce:", str(d[2])[:120])
    print(f"joined={joined} mismatched={mismatched} by_field={kinds}")
    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main())
