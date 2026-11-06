"""`python -m illumio_ops.migrate --from <5.x root> (--report-only | --write --root <v6 root>) [--lang zh_TW]`

--report-only prints what the upgrade would do with every key and writes nothing. --write (install.sh runs it after
stopping 5.x) writes the migrated settings, the TLS files and the handover into a new v6 root, never into an existing
one, and never changes the 5.x installation.
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from illumio_ops.domain.values import Language
from illumio_ops.migrate.report import render
from illumio_ops.migrate.v5 import migrate_v5, not_carried_files, read_v5
from illumio_ops.migrate.v5_alerts import read_v5_rules
from illumio_ops.migrate.v5_write import (
    REPORT_FILE,
    AlreadyInstalled,
    MigrationBlocked,
    UnsafeSource,
    upgrade,
)

EX_DATAERR, EX_NOINPUT, EX_CANTCREAT, EX_USAGE = 65, 66, 73, 64


def _blocking(items: list[tuple[str, str]]) -> None:
    sys.stderr.write("these 5.x values cannot become v6 settings; nothing would be migrated:\n")
    sys.stderr.write("".join(f"  {loc}: {msg}\n" for loc, msg in items))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m illumio_ops.migrate")
    ap.add_argument("--from", dest="source", type=Path, required=True, help="the 5.x installation directory")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--report-only", action="store_true", help="print the report and change nothing")
    mode.add_argument("--write", action="store_true", help="write the v6 settings and handover into --root")
    ap.add_argument("--root", type=Path, help="the new v6 root (with --write)")
    ap.add_argument("--original-root", type=Path, help="where 5.x ran, when it has been moved to --from (with --write)")
    ap.add_argument("--lang", choices=[lang.value for lang in Language], default="en")
    args = ap.parse_args(argv)
    lang = Language(args.lang)
    if args.write and args.root is None:
        sys.stderr.write("--write needs --root\n")
        return EX_USAGE
    try:
        raw = read_v5(args.source)
    except FileNotFoundError:
        sys.stderr.write(f"no 5.x settings found under {args.source}/config/config.json\n")
        return EX_NOINPUT
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return EX_DATAERR
    if args.report_only:
        rules, legacy_channels = read_v5_rules(args.source)
        result = migrate_v5(raw, rules=rules, legacy_channels=legacy_channels)
        result.report.items.extend(not_carried_files(args.source))
        sys.stdout.write(render(result.report, lang))
        if result.blocking:
            _blocking(result.blocking)
            return EX_DATAERR
        return 0
    try:
        lines = upgrade(args.source, args.root, now=datetime.now(UTC).replace(microsecond=0), lang=lang,
                        original_root=args.original_root)
    except AlreadyInstalled as exc:
        sys.stderr.write(f"{exc} already exists; nothing was changed\n")
        return EX_CANTCREAT
    except MigrationBlocked as exc:
        _blocking(exc.result.blocking)
        return EX_DATAERR
    except UnsafeSource as exc:
        sys.stderr.write(f"{exc} is a link; the upgrade does not follow links in the 5.x directory. Replace it with "
                         "the file itself and run again; nothing was changed\n")
        return EX_DATAERR
    sys.stdout.write("".join(f"{line}\n" for line in lines))
    sys.stdout.write(f"{args.root / 'logs' / REPORT_FILE}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
