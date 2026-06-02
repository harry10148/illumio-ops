import json
from pathlib import Path
from src.events.reference import load_reference, EventRef

REF_PATH = Path("docs/_meta/illumio-event-reference.json")

def test_reference_loads_and_is_typed():
    ref = load_reference()
    assert isinstance(ref, dict)
    sample = ref["agent.tampering"]
    assert isinstance(sample, EventRef)
    assert sample.category and sample.description  # non-empty
    assert sample.severity in ("info", "warning", "critical")


def test_runbook_lookup_returns_severity_and_response():
    from src.events.runbooks import runbook_for
    rb = runbook_for("request.authentication_failed")
    assert rb is not None
    assert rb["severity_hint"] == "critical"
    assert "brute force" in rb["response"].lower()
    assert runbook_for("totally.unknown") is None


def test_every_known_type_has_reference_and_i18n():
    import json
    from src.events.catalog import KNOWN_EVENT_TYPES, _HIDDEN_EVENT_TYPES
    from src.events.reference import load_reference
    ref = load_reference()
    visible = set(KNOWN_EVENT_TYPES) - set(_HIDDEN_EVENT_TYPES)
    missing_ref = sorted(visible - set(ref))
    assert not missing_ref, f"types missing from reference: {missing_ref}"
    en = json.load(open("src/i18n_en.json")); zh = json.load(open("src/i18n_zh_TW.json"))
    for et in sorted(visible):
        key = "event_desc_" + et.replace(".", "_")
        assert en.get(key), f"{key} missing/empty in i18n_en.json"
        assert zh.get(key), f"{key} missing/empty in i18n_zh_TW.json"
