"""python -m illumio_ops.crosscheck {events|alerts|reports|all} --out DIR [--days N] [--margin-minutes M] [--root PATH]

Runs beside the service: it takes no service lock, opens the databases read-only and creates nothing but --out.
Exit codes: 0 nothing inconsistent (unchecked items are listed, they are not a pass); 1 something inconsistent;
2 the settings cannot be read, the PCE is not configured or cannot be reached, the results cannot be written (and
argparse's usage errors).

The one module in this package allowed to print.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from illumio_ops import __version__
from illumio_ops.crosscheck import io
from illumio_ops.crosscheck.model import STATUSES, Finding, Run
from illumio_ops.paths import resolve_paths
from illumio_ops.pce.client import (
    PceBudgetExhausted,
    PceNotConfigured,
    PceTransportError,
)
from illumio_ops.pce.timefmt import pce_time
from illumio_ops.settings.schema import Settings
from illumio_ops.settings.store import SettingsInvalid, SettingsStore

EXIT_OK = 0
EXIT_INCONSISTENT = 1
EXIT_CANNOT_RUN = 2
DAYS_MIN, DAYS_MAX = 1, 90
AREAS = ("events", "alerts", "reports")


def _not_implemented(area: str) -> Callable[[Run], list[Finding]]:
    def check(run: Run) -> list[Finding]:
        return [Finding(area, f"{area} check", "unchecked", "not implemented yet")]
    return check


# area -> check; later tasks replace the placeholders (tests swap entries in).
CHECKS: dict[str, Callable[[Run], list[Finding]]] = {area: _not_implemented(area) for area in AREAS}


def _days(raw: str) -> int:
    try:
        n = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {raw!r}") from None
    if not DAYS_MIN <= n <= DAYS_MAX:
        raise argparse.ArgumentTypeError(f"must be {DAYS_MIN}–{DAYS_MAX}, not {n}")
    return n


def _minutes(raw: str) -> int:
    try:
        n = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {raw!r}") from None
    if n < 0:
        raise argparse.ArgumentTypeError(f"must be 0 or more, not {n}")
    return n


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m illumio_ops.crosscheck",
                                 description="Compare events, event-rule alerts and report numbers with the PCE.")
    ap.add_argument("command", choices=(*AREAS, "all"))
    ap.add_argument("--days", type=_days, default=7, help=f"length of the period ({DAYS_MIN}–{DAYS_MAX}, default 7)")
    ap.add_argument("--margin-minutes", type=_minutes, default=30,
                    help="the period ends this long before now, for late-arriving PCE data (default 30)")
    ap.add_argument("--out", type=Path, required=True, help="output directory (created when missing)")
    ap.add_argument("--root", type=Path, default=None, help="install root (default: as the service resolves it)")
    return ap.parse_args(argv)


def period(now: datetime, days: int, margin_minutes: int) -> tuple[datetime, datetime]:
    """[start, end] in UTC: end = now − margin, start = end − days (whole seconds, as the PCE takes them)."""
    end = now.astimezone(UTC).replace(microsecond=0) - timedelta(minutes=margin_minutes)
    return end - timedelta(days=days), end


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _load_settings(store: SettingsStore) -> Settings | None:
    try:
        return store.load()
    except FileNotFoundError:
        _err(f"no settings file at {store.path}")
    except SettingsInvalid as exc:
        _err(f"the settings file {store.path} is not valid:")
        for loc, msg in exc.errors:  # field paths and reasons, never values
            _err(f"  {loc or '(file)'}: {msg}")
    except OSError as exc:
        _err(f"cannot read the settings file {store.path}: {exc.strerror or type(exc).__name__}")
    return None


def main(argv: list[str] | None = None, *, now: datetime | None = None) -> int:
    args = parse_args(argv)
    paths = resolve_paths(args.root)
    settings = _load_settings(SettingsStore(paths.settings_file))
    if settings is None:
        return EXIT_CANNOT_RUN
    try:
        client = io.pce(settings)
    except PceNotConfigured:
        _err(f"the PCE connection is not configured in {paths.settings_file} (URL, org ID, API key and secret)")
        return EXIT_CANNOT_RUN
    started = now if now is not None else datetime.now(UTC)
    start, end = period(started, args.days, args.margin_minutes)
    areas = AREAS if args.command == "all" else (args.command,)
    run = Run(paths=paths, settings=settings, pce=client, start=start, end=end)
    findings: list[Finding] = []
    try:
        for area in areas:
            findings += CHECKS[area](run)
    except PceTransportError as exc:
        _err(f"the PCE at {settings.pce.url} cannot be reached ({exc.kind} on {exc.path}); nothing was written")
        return EXIT_CANNOT_RUN
    except PceBudgetExhausted as exc:
        _err(f"no PCE request budget left for {exc}; nothing was written")
        return EXIT_CANNOT_RUN
    finally:
        client.close()
    meta = {
        "command": args.command,
        "period_start": pce_time(start),
        "period_end": pce_time(end),
        "days": args.days,
        "margin_minutes": args.margin_minutes,
        "pce_url": settings.pce.url,
        "org_id": settings.pce.org_id,
        "version": __version__,
        "generated_at": pce_time(started),
        "limitations": [
            f"The period ends {args.margin_minutes} minutes before the run, to leave room for late-arriving PCE data.",
        ],
    }
    try:
        args.out.mkdir(parents=True, exist_ok=True)
        io.write(args.out, findings, meta)
    except OSError as exc:
        _err(f"cannot write the results to {args.out}: {exc.strerror or type(exc).__name__}")
        return EXIT_CANNOT_RUN
    counts = {s: sum(1 for f in findings if f.status == s) for s in STATUSES}
    print(f"{pce_time(start)} to {pce_time(end)}: " + ", ".join(f"{s} {counts[s]}" for s in STATUSES))
    print(f"wrote {args.out / 'report.md'} and {args.out / 'findings.json'}")
    return EXIT_INCONSISTENT if counts["inconsistent"] else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
