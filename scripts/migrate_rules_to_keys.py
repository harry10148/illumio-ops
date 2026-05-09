"""Phase 4: convert config.json rules from text to key-based fields.

Looks up event_type in src/reporter.py:_REC_I18N_KEYS to find the canonical
rec_key. For desc_key, derives from event_type as `rule_{event_type}_desc`
(matches the existing strict-prefix convention in i18n_*.json).

Idempotent: rules already having desc_key + rec_key are skipped.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.reporter import Reporter  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.write and args.dry_run:
        parser.error("--write and --dry-run are mutually exclusive")

    data = json.loads(args.config.read_text(encoding="utf-8"))
    rules = data.get("rules", [])
    rec_map = Reporter._REC_I18N_KEYS

    migrated = 0
    for rule in rules:
        event_type = rule.get("event_type")
        if not event_type:
            continue
        if rule.get("desc_key") and rule.get("rec_key"):
            continue
        if not rule.get("desc_key"):
            rule["desc_key"] = f"rule_{event_type}_desc"
        if not rule.get("rec_key"):
            rule["rec_key"] = rec_map.get(event_type, "alert_rec_default")
        migrated += 1

    if args.write:
        args.config.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"WROTE: migrated {migrated} rules in {args.config}")
    else:
        word = "rule" if migrated == 1 else "rules"
        print(f"DRY-RUN: would migrate {migrated} {word} in {args.config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
