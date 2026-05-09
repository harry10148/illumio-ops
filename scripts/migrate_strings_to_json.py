"""Migrate STRINGS dict → i18n_*.json. Dry-run first, apply with --write."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.report.exporters.report_i18n import STRINGS  # noqa: E402

EN_PATH = ROOT / "src" / "i18n_en.json"
ZH_PATH = ROOT / "src" / "i18n_zh_TW.json"


def _load(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, data: dict[str, str]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Apply changes")
    parser.add_argument("--dry-run", action="store_true", help="Report only")
    parser.add_argument("--manifest", type=Path, default=ROOT / "scripts" / "migrate_strings_manifest.json")
    parser.add_argument("--prefer", choices=["strings", "json"], default="strings",
                        help="Canonical source for overlap keys (default: strings — newer)")
    args = parser.parse_args()

    if args.write and args.dry_run:
        parser.error("--write and --dry-run are mutually exclusive")

    en = _load(EN_PATH)
    zh = _load(ZH_PATH)

    string_keys = set(STRINGS.keys())
    en_keys = set(en.keys())
    only_strings = string_keys - en_keys
    overlap = string_keys & en_keys

    additions_en: dict[str, str] = {}
    additions_zh: dict[str, str] = {}
    overlap_changes: list[tuple[str, str, str]] = []

    for key in only_strings:
        entry = STRINGS[key]
        additions_en[key] = entry["en"]
        additions_zh[key] = entry.get("zh_TW") or entry["en"]

    for key in overlap:
        s_en = STRINGS[key]["en"]
        s_zh = STRINGS[key].get("zh_TW") or s_en
        if s_en != en.get(key) or s_zh != zh.get(key):
            overlap_changes.append((key, en.get(key, ""), s_en))
            if args.prefer == "strings":
                additions_en[key] = s_en
                additions_zh[key] = s_zh

    manifest = {
        "only_in_strings": len(only_strings),
        "overlap": len(overlap),
        "overlap_changes": len(overlap_changes),
        "samples": list(only_strings)[:10] + [c[0] for c in overlap_changes[:10]],
        "prefer": args.prefer,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if args.write:
        en.update(additions_en)
        zh.update(additions_zh)
        _save(EN_PATH, en)
        _save(ZH_PATH, zh)
        print(f"WROTE: +{len(additions_en)} en keys, +{len(additions_zh)} zh keys")
    else:
        print(f"DRY-RUN: would add {len(additions_en)} en, {len(additions_zh)} zh; "
              f"would change {len(overlap_changes)} overlap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
