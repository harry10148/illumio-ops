"""Contract: FilterBar keys must appear in every endpoint forward whitelist.

Whitelist misses are SILENT drops (the analyzer never sees the key) — the
seventh..ninth incidents of this class. This is a static source contract:
each (file, anchor) surface below must name every key in KEYS.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (label, file, anchor-substring-that-identifies-the-dict)
FORWARD_SURFACES = (
    ("reports.report_filters", "src/gui/routes/reports.py", "report_filters = {"),
    ("dashboard._fb_keys", "src/gui/routes/dashboard.py", "_fb_keys = ("),
    ("dashboard.top10_params", "src/gui/routes/dashboard.py", '"src_ip_in": d.get("src_ip_in")'),
)

PILL_KEYS = ("ports", "ex_ports", "services", "ex_services")

NAME_KEYS = ("process_name", "ex_process_name",
             "windows_service_name", "ex_windows_service_name")

FORWARD_SURFACES_ALL = FORWARD_SURFACES + (
    ("rules.whitelist", "src/gui/routes/rules.py", "src_labels"),
    ("actions.quarantine", "src/gui/routes/actions.py", "src_labels"),
)


def _surface_text(path: str, anchor: str, span: int = 4000) -> str:
    text = (ROOT / path).read_text()
    idx = text.find(anchor)
    assert idx >= 0, f"anchor not found in {path}: {anchor}"
    return text[idx : idx + span]


def test_pill_port_service_keys_forwarded_everywhere():
    for label, path, anchor in FORWARD_SURFACES:
        seg = _surface_text(path, anchor)
        missing = [k for k in PILL_KEYS if f"'{k}'" not in seg and f'"{k}"' not in seg]
        assert not missing, f"{label} missing keys: {missing}"


def test_name_keys_forwarded_everywhere():
    for label, path, anchor in FORWARD_SURFACES_ALL:
        seg = _surface_text(path, anchor)
        missing = [k for k in NAME_KEYS if f"'{k}'" not in seg and f'"{k}"' not in seg]
        assert not missing, f"{label} missing keys: {missing}"
