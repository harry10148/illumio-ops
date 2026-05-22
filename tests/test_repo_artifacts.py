from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

def test_license_exists():
    license_file = ROOT / "LICENSE"
    assert license_file.exists(), "LICENSE file must exist at repo root"
    content = license_file.read_text().lower()
    assert "mit license" in content or "apache" in content or "bsd" in content, \
        "LICENSE must reference a recognized open-source license"

def test_sbom_generator_script_exists():
    script = ROOT / "scripts" / "generate_sbom.sh"
    assert script.exists(), "SBOM generator script must exist"
    assert script.stat().st_mode & 0o111, "SBOM generator must be executable"

def test_third_party_notices_generator_exists():
    script = ROOT / "scripts" / "generate_third_party_notices.sh"
    assert script.exists()
    assert script.stat().st_mode & 0o111

def test_ci_workflow_uses_lock_file():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "requirements.lock" in ci, "CI must use requirements.lock for reproducible builds"

def test_ci_workflow_runs_pip_audit():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "pip-audit" in ci or "pip_audit" in ci, "CI must run pip-audit security scan"
