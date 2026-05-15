"""After refactor, loadSettings() delegates to 4 helpers, each rendering into
its own panel container, while preserving every existing input id used by
saveSettings()."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parent.parent
JS = ROOT / "src" / "static" / "js" / "settings.js"


# Input ids saveSettings() (settings.js:512-559) currently reads.
# This set MUST remain after the refactor; any removed id breaks save.
PRESERVED_IDS = [
    # PCE / API
    "s-url", "s-org", "s-key", "s-sec", "s-ssl",
    "s-pce-name", "s-pce-url", "s-pce-org", "s-pce-key", "s-pce-secret", "s-pce-ssl",
    # Display
    "s-timezone", "s-rpt-dir", "s-rpt-retention",
    # TLS
    "s-tls-enabled", "s-tls-selfsigned", "s-tls-cert", "s-tls-key",
    "s-tls-auto-renew", "s-tls-auto-renew-days", "s-tls-options",
    "s-csr-cn", "s-csr-o", "s-csr-c", "s-csr-san-dns", "s-csr-san-ip", "s-csr-alg",
    "s-csr-result", "s-csr-pem",
    "s-import-cert-pem",
    # Web security
    "s-sec-user", "s-sec-ips", "s-sec-newpass",
]


def test_load_settings_uses_four_helpers():
    js = JS.read_text(encoding="utf-8")
    for name in (
        "_renderPceSection",
        "_renderChannelsSection",
        "_renderDisplaySection",
        "_renderSecuritySection",
    ):
        assert f"function {name}" in js, f"Expected helper function {name}() in settings.js"


def test_helpers_inject_into_correct_panel_targets():
    js = JS.read_text(encoding="utf-8")
    for target in (
        "s-panel-pce",
        "s-panel-channels",
        "s-panel-display",
        "s-panel-security",
    ):
        assert target in js, f"Expected render target id {target!r} referenced in settings.js"


def test_legacy_s_form_target_removed_from_loader():
    """loadSettings() should no longer write to #s-form (that div is gone)."""
    js = JS.read_text(encoding="utf-8")
    start = js.index("async function loadSettings()")
    end = js.index("\nfunction toggleTlsMode()", start)
    body = js[start:end]
    assert "s-form" not in body, (
        "loadSettings() should not reference legacy 's-form' container after refactor"
    )


def test_all_save_target_ids_still_in_render_helpers():
    js = JS.read_text(encoding="utf-8")
    # We only care that the id literally appears somewhere in the file
    # (the render helpers will produce them via template strings).
    for el_id in PRESERVED_IDS:
        assert f'id="{el_id}"' in js or f"id='{el_id}'" in js, (
            f"Input id {el_id!r} disappeared from settings.js — saveSettings() will break"
        )
