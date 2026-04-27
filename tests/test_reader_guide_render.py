"""Reader-guide rendering: when a module has registered guidance, the HTML
section starts with a guidance card that includes the four labels."""
import src.i18n as i18n_mod
from src.report.exporters.html_exporter import render_section_guidance


def _patch_en_keys(monkeypatch, extras: dict):
    """Add extra keys to EN_MESSAGES and clear lru_cache so t() sees them."""
    new_messages = dict(i18n_mod.EN_MESSAGES)
    new_messages.update(extras)
    monkeypatch.setattr(i18n_mod, "EN_MESSAGES", new_messages)
    i18n_mod._build_messages.cache_clear()
    i18n_mod._normalized_en_messages.cache_clear()


def test_returns_empty_when_module_unregistered():
    assert render_section_guidance("nope_unknown_mod", profile="security_risk",
                                    detail_level="standard") == ""


def test_returns_card_when_registered(monkeypatch):
    from src.report import section_guidance as sg
    fake = sg.SectionGuidance(
        module_id="demo",
        purpose_key="rpt_guidance_demo_purpose",
        watch_signals_key="rpt_guidance_demo_signals",
        how_to_read_key="rpt_guidance_demo_how",
        recommended_actions_key="rpt_guidance_demo_actions",
        profile_visibility=("security_risk", "network_inventory"),
        min_detail_level="full",
    )
    monkeypatch.setitem(sg.REGISTRY, "demo", fake)
    _patch_en_keys(monkeypatch, {
        "rpt_guidance_demo_purpose": "Demo purpose text",
        "rpt_guidance_demo_signals": "Demo signals text",
        "rpt_guidance_demo_how": "Demo how text",
        "rpt_guidance_demo_actions": "Demo actions text",
    })
    try:
        html = render_section_guidance("demo", profile="security_risk",
                                        detail_level="standard")
        assert "Demo purpose text" in html
        assert "rpt_guidance_demo_purpose" not in html
    finally:
        i18n_mod._build_messages.cache_clear()
        i18n_mod._normalized_en_messages.cache_clear()


def test_legacy_executive_mode_still_renders_full_guidance(monkeypatch):
    from src.report import section_guidance as sg
    fake = sg.SectionGuidance(
        module_id="demo2",
        purpose_key="rpt_guidance_demo_purpose",
        watch_signals_key="rpt_guidance_demo_signals",
        how_to_read_key="rpt_guidance_demo_how",
        recommended_actions_key="rpt_guidance_demo_actions",
        profile_visibility=("security_risk",),
        min_detail_level="full",
    )
    monkeypatch.setitem(sg.REGISTRY, "demo2", fake)
    _patch_en_keys(monkeypatch, {
        "rpt_guidance_demo_purpose": "Demo purpose",
        "rpt_guidance_demo_signals": "Demo signals",
        "rpt_guidance_demo_how": "Demo how",
        "rpt_guidance_demo_actions": "Demo actions",
    })
    try:
        html = render_section_guidance("demo2", profile="security_risk",
                                        detail_level="executive")
        assert "Demo signals" in html
        assert "Demo how" in html
    finally:
        i18n_mod._build_messages.cache_clear()
        i18n_mod._normalized_en_messages.cache_clear()


def test_returns_empty_when_profile_excluded(monkeypatch):
    from src.report import section_guidance as sg
    fake = sg.SectionGuidance(
        module_id="demo3",
        purpose_key="rpt_guidance_demo_purpose",
        watch_signals_key="rpt_guidance_demo_signals",
        how_to_read_key="rpt_guidance_demo_how",
        recommended_actions_key="rpt_guidance_demo_actions",
        profile_visibility=("network_inventory",),  # only network, not security
        min_detail_level="full",
    )
    monkeypatch.setitem(sg.REGISTRY, "demo3", fake)
    html = render_section_guidance("demo3", profile="security_risk",
                                    detail_level="standard")
    assert html == ""
