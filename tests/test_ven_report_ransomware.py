"""VenStatusGenerator wires ransomware posture into module_results."""
from __future__ import annotations

import types
from unittest.mock import MagicMock


def _wl(href, host, sev):
    return {
        "href": href, "hostname": host,
        "os_id": "win-x86_64-server", "enforcement_mode": "selective",
        "interfaces": [], "labels": [],
        "agent": {"status": {"status": "active", "hours_since_last_heartbeat": 0.1,
                             "security_policy_sync_state": "synced",
                             "last_heartbeat_on": "2026-06-01T00:00:00Z",
                             "agent_version": "21.5"}},
        "risk_summary": {"ransomware": {"workload_exposure_severity": sev,
                                        "ransomware_protection_percent": 0.0}},
    }


_WORKLOADS = [_wl("/w/dc", "dc", "critical")]


def _make_cm():
    return types.SimpleNamespace(config={"settings": {"timezone": "UTC"}})


def _make_api():
    api = MagicMock()
    api.fetch_managed_workloads.return_value = _WORKLOADS
    api.get_workload.return_value = {"services": {"open_service_ports": [
        {"port": 3389, "protocol": 6, "process_name": "svchost.exe",
         "win_service_name": "TermService", "user": "SYSTEM"}]}}
    api.get_workload_risk_details.return_value = {"risk_details": {"ransomware": {"details": [
        {"port": 3389, "proto": 6, "name": "S-RDP", "severity": "critical",
         "port_status": "listening", "protection_state": "unprotected"}]}}}
    return api


def _generate(tmp_path, api):
    from src.report.ven_status_generator import VenStatusGenerator
    gen = VenStatusGenerator(_make_cm(), api_client=api)
    return gen.generate(output_dir=str(tmp_path))


def test_ransomware_posture_key_present(tmp_path):
    result = _generate(tmp_path, _make_api())
    assert "ransomware_posture" in result.module_results
    rp = result.module_results["ransomware_posture"]
    assert rp["kpi"]["by_exposure"]["critical"] == 1
    assert rp["per_ven"][0]["hostname"] == "dc"
    assert rp["ports"][0]["process"] == "TermService"


def test_skipped_when_pce_lacks_risk_summary(tmp_path):
    api = _make_api()
    api.fetch_managed_workloads.return_value = [
        {**_WORKLOADS[0], "risk_summary": None}]
    result = _generate(tmp_path, api)
    assert "ransomware_posture" not in result.module_results


def test_section_renders_tables(tmp_path):
    from src.report.exporters.ven_html_exporter import VenHtmlExporter
    result = _generate(tmp_path, _make_api())
    html_out = VenHtmlExporter(result.module_results, df=result.dataframe,
                               lang="en").export(str(tmp_path))
    page = open(html_out, encoding="utf-8").read()
    assert "Ransomware Exposure &amp; High-Risk Open Ports" in page or \
           "Ransomware Exposure & High-Risk Open Ports" in page
    assert "TermService" in page
    assert "ransomware-posture" in page


def test_section_absent_without_data(tmp_path):
    from src.report.exporters.ven_html_exporter import VenHtmlExporter
    api = _make_api()
    api.fetch_managed_workloads.return_value = [
        {**_WORKLOADS[0], "risk_summary": None}]
    result = _generate(tmp_path, api)
    html_out = VenHtmlExporter(result.module_results, df=result.dataframe,
                               lang="en").export(str(tmp_path))
    page = open(html_out, encoding="utf-8").read()
    assert "ransomware-posture" not in page
