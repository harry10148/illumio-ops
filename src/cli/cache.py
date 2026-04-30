"""illumio-ops cache subcommands — backfill, status, retention."""
from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

console = Console()


def _get_cache_config() -> dict:
    """Load cache config from ConfigManager; return defaults if unavailable."""
    try:
        from src.config import ConfigManager
        cm = ConfigManager()
        cm.load()
        return cm.config.get("pce_cache", {})
    except Exception:
        return {}


def _get_db_session_factory():
    """Return a SQLAlchemy sessionmaker from config, or None if not configured."""
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.config import ConfigManager
        from src.pce_cache.schema import init_schema
        cm = ConfigManager()
        cm.load()
        db_path = cm.config.get("pce_cache", {}).get("db_path", "config/pce_cache.sqlite")
        engine = create_engine(f"sqlite:///{db_path}")
        init_schema(engine)
        return sessionmaker(engine)
    except Exception:
        return None


@click.group("cache")
def cache_group():
    """PCE cache management — backfill, status, retention."""


@cache_group.command("backfill")
@click.option("--source", type=click.Choice(["events", "traffic"]), required=True)
@click.option("--since", required=True, help="Start date YYYY-MM-DD")
@click.option("--until", default=None, help="End date YYYY-MM-DD (default: today)")
def cache_backfill(source: str, since: str, until: str | None):
    """Backfill the PCE cache from the API for a historical date range."""
    from datetime import datetime, timezone
    import sys
    try:
        since_dt = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        console.print(f"[red]Invalid --since date: {since!r} (expected YYYY-MM-DD)[/red]")
        sys.exit(1)
    if until:
        try:
            until_dt = datetime.strptime(until, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            console.print(f"[red]Invalid --until date: {until!r} (expected YYYY-MM-DD)[/red]")
            sys.exit(1)
    else:
        until_dt = datetime.now(timezone.utc)

    sf = _get_db_session_factory()
    if sf is None:
        console.print("[red]Cannot connect to cache database. Is pce_cache.db_path configured?[/red]")
        sys.exit(1)
    try:
        from src.config import ConfigManager
        from src.api_client import ApiClient
        cm = ConfigManager()
        cm.load()
        api = ApiClient(cm)
        from src.pce_cache.backfill import BackfillRunner
        runner = BackfillRunner(api, sf)
        console.print(f"Backfilling [bold]{source}[/bold] from {since} to {until or 'now'}…")
        if source == "events":
            result = runner.run_events(since_dt, until_dt)
        else:
            result = runner.run_traffic(since_dt, until_dt)
        console.print(f"[green]Done:[/green] {result.inserted} inserted, {result.duplicates} duplicates, {result.elapsed_seconds:.1f}s")
    except Exception as exc:
        console.print(f"[red]Backfill failed: {exc}[/red]")
        sys.exit(1)


@cache_group.command("status")
def cache_status():
    """Show cache row counts and last-sync timestamps."""
    sf = _get_db_session_factory()
    if sf is None:
        console.print("[yellow]Cache database not configured.[/yellow]")
        return
    try:
        from sqlalchemy import func, select
        from src.pce_cache.models import PceEvent, PceTrafficFlowRaw, PceTrafficFlowAgg
        table = Table("Source", "Rows", "Last ingested")
        with sf() as s:
            for model, label in [
                (PceEvent, "events"),
                (PceTrafficFlowRaw, "traffic_raw"),
                (PceTrafficFlowAgg, "traffic_agg"),
            ]:
                count = s.execute(select(func.count()).select_from(model)).scalar() or 0
                last = s.execute(
                    select(func.max(model.ingested_at))
                ).scalar()
                table.add_row(label, str(count), str(last or "—"))
        console.print(table)
    except Exception as exc:
        console.print(f"[red]Status query failed: {exc}[/red]")


@cache_group.command("retention")
@click.option("--run", "do_run", is_flag=True, default=False, help="Execute retention purge now.")
def cache_retention(do_run: bool):
    """Show configured cache retention policy, or run it immediately with --run."""
    cfg = _get_cache_config()
    table = Table("Setting", "Days")
    table.add_row("events_retention_days", str(cfg.get("events_retention_days", 90)))
    table.add_row("traffic_raw_retention_days", str(cfg.get("traffic_raw_retention_days", 7)))
    table.add_row("traffic_agg_retention_days", str(cfg.get("traffic_agg_retention_days", 365)))
    console.print(table)

    if not do_run:
        return

    import sys
    sf = _get_db_session_factory()
    if sf is None:
        console.print("[red]Cannot connect to cache database. Is pce_cache.db_path configured?[/red]")
        sys.exit(1)
    try:
        from src.pce_cache.retention import RetentionWorker
        worker = RetentionWorker(sf)
        result = worker.run_once(
            events_days=int(cfg.get("events_retention_days", 90)),
            traffic_raw_days=int(cfg.get("traffic_raw_retention_days", 7)),
            traffic_agg_days=int(cfg.get("traffic_agg_retention_days", 365)),
        )
        result_table = Table("Table", "Rows deleted")
        for key, count in result.items():
            result_table.add_row(key, str(count))
        console.print(result_table)
        console.print("[green]Retention purge complete.[/green]")
    except Exception as exc:
        console.print(f"[red]Retention failed: {exc}[/red]")
        sys.exit(1)
