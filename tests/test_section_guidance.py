"""Validates the section_guidance registry shape and internal consistency."""
import json
from pathlib import Path

import pytest

from src.report.section_guidance import (
    SectionGuidance, REGISTRY, get_guidance, ProfileVisibility, DetailLevel,
)


def test_registry_is_a_dict_keyed_by_module_id():
    assert isinstance(REGISTRY, dict)
    assert all(isinstance(k, str) for k in REGISTRY)


def test_each_entry_is_section_guidance_instance():
    for module_id, entry in REGISTRY.items():
        assert isinstance(entry, SectionGuidance), f"{module_id} not SectionGuidance"


def test_guidance_fields_are_i18n_keys():
    for module_id, entry in REGISTRY.items():
        for fld in ("purpose_key", "watch_signals_key", "how_to_read_key", "recommended_actions_key"):
            v = getattr(entry, fld)
            assert isinstance(v, str) and len(v) > 0, f"{module_id}.{fld} empty"
            assert v.startswith("rpt_guidance_"), f"{module_id}.{fld} bad prefix: {v}"


def test_profile_visibility_values_are_valid():
    valid = {"security_risk", "network_inventory"}
    for module_id, entry in REGISTRY.items():
        for p in entry.profile_visibility:
            assert p in valid, f"{module_id} bad profile: {p}"


def test_min_detail_level_is_valid():
    valid = {"full"}
    for module_id, entry in REGISTRY.items():
        assert entry.min_detail_level in valid


def test_get_guidance_returns_none_for_unknown():
    assert get_guidance("no_such_module") is None


def test_get_guidance_returns_entry_for_known():
    # Pick any registered module from the registry.
    if not REGISTRY:
        pytest.skip("registry empty in this phase task")
    sample_id = next(iter(REGISTRY))
    g = get_guidance(sample_id)
    assert g is not None
    assert g.module_id == sample_id


def test_all_referenced_i18n_keys_exist_in_both_locales():
    en = json.loads(Path("src/i18n_en.json").read_text())
    zh = json.loads(Path("src/i18n_zh_TW.json").read_text())
    missing_en, missing_zh = [], []
    for module_id, entry in REGISTRY.items():
        for fld in ("purpose_key", "watch_signals_key", "how_to_read_key", "recommended_actions_key"):
            key = getattr(entry, fld)
            if key not in en: missing_en.append(f"{module_id}.{fld}={key}")
            if key not in zh: missing_zh.append(f"{module_id}.{fld}={key}")
    assert not missing_en, f"missing in i18n_en.json: {missing_en}"
    assert not missing_zh, f"missing in i18n_zh_TW.json: {missing_zh}"
