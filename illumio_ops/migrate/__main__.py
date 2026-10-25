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
    result = migrate_v5(raw)
    sys.stdout.write(render(result.report, Language(args.lang)))
    if result.blocking:
        sys.stderr.write("these 5.x values cannot become v6 settings; nothing would be migrated:\n")
        sys.stderr.write("".join(f"  {loc}: {msg}\n" for loc, msg in result.blocking))
        return 65
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
