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
