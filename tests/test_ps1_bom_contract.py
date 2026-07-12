"""Contract: every PowerShell script shipped in the offline bundle must start
with a UTF-8 BOM.

Windows PowerShell 5.1 reads BOM-less files using the system ANSI code page.
These scripts contain non-ASCII characters (em-dashes, box-drawing comment
rules), whose UTF-8 bytes act as DBCS lead bytes on CJK code pages (e.g.
CP950) and swallow the following character — including closing quotes —
producing bogus parse errors and an unrunnable installer. Found live on a
zh-TW Windows Server 2022 host during bundle verification (2026-07-12).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

UTF8_BOM = b"\xef\xbb\xbf"


def _shipped_ps1_files():
    # build_offline_bundle.sh stages scripts/ and deploy/ wholesale, so every
    # .ps1 under either directory lands in the bundle.
    return sorted(
        list((ROOT / "scripts").glob("*.ps1"))
        + list((ROOT / "deploy").glob("*.ps1"))
    )


def test_shipped_ps1_files_exist():
    names = {p.name for p in _shipped_ps1_files()}
    assert {"preflight.ps1", "install.ps1", "install_service.ps1"} <= names


def test_shipped_ps1_files_have_utf8_bom():
    for path in _shipped_ps1_files():
        head = path.read_bytes()[:3]
        assert head == UTF8_BOM, (
            f"{path.relative_to(ROOT)} lacks a UTF-8 BOM; PowerShell 5.1 "
            "misparses BOM-less UTF-8 containing non-ASCII characters on "
            "CJK ANSI code pages"
        )
