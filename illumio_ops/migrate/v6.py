"""An installed v6 taken over by this program's version (install.sh, when the prefix already holds v6, or only the
settings and data uninstall.sh kept).

`python -m illumio_ops.migrate.v6 --root <prefix> [--env FILE]` reads the installation and changes nothing. It refuses
an older program over a newer installation (the older one would refuse the newer settings or databases at its start,
after the newer code was already gone) and settings this program would not start with. With --env it writes what
install.sh needs, as shell assignments: both versions, and which databases this program migrates at its first start,
so that install.sh backs them up first and restore-previous.sh can go back.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from illumio_ops import __version__
from illumio_ops.paths import InstallPaths
from illumio_ops.settings.store import SettingsInvalid, validate_settings
from illumio_ops.store.db import APP_MIGRATIONS, _migrations
from illumio_ops.store.flowdb.db import MIGRATIONS_PACKAGE as FLOW_MIGRATIONS

EX_DATAERR, EX_NOINPUT = 65, 66
_VERSION = re.compile(r'^__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', re.MULTILINE)


class Refused(Exception):
    """This program must not take the installation over; the message says why."""


@dataclass(frozen=True)
class Plan:
    installed: str     # "" when only the settings and data are there (uninstall.sh kept them)
    bundle: str
    app_pending: int   # migrations this program applies to data/app.sqlite at its first start
    flow_pending: int  # the same for data/flows.sqlite


def _parse(version: str) -> tuple[int, int, int]:
    m = _VERSION.search(f'__version__ = "{version}"')
    if not m:
        raise Refused(f"cannot read the version {version!r}")
    return int(m[1]), int(m[2]), int(m[3])


def installed_version(root: Path) -> str:
    """The installed program's version, read from its source (it is never imported: it may be a different build)."""
    init = root / "illumio_ops" / "__init__.py"
    try:
        m = _VERSION.search(init.read_text(encoding="utf-8"))
    except OSError:
        m = None
    if not m:
        raise Refused(f"{init} does not say which version is installed")
    return f"{m[1]}.{m[2]}.{m[3]}"


def _pending(db: Path, package: str) -> int:
    """How many of this program's migrations the database lacks; a database newer than this program is refused."""
    if not db.exists():
        return 0
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()
    latest = len(_migrations(package))
    if current > latest:
        raise Refused(f"{db} is at schema {current}, newer than this program ({latest})")
    return latest - current


def plan(root: Path) -> Plan:
    paths = InstallPaths(root)
    installed = installed_version(root) if (root / "illumio_ops").exists() else ""
    if installed and _parse(__version__) < _parse(installed):
        raise Refused(f"{root} runs {installed}, newer than this bundle ({__version__}); an older version is not "
                      "installed over a newer one")
    try:
        data = json.loads(paths.settings_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused(f"cannot read {paths.settings_file}: {exc}") from None
    try:
        validate_settings(data)
    except SettingsInvalid as exc:
        fields = ", ".join(loc for loc, _ in exc.errors)
        raise Refused(f"{paths.settings_file} would not start with {__version__} (fields: {fields})") from None
    return Plan(installed=installed, bundle=__version__, app_pending=_pending(paths.app_db, APP_MIGRATIONS),
                flow_pending=_pending(paths.flows_db, FLOW_MIGRATIONS))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m illumio_ops.migrate.v6")
    ap.add_argument("--root", type=Path, required=True, help="the installed v6 directory")
    ap.add_argument("--env", type=Path, help="write the plan here as shell assignments for install.sh")
    args = ap.parse_args(argv)
    if not (args.root / "config" / "settings.json").is_file():
        sys.stderr.write(f"{args.root} holds no v6 settings (config/settings.json)\n")
        return EX_NOINPUT
    try:
        p = plan(args.root)
    except Refused as exc:
        sys.stderr.write(f"{exc}; nothing was changed\n")
        return EX_DATAERR
    same = " (the same version: its files are installed again)" if p.installed == p.bundle else ""
    lines = ([f"Upgrade {args.root} from {p.installed} to {p.bundle}{same}."] if p.installed else
             [f"Install {p.bundle} into {args.root} again, with the settings and data an uninstall kept there."])
    lines.append("Kept as they are: settings, data, reports, logs and certificates.")
    lines += [f"data/{name}: {n} schema change(s) at the first start; a copy is kept first so the previous version "
              "can come back." for name, n in (("app.sqlite", p.app_pending), ("flows.sqlite", p.flow_pending)) if n]
    sys.stdout.write("".join(f"{line}\n" for line in lines))
    if args.env:
        args.env.write_text("".join(f"{k}={shlex.quote(str(v))}\n" for k, v in (
            ("OLD_VERSION", p.installed), ("NEW_VERSION", p.bundle),
            ("APP_PENDING", p.app_pending), ("FLOW_PENDING", p.flow_pending))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
