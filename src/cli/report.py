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

_REPORT_FORMATS = ["html", "csv", "pdf", "xlsx", "all"]

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
            f"Invalid date {value!r}. Expected YYYY-MM-DD."
        ) from exc
    suffix = "23:59:59Z" if end_of_day else "00:00:00Z"
    return parsed.strftime(f"%Y-%m-%dT{suffix}")


def _resolve_lang(cm) -> str:
    """Read settings.language from config; fall back to 'en'. Only en/zh_TW supported."""
    raw = (cm.config.get("settings", {}) or {}).get("language", "en")
    return raw if raw in {"en", "zh_TW"} else "en"


_TRAFFIC_PROFILES = ["security_risk", "network_inventory"]


def generate_traffic_report(
    *,
    source: str = "api",
    file_path: str | None = None,
    fmt: str = "html",
    output_dir: str | None = None,
    email: bool = False,
    traffic_report_profile: str = "security_risk",
    vuln_csv_path: str | None = None,
) -> list[str]:
    from src.api_client import ApiClient
    from src.config import ConfigManager
    from src.report.report_generator import ReportGenerator
    from src.reporter import Reporter

    cm = ConfigManager()
    api = ApiClient(cm)
    reporter = Reporter(cm)
    _root_dir, config_dir = _resolve_paths(output_dir)
    out = _resolve_output_dir(cm, output_dir)

    from src.main import _make_cache_reader
    lang = _resolve_lang(cm)
    gen = ReportGenerator(cm, api_client=api, config_dir=config_dir,
                          cache_reader=_make_cache_reader(cm))
    if source == "csv":
        if not file_path:
            raise click.ClickException("--file is required when --source csv is used")
        result = gen.generate_from_csv(file_path, traffic_report_profile=traffic_report_profile, lang=lang,
                                       vuln_csv_path=vuln_csv_path)
    else:
        result = gen.generate_from_api(traffic_report_profile=traffic_report_profile, lang=lang,
                                       vuln_csv_path=vuln_csv_path)

    if result.record_count == 0:
        raise click.ClickException("No data for report")

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
        raise click.ClickException("No data for report")
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
        raise click.ClickException("No data for report")
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
            raise click.ClickException("--file is required when --source csv is used")
        result = gen.generate_from_csv(file_path, lang=lang)
    else:
        result = gen.generate_from_api(
            start_date=_iso_date(start_date, end_of_day=False),
            end_date=_iso_date(end_date, end_of_day=True),
            lang=lang,
        )

    if result.record_count == 0:
        raise click.ClickException("No data for report")
    return gen.export(result, fmt=fmt, output_dir=out, lang=lang)


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
    default="security_risk",
    help="Traffic report profile (security_risk or network_inventory)",
)
@click.pass_context
def report_traffic(ctx: click.Context, source: str, file_path, fmt: str, output_dir, email: bool, traffic_report_profile: str) -> None:
    """Generate Traffic Flow Report."""
    if ctx.get_parameter_source("traffic_report_profile") == click.core.ParameterSource.COMMANDLINE:
        click.echo("note: 'report traffic --profile' is deprecated; use 'report security' / 'report inventory'", err=True)
    try:
        paths = generate_traffic_report(
            source=source,
            file_path=file_path,
            fmt=fmt,
            output_dir=output_dir,
            email=email,
            traffic_report_profile=traffic_report_profile,
        )
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, f"Connection failed: {exc}")
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, f"Input file not found: {exc}")
        ctx.exit(EXIT_NOINPUT)
        return
    except Exception as exc:
        log.exception("traffic report failed")
        echo_error(ctx, f"Unexpected error: {exc}")
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
@click.pass_context
def report_security(ctx: click.Context, source: str, file_path, fmt: str, output_dir, email: bool,
                    vuln_csv_path) -> None:
    """Generate Security & Risk Report."""
    try:
        paths = generate_security_report(
            source=source,
            file_path=file_path,
            fmt=fmt,
            output_dir=output_dir,
            email=email,
            vuln_csv_path=vuln_csv_path,
        )
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, f"Connection failed: {exc}")
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, f"Input file not found: {exc}")
        ctx.exit(EXIT_NOINPUT)
        return
    except Exception as exc:
        log.exception("security report failed")
        echo_error(ctx, f"Unexpected error: {exc}")
        ctx.exit(EXIT_SOFTWARE)
        return
    _emit_paths(ctx, paths, fmt)


@report_group.command("inventory")
@click.option("--source", type=click.Choice(["api", "csv"]), default="api")
@click.option("--file", "file_path", type=click.Path(exists=True), default=None)
@click.option("--format", "fmt", type=click.Choice(_REPORT_FORMATS), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
@click.option("--email", is_flag=True)
@click.pass_context
def report_inventory(ctx: click.Context, source: str, file_path, fmt: str, output_dir, email: bool) -> None:
    """Generate Network & Traffic Inventory Report."""
    try:
        paths = generate_inventory_report(
            source=source,
            file_path=file_path,
            fmt=fmt,
            output_dir=output_dir,
            email=email,
        )
    except click.ClickException as exc:
        echo_error(ctx, exc.format_message())
        ctx.exit(EXIT_DATAERR)
        return
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, f"Connection failed: {exc}")
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, f"Input file not found: {exc}")
        ctx.exit(EXIT_NOINPUT)
        return
    except Exception as exc:
        log.exception("inventory report failed")
        echo_error(ctx, f"Unexpected error: {exc}")
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
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, f"Connection failed: {exc}")
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, f"Input file not found: {exc}")
        ctx.exit(EXIT_NOINPUT)
        return
    except Exception as exc:
        log.exception("audit report failed")
        echo_error(ctx, f"Unexpected error: {exc}")
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
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, f"Connection failed: {exc}")
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, f"Input file not found: {exc}")
        ctx.exit(EXIT_NOINPUT)
        return
    except Exception as exc:
        log.exception("ven-status report failed")
        echo_error(ctx, f"Unexpected error: {exc}")
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
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, f"Connection failed: {exc}")
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, f"Input file not found: {exc}")
        ctx.exit(EXIT_NOINPUT)
        return
    except Exception as exc:
        log.exception("policy-usage report failed")
        echo_error(ctx, f"Unexpected error: {exc}")
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
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, f"Connection failed: {exc}")
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, f"Input file not found: {exc}")
        ctx.exit(EXIT_NOINPUT)
        return
    except Exception as exc:
        log.exception("policy resolver report failed")
        echo_error(ctx, f"Unexpected error: {exc}")
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
    except (ConnectionError, OSError) as exc:
        if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
            raise
        echo_error(ctx, f"Connection failed: {exc}")
        ctx.exit(EXIT_UNAVAILABLE)
        return
    except FileNotFoundError as exc:
        echo_error(ctx, f"Input file not found: {exc}")
        ctx.exit(EXIT_NOINPUT)
        return
    except Exception as exc:
        log.exception("policy-diff report failed")
        echo_error(ctx, f"Unexpected error: {exc}")
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
