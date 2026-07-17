from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table
from sqlalchemy.exc import OperationalError

from src.cli._output import is_json, is_quiet, echo_error, echo_warning, echo_info, echo_json
from src.cli._exit_codes import EXIT_OK, EXIT_DATAERR, EXIT_NOINPUT, EXIT_UNAVAILABLE, EXIT_SOFTWARE, EXIT_USAGE
from src.i18n import t

console = Console()


@click.group("siem")
def siem_group():
    """SIEM forwarder management."""


@siem_group.command("test")
@click.argument("destination")
@click.pass_context
def siem_test(ctx: click.Context, destination: str):
    """Send a synthetic test event to DESTINATION and report success/fail."""
    from src.config import ConfigManager
    from src.siem.tester import send_test_event

    # Validate destination before entering the exception-catching block so
    # that ctx.exit(EXIT_USAGE) is not swallowed by the broad except below.
    try:
        cm = ConfigManager()
        siem_cfg = cm.models.siem
        dest_names = [d.name for d in siem_cfg.destinations if d.enabled]
    except Exception as exc:
        echo_error(ctx, t("cli_siem_test_fail", dest=destination, error=exc))
        ctx.exit(EXIT_UNAVAILABLE)
        return

    if destination not in dest_names:
        echo_error(ctx, t("cli_siem_err_dest_not_found", destination=destination))
        ctx.exit(EXIT_USAGE)
        return

    try:
        dest_cfg = next(d for d in siem_cfg.destinations if d.name == destination)
        result = send_test_event(dest_cfg)
    except Exception as exc:
        echo_error(ctx, t("cli_siem_test_fail", dest=destination, error=exc))
        ctx.exit(EXIT_UNAVAILABLE)
        return

    if result.ok:
        if is_json(ctx):
            echo_json(ctx, {"ok": True, "destination": destination, "latency_ms": result.latency_ms})
        elif not is_quiet(ctx):
            console.print(f"[green]{t('cli_siem_test_sent', destination=destination, latency=result.latency_ms)}[/green]")
    else:
        echo_error(ctx, t("cli_siem_test_fail", dest=destination, error=result.error))
        if is_json(ctx):
            echo_json(ctx, {"ok": False, "destination": destination, "details": result.error})
        ctx.exit(EXIT_UNAVAILABLE)


@siem_group.command("status")
@click.pass_context
def siem_status(ctx: click.Context):
    """Show per-destination dispatch counts.

    The destination set is the union of (a) configured destinations from
    ``cm.models.siem.destinations`` and (b) destinations observed in the
    ``SiemDispatch`` table. This matches what the WebUI integrations tab
    shows, which merges ``/api/siem/destinations`` with ``/api/siem/status``
    on the client side — see UX_Review §11.2.
    """
    try:
        from sqlalchemy import create_engine, func, select
        from sqlalchemy.orm import sessionmaker
        from src.config import ConfigManager
        from src.pce_cache.models import SiemDispatch, DeadLetter
        from src.pce_cache.schema import init_schema
        cm = ConfigManager()
        cfg = cm.models.pce_cache
        # Seed with configured destinations so they appear even with zero
        # dispatch rows, mirroring the WebUI's merged view.
        try:
            configured_names = [d.name for d in cm.models.siem.destinations]
        except Exception:
            configured_names = []
        engine = create_engine(f"sqlite:///{cfg.db_path}")
        init_schema(engine)
        sf = sessionmaker(engine)
        rows = []
        with sf() as s:
            db_dests = s.execute(
                select(SiemDispatch.destination).distinct()
            ).scalars().all()
            # Preserve config order, then append any DB-only destinations.
            seen = set()
            merged: list[str] = []
            for name in list(configured_names) + list(db_dests):
                if name in seen:
                    continue
                seen.add(name)
                merged.append(name)
            # 一次 GROUP BY 取回所有 destination x status 的計數，取代原本每個
            # destination 各 4 個 count 查詢（destinations 多時查詢數會線性成長）。
            status_counts: dict[tuple[str, str], int] = {}
            for dest, st, cnt in s.execute(
                select(SiemDispatch.destination, SiemDispatch.status, func.count())
                .group_by(SiemDispatch.destination, SiemDispatch.status)
            ):
                status_counts[(dest, st)] = cnt
            dlq_counts: dict[str, int] = {}
            for dest, cnt in s.execute(
                select(DeadLetter.destination, func.count())
                .group_by(DeadLetter.destination)
            ):
                dlq_counts[dest] = cnt
            for dest in merged:
                rows.append({
                    "destination": dest,
                    "pending": status_counts.get((dest, "pending"), 0),
                    "sent": status_counts.get((dest, "sent"), 0),
                    "failed": status_counts.get((dest, "failed"), 0),
                    "dlq": dlq_counts.get(dest, 0),
                })
        if is_json(ctx):
            echo_json(ctx, rows)
            return
        if not rows:
            if not is_quiet(ctx):
                console.print(f"[dim]{t('cli_siem_no_records')}[/dim]")
            return
        _render_status_table(rows)
    except OperationalError as exc:
        if not _is_first_run_db_error(exc):
            # Schema mismatch / corruption — surface it; zeros would lie.
            echo_error(ctx, str(exc))
            ctx.exit(EXIT_SOFTWARE)
        # SIEM cache db not initialized — first-run / pre-collect path.
        # Still surface configured destinations with zero counts so the CLI
        # agrees with the WebUI's configured-destinations view.
        try:
            from src.config import ConfigManager
            cm = ConfigManager()
            configured_names = [d.name for d in cm.models.siem.destinations]
        except Exception:
            configured_names = []
        rows = [
            {"destination": n, "pending": 0, "sent": 0, "failed": 0, "dlq": 0}
            for n in configured_names
        ]
        if is_json(ctx):
            echo_json(ctx, rows)
            return
        if not rows:
            if not is_quiet(ctx):
                console.print(f"[dim]{t('cli_siem_no_records')}[/dim]")
            return
        _render_status_table(rows)
    except Exception as exc:
        echo_error(ctx, str(exc))
        ctx.exit(EXIT_SOFTWARE)


def _is_first_run_db_error(exc: OperationalError) -> bool:
    """True only when the OperationalError means the cache DB doesn't exist
    yet (first run before any collection) — the sole case where a zero-count
    fallback is honest. Schema mismatches ("no such column") and corruption
    must surface as errors instead of silently rendering zeros."""
    msg = str(exc).lower()
    return "no such table" in msg or "unable to open database file" in msg


def _render_status_table(rows: list[dict]) -> None:
    """Render the SIEM dispatch-status table for ``rows`` to the console.

    Shared by the success branch and the OperationalError fallback so the two
    paths cannot drift apart (e.g. dropping the empty-state hint as fixed in
    follow-up to d217646).
    """
    table = Table(title="SIEM Dispatch Status")
    table.add_column("Destination")
    table.add_column("Pending", justify="right")
    table.add_column("Sent", justify="right")
    table.add_column("Failed", justify="right")
    table.add_column("DLQ", justify="right")
    for r in rows:
        table.add_row(r["destination"], str(r["pending"]), str(r["sent"]),
                      str(r["failed"]), str(r["dlq"]))
    console.print(table)


@siem_group.command("replay")
@click.option("--dest", required=True, help="Destination name")
@click.option("--limit", default=100, show_default=True, help="Max DLQ entries to replay")
@click.pass_context
def siem_replay(ctx: click.Context, dest: str, limit: int):
    """Requeue DLQ entries for DEST as pending dispatch rows."""
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.config import ConfigManager
        from src.pce_cache.schema import init_schema
        from src.siem.dlq import DeadLetterQueue
        cm = ConfigManager()
        cfg = cm.models.pce_cache
        engine = create_engine(f"sqlite:///{cfg.db_path}")
        init_schema(engine)
        sf = sessionmaker(engine)
        dlq = DeadLetterQueue(sf)
        count = dlq.replay(dest, limit=limit)
        if is_json(ctx):
            echo_json(ctx, {"ok": True, "destination": dest, "requeued": count})
        elif not is_quiet(ctx):
            console.print(f"[green]{t('cli_siem_replayed', count=count, dest=dest)}[/green]")
    except OperationalError as exc:
        if not _is_first_run_db_error(exc):
            echo_error(ctx, str(exc))
            ctx.exit(EXIT_SOFTWARE)
        # SIEM cache db not initialized — replay needs existing dispatch records.
        echo_error(ctx, t("cli_siem_err_no_replay_data", dest=dest))
        ctx.exit(1)
    except Exception as exc:
        echo_error(ctx, str(exc))
        ctx.exit(EXIT_SOFTWARE)


@siem_group.command("purge")
@click.option("--dest", required=True, help="Destination name")
@click.option("--older-than", default=30, show_default=True, help="Purge entries older than N days")
@click.pass_context
def siem_purge(ctx: click.Context, dest: str, older_than: int):
    """Delete DLQ entries for DEST older than N days."""
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.config import ConfigManager
        from src.pce_cache.schema import init_schema
        from src.siem.dlq import DeadLetterQueue
        cm = ConfigManager()
        cfg = cm.models.pce_cache
        engine = create_engine(f"sqlite:///{cfg.db_path}")
        init_schema(engine)
        sf = sessionmaker(engine)
        dlq = DeadLetterQueue(sf)
        removed = dlq.purge(dest, older_than_days=older_than)
        if is_json(ctx):
            echo_json(ctx, {"ok": True, "destination": dest, "removed": removed})
        elif not is_quiet(ctx):
            console.print(f"[green]{t('cli_siem_purged', count=removed, dest=dest)}[/green]")
    except Exception as exc:
        echo_error(ctx, str(exc))
        ctx.exit(EXIT_SOFTWARE)


@siem_group.command("dlq")
@click.option("--dest", required=True, help="Destination name")
@click.option("--limit", default=50, show_default=True, help="Max entries to show")
@click.pass_context
def siem_dlq(ctx: click.Context, dest: str, limit: int):
    """List DLQ entries for DEST."""
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.config import ConfigManager
        from src.pce_cache.schema import init_schema
        from src.siem.dlq import DeadLetterQueue
        cm = ConfigManager()
        cfg = cm.models.pce_cache
        engine = create_engine(f"sqlite:///{cfg.db_path}")
        init_schema(engine)
        sf = sessionmaker(engine)
        dlq = DeadLetterQueue(sf)
        entries = dlq.list_entries(dest, limit=limit)
        if not entries:
            if not is_quiet(ctx):
                console.print(f"[yellow]{t('cli_siem_no_dlq', dest=dest)}[/yellow]")
            if is_json(ctx):
                echo_json(ctx, [])
            return
        if is_json(ctx):
            echo_json(ctx, [
                {
                    "id": e.id,
                    "source_table": e.source_table,
                    "retries": e.retries,
                    "last_error": e.last_error,
                    "quarantined_at": str(e.quarantined_at),
                }
                for e in entries
            ])
            return
        table = Table(title=f"DLQ — {dest}")
        table.add_column("ID", justify="right")
        table.add_column("Source")
        table.add_column("Retries", justify="right")
        table.add_column("Error")
        table.add_column("Quarantined At")
        for e in entries:
            table.add_row(str(e.id), e.source_table, str(e.retries),
                          e.last_error[:60], str(e.quarantined_at)[:19])
        console.print(table)
    except Exception as exc:
        echo_error(ctx, str(exc))
        ctx.exit(EXIT_SOFTWARE)
