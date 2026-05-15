"""Documentation contracts for deployment/runtime promises."""
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
        "docs/Installation.md": _read("docs/Installation.md"),
        "docs/Installation_zh.md": _read("docs/Installation_zh.md"),
    }

    for path, text in docs.items():
        assert "Python-3.8" not in text
        assert "Python 3.8+" not in text
        assert "Python 3.8+" not in text

    assert "Python-3.10%2B" in docs["README.md"]
    assert "Python-3.10%2B" in docs["README_zh.md"]
    assert "Source/development runtime: Python 3.10+" in docs["docs/Installation.md"]
    assert "原始碼/開發執行環境：Python 3.10+" in docs["docs/Installation_zh.md"]
    assert "bundled CPython 3.12" in docs["docs/Installation.md"]
    assert "內建 CPython 3.12" in docs["docs/Installation_zh.md"]


def test_docs_list_alerts_json_as_preserved_operator_config():
    docs = {
        "README.md": _read("README.md"),
        "README_zh.md": _read("README_zh.md"),
        "docs/Installation.md": _read("docs/Installation.md"),
        "docs/Installation_zh.md": _read("docs/Installation_zh.md"),
        "docs/User_Manual.md": _read("docs/User_Manual.md"),
        "docs/User_Manual_zh.md": _read("docs/User_Manual_zh.md"),
        "docs/Troubleshooting.md": _read("docs/Troubleshooting.md"),
        "docs/Troubleshooting_zh.md": _read("docs/Troubleshooting_zh.md"),
    }

    for path, text in docs.items():
        assert "alerts.json" in text, f"{path} must document the split alert rules file"

    for path in (
        "docs/Installation.md",
        "docs/Installation_zh.md",
        "docs/User_Manual.md",
        "docs/User_Manual_zh.md",
    ):
        text = docs[path]
        assert "config.json" in text
        assert "alerts.json" in text
        assert "rule_schedules.json" in text

    assert "config.json, alerts.json (rules), and rule_schedules.json are preserved" in docs["docs/Installation.md"]
    assert "config.json、alerts.json（rules）與 rule_schedules.json 會被保留" in docs["docs/Installation_zh.md"]


def test_version_badges_match_runtime_version():
    version_text = _read("src/__init__.py")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', version_text)
    assert match, "src/__init__.py must expose __version__"
    shield_version = match.group(1).replace("-", "--")

    assert f"Version-v{shield_version}-blue" in _read("README.md")
    assert f"Version-v{shield_version}-blue" in _read("README_zh.md")


def test_gui_port_and_bind_host_docs_match_runtime_defaults():
    docs = {
        "docs/User_Manual.md": _read("docs/User_Manual.md"),
        "docs/User_Manual_zh.md": _read("docs/User_Manual_zh.md"),
        "docs/Troubleshooting.md": _read("docs/Troubleshooting.md"),
        "docs/Troubleshooting_zh.md": _read("docs/Troubleshooting_zh.md"),
    }
    scripts = {
        "scripts/preflight.sh": _read("scripts/preflight.sh"),
    }

    for path, text in docs.items():
        assert "https://<host>:5000" not in text, f"{path} must not document stale GUI port 5000"
    for path, text in scripts.items():
        assert "Port 5000" not in text, f"{path} must not preflight stale GUI port 5000"

    assert 'default="0.0.0.0"' in _read("src/cli/gui_cmd.py")
    assert "default `0.0.0.0`" in docs["docs/User_Manual.md"]
    assert "預設 `0.0.0.0`" in docs["docs/User_Manual_zh.md"]


def test_report_format_and_click_examples_match_cli_contracts():
    docs = {
        "README.md": _read("README.md"),
        "README_zh.md": _read("README_zh.md"),
        "docs/User_Manual.md": _read("docs/User_Manual.md"),
        "docs/User_Manual_zh.md": _read("docs/User_Manual_zh.md"),
        "docs/Report_Modules.md": _read("docs/Report_Modules.md"),
        "docs/Report_Modules_zh.md": _read("docs/Report_Modules_zh.md"),
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

    assert 'choices=["html", "csv", "xlsx", "all"]' in _read("src/main.py")
    assert '_REPORT_FORMATS = ["html", "csv", "xlsx", "all"]' in _read("src/cli/report.py")
    assert "illumio-ops report traffic --format html" in docs["docs/User_Manual.md"]
    assert "illumio-ops report traffic --format html" in docs["docs/User_Manual_zh.md"]


def test_siem_docs_do_not_list_nonexistent_flush_command():
    for path in ("docs/User_Manual.md", "docs/User_Manual_zh.md"):
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
