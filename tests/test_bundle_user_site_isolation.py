"""The offline bundle must not touch the host's user site-packages.

The bundled interpreter is not marked externally-managed, so PEP 668 does not
hold its pip back the way it holds back a distro python. Installing the
bundle's wheel set therefore UNINSTALLS whatever the host had under
``~/.local/lib/pythonX.Y/site-packages`` for any package sharing a name.

Observed on 2026-09-02 while smoke-testing the 5.0.0 bundle: the install
stripped greenlet, sqlalchemy, pandas, numpy, apscheduler, matplotlib and
pydantic out of the developer's environment. The bundle is meant to be
self-contained in both directions — it neither reads from nor writes to
anything outside its own tree.

`PYTHONNOUSERSITE=1` is the switch that enforces it. These tests pin it at all
three places the bundled interpreter runs: the installer, the CLI wrapper the
installer writes, and the systemd unit.
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "scripts" / "install.sh"
BUILD_SH = ROOT / "scripts" / "build_offline_bundle.sh"
UNIT = ROOT / "deploy" / "illumio-ops.service"


def test_installer_exports_no_user_site() -> None:
    body = INSTALL_SH.read_text(encoding="utf-8")
    assert re.search(r"^export PYTHONNOUSERSITE=1$", body, re.M), (
        "install.sh runs the bundled python's pip; without PYTHONNOUSERSITE it "
        "uninstalls the host's user site-packages"
    )


def test_cli_wrapper_carries_the_isolation() -> None:
    """The wrapper runs outside the installer process, so it needs its own."""
    body = INSTALL_SH.read_text(encoding="utf-8")
    start = body.index('cat > "$WRAPPER"')
    end = body.index("chmod 0755", start)
    wrapper = body[start:end]
    assert "PYTHONNOUSERSITE=1" in wrapper, (
        "the illumio-ops wrapper must isolate the bundled interpreter too"
    )


def test_build_script_exports_no_user_site() -> None:
    body = BUILD_SH.read_text(encoding="utf-8")
    assert re.search(r"^export PYTHONNOUSERSITE=1$", body, re.M)


def test_systemd_unit_sets_no_user_site() -> None:
    body = UNIT.read_text(encoding="utf-8")
    assert re.search(r"^Environment=PYTHONNOUSERSITE=1$", body, re.M)
    # The unit's other defence must stay too — they guard different things:
    # ProtectHome hides /home, PYTHONNOUSERSITE also covers a root-owned
    # user site under /root.
    assert re.search(r"^ProtectHome=true$", body, re.M)
