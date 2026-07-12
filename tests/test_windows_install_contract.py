"""Contract: the Windows offline bundle must actually be installable.

Found live on Windows Server 2022 during bundle verification (2026-07-12):

- `pip download` evaluates environment markers against the machine RUNNING
  the download (Linux), so Windows-only transitive deps guarded by
  `platform_system == "Windows"` / `sys_platform == "win32"` markers
  (colorama for click/loguru, win32-setctime for loguru) were never
  downloaded, and the on-box `pip install --no-index` failed.
- install.ps1 ignored pip's exit code, registered and started the NSSM
  service anyway, and reported success while the app was uninstallable.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_requirements_offline_pins_windows_only_transitive_deps():
    req = (ROOT / "requirements-offline.txt").read_text()
    # Must be UNCONDITIONAL lines (no trailing environment marker): markers
    # are evaluated by the Linux build host during pip download and would
    # exclude these wheels from the bundle again.
    for pkg in ("colorama", "win32-setctime"):
        line = next(
            (ln for ln in req.splitlines() if ln.startswith(pkg)), None
        )
        assert line is not None, f"{pkg} missing from requirements-offline.txt"
        assert ";" not in line, (
            f"{pkg} must be unconditional — an environment marker would be "
            "evaluated on the Linux build host and skip the wheel again"
        )


def test_build_script_guards_windows_wheel_closure():
    src = (ROOT / "scripts" / "build_offline_bundle.sh").read_text()
    assert "colorama" in src and "win32_setctime" in src, (
        "build_offline_bundle.sh must assert the Windows-only wheels landed "
        "in the windows wheels dir before zipping"
    )


def test_install_ps1_fails_on_pip_error_and_verifies_deps():
    src = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8-sig")
    assert "pip install failed" in src, (
        "install.ps1 must check $LASTEXITCODE after pip install and abort"
    )
    assert "verify_deps.py" in src and "--offline-bundle" in src, (
        "install.ps1 must run the post-install dependency verification "
        "before registering the service"
    )
