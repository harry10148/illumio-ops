import click


@click.group("report")
def report_group() -> None:
    """Generate reports (traffic/audit/ven/policy-usage)."""


@report_group.command("traffic")
@click.option("--source", type=click.Choice(["api", "csv"]), default="api")
@click.option("--file", "file_path", type=click.Path(exists=True), default=None)
@click.option("--format", "fmt", type=click.Choice(["html", "csv", "pdf", "xlsx", "all"]), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
@click.option("--email", is_flag=True)
def report_traffic(source: str, file_path, fmt: str, output_dir, email: bool) -> None:
    """Generate Traffic Flow Report."""
    import os
    from src.config import ConfigManager
    from src.api_client import ApiClient
    from src.reporter import Reporter
    from src.report.report_generator import ReportGenerator

    cm = ConfigManager()
    api = ApiClient(cm)
    reporter = Reporter(cm)
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root_dir = os.path.dirname(pkg_dir)
    config_dir = os.path.join(root_dir, 'config')
    out = output_dir or cm.config.get('report', {}).get('output_dir', 'reports')
    if not os.path.isabs(out):
        out = os.path.join(root_dir, out)
    gen = ReportGenerator(cm, api_client=api, config_dir=config_dir)
    result = (gen.generate_from_csv(file_path) if source == "csv"
              else gen.generate_from_api())
    if result.record_count == 0:
        raise click.ClickException("No data for report")
    paths = gen.export(result, fmt=fmt, output_dir=out,
                       send_email=email, reporter=reporter if email else None)
    for p in paths:
        click.echo(p)
