"""Every gui_ i18n key referenced from front-end JS must exist in i18n_en.json.

The parity tests only check that keys present in en also exist in zh_TW; they
cannot catch a key that JS references via T('gui_...','fallback') but that was
never added to the i18n sources. Because gui_ is a strict prefix, the engine
renders such a key as the literal marker [MISSING:key] at runtime (the JS
fallback is ignored), which is what surfaced the gui_ov_drill_* / gui_ov_dlq_label
gap on the overview dashboard.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / "src" / "static" / "js"

# Matches t('gui_x'), _t("gui_x"), T('gui_x', 'fallback') — the front-end i18n helpers.
_REF = re.compile(r"""\b_?[tT]\(\s*['"](gui_[A-Za-z0-9_]+)['"]""")


def test_all_js_referenced_gui_keys_exist_in_i18n():
    en = json.loads((ROOT / "src" / "i18n_en.json").read_text(encoding="utf-8"))
    missing: dict[str, set[str]] = {}
    for js in sorted(JS_DIR.glob("*.js")):
        for m in _REF.finditer(js.read_text(encoding="utf-8")):
            key = m.group(1)
            if key not in en:
                missing.setdefault(key, set()).add(js.name)
    assert not missing, (
        "Front-end JS references gui_ i18n keys that are absent from "
        "i18n_en.json (they render as [MISSING:key] at runtime):\n"
        + "\n".join(f"  {k}  <- {sorted(v)}" for k, v in sorted(missing.items()))
    )
