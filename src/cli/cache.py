"""illumio-ops cache subcommands — backfill, status, retention, flush."""
from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from src.cli._global_flags import get_global_flags
from src.i18n import t
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
    EXIT_USAGE,
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
    """PCE cache management — backfill, status, retention, flush."""


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
        echo_error(ctx, t("cli_cache_invalid_since_date", since=repr(since)))
        ctx.exit(EXIT_DATAERR)
        return
    if until:
        try:
            until_dt = datetime.strptime(until, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            echo_error(ctx, t("cli_cache_invalid_until_date", until=repr(until)))
            ctx.exit(EXIT_DATAERR)
            return
    else:
        until_dt = datetime.now(timezone.utc)

    sf = _get_db_session_factory()
    if sf is None:
        echo_error(ctx, t("cli_cache_err_no_db"))
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
            console.print(t("cli_cache_backfilling", source=source, a=since, b=until or "now"))
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
            console.print(t("cli_cache_done", inserted=result.inserted, duplicates=result.duplicates, elapsed=f"{result.elapsed_seconds:.1f}"))
    except Exception as exc:
        echo_error(ctx, t("cli_cache_backfill_failed", exc=exc))
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
            console.print(f"[yellow]{t('cli_cache_db_not_configured')}[/yellow]")
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
        table = Table(t("cli_cache_col_source"), t("cli_cache_col_rows"), t("cli_cache_col_last_ingested"))
        for r in rows:
            table.add_row(r['source'], str(r['rows']), r['last_ingested'] or "—")
        console.print(table)
    except Exception as exc:
        echo_error(ctx, t("cli_cache_status_failed", exc=exc))
        ctx.exit(EXIT_SOFTWARE)


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
        "archive_enabled": bool(cfg.get("archive_enabled", False)),
    }

    if not do_run:
        if json_output or is_json(ctx):
            echo_json(ctx, config_data)
        elif not is_quiet(ctx):
            table = Table(t("cli_cache_col_setting"), t("cli_cache_col_days"))
            for key, val in config_data.items():
                table.add_row(key, str(val))
            console.print(table)
        return

    sf = _get_db_session_factory()
    if sf is None:
        echo_error(ctx, t("cli_cache_err_no_db"))
        ctx.exit(EXIT_UNAVAILABLE)
        return
    try:
        from src.pce_cache.retention import RetentionWorker
        worker = RetentionWorker(sf)
        result = worker.run_once(
            events_days=config_data["events_retention_days"],
            traffic_raw_days=config_data["traffic_raw_retention_days"],
            traffic_agg_days=config_data["traffic_agg_retention_days"],
            archive_enabled=config_data["archive_enabled"],
        )
        if json_output or is_json(ctx):
            echo_json(ctx, result)
        elif not is_quiet(ctx):
            result_table = Table(t("cli_cache_col_table"), t("cli_cache_col_rows_deleted"))
            for key, count in result.items():
                result_table.add_row(key, str(count))
            console.print(result_table)
            console.print(f"[green]{t('cli_cache_retention_done')}[/green]")
    except Exception as exc:
        echo_error(ctx, t("cli_cache_retention_failed", exc=exc))
        ctx.exit(EXIT_SOFTWARE)
        return


@cache_group.command("flush")
@click.option("--confirm", is_flag=True, default=False,
              help="Required. Clears every cached PCE row and the PCE-derived state.")
@click.option("--json", "json_output", is_flag=True, default=False,
              help="Emit the per-table counts as JSON.")
@click.pass_context
def cache_flush(ctx: click.Context, confirm: bool, json_output: bool):
    """Clear the cached PCE data and the state derived from it.

    For an appliance whose cache accumulated rows from more than one PCE:
    `config login --pce-target-change flush` only clears when the PCE also
    changes, so staying on the current PCE needs this instead.
    """
    if not confirm:
        echo_error(ctx, t("cli_cache_flush_needs_confirm"))
        ctx.exit(EXIT_USAGE)
        return
    from src.config import ConfigManager, resolve_state_file
    from src.pce_cache.flush import flush_pce_derived_state
    cm = ConfigManager()
    try:
        counts = flush_pce_derived_state(cm.models.pce_cache.db_path, resolve_state_file())
    except TimeoutError as exc:
        echo_error(ctx, t("cli_cache_flush_busy", error=str(exc)[:200]))
        ctx.exit(EXIT_UNAVAILABLE)
        return
    # Always shown, json or not: it goes to stderr (echo_warning), so it
    # never lands in a --json consumer's stdout, but a running monitor holds
    # its own ConfigManager for the life of the process and will refill what
    # was just cleared regardless of which output format the operator chose.
    echo_warning(ctx, t("cli_cache_flush_restart_required"))
    if json_output or is_json(ctx):
        echo_json(ctx, counts)
    elif not is_quiet(ctx):
        table = Table(t("cli_cache_col_setting"), t("cli_cache_col_rows_deleted"))
        for key, val in sorted(counts.items()):
            table.add_row(key, str(val))
        console.print(table)
