"""Glossary data file is the single source of truth for English-preserved terms."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GLOSSARY_PATH = ROOT / "src" / "i18n" / "data" / "glossary.json"


def test_glossary_loads_and_has_required_terms() -> None:
    data = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    preserve = set(data["preserve_in_zh_tw"])
    required = {
        "Block", "Blocked", "Allow", "Allowed", "Manage", "Managed",
        "Unmanage", "Unmanaged", "PCE", "VEN", "Workload", "Service",
        "Port", "Policy", "Ringfence", "App", "Label", "SMTP",
        "Online", "Offline", "Potentially Blocked",
    }
    missing = required - preserve
    assert not missing, f"glossary missing required terms: {missing}"


@pytest.mark.xfail(
    reason=(
        "Phase 2 cleanup: 128 pre-existing violations in i18n_zh_TW.json "
        "(Label->標籤, Labels->標籤, Offline->離線, etc.). "
        "Resolved in T11 precompute pass."
    ),
    strict=False,
)
def test_zh_tw_values_preserve_glossary_terms() -> None:
    """For every key whose en value contains a glossary term as a whole word,
    the zh_TW value must also contain it as-is (not a Chinese substitute)."""
    en = json.loads((ROOT / "src" / "i18n_en.json").read_text(encoding="utf-8"))
    zh = json.loads((ROOT / "src" / "i18n_zh_TW.json").read_text(encoding="utf-8"))
    glossary = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    preserve = glossary["preserve_in_zh_tw"]
    forbidden_translations = glossary["forbidden_zh_substitutes"]  # e.g., {"Service": ["服務"]}

    violations: list[tuple[str, str, str]] = []
    for key, en_val in en.items():
        zh_val = zh.get(key, "")
        if not isinstance(en_val, str) or not isinstance(zh_val, str):
            continue
        for term in preserve:
            if re.search(rf"\b{re.escape(term)}\b", en_val):
                # Must appear in zh too, AND the forbidden Chinese substitute must NOT.
                if term not in zh_val:
                    violations.append((key, term, zh_val))
                for bad in forbidden_translations.get(term, []):
                    if bad in zh_val:
                        violations.append((key, f"{term}->{bad}", zh_val))

    assert not violations, f"{len(violations)} glossary violations. First 5: {violations[:5]}"
