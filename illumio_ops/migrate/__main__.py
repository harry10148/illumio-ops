"""`python -m illumio_ops.migrate --from <5.x root> --report-only [--lang zh_TW]`

Reads the 5.x settings and prints what the upgrade would do with every key. Writes nothing.
(The upgrade itself is wired into install.sh in P6.)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from illumio_ops.domain.values import Language
from illumio_ops.migrate.report import render
from illumio_ops.migrate.v5 import migrate_v5, read_v5
from illumio_ops.settings.store import SettingsInvalid


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m illumio_ops.migrate")
    ap.add_argument("--from", dest="source", type=Path, required=True, help="the 5.x installation directory")
    ap.add_argument("--report-only", action="store_true", help="print the report and change nothing")
    ap.add_argument("--lang", choices=[lang.value for lang in Language], default="en")
    args = ap.parse_args(argv)
    if not args.report_only:
        sys.stderr.write("only --report-only is available in this version\n")
        return 64
    try:
        raw = read_v5(args.source)
    except FileNotFoundError:
        sys.stderr.write(f"no 5.x settings found under {args.source}/config/config.json\n")
        return 66
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 65
    try:
        _settings, report = migrate_v5(raw)
    except SettingsInvalid as exc:
        sys.stderr.write("the 5.x values cannot become valid v6 settings:\n")
        sys.stderr.write("".join(f"  {loc}: {msg}\n" for loc, msg in exc.errors))
        return 65
    sys.stdout.write(render(report, Language(args.lang)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
