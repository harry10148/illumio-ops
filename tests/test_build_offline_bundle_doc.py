"""Tests for L-7 + L-10: nssm hash documentation and PBS TOFU risk disclosure."""
from pathlib import Path


def test_build_offline_bundle_documents_tofu_risk():
    """scripts/build_offline_bundle.sh should document that SHA256 sidecar from same origin is TOFU."""
    script = (
        Path(__file__).resolve().parent.parent / "scripts" / "build_offline_bundle.sh"
    ).read_text()
    assert "TOFU" in script or "trust-on-first" in script.lower() or "GPG" in script or "Sigstore" in script, (
        "build_offline_bundle.sh should reference TOFU or GPG/Sigstore in comments"
    )


def test_vendor_windows_readme_exists():
    readme = Path(__file__).resolve().parent.parent / "vendor" / "windows" / "README.md"
    assert readme.exists()
    content = readme.read_text()
    assert "SHA256" in content
    assert len([line for line in content.splitlines() if "SHA256:" in line and "<" not in line]) >= 1, (
        "README should have a real SHA256 hash (not <FILL_IN> placeholder)"
    )
