from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.i18n import get_messages
from src.report.exporters.report_i18n import STRINGS as REPORT_STRINGS

GUI_PATTERNS = [
    re.compile(r'data-i18n=["\']([A-Za-z0-9_&]+)["\']'),
    re.compile(r"""_translations\[['"]([A-Za-z0-9_&]+)['"]\]"""),
    re.compile(r't\(\s*["\']([A-Za-z0-9_&]+)["\']'),
]

SUSPECT_TOKENS = (
    "Title",
    "Guide",
    "Latest Traffic Report Summary",
    "Workload Search",
    "Rule Scheduler",
    "Report Schedules",
    "Top 10 Widgets",
    "Rpt ",
)


def iter_files() -> list[Path]:
    return list(SRC.rglob("*.py")) + list(SRC.rglob("*.html")) + list(SRC.rglob("*.js"))


def collect_keys() -> set[str]:
    keys: set[str] = set()
    for path in iter_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in GUI_PATTERNS:
            keys.update(pattern.findall(text))
    return keys


def audit_gui_keys() -> list[tuple[str, str]]:
    messages = get_messages("zh_TW")
    findings: list[tuple[str, str]] = []
    for key in sorted(collect_keys()):
        if not key.startswith(("gui_", "sched_", "rs_", "wgs_", "login_", "cli_", "main_", "settings_")):
            continue
        value = str(messages.get(key, ""))
        if not value or any(token in value for token in SUSPECT_TOKENS):
            findings.append((key, value))
    return findings


def audit_report_keys() -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for key, value in sorted(REPORT_STRINGS.items()):
        zh = value.get("zh_TW", "") if isinstance(value, dict) else str(value)
        if not zh or any(token in zh for token in SUSPECT_TOKENS):
            findings.append((key, zh))
    return findings


def print_findings(title: str, findings: list[tuple[str, str]]) -> None:
    print(f"[{title}] {len(findings)} issue(s)")
    for key, value in findings:
        print(f"{key}: {value}")


def main() -> int:
    gui_findings = audit_gui_keys()
    report_findings = audit_report_keys()
    print_findings("GUI", gui_findings)
    print_findings("REPORT", report_findings)
    return 1 if gui_findings or report_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
