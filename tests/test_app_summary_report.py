"""App Summary facade: fetch → scope → modules subset → export."""
import pandas as pd
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from src.cli.report import report_group
from src.report.app_summary_report import AppSummaryReport, _safe_filename_token


def _row(src_app, dst_app, dst_ip, port):
    return {
        "src_app": src_app, "src_env": "P", "dst_app": dst_app, "dst_env": "P",
        "port": port, "proto": "TCP", "policy_decision": "allowed",
        "num_connections": 1, "src_ip": "a", "dst_ip": dst_ip,
        "src_managed": True, "dst_managed": True, "bytes_total": 0,
        "first_detected": pd.Timestamp("2026-01-01"),
        "last_detected": pd.Timestamp("2026-01-02"),
    }


def _row_decision(src_app, dst_app, dst_ip, port, decision, conns):
    r = _row(src_app, dst_app, dst_ip, port)
    r["policy_decision"] = decision
    r["num_connections"] = conns
    return r


def test_safe_filename_token():
    assert _safe_filename_token("My App/v2 (Prod)") == "My_App_v2_Prod"


def test_build_adds_policy_impact_and_enforcement(monkeypatch):
    df = pd.DataFrame([
        _row_decision("Web", "DB", "b", 3306, "allowed", 5),
        _row_decision("Batch", "DB", "b", 3306, "potentially_blocked", 2),
    ])
    api = MagicMock()
    api.fetch_managed_workloads.return_value = [
        {"hostname": "db1", "enforcement_mode": "full",
         "labels": [{"key": "app", "value": "DB"}]},
    ]
    rep = AppSummaryReport(cm=MagicMock(), api_client=api)
    with patch.object(rep, "_fetch_estate_df", return_value=df):
        res = rep.build(app="DB", lang="en")
    assert res["policy_impact"]["available"] is True
    assert res["policy_impact"]["would_be_blocked"] == 1
    assert res["enforcement"]["available"] is True
    assert res["enforcement"]["total"] == 1
    api.fetch_managed_workloads.assert_called_once()


def test_build_enforcement_unavailable_when_workloads_fetch_fails(monkeypatch):
    df = pd.DataFrame([_row_decision("Web", "DB", "b", 3306, "allowed", 5)])
    api = MagicMock()
    api.fetch_managed_workloads.side_effect = Exception("boom")
    rep = AppSummaryReport(cm=MagicMock(), api_client=api)
    with patch.object(rep, "_fetch_estate_df", return_value=df):
        res = rep.build(app="DB", lang="en")
    assert res["enforcement"]["available"] is False
    assert res["empty"] is False


def test_build_scopes_and_runs_modules():
    df = pd.DataFrame([
        _row("Web", "DB", "b", 3306),
        _row("Web", "Cache", "c", 6379),
    ])
    rep = AppSummaryReport(cm=MagicMock(), api_client=MagicMock())
    with patch.object(rep, "_fetch_estate_df", return_value=df):
        result = rep.build(app="DB", lang="en")
    assert result["app"] == "DB"
    assert result["baseline"]["flow_count"] == 1            # 只剩 DB 相關
    assert result["mod01"]["total_flows"] == 1              # 模組看到的是已過濾 df
    assert "findings" in result


def test_build_unknown_app_flags_empty():
    rep = AppSummaryReport(cm=MagicMock(), api_client=MagicMock())
    with patch.object(rep, "_fetch_estate_df", return_value=pd.DataFrame()):
        result = rep.build(app="Nope", lang="en")
    assert result["empty"] is True


def test_export_writes_html(tmp_path):
    df = pd.DataFrame([
        _row("Web", "DB", "b", 3306),
        _row("Web", "Cache", "c", 6379),
    ])
    rep = AppSummaryReport(cm=MagicMock(), api_client=MagicMock())
    with patch.object(rep, "_fetch_estate_df", return_value=df):
        results = rep.build(app="DB", lang="zh_TW")
    from src.report.exporters.app_summary_html_exporter import AppSummaryHtmlExporter
    path = AppSummaryHtmlExporter(results, lang="zh_TW").export(str(tmp_path))
    html = open(path, encoding="utf-8").read()
    assert "App Summary" in html or "App 摘要" in html
    assert 'id="inbound"' in html and 'id="outbound"' in html
    assert "Illumio_App_Summary_DB_" in path


# --- CLI subcommand tests (mirror tests/test_cli_report_policy_diff.py) -------


def test_app_summary_command_registered():
    assert "app-summary" in report_group.commands


def test_app_summary_invokes_run(tmp_path):
    runner = CliRunner()
    mock_cm = MagicMock()
    mock_cm.config = {"settings": {"language": "en"},
                      "report": {"output_dir": str(tmp_path)}}
    with patch("src.config.ConfigManager", return_value=mock_cm), \
         patch("src.api_client.ApiClient"), \
         patch("src.main._make_cache_reader", return_value=MagicMock()), \
         patch("src.report.app_summary_report.AppSummaryReport") as MockReport:
        MockReport.return_value.run.return_value = str(
            tmp_path / "Illumio_App_Summary_DB_x.html")
        result = runner.invoke(
            report_group,
            ["app-summary", "--app", "DB", "--env", "Prod",
             "--output-dir", str(tmp_path)],
        )
    assert result.exit_code == 0, result.output
    _, kwargs = MockReport.return_value.run.call_args
    assert kwargs["app"] == "DB"
    assert kwargs["env"] == "Prod"
    assert kwargs["output_dir"] == str(tmp_path)


def test_app_summary_requires_app():
    runner = CliRunner()
    result = runner.invoke(report_group, ["app-summary"])
    assert result.exit_code != 0
