from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

def test_setup_uses_requirements_lock():
    setup = (ROOT / "scripts" / "setup.sh").read_text()
    # Must use requirements.lock with hashes
    assert "requirements.lock" in setup, "setup.sh must reference requirements.lock"
    assert "--require-hashes" in setup, "setup.sh must require hash verification"


def test_setup_does_not_use_range_requirements():
    """setup.sh should NOT fall back to requirements.txt (range pins) for the runtime install."""
    setup = (ROOT / "scripts" / "setup.sh").read_text()
    # Allow `requirements-dev.txt` (used for dev install) but not bare `requirements.txt`
    # Check via string matches — comments are OK
    import re
    # Strip comments
    code_lines = [l.split("#")[0].strip() for l in setup.splitlines()]
    code = "\n".join(code_lines)
    # No `pip install -r requirements.txt` (without -dev suffix) in non-comment code
    matches = re.findall(r"pip\s+install\s+(?:[^&|;]*\s)?-r\s+requirements\.txt(?!\.[a-z]|-)", code)
    assert not matches, f"setup.sh still uses requirements.txt (range pins) in install: {matches}"
