from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

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
def siem_test(destination: str):
    """Send a synthetic test event to DESTINATION and report success/fail."""
    from src.config import ConfigManager
    from src.siem.tester import send_test_event

    try:
        cm = ConfigManager()
        siem_cfg = cm.models.siem
        dest_names = [d.name for d in siem_cfg.destinations if d.enabled]
        if destination not in dest_names:
            console.print(f"[red]Destination '{destination}' not found or disabled.[/red]")
            raise SystemExit(1)
        dest_cfg = next(d for d in siem_cfg.destinations if d.name == destination)
        result = send_test_event(dest_cfg)
    except SystemExit:
        raise
    except Exception as exc:
        console.print(f"[red]✗ Test failed for '{destination}': {exc}[/red]")
        raise SystemExit(1)

    if result.ok:
        console.print(f"[green]✓ Test event sent to '{destination}' ({result.latency_ms} ms)[/green]")
    else:
        console.print(f"[red]✗ Test failed for '{destination}': {result.error}[/red]")
        raise SystemExit(1)


@siem_group.command("status")
def siem_status():
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
        table = Table(title="SIEM Dispatch Status")
        table.add_column("Destination")
        table.add_column("Pending", justify="right")
        table.add_column("Sent", justify="right")
        table.add_column("Failed", justify="right")
        table.add_column("DLQ", justify="right")
        with sf() as s:
            for status in ["pending", "sent", "failed"]:
                pass  # queried per-dest below
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
                table.add_row(dest, str(counts["pending"]), str(counts["sent"]),
                              str(counts["failed"]), str(dlq_cnt))
        console.print(table)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise SystemExit(1)


@siem_group.command("replay")
@click.option("--dest", required=True, help="Destination name")
@click.option("--limit", default=100, show_default=True, help="Max DLQ entries to replay")
def siem_replay(dest: str, limit: int):
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
        console.print(f"[green]Requeued {count} entries for '{dest}'[/green]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise SystemExit(1)


@siem_group.command("purge")
@click.option("--dest", required=True, help="Destination name")
@click.option("--older-than", default=30, show_default=True, help="Purge entries older than N days")
def siem_purge(dest: str, older_than: int):
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
        console.print(f"[green]Purged {removed} DLQ entries for '{dest}'[/green]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise SystemExit(1)


@siem_group.command("dlq")
@click.option("--dest", required=True, help="Destination name")
@click.option("--limit", default=50, show_default=True, help="Max entries to show")
def siem_dlq(dest: str, limit: int):
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
            console.print(f"[yellow]No DLQ entries for '{dest}'[/yellow]")
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
        console.print(f"[red]Error: {exc}[/red]")
        raise SystemExit(1)
