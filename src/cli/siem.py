from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from src.cli._output import is_json, is_quiet, echo_error, echo_warning, echo_info, echo_json
from src.cli._exit_codes import EXIT_OK, EXIT_DATAERR, EXIT_NOINPUT, EXIT_UNAVAILABLE, EXIT_SOFTWARE, EXIT_USAGE

console = Console()


@click.group("siem")
def siem_group():
    """SIEM forwarder management."""
    try:
        from src.config import ConfigManager
        from src.siem.preview import emit_preview_warning
        emit_preview_warning(ConfigManager(), context="cli_siem")
    except Exception:
        pass  # intentional fallback: warning hook must never break CLI command routing


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
        echo_error(ctx, f"Test failed for '{destination}': {exc}")
        ctx.exit(EXIT_UNAVAILABLE)
        return

    if destination not in dest_names:
        echo_error(ctx, f"Destination '{destination}' not found or disabled.")
        ctx.exit(EXIT_USAGE)
        return

    try:
        dest_cfg = next(d for d in siem_cfg.destinations if d.name == destination)
        result = send_test_event(dest_cfg)
    except Exception as exc:
        echo_error(ctx, f"Test failed for '{destination}': {exc}")
        ctx.exit(EXIT_UNAVAILABLE)
        return

    if result.ok:
        if is_json(ctx):
            echo_json(ctx, {"ok": True, "destination": destination, "latency_ms": result.latency_ms})
        elif not is_quiet(ctx):
            console.print(f"[green]✓ Test event sent to '{destination}' ({result.latency_ms} ms)[/green]")
    else:
        echo_error(ctx, f"Test failed for '{destination}': {result.error}")
        if is_json(ctx):
            echo_json(ctx, {"ok": False, "destination": destination, "details": result.error})
        ctx.exit(EXIT_UNAVAILABLE)


@siem_group.command("status")
@click.pass_context
def siem_status(ctx: click.Context):
    """Show per-destination dispatch counts."""
    try:
        from sqlalchemy import create_engine, func, select
        from sqlalchemy.orm import sessionmaker
        from src.config import ConfigManager
        from src.pce_cache.models import SiemDispatch, DeadLetter
        from src.pce_cache.schema import init_schema
        cm = ConfigManager()
        cfg = cm.models.pce_cache
        engine = create_engine(f"sqlite:///{cfg.db_path}")
        init_schema(engine)
        sf = sessionmaker(engine)
        rows = []
        with sf() as s:
            dests_q = s.execute(
                select(SiemDispatch.destination).distinct()
            ).scalars().all()
            for dest in dests_q:
                counts = {}
                for st in ["pending", "sent", "failed"]:
                    cnt = s.execute(
                        select(func.count()).select_from(SiemDispatch)
                        .where(SiemDispatch.destination == dest)
                        .where(SiemDispatch.status == st)
                    ).scalar()
                    counts[st] = cnt or 0
                dlq_cnt = s.execute(
                    select(func.count()).select_from(DeadLetter)
                    .where(DeadLetter.destination == dest)
                ).scalar() or 0
                rows.append({
                    "destination": dest,
                    "pending": counts["pending"],
                    "sent": counts["sent"],
                    "failed": counts["failed"],
                    "dlq": dlq_cnt,
                })
        if is_json(ctx):
            echo_json(ctx, rows)
            return
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
    except Exception as exc:
        echo_error(ctx, f"Error: {exc}")
        ctx.exit(EXIT_SOFTWARE)


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
            console.print(f"[green]Requeued {count} entries for '{dest}'[/green]")
    except Exception as exc:
        echo_error(ctx, f"Error: {exc}")
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
            console.print(f"[green]Purged {removed} DLQ entries for '{dest}'[/green]")
    except Exception as exc:
        echo_error(ctx, f"Error: {exc}")
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
                console.print(f"[yellow]No DLQ entries for '{dest}'[/yellow]")
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
        echo_error(ctx, f"Error: {exc}")
        ctx.exit(EXIT_SOFTWARE)
