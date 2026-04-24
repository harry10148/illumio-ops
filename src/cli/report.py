from __future__ import annotations

import datetime as dt
import os

import click

_REPORT_FORMATS = ["html", "csv", "pdf", "xlsx", "all"]


def _check_pdf_available(fmt: str) -> None:
    """Raise ClickException if PDF was requested but weasyprint is not installed."""
    if fmt == "pdf":
        from src.report.exporters.pdf_exporter import PDF_AVAILABLE
        if not PDF_AVAILABLE:
            raise click.ClickException(
                "PDF export is not available in this build. "
                "Use --format html or --format xlsx."
            )


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


def generate_traffic_report(
    *,
    source: str = "api",
    file_path: str | None = None,
    fmt: str = "html",
    output_dir: str | None = None,
    email: bool = False,
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

    gen = ReportGenerator(cm, api_client=api, config_dir=config_dir)
    if source == "csv":
        if not file_path:
            raise click.ClickException("--file is required when --source csv is used")
        result = gen.generate_from_csv(file_path)
    else:
        result = gen.generate_from_api()

    if result.record_count == 0:
        raise click.ClickException("No data for report")

    return gen.export(
        result,
        fmt=fmt,
        output_dir=out,
        send_email=email,
        reporter=reporter if email else None,
    )


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

    gen = AuditGenerator(cm, api_client=api, config_dir=config_dir)
    result = gen.generate_from_api(
        start_date=_iso_date(start_date, end_of_day=False),
        end_date=_iso_date(end_date, end_of_day=True),
    )
    if result.record_count == 0:
        raise click.ClickException("No data for report")
    return gen.export(result, fmt=fmt, output_dir=out)


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

    gen = VenStatusGenerator(cm, api_client=api)
    result = gen.generate()
    if result.record_count == 0:
        raise click.ClickException("No data for report")
    return gen.export(result, fmt=fmt, output_dir=out)


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
    if source == "csv":
        if not file_path:
            raise click.ClickException("--file is required when --source csv is used")
        result = gen.generate_from_csv(file_path)
    else:
        result = gen.generate_from_api(
            start_date=_iso_date(start_date, end_of_day=False),
            end_date=_iso_date(end_date, end_of_day=True),
        )

    if result.record_count == 0:
        raise click.ClickException("No data for report")
    return gen.export(result, fmt=fmt, output_dir=out)


@click.group("report")
def report_group() -> None:
    """Generate reports (traffic/audit/ven/policy-usage)."""


@report_group.command("traffic")
@click.option("--source", type=click.Choice(["api", "csv"]), default="api")
@click.option("--file", "file_path", type=click.Path(exists=True), default=None)
@click.option("--format", "fmt", type=click.Choice(_REPORT_FORMATS), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
@click.option("--email", is_flag=True)
def report_traffic(source: str, file_path, fmt: str, output_dir, email: bool) -> None:
    """Generate Traffic Flow Report."""
    _check_pdf_available(fmt)
    for path in generate_traffic_report(
        source=source,
        file_path=file_path,
        fmt=fmt,
        output_dir=output_dir,
        email=email,
    ):
        click.echo(path)


@report_group.command("audit")
@click.option("--start-date", type=str, default=None, help="Start date in YYYY-MM-DD")
@click.option("--end-date", type=str, default=None, help="End date in YYYY-MM-DD")
@click.option("--format", "fmt", type=click.Choice(_REPORT_FORMATS), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
def report_audit(start_date: str | None, end_date: str | None, fmt: str, output_dir) -> None:
    """Generate Audit Report."""
    _check_pdf_available(fmt)
    for path in generate_audit_report(
        start_date=start_date,
        end_date=end_date,
        fmt=fmt,
        output_dir=output_dir,
    ):
        click.echo(path)


@report_group.command("ven-status")
@click.option("--format", "fmt", type=click.Choice(_REPORT_FORMATS), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
def report_ven_status(fmt: str, output_dir) -> None:
    """Generate VEN Status Report."""
    _check_pdf_available(fmt)
    for path in generate_ven_status_report(fmt=fmt, output_dir=output_dir):
        click.echo(path)


@report_group.command("policy-usage")
@click.option("--source", type=click.Choice(["api", "csv"]), default="api")
@click.option("--file", "file_path", type=click.Path(exists=True), default=None)
@click.option("--start-date", type=str, default=None, help="Start date in YYYY-MM-DD")
@click.option("--end-date", type=str, default=None, help="End date in YYYY-MM-DD")
@click.option("--format", "fmt", type=click.Choice(_REPORT_FORMATS), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
def report_policy_usage(
    source: str,
    file_path,
    start_date: str | None,
    end_date: str | None,
    fmt: str,
    output_dir,
) -> None:
    """Generate Policy Usage Report."""
    _check_pdf_available(fmt)
    for path in generate_policy_usage_report(
        source=source,
        file_path=file_path,
        start_date=start_date,
        end_date=end_date,
        fmt=fmt,
        output_dir=output_dir,
    ):
        click.echo(path)
