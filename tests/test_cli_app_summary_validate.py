"""CLI app-summary soft-validates --app against the PCE app labels (warn, not fail)."""
from unittest.mock import MagicMock, patch

from click.testing import CliRunner


def _invoke(app):
    from src.cli.report import report_group
    runner = CliRunner()
    mock_cm = MagicMock()
    mock_cm.config = {"settings": {"language": "en"}, "report": {"output_dir": "/tmp/x"}}
    with patch("src.config.ConfigManager", return_value=mock_cm), \
         patch("src.api_client.ApiClient") as A, \
         patch("src.main._make_cache_reader", return_value=MagicMock()), \
         patch("src.report.app_summary_report.AppSummaryReport") as R:
        A.return_value.get_labels.return_value = [{"key": "app", "value": "DB"}]
        R.return_value.run.return_value = "/tmp/x.html"
        return runner.invoke(
            report_group,
            ["app-summary", "--app", app, "--output-dir", "/tmp/x"],
        )


def test_unknown_app_warns_but_proceeds():
    res = _invoke("Nope")
    assert res.exit_code == 0, res.output
    assert "DB" in res.output      # suggests known labels
    assert "Nope" in res.output    # mentions the bad value


def test_known_app_no_warning():
    res = _invoke("DB")
    assert res.exit_code == 0, res.output
    assert "not found" not in res.output
