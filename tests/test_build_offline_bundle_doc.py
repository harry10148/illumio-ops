"""Tests for L-10: PBS TOFU risk disclosure."""
from pathlib import Path


def test_build_offline_bundle_documents_tofu_risk():
    """scripts/build_offline_bundle.sh should document that SHA256 sidecar from same origin is TOFU."""
    script = (
        Path(__file__).resolve().parent.parent / "scripts" / "build_offline_bundle.sh"
    ).read_text()
    assert "TOFU" in script or "trust-on-first" in script.lower() or "GPG" in script or "Sigstore" in script, (
        "build_offline_bundle.sh should reference TOFU or GPG/Sigstore in comments"
    )
