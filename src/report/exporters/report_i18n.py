"""
Shared i18n helpers for HTML report exporters.

After Phase 1 migration, STRINGS is a _StringsView that:
  - Keeps an in-memory overlay for any key written at runtime (this module
    no longer writes any: report strings live in the i18n JSON catalogues)
  - Falls back to get_messages() for any key not in the overlay
  - Preserves the dict-like API (subscript, .get, __setitem__, __delitem__,
    __contains__, keys()) that 9 exporter files depend on.
"""
from __future__ import annotations

import os
from typing import Iterator


class _StringsView:
    """Compatibility layer over a runtime overlay + get_messages()-backed JSON."""

    def __init__(self) -> None:
        self._overlay: dict[str, dict[str, str]] = {}

    def __getitem__(self, key: str) -> dict[str, str]:
        if key in self._overlay:
            return self._overlay[key]
        from src.i18n.engine import EN_MESSAGES, get_messages
        if os.getenv("ILLUMIO_OPS_I18N_STRICT") and key not in EN_MESSAGES:
            raise KeyError(f"Missing i18n key: {key}")
        return {
            "en": get_messages("en").get(key, key),
            "zh_TW": get_messages("zh_TW").get(key, key),
        }

    def __setitem__(self, key: str, value: dict[str, str]) -> None:
        self._overlay[key] = value

    def __delitem__(self, key: str) -> None:
        del self._overlay[key]

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        if key in self._overlay:
            return True
        from src.i18n.engine import EN_MESSAGES
        return key in EN_MESSAGES

    def __len__(self) -> int:
        from src.i18n.engine import EN_MESSAGES
        return len(self._overlay) + sum(1 for k in EN_MESSAGES if k not in self._overlay)

    def get(self, key: str, default: dict[str, str] | None = None) -> dict[str, str] | None:
        try:
            return self[key]
        except KeyError:
            return default

    def keys(self) -> Iterator[str]:
        from src.i18n.engine import EN_MESSAGES
        seen: set[str] = set()
        for k in self._overlay:
            seen.add(k)
            yield k
        for k in EN_MESSAGES:
            if k not in seen:
                yield k

    def items(self) -> Iterator[tuple[str, dict[str, str]]]:
        for k in self.keys():
            yield k, self[k]

    def overlay_items(self) -> Iterator[tuple[str, dict[str, str]]]:
        """Yield only the dynamic-write overlay entries — not JSON-backed ones.

        Use this when iterating for prefix-filtering on overlay-resident keys
        (rpt_col_*, rpt_cat_*, rpt_rule_*) to avoid the ~2569-key JSON scan
        that items() does. ~60x faster at module load when callers only need
        overlay entries.
        """
        yield from self._overlay.items()


def _entry(en: str, zh_tw: str | None = None) -> dict[str, str]:
    return {"en": en, "zh_TW": zh_tw or en}


STRINGS: _StringsView = _StringsView()

# Every report string lives in src/i18n_en.json / src/i18n_zh_TW.json (AGENTS.md).
# This module used to register ~256 English/Chinese pairs inline as a runtime
# overlay; they were moved into the JSON catalogues verbatim, so STRINGS now
# resolves straight from there.

# Table header → i18n key. Report DataFrames are keyed by an ENGLISH DISPLAY
# NAME ("Total Connections") or, for the audit tables, a raw snake_case id; this
# map turns either into the catalogue key. It is data, not text — the values are
# keys — so it is kept as a JSON file next to this module rather than derived
# from the overlay (which no longer exists).
import json as _json

with open(os.path.join(os.path.dirname(__file__), "col_i18n_map.json"), encoding="utf-8") as _fh:
    COL_I18N: dict[str, str] = _json.load(_fh)

# Render-layer value i18n maps. Pass these to render_df_table via
# value_i18n_maps={col_name: <map>}. Stable English keys; values are
# STRINGS lookup keys.

TIER_VALUE_I18N: dict[str, str] = {
    "Tier-1 Critical":   "rpt_tier_1_critical",
    "Tier-2 Important":  "rpt_tier_2_important",
    "Tier-3 Shared":     "rpt_tier_3_shared",
    "Tier-4 Peripheral": "rpt_tier_4_peripheral",
}

ROLE_VALUE_I18N: dict[str, str] = {
    "Identity": "rpt_role_identity",
    "Database": "rpt_role_database",
    "Provider": "rpt_role_provider",
    "Consumer": "rpt_role_consumer",
    "Bridge":   "rpt_role_bridge",
    "Peer":     "rpt_role_peer",
}

ASSET_TYPE_VALUE_I18N: dict[str, str] = {
    "Identity Infrastructure": "rpt_asset_type_identity_infra",
    "Database":                "rpt_asset_type_database",
}

SEVERITY_VALUE_I18N: dict[str, str] = {
    "CRITICAL": "rpt_severity_critical",
    "HIGH":     "rpt_severity_high",
    "MEDIUM":   "rpt_severity_medium",
    "LOW":      "rpt_severity_low",
    "INFO":     "rpt_severity_info",
}

MOD01_METRIC_VALUE_I18N: dict[str, str] = {
    "Policy Coverage":                       "rpt_metric_policy_coverage",
    "Allowed / Blocked / Potentially Blocked": "rpt_metric_allowed_blocked_potential",
    "Total Data":                            "rpt_metric_total_data",
    "Date Range":                            "rpt_metric_date_range",
}

RISK_TYPE_VALUE_I18N: dict[str, str] = {
    "Visibility Risk": "rpt_pu_risk_type_visibility",
    "Draft Conflict":  "rpt_pu_risk_type_conflict",
    "Draft Coverage":  "rpt_pu_risk_type_coverage",
}

def lang_btn_html() -> str:
    return ''
