"""illumio-ops cache subcommands — backfill, status, retention."""
from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from src.cli._global_flags import get_global_flags
from src.cli._output import (
    echo_error,
    echo_info,
    echo_json,
    echo_warning,
    is_json,
    is_quiet,
    echo_verbose,
)
from src.cli._exit_codes import (
    EXIT_OK,
    EXIT_DATAERR,
    EXIT_NOINPUT,
    EXIT_UNAVAILABLE,
    EXIT_SOFTWARE,
)

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
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit result as JSON.")
@click.pass_context
def cache_backfill(ctx: click.Context, source: str, since: str, until: str | None, json_output: bool):
    """Backfill the PCE cache from the API for a historical date range."""
    from datetime import datetime, timezone
    try:
        since_dt = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        echo_error(ctx, f"Invalid --since date: {since!r} (expected YYYY-MM-DD)")
        ctx.exit(EXIT_DATAERR)
        return
    if until:
        try:
            until_dt = datetime.strptime(until, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            echo_error(ctx, f"Invalid --until date: {until!r} (expected YYYY-MM-DD)")
            ctx.exit(EXIT_DATAERR)
            return
    else:
        until_dt = datetime.now(timezone.utc)

    sf = _get_db_session_factory()
    if sf is None:
        echo_error(ctx, "Cannot connect to cache database. Is pce_cache.db_path configured?")
        ctx.exit(EXIT_UNAVAILABLE)
        return
    try:
        from src.config import ConfigManager
        from src.api_client import ApiClient
        cm = ConfigManager()
        cm.load()
        api = ApiClient(cm)
        from src.pce_cache.backfill import BackfillRunner
        runner = BackfillRunner(api, sf)
        if not is_quiet(ctx):
            console.print(f"Backfilling [bold]{source}[/bold] from {since} to {until or 'now'}…")
        if source == "events":
            result = runner.run_events(since_dt, until_dt)
        else:
            result = runner.run_traffic(since_dt, until_dt)
        if json_output or is_json(ctx):
            echo_json(ctx, {
                "source": source,
                "inserted": result.inserted,
                "duplicates": result.duplicates,
                "elapsed": round(result.elapsed_seconds, 1),
            })
        elif not is_quiet(ctx):
            console.print(f"[green]Done:[/green] {result.inserted} inserted, {result.duplicates} duplicates, {result.elapsed_seconds:.1f}s")
    except Exception as exc:
        echo_error(ctx, f"Backfill failed: {exc}")
        ctx.exit(EXIT_SOFTWARE)
        return


@cache_group.command("status")
@click.pass_context
def cache_status(ctx: click.Context):
    """Show cache row counts and last-sync timestamps."""
    flags = get_global_flags(ctx)
    sf = _get_db_session_factory()
    if sf is None:
        if not flags['quiet']:
            console.print("[yellow]Cache database not configured.[/yellow]")
        return
    try:
        from sqlalchemy import func, select
        from src.pce_cache.models import PceEvent, PceTrafficFlowRaw, PceTrafficFlowAgg
        rows = []
        with sf() as s:
            for model, label, ts_col in [
                (PceEvent, "events", PceEvent.ingested_at),
                (PceTrafficFlowRaw, "traffic_raw", PceTrafficFlowRaw.ingested_at),
                (PceTrafficFlowAgg, "traffic_agg", PceTrafficFlowAgg.bucket_day),
            ]:
                count = s.execute(select(func.count()).select_from(model)).scalar() or 0
                last = s.execute(select(func.max(ts_col))).scalar()
                rows.append({"source": label, "rows": count, "last_ingested": str(last or "")})
        if flags['json']:
            echo_json(ctx, rows)
            return
        if flags['quiet']:
            for r in rows:
                click.echo(r['source'])
            return
        table = Table("Source", "Rows", "Last ingested")
        for r in rows:
            table.add_row(r['source'], str(r['rows']), r['last_ingested'] or "—")
        console.print(table)
    except Exception as exc:
        echo_error(ctx, f"Status query failed: {exc}")


@cache_group.command("retention")
@click.option("--run", "do_run", is_flag=True, default=False, help="Execute retention purge now.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit config (or results) as JSON.")
@click.pass_context
def cache_retention(ctx: click.Context, do_run: bool, json_output: bool):
    """Show configured cache retention policy, or run it immediately with --run."""
    cfg = _get_cache_config()
    config_data = {
        "events_retention_days": int(cfg.get("events_retention_days", 90)),
        "traffic_raw_retention_days": int(cfg.get("traffic_raw_retention_days", 7)),
        "traffic_agg_retention_days": int(cfg.get("traffic_agg_retention_days", 365)),
    }

    if not do_run:
        if json_output or is_json(ctx):
            echo_json(ctx, config_data)
        elif not is_quiet(ctx):
            table = Table("Setting", "Days")
            for key, val in config_data.items():
                table.add_row(key, str(val))
            console.print(table)
        return

    sf = _get_db_session_factory()
    if sf is None:
        echo_error(ctx, "Cannot connect to cache database. Is pce_cache.db_path configured?")
        ctx.exit(EXIT_UNAVAILABLE)
        return
    try:
        from src.pce_cache.retention import RetentionWorker
        worker = RetentionWorker(sf)
        result = worker.run_once(
            events_days=config_data["events_retention_days"],
            traffic_raw_days=config_data["traffic_raw_retention_days"],
            traffic_agg_days=config_data["traffic_agg_retention_days"],
        )
        if json_output or is_json(ctx):
            echo_json(ctx, result)
        elif not is_quiet(ctx):
            result_table = Table("Table", "Rows deleted")
            for key, count in result.items():
                result_table.add_row(key, str(count))
            console.print(result_table)
            console.print("[green]Retention purge complete.[/green]")
    except Exception as exc:
        echo_error(ctx, f"Retention failed: {exc}")
        ctx.exit(EXIT_SOFTWARE)
        return
