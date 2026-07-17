from __future__ import annotations

import datetime as dt
import logging
import os

import click

from src.cli._exit_codes import (
    EXIT_DATAERR,
    EXIT_NOINPUT,
    EXIT_SOFTWARE,
    EXIT_UNAVAILABLE,
)
from src.cli._output import echo_error, echo_json, is_json
from src.i18n import t

_REPORT_FORMATS = ["html", "csv", "xlsx", "all"]

log = logging.getLogger(__name__)


def _resolve_paths(output_dir: str | None) -> tuple[str, str]:
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root_dir = os.path.dirname(pkg_dir)
    config_dir = os.path.join(root_dir, "config")
    return root_dir, config_dir


def _resolve_output_dir(cm, output_dir: str | None) -> str:
    root_dir, _ = _resolve_paths(output_dir)
    out = output_dir or cm.config.get("report", {}).get("output_dir", "reports")
    if not os.path.isabs(out):
        out = os.path.join(root_dir, out)
    return out


def _iso_date(value: str | None, *, end_of_day: bool) -> str | None:
    if value is None:
        return None
    try:
        parsed = dt.datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError as exc:
        raise click.ClickException(
            t("cli_report_invalid_date", value=value, lang=_ctx_lang())
        ) from exc
    suffix = "23:59:59Z" if end_of_day else "00:00:00Z"
    return parsed.strftime(f"%Y-%m-%dT{suffix}")


def _resolve_lang(cm) -> str:
    """Read settings.language from config; fall back to 'en'. Only en/zh_TW supported."""
    raw = (cm.config.get("settings", {}) or {}).get("language", "en")
    return raw if raw in {"en", "zh_TW"} else "en"


def _ctx_lang() -> str:
    """Resolve the active UI language when no ConfigManager is in scope
    (mirrors the inline pattern used by report_resolve)."""
    from src.config import ConfigManager
    return _resolve_lang(ConfigManager())


_TRAFFIC_PROFILES = ["security_risk", "network_inventory"]


def _data_source_options(f):
    """Shared --data-source / deprecated --cache options for cache-capable reports."""
    f = click.option(
        "--data-source", type=click.Choice(["hybrid", "live", "cache-only"]), default=None,
        help="Report data source: hybrid (cache + live gap-fill, default), "
             "live (PCE only), cache-only (fastest, within cached range).",
    )(f)
    f = click.option("--cache/--no-cache", "legacy_cache", default=None,
                     help="(deprecated) use --data-source instead.")(f)
    return f


def _resolve_cli_data_source(data_source, legacy_cache):
    """Map the CLI's --data-source / legacy --cache flags to (data_source, use_cache)
    for generate_traffic_report. Emits a deprecation note when the legacy flag is used."""
    if data_source is None and legacy_cache is not None:
        click.echo(t("cli_report_cache_deprecated", lang=_ctx_lang()), err=True)
    use_cache = legacy_cache if legacy_cache is not None else True
    return data_source, use_cache


def generate_traffic_report(
    *,
    source: str = "api",
    file_path: str | None = None,
    fmt: str = "html",
    output_dir: str | None = None,
    email: bool = False,
    traffic_report_profile: str = "security_risk",
    vuln_csv_path: str | None = None,
    use_cache: bool = True,
    data_source: str | None = None,
    draft_policy: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
    max_results: int | None = None,
) -> list[str]:
    from src.api_client import ApiClient
    from src.config import ConfigManager
    from src.report.report_generator import ReportGenerator
    from src.reporter import Reporter
    from src.report.cache_support import resolve_data_source, cache_available

    cm = ConfigManager()
    api = ApiClient(cm)
    reporter = Reporter(cm)

    # Resolve the 3-mode data-source choice to backend flags. Back-compat: when
    # no explicit data_source is given, derive it from the legacy use_cache bool.
    eff_ds = data_source if data_source is not None else ("cache" if use_cache else "no-cache")
    use_cache, clip_to_cache, _ds_warn = resolve_data_source(eff_ds, cache_available(cm))
    if _ds_warn:
        click.echo(t("cli_report_data_source_warning", msg=_ds_warn, lang=_ctx_lang()), err=True)
    _root_dir, config_dir = _resolve_paths(output_dir)
    out = _resolve_output_dir(cm, output_dir)

    from src.main import _make_cache_reader
    lang = _resolve_lang(cm)
    gen = ReportGenerator(cm, api_client=api, config_dir=config_dir,
                          cache_reader=_make_cache_reader(cm))
    if source == "csv":
        if not file_path:
            raise click.ClickException(t("cli_report_file_required_csv", lang=lang))
        result = gen.generate_from_csv(file_path, traffic_report_profile=traffic_report_profile, lang=lang,
                                       vuln_csv_path=vuln_csv_path)
    else:
        result = gen.generate_from_api(start_date=start_date, end_date=end_date,
                                       max_results=max_results,
                                       traffic_report_profile=traffic_report_profile, lang=lang,
                                       vuln_csv_path=vuln_csv_path, use_cache=use_cache,
                                       clip_to_cache=clip_to_cache, draft_policy=draft_policy)

    if result.record_count == 0:
        raise click.ClickException(t("cli_report_no_data", lang=lang))

    return gen.export(
        result,
        fmt=fmt,
        output_dir=out,
        send_email=email,
        reporter=reporter if email else None,
        traffic_report_profile=traffic_report_profile,
        lang=lang,
    )


def generate_security_report(**kw):
    """Generate the Security & Risk traffic report (fixed profile)."""
    return generate_traffic_report(traffic_report_profile="security_risk", **kw)


def generate_inventory_report(**kw):
    """Generate the Network & Traffic Inventory report (fixed profile)."""
    return generate_traffic_report(traffic_report_profile="network_inventory", **kw)


def generate_audit_report(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    fmt: str = "html",
    output_dir: str | None = None,
) -> list[str]:
    from src.api_client import ApiClient
    from src.config import ConfigManager
    from src.report.audit_generator import AuditGenerator

    cm = ConfigManager()
    api = ApiClient(cm)
    _root_dir, config_dir = _resolve_paths(output_dir)
    out = _resolve_output_dir(cm, output_dir)

    from src.main import _make_cache_reader
    lang = _resolve_lang(cm)
    gen = AuditGenerator(cm, api_client=api, config_dir=config_dir,
                         cache_reader=_make_cache_reader(cm))
    result = gen.generate_from_api(
        start_date=_iso_date(start_date, end_of_day=False),
        end_date=_iso_date(end_date, end_of_day=True),
        lang=lang,
    )
    if result.record_count == 0:
        raise click.ClickException(t("cli_report_no_data", lang=lang))
    return gen.export(result, fmt=fmt, output_dir=out, lang=lang)


def generate_ven_status_report(
    *,
    fmt: str = "html",
    output_dir: str | None = None,
) -> list[str]:
    from src.api_client import ApiClient
    from src.config import ConfigManager
    from src.report.ven_status_generator import VenStatusGenerator

    cm = ConfigManager()
    api = ApiClient(cm)
    out = _resolve_output_dir(cm, output_dir)
    lang = _resolve_lang(cm)

    gen = VenStatusGenerator(cm, api_client=api)
    result = gen.generate(lang=lang)
    if result.record_count == 0:
        raise click.ClickException(t("cli_report_no_data", lang=lang))
    return gen.export(result, fmt=fmt, output_dir=out, lang=lang)


def generate_policy_usage_report(
    *,
    source: str = "api",
    file_path: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    fmt: str = "html",
    output_dir: str | None = None,
) -> list[str]:
    from src.api_client import ApiClient
    from src.config import ConfigManager
    from src.report.policy_usage_generator import PolicyUsageGenerator

    cm = ConfigManager()
    api = ApiClient(cm)
    _root_dir, config_dir = _resolve_paths(output_dir)
    out = _resolve_output_dir(cm, output_dir)

    gen = PolicyUsageGenerator(cm, api_client=api, config_dir=config_dir)
    lang = _resolve_lang(cm)
    if source == "csv":
        if not file_path:
            raise click.ClickException(t("cli_report_file_required_csv", lang=lang))
        result = gen.generate_from_csv(file_path, lang=lang)
    else:
        result = gen.generate_from_api(
            start_date=_iso_date(start_date, end_of_day=False),
            end_date=_iso_date(end_date, end_of_day=True),
            lang=lang,
        )

    if result.record_count == 0:
        raise click.ClickException(t("cli_report_no_data", lang=lang))
    return gen.export(result, fmt=fmt, output_dir=out, lang=lang)


def generate_rule_hit_count_report(
    *,
    source: str = "native",
    file_path: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    fmt: str = "html",
    output_dir: str | None = None,
) -> list[str]:
    """Raises RuleHitCountNotEnabled (native source) for the command layer to handle."""
    from src.api_client import ApiClient
    from src.config import ConfigManager
    from src.report.rule_hit_count_generator import RuleHitCountGenerator

    cm = ConfigManager()
    api = ApiClient(cm)
    _root_dir, config_dir = _resolve_paths(output_dir)
    out = _resolve_output_dir(cm, output_dir)
    lang = _resolve_lang(cm)

    gen = RuleHitCountGenerator(cm, api_client=api, config_dir=config_dir)
    if source == "csv":
        if not file_path:
            raise click.ClickException(t("cli_report_file_required_csv", lang=lang))
        result = gen.generate_from_csv(file_path, lang=lang)
    else:
        result = gen.generate_from_native(
            start_date=_iso_date(start_date, end_of_day=False),
            end_date=_iso_date(end_date, end_of_day=True),
            lang=lang,
        )

    if result.record_count == 0:
        raise click.ClickException(t("cli_report_no_data", lang=lang))
    return gen.export(result, fmt=fmt, output_dir=out, lang=lang)


def generate_readiness_report(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    fmt: str = "html",
    output_dir: str | None = None,
    data_source: str | None = None,
    use_cache: bool = True,
) -> list[str]:
    from src.api_client import ApiClient
    from src.config import ConfigManager
    from src.main import _make_cache_reader
    from src.report.cache_support import cache_available, resolve_data_source
    from src.report.readiness_report import ReadinessReportGenerator

    cm = ConfigManager()
    api = ApiClient(cm)
    lang = _resolve_lang(cm)
    eff_ds = data_source if data_source is not None else ("cache" if use_cache else "no-cache")
    # fetch_traffic_df has no clip_to_cache knob — only use_cache applies here.
    use_cache, _clip, _ds_warn = resolve_data_source(eff_ds, cache_available(cm))
    if _ds_warn:
        click.echo(t("cli_report_data_source_warning", msg=_ds_warn, lang=lang), err=True)
    _root_dir, config_dir = _resolve_paths(output_dir)
    out = _resolve_output_dir(cm, output_dir)
    gen = ReadinessReportGenerator(cm, api_client=api, config_dir=config_dir,
                                   cache_reader=_make_cache_reader(cm))
    result = gen.generate_from_api(
        start_date=_iso_date(start_date, end_of_day=False),
        end_date=_iso_date(end_date, end_of_day=True),
        lang=lang, use_cache=use_cache, output_dir=out)
    if result.record_count == 0:
        raise click.ClickException(t("cli_report_no_data", lang=lang))
    return gen.export(result, fmt=fmt, output_dir=out, lang=lang)


def _run_rhc_enablement_wizard(api, lang: str) -> bool:
    """Interactive enablement wizard (TTY only). Returns True if enable ran.

    WARNING shown to the operator: the VEN side writes draft firewall_settings
    and provisions — a production policy write.
    """
    import sys

    import questionary

    from src.cli.object_picker import pick_objects
    from src.report.rule_hit_count_enablement import EnablementError, enable_rule_hit_count

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False

    click.echo(t("cli_rhc_not_enabled_intro", lang=lang))
    click.echo(t("cli_rhc_provision_warning", lang=lang))
    if not questionary.confirm(t("cli_rhc_confirm_enable", lang=lang), default=False).unsafe_ask():
        click.echo(t("cli_rhc_enable_declined", lang=lang))
        return False

    scope_choice = questionary.select(
        t("cli_rhc_scope_question", lang=lang),
        choices=[
            questionary.Choice(t("cli_rhc_scope_all", lang=lang), value="all"),
            questionary.Choice(t("cli_rhc_scope_labels", lang=lang), value="labels"),
        ],
    ).unsafe_ask()

    scopes = None   # None → all VENs ([[]])
    if scope_choice == "labels":
        picked = pick_objects(api, ["label"], t("cli_rhc_scope_pick_title", lang=lang), lang=lang)
        kv_to_href = {f"{l['key']}={l['value']}": l.get("href", "")
                      for l in api.get_all_labels()}
        hrefs = [kv_to_href[v] for v in picked.get("labels", []) if kv_to_href.get(v)]
        if not hrefs:
            # No labels selected (picker Done immediately) or href lookup missed —
            # must NOT fall through with scopes=None, which means "all VENs".
            click.echo(t("cli_rhc_no_labels_selected", lang=lang))
            return False
        scopes = [[{"label": {"href": h}} for h in hrefs]]

    try:
        steps = enable_rule_hit_count(api, scopes=scopes)
    except EnablementError as exc:
        click.echo(t("cli_rhc_enable_failed", steps=", ".join(exc.steps_done) or "-",
                     error=str(exc), lang=lang), err=True)
        return False
    click.echo(t("cli_rhc_enable_done", steps=", ".join(steps), lang=lang))
    click.echo(t("cli_rhc_ven_delay_note", lang=lang))
    return True


def _emit_paths(ctx: click.Context, paths: list[str], fmt: str) -> None:
    """Emit report paths — JSON array when --json, else one path per line."""
    if is_json(ctx):
        data = [
            {"output_path": p, "type": fmt, "size": os.path.getsize(p)}
            for p in paths
        ]
        echo_json(ctx, data)
    else:
        for p in paths:
            click.echo(p)


@click.group("report")
def report_group() -> None:
    """Generate reports (traffic/audit/ven/policy-usage)."""


@report_group.command("traffic")
@click.option("--source", type=click.Choice(["api", "csv"]), default="api")
@click.option("--file", "file_path", type=click.Path(exists=True), default=None)
@click.option("--format", "fmt", type=click.Choice(_REPORT_FORMATS), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
@click.option("--email", is_flag=True)
@click.option(
    "--profile",
    "traffic_report_profile",
    type=click.Choice(_TRAFFIC_PROFILES),
    default=None,
    help="(deprecated) use `report security` / `report inventory` instead.",
)
@_data_source_options
@click.pass_context
def report_traffic(ctx: click.Context, source: str, file_path, fmt: str, output_dir, email: bool, traffic_report_profile: str, data_source, legacy_cache) -> None:
    """Generate Traffic Flow Report."""
    if traffic_report_profile is None:
        traffic_report_profile = "traffic"
    else:
        click.echo(t("cli_report_profile_deprecated", lang=_ctx_lang()), err=True)
    data_source, use_cache = _resolve_cli_data_source(data_source, legacy_cache)
    try:
        paths = generate_traffic_report(
            source=source,
            file_path=file_path,
            fmt=fmt,
            output_dir=output_dir,
            email=email,
            traffic_report_profile=traffic_report_profile,
            use_cache=use_cache,
            data_source=data_source,
        )
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, t("cli_report_input_not_found", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_NOINPUT)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, t("cli_report_connection_failed", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except Exception as exc:
        log.exception("traffic report failed")
        echo_error(ctx, t("cli_report_unexpected_error", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_SOFTWARE)
        return
    _emit_paths(ctx, paths, fmt)


@report_group.command("draft-policy")
@click.option("--start-date", type=str, default=None, help="Start date in YYYY-MM-DD")
@click.option("--end-date", type=str, default=None, help="End date in YYYY-MM-DD")
@click.option("--max-records", type=int, default=None,
              help="Cap analysed flows (draft-divergent flows are kept first) — keeps render "
                   "tractable on high-volume PCEs")
@click.option("--format", "fmt", type=click.Choice(_REPORT_FORMATS), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
@click.option("--email", is_flag=True)
@click.pass_context
def report_draft_policy(ctx: click.Context, start_date: str | None, end_date: str | None,
                        max_records: int | None, fmt: str, output_dir, email: bool) -> None:
    """Generate a Draft-Policy report (R01-R05).

    Always fetches live from the PCE with compute_draft (the ~12s update_rules
    pass) so the flows carry draft_policy_decision; the cache cannot serve this
    report because it has no draft column. compute_draft is expensive over a wide
    window, so scope the query with --start-date/--end-date (defaults to 7 days).
    """
    try:
        paths = generate_traffic_report(
            source="api",
            start_date=start_date,
            end_date=end_date,
            max_results=max_records,
            fmt=fmt,
            output_dir=output_dir,
            email=email,
            draft_policy=True,
        )
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, t("cli_report_connection_failed", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except Exception as exc:
        log.exception("draft-policy report failed")
        echo_error(ctx, t("cli_report_unexpected_error", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_SOFTWARE)
        return
    _emit_paths(ctx, paths, fmt)


@report_group.command("security")
@click.option("--source", type=click.Choice(["api", "csv"]), default="api")
@click.option("--file", "file_path", type=click.Path(exists=True), default=None)
@click.option("--format", "fmt", type=click.Choice(_REPORT_FORMATS), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
@click.option("--email", is_flag=True)
@click.option(
    "--vuln-csv",
    "vuln_csv_path",
    type=click.Path(exists=True),
    default=None,
    help="Vulnerability-scan CSV (ip + cve columns; Qualys/Tenable exports accepted) "
         "for the V-E exposure section.",
)
@_data_source_options
@click.pass_context
def report_security(ctx: click.Context, source: str, file_path, fmt: str, output_dir, email: bool,
                    vuln_csv_path, data_source, legacy_cache) -> None:
    """Generate Security & Risk Report."""
    data_source, use_cache = _resolve_cli_data_source(data_source, legacy_cache)
    try:
        paths = generate_security_report(
            source=source,
            file_path=file_path,
            fmt=fmt,
            output_dir=output_dir,
            email=email,
            vuln_csv_path=vuln_csv_path,
            use_cache=use_cache,
            data_source=data_source,
        )
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, t("cli_report_input_not_found", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_NOINPUT)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, t("cli_report_connection_failed", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except Exception as exc:
        log.exception("security report failed")
        echo_error(ctx, t("cli_report_unexpected_error", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_SOFTWARE)
        return
    _emit_paths(ctx, paths, fmt)


@report_group.command("inventory")
@click.option("--source", type=click.Choice(["api", "csv"]), default="api")
@click.option("--file", "file_path", type=click.Path(exists=True), default=None)
@click.option("--format", "fmt", type=click.Choice(_REPORT_FORMATS), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
@click.option("--email", is_flag=True)
@_data_source_options
@click.pass_context
def report_inventory(ctx: click.Context, source: str, file_path, fmt: str, output_dir, email: bool, data_source, legacy_cache) -> None:
    """Generate Network & Traffic Inventory Report."""
    data_source, use_cache = _resolve_cli_data_source(data_source, legacy_cache)
    try:
        paths = generate_inventory_report(
            source=source,
            file_path=file_path,
            fmt=fmt,
            output_dir=output_dir,
            email=email,
            use_cache=use_cache,
            data_source=data_source,
        )
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, t("cli_report_input_not_found", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_NOINPUT)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, t("cli_report_connection_failed", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except Exception as exc:
        log.exception("inventory report failed")
        echo_error(ctx, t("cli_report_unexpected_error", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_SOFTWARE)
        return
    _emit_paths(ctx, paths, fmt)


@report_group.command("audit")
@click.option("--start-date", type=str, default=None, help="Start date in YYYY-MM-DD")
@click.option("--end-date", type=str, default=None, help="End date in YYYY-MM-DD")
@click.option("--format", "fmt", type=click.Choice(_REPORT_FORMATS), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
@click.pass_context
def report_audit(ctx: click.Context, start_date: str | None, end_date: str | None, fmt: str, output_dir) -> None:
    """Generate Audit Report."""
    try:
        paths = generate_audit_report(
            start_date=start_date,
            end_date=end_date,
            fmt=fmt,
            output_dir=output_dir,
        )
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, t("cli_report_input_not_found", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_NOINPUT)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, t("cli_report_connection_failed", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except Exception as exc:
        log.exception("audit report failed")
        echo_error(ctx, t("cli_report_unexpected_error", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_SOFTWARE)
        return
    _emit_paths(ctx, paths, fmt)


@report_group.command("ven-status")
@click.option("--format", "fmt", type=click.Choice(_REPORT_FORMATS), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
@click.pass_context
def report_ven_status(ctx: click.Context, fmt: str, output_dir) -> None:
    """Generate VEN Status Report."""
    try:
        paths = generate_ven_status_report(fmt=fmt, output_dir=output_dir)
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, t("cli_report_input_not_found", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_NOINPUT)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, t("cli_report_connection_failed", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except Exception as exc:
        log.exception("ven-status report failed")
        echo_error(ctx, t("cli_report_unexpected_error", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_SOFTWARE)
        return
    _emit_paths(ctx, paths, fmt)


@report_group.command("policy-usage")
@click.option("--source", type=click.Choice(["api", "csv"]), default="api")
@click.option("--file", "file_path", type=click.Path(exists=True), default=None)
@click.option("--start-date", type=str, default=None, help="Start date in YYYY-MM-DD")
@click.option("--end-date", type=str, default=None, help="End date in YYYY-MM-DD")
@click.option("--format", "fmt", type=click.Choice(_REPORT_FORMATS), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
@click.pass_context
def report_policy_usage(
    ctx: click.Context,
    source: str,
    file_path,
    start_date: str | None,
    end_date: str | None,
    fmt: str,
    output_dir,
) -> None:
    """Generate Policy Usage Report."""
    try:
        paths = generate_policy_usage_report(
            source=source,
            file_path=file_path,
            start_date=start_date,
            end_date=end_date,
            fmt=fmt,
            output_dir=output_dir,
        )
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, t("cli_report_input_not_found", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_NOINPUT)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, t("cli_report_connection_failed", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except Exception as exc:
        log.exception("policy-usage report failed")
        echo_error(ctx, t("cli_report_unexpected_error", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_SOFTWARE)
        return
    _emit_paths(ctx, paths, fmt)


@report_group.command("rule-hit-count")
@click.option("--source", type=click.Choice(["native", "csv"]), default="native")
@click.option("--file", "file_path", type=click.Path(exists=True), default=None)
@click.option("--start-date", type=str, default=None, help="Start date in YYYY-MM-DD")
@click.option("--end-date", type=str, default=None, help="End date in YYYY-MM-DD")
@click.option("--format", "fmt", type=click.Choice(["html", "csv", "all"]), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
@click.pass_context
def report_rule_hit_count(
    ctx: click.Context,
    source: str,
    file_path,
    start_date: str | None,
    end_date: str | None,
    fmt: str,
    output_dir,
) -> None:
    """Generate Rule Hit Count Report (native PCE data, enriched with rule details)."""
    from src.api.reports import RuleHitCountPullTimeout
    from src.report.rule_hit_count_enablement import RuleHitCountNotEnabled
    try:
        paths = generate_rule_hit_count_report(
            source=source,
            file_path=file_path,
            start_date=start_date,
            end_date=end_date,
            fmt=fmt,
            output_dir=output_dir,
        )
    except RuleHitCountNotEnabled as exc:
        lang = _ctx_lang()
        echo_error(ctx, t("cli_rhc_not_enabled", state=exc.status.state,
                          detail=exc.status.detail, lang=lang))
        from src.api_client import ApiClient
        from src.config import ConfigManager
        _run_rhc_enablement_wizard(ApiClient(ConfigManager()), lang)
        # Wizard never auto-generates (VENs need time to report) — exit either way.
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except RuleHitCountPullTimeout:
        # TimeoutError is an OSError subclass — must be caught here, before the
        # (ConnectionError, OSError) block below, or it re-raises as an
        # uncaught traceback / EXIT_SOFTWARE instead of a clear i18n message.
        echo_error(ctx, t("cli_rhc_pull_timeout", lang=_ctx_lang()))
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, t("cli_report_input_not_found", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_NOINPUT)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, t("cli_report_connection_failed", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except Exception as exc:
        log.exception("rule-hit-count report failed")
        echo_error(ctx, t("cli_report_unexpected_error", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_SOFTWARE)
        return
    _emit_paths(ctx, paths, fmt)


def generate_policy_diff_report(
    *,
    fmt: str = "html",
    output_dir: str | None = None,
    email: bool = False,
    attribution_days: int = 30,
) -> list[str]:
    """Generate the Policy Diff (DRAFT vs ACTIVE) report."""
    from src.api_client import ApiClient
    from src.config import ConfigManager
    from src.report.policy_diff_report import PolicyDiffReport
    from src.main import _make_cache_reader

    cm = ConfigManager()
    api = ApiClient(cm)
    _root_dir, config_dir = _resolve_paths(output_dir)
    out = _resolve_output_dir(cm, output_dir)
    lang = _resolve_lang(cm)

    rpt = PolicyDiffReport(cm, api_client=api, config_dir=config_dir,
                           cache_reader=_make_cache_reader(cm),
                           attribution_days=attribution_days)
    paths: list[str] = []
    if fmt in ("html", "all"):
        paths.append(rpt.run(output_dir=out, lang=lang, fmt="html"))
    if fmt in ("csv", "all"):
        paths.append(rpt.run(output_dir=out, lang=lang, fmt="csv"))

    if email:
        from src.reporter import Reporter
        from src.i18n import t
        html_paths = [p for p in paths if p.endswith(".html")]
        if html_paths:
            html_path = html_paths[0]
            with open(html_path, encoding="utf-8") as fh:
                html_body = fh.read()
            subject = t("rpt_policy_diff_report_title", lang=lang)
            Reporter(cm).send_report_email(subject, html_body, attachment_path=html_path)

    return paths


def generate_app_summary_report(
    *,
    app: str,
    env: str | None = None,
    days: int = 7,
    output_dir: str | None = None,
    use_cache: bool = True,
    data_source: str | None = None,
) -> list[str]:
    """Generate the single-App Summary report (HTML)."""
    from src.api_client import ApiClient
    from src.config import ConfigManager
    from src.report.app_summary_report import AppSummaryReport
    from src.main import _make_cache_reader
    from src.report.cache_support import resolve_data_source, cache_available

    cm = ConfigManager()
    api = ApiClient(cm)
    _root_dir, config_dir = _resolve_paths(output_dir)
    out = _resolve_output_dir(cm, output_dir)
    lang = _resolve_lang(cm)

    # App Summary supports cache (use_cache) but not clip-to-cache, so cache-only
    # collapses to the cached read here. Resolve the data-source for consistency.
    eff_ds = data_source if data_source is not None else ("cache" if use_cache else "no-cache")
    use_cache, _clip, _ds_warn = resolve_data_source(eff_ds, cache_available(cm))
    if _ds_warn:
        click.echo(t("cli_report_data_source_warning", msg=_ds_warn, lang=_ctx_lang()), err=True)

    try:
        known = {l.get("value") for l in api.get_labels("app") if l.get("value")}
        if app not in known:
            close = ", ".join(sorted(k for k in known if app.lower() in k.lower())[:5]) \
                or ", ".join(sorted(known)[:8])
            click.echo(t("cli_report_app_label_not_found", app=app, known=close, lang=lang))
    except Exception:
        pass  # best-effort; never block generation

    now = dt.datetime.now(dt.timezone.utc)
    start = (now - dt.timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    end = now.strftime("%Y-%m-%dT23:59:59Z")

    rpt = AppSummaryReport(cm, api_client=api, config_dir=config_dir,
                           cache_reader=_make_cache_reader(cm))
    path = rpt.run(app=app, env=env, output_dir=out, lang=lang,
                   start_date=start, end_date=end, use_cache=use_cache)
    return [path]


@report_group.command("app-summary")
@click.option("--app", required=True, help="App Label value to scope the report to.")
@click.option("--env", default=None, help="Optional Env Label refinement.")
@click.option("--days", type=int, default=7, show_default=True,
              help="Lookback window (days) for traffic flows.")
@click.option("--output-dir", type=click.Path(), default=None)
@_data_source_options
@click.pass_context
def report_app_summary(ctx: click.Context, app: str, env: str | None, days: int,
                       output_dir, data_source, legacy_cache) -> None:
    """Generate App Summary Report (single App Label, inbound/outbound view)."""
    data_source, use_cache = _resolve_cli_data_source(data_source, legacy_cache)
    try:
        paths = generate_app_summary_report(
            app=app, env=env, days=days, output_dir=output_dir, use_cache=use_cache,
            data_source=data_source,
        )
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, t("cli_report_input_not_found", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_NOINPUT)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, t("cli_report_connection_failed", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except Exception as exc:
        log.exception("app-summary report failed")
        echo_error(ctx, t("cli_report_unexpected_error", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_SOFTWARE)
        return
    _emit_paths(ctx, paths, "html")


def generate_policy_resolver_report(
    *,
    fmt: str = "json",
    output_dir: str | None = None,
) -> list[str]:
    """Resolve ACTIVE policy into IP-level rows; export JSON + CSV."""
    from src.api_client import ApiClient
    from src.config import ConfigManager
    from src.report.policy_resolver_report import PolicyResolverReport

    cm = ConfigManager()
    api = ApiClient(cm)
    _root_dir, config_dir = _resolve_paths(output_dir)
    out = _resolve_output_dir(cm, output_dir)
    lang = _resolve_lang(cm)

    rpt = PolicyResolverReport(cm, api_client=api, config_dir=config_dir)
    return rpt.run(output_dir=out, lang=lang, fmt=fmt)


@report_group.command("resolve")
@click.option("--format", "fmt", type=click.Choice(["json", "csv", "all"]), default="json")
@click.option("--output-dir", type=click.Path(), default=None)
@click.pass_context
def report_resolve(ctx: click.Context, fmt: str, output_dir) -> None:
    """Resolve ACTIVE label-based Policy into IP-level firewall rules."""
    try:
        paths = generate_policy_resolver_report(
            fmt=fmt, output_dir=output_dir,
        )
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, t("cli_report_input_not_found", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_NOINPUT)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, t("cli_report_connection_failed", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except Exception as exc:
        log.exception("policy resolver report failed")
        echo_error(ctx, t("cli_report_unexpected_error", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_SOFTWARE)
        return
    if not paths and not is_json(ctx):
        # Empty ACTIVE policy resolves to 0 rows → no files written. Say so
        # explicitly (mirrors the GUI empty-state toast) so a clean empty run
        # is distinguishable from a silent failure.
        from src.config import ConfigManager
        from src.i18n import t as _t
        click.echo(_t("gui_toast_policy_resolver_empty",
                      lang=_resolve_lang(ConfigManager())), err=True)
    _emit_paths(ctx, paths, fmt)


@report_group.command("readiness")
@click.option("--start-date", default=None, help="Start date (YYYY-MM-DD).")
@click.option("--end-date", default=None, help="End date (YYYY-MM-DD).")
@click.option("--format", "fmt", type=click.Choice(["html", "csv", "all"]), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
@_data_source_options
@click.pass_context
def report_readiness(ctx: click.Context, start_date: str | None, end_date: str | None,
                     fmt: str, output_dir, data_source, legacy_cache) -> None:
    """Generate the Enforcement Readiness report (which app to enforce next)."""
    data_source, use_cache = _resolve_cli_data_source(data_source, legacy_cache)
    try:
        paths = generate_readiness_report(start_date=start_date, end_date=end_date,
                                          fmt=fmt, output_dir=output_dir,
                                          data_source=data_source, use_cache=use_cache)
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, t("cli_report_connection_failed", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except Exception as exc:
        log.exception("readiness report failed")
        echo_error(ctx, t("cli_report_unexpected_error", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_SOFTWARE)
        return
    _emit_paths(ctx, paths, fmt)


@report_group.command("policy-diff")
@click.option("--format", "fmt", type=click.Choice(["html", "csv", "all"]), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
@click.option("--email", is_flag=True)
@click.option("--attribution-days", type=int, default=30, show_default=True,
              help="Audit-event lookback window for operator attribution.")
@click.pass_context
def report_policy_diff(ctx: click.Context, fmt: str, output_dir, email: bool,
                       attribution_days: int) -> None:
    """Generate Policy Diff Report (DRAFT vs ACTIVE, Ruleset/Rule scope)."""
    try:
        paths = generate_policy_diff_report(fmt=fmt, output_dir=output_dir, email=email,
                                            attribution_days=attribution_days)
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, t("cli_report_input_not_found", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_NOINPUT)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, t("cli_report_connection_failed", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except Exception as exc:
        log.exception("policy-diff report failed")
        echo_error(ctx, t("cli_report_unexpected_error", error=exc, lang=_ctx_lang()))
        ctx.exit(EXIT_SOFTWARE)
        return
    _emit_paths(ctx, paths, fmt)


# Verb-prefixed aliases (Track C b2). Canonical names are the short forms
# (traffic / audit / ven-status / policy-usage); generate-* are aliases kept
# for backwards compatibility. The alias short_help is annotated so
# `report --help` makes the relationship visible.
import copy as _copy


def _alias(cmd, canonical_name):
    """Return a shallow copy of cmd whose short_help is annotated as an alias."""
    alias_cmd = _copy.copy(cmd)
    base_short = (cmd.short_help or cmd.help or '').splitlines()[0].strip()
    alias_cmd.short_help = f"(alias of {canonical_name}) {base_short}"
    return alias_cmd


report_group.add_command(_alias(report_traffic,      "traffic"),      name="generate-traffic")
report_group.add_command(_alias(report_security,     "security"),     name="generate-security")
report_group.add_command(_alias(report_inventory,    "inventory"),    name="generate-inventory")
report_group.add_command(_alias(report_audit,        "audit"),        name="generate-audit")
report_group.add_command(_alias(report_ven_status,   "ven-status"),   name="generate-ven-status")
report_group.add_command(_alias(report_policy_usage, "policy-usage"), name="generate-policy-usage")
report_group.add_command(_alias(report_app_summary,  "app-summary"),  name="generate-app-summary")
