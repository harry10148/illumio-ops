import re
from pathlib import Path


def _gui_init_src() -> str:
    return (Path(__file__).resolve().parent.parent / "src" / "gui" / "__init__.py").read_text()


def test_ip_allowlist_gate_registered_before_extension_hooks():
    """The IP allowlist / RST-drop gate must be the FIRST before_request hook.

    Flask runs before_request hooks in registration order. If CSRFProtect /
    Limiter / Talisman are instantiated before the gate, their hooks answer
    non-allowlisted IPs with real HTTP responses (CSRF 400 + fresh token +
    session cookie, 429 JSON, HTTPS redirect), defeating the RST-drop
    stealth invariant.
    """
    src = _gui_init_src()

    gate_idx = src.find("def ip_allowlist_gate")
    assert gate_idx >= 0, "ip_allowlist_gate hook not found in gui/__init__.py"

    for marker in ("CSRFProtect(app)", "Limiter(", "Talisman("):
        ext_idx = src.find(marker)
        assert ext_idx >= 0, f"{marker} not found in gui/__init__.py"
        assert gate_idx < ext_idx, (
            f"ip_allowlist_gate must be registered BEFORE {marker} so untrusted "
            "IPs are RST-dropped before any extension hook can respond"
        )


def test_ip_allowlist_gate_covers_static_unconditionally():
    """The gate must apply the IP check to ALL paths — no static-path skip
    before _check_ip_allowed / _rst_drop (IP-enumeration of /static/ assets
    must stay impossible)."""
    src = _gui_init_src()

    gate_match = re.search(
        r"def\s+ip_allowlist_gate.*?(?=\n\s*@app\.|\n\s*def\s|\Z)", src, re.DOTALL)
    assert gate_match, "ip_allowlist_gate not found in gui/__init__.py"
    body = gate_match.group(0)

    assert "_check_ip_allowed" in body, "_check_ip_allowed call not found inside ip_allowlist_gate"
    assert "_rst_drop" in body, "_rst_drop call not found inside ip_allowlist_gate"

    lines = [l.strip() for l in body.splitlines() if l.strip() and not l.strip().startswith("#")]
    ip_check_idx = next((i for i, l in enumerate(lines) if "_check_ip_allowed" in l), -1)
    static_skip_idx = next(
        (i for i, l in enumerate(lines)
         if ("is_static" in l or "/static/" in l) and ("return" in l or l.startswith("if "))),
        None,
    )
    assert static_skip_idx is None or ip_check_idx < static_skip_idx, (
        "IP allowlist check must not be skippable for static paths"
    )
