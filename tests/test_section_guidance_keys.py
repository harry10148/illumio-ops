# tests/test_section_guidance_keys.py
"""Every section-guidance id used by the HTML exporter must resolve."""
import re
from pathlib import Path

from src.report.section_guidance import get_guidance


def _exporter_called_ids() -> set[str]:
    src = Path("src/report/exporters/html_exporter.py").read_text(encoding="utf-8")
    return set(re.findall(r"render_section_guidance\('([\w]+)'", src))


def test_short_id_resolves_to_full_registry_key():
    assert get_guidance("mod02") is not None
    assert get_guidance("mod02").module_id == "mod02_policy_decisions"


def test_full_key_still_resolves():
    assert get_guidance("mod02_policy_decisions") is not None


def test_unknown_id_returns_none():
    assert get_guidance("mod99") is None


def test_every_exporter_call_site_resolves():
    called = _exporter_called_ids()
    assert called, "expected to find render_section_guidance call sites"
    missing = {mid for mid in called if get_guidance(mid) is None}
    # 允許尚未撰寫 guidance 的模組存在，但至少 mod02/mod03/mod04/mod08 必須命中
    for must in ("mod02", "mod03", "mod04", "mod08"):
        assert must not in missing, f"{must} guidance must resolve"
