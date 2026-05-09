"""Phase 2: persist every key's zh_TW value into i18n_zh_TW.json.

Drains _translate_text(), zh_explicit, and humanize fallbacks into static JSON
so the runtime can stop calling them. Idempotent: running twice is a no-op.

After this lands, _build_messages can be simplified to a pure dictionary lookup
(plus strict-prefix MISSING marker), and _translate_text becomes migration-only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.i18n.engine import (  # noqa: E402
    EN_MESSAGES,
    ZH_MESSAGES,
    _ZH_EXPLICIT,
    _humanize_key_zh,
    _is_strict_surface_key,
    _translate_text,
)

ZH_PATH = ROOT / "src" / "i18n_zh_TW.json"
GLOSSARY_PATH = ROOT / "src" / "i18n" / "data" / "glossary.json"


def _resolve_zh(key: str, en_val: str) -> str:
    """Replicate the legacy _build_messages('zh_TW') resolution order, but as data."""
    if _is_strict_surface_key(key):
        return f"[MISSING:{key}]"
    if key in _ZH_EXPLICIT:
        return _ZH_EXPLICIT[key]
    if isinstance(en_val, str) and en_val:
        translated = _translate_text(en_val)
        if translated and translated != en_val:
            return translated
    return _humanize_key_zh(key)


def _check_glossary(zh_val: str) -> list[str]:
    glossary = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    bad = []
    for term, substitutes in glossary["forbidden_zh_substitutes"].items():
        for sub in substitutes:
            if sub in zh_val:
                bad.append(f"{term}->{sub}")
    return bad


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.write and args.dry_run:
        parser.error("--write and --dry-run are mutually exclusive")

    zh_now = dict(ZH_MESSAGES)
    updates: dict[str, str] = {}
    glossary_violations: list[tuple[str, list[str]]] = []

    for key, en_val in EN_MESSAGES.items():
        existing = zh_now.get(key, "").strip() if isinstance(zh_now.get(key), str) else ""
        if existing and not existing.startswith("[MISSING:"):
            continue
        resolved = _resolve_zh(key, en_val)
        bad = _check_glossary(resolved)
        if bad:
            glossary_violations.append((key, bad))
        updates[key] = resolved

    if glossary_violations:
        print(f"GLOSSARY VIOLATIONS ({len(glossary_violations)}):")
        for key, bad in glossary_violations[:20]:
            print(f"  {key}: {bad}")
        print("Fix the offending en strings or add to phrase_overrides.json before --write.")
        return 1

    if args.write:
        zh_now.update(updates)
        ZH_PATH.write_text(
            json.dumps(zh_now, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"WROTE: {len(updates)} new zh_TW entries")
    else:
        print(f"DRY-RUN: would update {len(updates)} keys")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
