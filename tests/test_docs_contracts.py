"""Documentation contracts for deployment/runtime promises.

These tests guard against silent drift between code defaults and what user-
facing docs claim. The 2026-05 doc refactor (PR #29) reorganised the docs
into `docs/INDEX.md` + a structured tree (getting-started / user-guide /
reference / architecture / contributing); tests now point at the new paths.
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_docs_do_not_advertise_python38_source_runtime():
    docs = {
        "README.md": _read("README.md"),
        "README_zh.md": _read("README_zh.md"),
        "docs/getting-started.md": _read("docs/getting-started.md"),
        "docs/getting-started_zh.md": _read("docs/getting-started_zh.md"),
    }

    for path, text in docs.items():
        assert "Python-3.8" not in text, f"{path} mentions Python-3.8 badge"
        assert "Python 3.8+" not in text, f"{path} mentions Python 3.8+"

    assert "Python-3.10%2B" in docs["README.md"]
    assert "Python-3.10%2B" in docs["README_zh.md"]
    assert "3.10 or later" in docs["docs/getting-started.md"]
    assert "3.10 以上" in docs["docs/getting-started_zh.md"]
    assert "CPython 3.12" in docs["docs/getting-started.md"]
    assert "CPython 3.12" in docs["docs/getting-started_zh.md"]


def test_docs_list_alerts_json_as_preserved_operator_config():
    docs = {
        "docs/getting-started.md": _read("docs/getting-started.md"),
        "docs/getting-started_zh.md": _read("docs/getting-started_zh.md"),
        "docs/user-guide/alerts-and-quarantine.md": _read("docs/user-guide/alerts-and-quarantine.md"),
        "docs/user-guide/alerts-and-quarantine_zh.md": _read("docs/user-guide/alerts-and-quarantine_zh.md"),
    }

    for path, text in docs.items():
        assert "alerts.json" in text, f"{path} must document the alert rules file"

    # getting-started must explicitly list the operator-owned trio as
    # preserved across upgrades.
    for path in ("docs/getting-started.md", "docs/getting-started_zh.md"):
        text = docs[path]
        assert "config.json" in text
        assert "alerts.json" in text
        assert "rule_schedules.json" in text

    assert "Files preserved across upgrades" in docs["docs/getting-started.md"]
    assert "升級後保留的檔案" in docs["docs/getting-started_zh.md"]


def test_version_badges_match_runtime_version():
    version_text = _read("src/__init__.py")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', version_text)
    assert match, "src/__init__.py must expose __version__"
    shield_version = match.group(1).replace("-", "--")

    assert f"Version-v{shield_version}-blue" in _read("README.md")
    assert f"Version-v{shield_version}-blue" in _read("README_zh.md")


def test_gui_port_and_bind_host_docs_match_runtime_defaults():
    # No new user-facing doc may advertise the stale GUI port 5000.
    doc_paths = [
        "docs/getting-started.md", "docs/getting-started_zh.md",
        "docs/user-guide/troubleshooting.md", "docs/user-guide/troubleshooting_zh.md",
        "docs/user-guide/settings-and-pce-cache.md", "docs/user-guide/settings-and-pce-cache_zh.md",
        "docs/reference/cli.md", "docs/reference/cli_zh.md",
    ]
    for path in doc_paths:
        text = _read(path)
        assert "https://<host>:5000" not in text, f"{path} must not document stale GUI port 5000"
        assert ":5000" not in text, f"{path} must not reference stale GUI port 5000"

    preflight = REPO_ROOT / "scripts/preflight.sh"
    if preflight.exists():
        assert "Port 5000" not in preflight.read_text(encoding="utf-8")

    # Runtime source default still 0.0.0.0; CLI reference docs the example.
    assert 'default="0.0.0.0"' in _read("src/cli/gui_cmd.py")
    assert "--host 0.0.0.0" in _read("docs/reference/cli.md")
    assert "--host 0.0.0.0" in _read("docs/reference/cli_zh.md")


def test_report_format_and_click_examples_match_cli_contracts():
    docs = {
        "README.md": _read("README.md"),
        "README_zh.md": _read("README_zh.md"),
        "docs/reference/cli.md": _read("docs/reference/cli.md"),
        "docs/reference/cli_zh.md": _read("docs/reference/cli_zh.md"),
        "docs/user-guide/reports.md": _read("docs/user-guide/reports.md"),
        "docs/user-guide/reports_zh.md": _read("docs/user-guide/reports_zh.md"),
    }

    stale_fragments = (
        "HTML + CSV",
        "HTML / CSV (15 traffic",
        "HTML / CSV（15 traffic",
        "HTML / CSV Raw ZIP / Both",
        "illumio-ops report --type traffic",
    )
    for path, text in docs.items():
        for fragment in stale_fragments:
            assert fragment not in text, f"{path} contains stale fragment: {fragment}"

    assert 'choices=["html", "csv", "pdf", "xlsx", "all"]' in _read("src/main.py")
    assert '_REPORT_FORMATS = ["html", "csv", "pdf", "xlsx", "all"]' in _read("src/cli/report.py")
    assert "illumio-ops report traffic --format html" in docs["docs/reference/cli.md"]
    assert "illumio-ops report traffic --format html" in docs["docs/reference/cli_zh.md"]


def test_siem_docs_do_not_list_nonexistent_flush_command():
    # CLI reference is the canonical command list; it must not document a
    # nonexistent `siem flush` subcommand, and must document the real triplet.
    for path in ("docs/reference/cli.md", "docs/reference/cli_zh.md"):
        text = _read(path)
        assert "siem flush" not in text, f"{path} must not document nonexistent siem flush"
        assert "siem dlq" in text
        assert "siem replay" in text
        assert "siem purge" in text


def test_preflight_upgrade_warnings_include_alerts_json():
    assert "alerts.json" in _read("scripts/preflight.sh")
    assert "alerts.json" in _read("scripts/preflight.ps1")


def test_legacy_argparse_examples_use_actual_entrypoint_name():
    main_text = _read("src/main.py")
    assert "illumio_ops.py" not in main_text
    assert "illumio-ops.py --gui" in main_text
