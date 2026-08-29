"""Capture pre-migration conservation baselines for the v2 report shell.

Run this on a commit where the named report types have NOT yet been moved onto
the v2 shell. It renders each type from ``tests/report_shell/fixtures.BUILDERS``
and records what that document contained, so the migration commit can be proven
to have rearranged the markup without losing text or dropping a table/chart.

    python scripts/capture_report_baselines.py --types traffic,security_risk

writes ``tests/report_shell/baselines/<type>.json``:

    {"report_type": ...,
     "captured_at_commit": "<git rev-parse HEAD>",
     "leaves": [... sorted normalised text nodes ...],
     "table_count": N,
     "chart_count": M}

``captured_at_commit`` is the audit trail: a baseline captured on the same
commit as the migration itself proves nothing, and the recorded SHA is what
makes that checkable after the fact.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bs4 import BeautifulSoup  # noqa: E402

from tests.report_shell.conservation import conservation_text  # noqa: E402
from tests.report_shell.fixtures import BUILDERS  # noqa: E402

BASELINE_DIR = ROOT / "tests" / "report_shell" / "baselines"


def _head_sha() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()


def capture(report_type: str, commit: str) -> dict:
    html = BUILDERS[report_type]()
    soup = BeautifulSoup(html, "html.parser")
    leaves, _ = conservation_text(html)
    return {
        "report_type": report_type,
        "captured_at_commit": commit,
        "leaves": sorted(leaves),
        "table_count": len(soup.select(".report-table")),
        "chart_count": len(soup.select("figure.chart-static")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--types", required=True,
                        help="comma-separated report types, e.g. traffic,audit")
    args = parser.parse_args(argv)

    requested = [t.strip() for t in args.types.split(",") if t.strip()]
    unknown = [t for t in requested if t not in BUILDERS]
    if unknown:
        parser.error(f"unknown report type(s): {', '.join(unknown)}; "
                     f"known: {', '.join(sorted(BUILDERS))}")

    commit = _head_sha()
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    for report_type in requested:
        data = capture(report_type, commit)
        path = BASELINE_DIR / f"{report_type}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        print(f"{report_type}: {len(data['leaves'])} leaves, "
              f"{data['table_count']} tables, {data['chart_count']} charts "
              f"→ {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
