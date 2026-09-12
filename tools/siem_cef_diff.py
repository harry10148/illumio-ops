#!/usr/bin/env python3
"""Join ops (input illumio-ops) and PCE-native (input illumio) CEF lines in
Graylog on event_href and print per-key diffs.  Usage:
    OP_TOKEN="$(op read op://Lab/garylog/credential)" python3 tools/siem_cef_diff.py --hours 2
Tolerated diffs (spec §6): header version, dst when the PCE JSON had FILTERED/none, dvchost."""
from __future__ import annotations
import argparse, base64, json, os, re, sys, urllib.parse, urllib.request

G = "http://172.16.15.105:9000"
TOLERATED = {"dst", "dvchost"}


def get(tok, path, **q):
    r = urllib.request.Request(G + path + "?" + urllib.parse.urlencode(q),
                               headers={"Authorization": "Basic " + base64.b64encode(f"{tok}:token".encode()).decode(),
                                        "Accept": "application/json", "X-Requested-By": "cli"})
    return json.load(urllib.request.urlopen(r, timeout=90))


def parse(line: str) -> tuple[list[str], dict[str, str]]:
    line = line[line.index("CEF:"):]
    head = line.split("|", 7)
    ext = head[7]
    keys = re.findall(r"(?:^| )([A-Za-z0-9_]+)=", ext)
    vals = {}
    for i, k in enumerate(keys):
        start = ext.index(f"{k}=", 0 if i == 0 else ext.index(f"{keys[i-1]}=") + 1) + len(k) + 1
        end = ext.index(f" {keys[i+1]}=", start) if i + 1 < len(keys) else len(ext)
        vals[k] = ext[start:end]
    return head[:7], vals


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--hours", type=int, default=2); a = ap.parse_args()
    tok = os.environ["OP_TOKEN"]
    ins = {i["title"]: i["id"] for i in get(tok, "/api/system/inputs")["inputs"]}
    ops = get(tok, "/api/search/universal/relative", query=f'gl2_source_input:{ins["illumio-ops"]} AND message:CEF* AND message:audit_events',
              range=a.hours * 3600, limit=2000)["messages"]
    pce = get(tok, "/api/search/universal/relative", query=f'gl2_source_input:{ins["illumio"]} AND message:audit_events',
              range=(a.hours + 1) * 3600, limit=5000)["messages"]
    by_href = {}
    for m in pce:
        _, v = parse(m["message"]["message"]); by_href[v.get("cs1", "")] = m["message"]["message"]
    joined = mismatched = 0
    for m in ops:
        oh, ov = parse(m["message"]["message"])
        ref = by_href.get(ov.get("cs1", ""))
        if not ref:
            continue
        joined += 1
        ph, pv = parse(ref)
        diffs = []
        if oh[4:] != ph[4:]:
            diffs.append(("header", oh[4:], ph[4:]))
        if list(ov) != list(pv):
            diffs.append(("key-order", list(ov), list(pv)))
        for k in pv:
            if k in TOLERATED:
                continue
            if k == "rt" and pv.get(k, "").endswith(" +0000") and ov.get(k) == pv[k][:-6]:
                continue  # deliberate: ops drops the zone suffix (see docs/guide/siem.md)
            if ov.get(k) != pv.get(k):
                diffs.append((k, ov.get(k), pv.get(k)))
        if diffs:
            mismatched += 1
            print("MISMATCH", ov.get("cs1"))
            for d in diffs:
                print("   ", d)
    print(f"joined={joined} mismatched={mismatched}")
    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main())
