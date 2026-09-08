#!/usr/bin/env python3
"""PCE 事件裡有哪些欄位沒有人在看。

用途一（真機）：PCE 升版後跑一次，看它有沒有多給我們什麼。
    PYTHONPATH=. venv/bin/python tools/audit_event_fields.py --days 90

用途二（維護語料）：把真機看到的**形狀**寫回 tests/data/pce_event_shapes.json，
CI 的 tests/test_event_field_coverage.py 之後就會用它常態把關。
    PYTHONPATH=. venv/bin/python tools/audit_event_fields.py --days 90 --write-shapes

只處理路徑，不處理值——輸出與語料檔都不含任何事件內容，所以可以進 repo。兩個
無界家族的路徑另外截在家族邊界（見 collapse()），因為 Kubernetes 的 annotation
與 label 鍵是使用者自己命名的，全深度寫下去等於把客戶的命名帶進語料檔。

背景：2026-09-08 發現 PCE 26.2 給 agent.tampering 加的五個欄位被整包丟掉，
全套測試與十道閘門皆綠。沒有機制在看「PCE 給了什麼、我們讀了什麼」的差集。
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.events.field_coverage import leaf_paths, unledgered  # noqa: E402

SHAPES = pathlib.Path(__file__).resolve().parent.parent / "tests" / "data" / "pce_event_shapes.json"


_COLLAPSE_AT = ("resource_changes[].changes.", "resource_changes[].resource.")


def collapse(path: str) -> str:
    """把兩個無界家族的路徑截到家族邊界，再深的不記進語料。

    理由有兩層。其一，那兩處底下的鍵本來就是豁免的（見
    src/events/field_coverage.py 的說明），全深度記下來只是噪音。其二也是更
    要緊的：Kubernetes 的 `metadata.annotations` / `metadata.labels` 鍵**是使用
    者自己命名的**，在客戶環境重跑 --write-shapes 會把客戶的命名寫進語料檔。
    截在家族邊界，語料就只剩 PCE 自己的 schema。

    `notifications[].info.*` 不截：那裡的鍵是 PCE 定義的，而且正是新欄位會冒出
    來的地方——這個工具第一次跑就在那裡找到 events[].process_name / tamper_type。
    """
    for prefix in _COLLAPSE_AT:
        if path.startswith(prefix):
            rest = path[len(prefix):]
            head = rest.split(".", 1)[0]
            return prefix + head + (".*" if "." in rest else "")
    return path


def shapes_from_events(events: list[dict]) -> dict[str, list[str]]:
    by_type: dict[str, set[str]] = collections.defaultdict(set)
    for ev in events:
        by_type[str(ev.get("event_type") or "?")].update(
            collapse(p) for p in leaf_paths(ev))
    return {k: sorted(v) for k, v in sorted(by_type.items())}


def report(shapes: dict[str, list[str]]) -> int:
    findings = 0
    for event_type, paths in shapes.items():
        missing = unledgered(paths)
        if missing:
            findings += len(missing)
            print(f"\n{event_type}  ({len(missing)} 個沒人看的欄位)")
            for path in missing:
                print(f"    {path}")
    if not findings:
        print("OK — 每個看到的欄位都在帳本裡（有人讀，或有人簽名說不讀）。")
    else:
        print(f"\n共 {findings} 條未登記的路徑。到 src/events/field_coverage.py 的 "
              "FIELD_LEDGER 逐條決定：讀它，或寫下不讀的理由。")
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=90, help="往回抓幾天的事件（預設 90）")
    ap.add_argument("--from-file", help="改讀一份事件 JSON（陣列）而不是打 PCE")
    ap.add_argument("--write-shapes", action="store_true",
                    help="把看到的形狀合併寫回 tests/data/pce_event_shapes.json")
    args = ap.parse_args()

    if args.from_file:
        events = json.loads(pathlib.Path(args.from_file).read_text(encoding="utf-8"))
    else:
        from src.config import ConfigManager
        import src.main as m
        cm = ConfigManager()
        cm.load()
        api = m.ApiClient(cm)
        since = (datetime.datetime.now(datetime.timezone.utc)
                 - datetime.timedelta(days=args.days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        events = api.fetch_events(since)
    print(f"事件數：{len(events)}；型別數：{len({e.get('event_type') for e in events})}")

    shapes = shapes_from_events(events)
    findings = report(shapes)

    if args.write_shapes:
        existing = json.loads(SHAPES.read_text(encoding="utf-8")) if SHAPES.exists() else {}
        merged = dict(existing)
        for event_type, paths in shapes.items():
            merged[event_type] = sorted(set(merged.get(event_type, [])) | set(paths))
        SHAPES.parent.mkdir(parents=True, exist_ok=True)
        SHAPES.write_text(json.dumps(merged, ensure_ascii=False, indent=2,
                                     sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n形狀已合併寫入 {SHAPES}（{len(merged)} 個 event_type）")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
