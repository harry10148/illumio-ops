"""Metadata sidecars for the four report types that used to write none (#15).

`/api/reports` (src/gui/routes/reports.py) reads `<report>.metadata.json` for
each listed artifact to fill report_type / summary / execution_stats. Only the
traffic family, audit, policy_usage, rule_hit_count and readiness wrote one, so
ven_status / policy_diff / policy_resolver / app_summary cards rendered blank.

The write must MERGE: report_scheduler._stamp_schedule_id() also owns a key in
the same file (`schedule_id`, which per-schedule retention prunes by). A
wholesale write would turn a display bug into a retention data-loss bug.
"""
from __future__ import annotations

import datetime
import json
import os
import types
from datetime import timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd

from src.report.report_metadata import write_metadata_sidecar


def _sidecar(path: str) -> dict:
    side = path + ".metadata.json"
    assert os.path.isfile(side), f"no sidecar written for {os.path.basename(path)}"
    with open(side, encoding="utf-8") as fh:
        return json.load(fh)


# ── the shared helper: merge semantics ──────────────────────────────────────

def test_helper_merge_preserves_existing_schedule_id(tmp_path):
    """A sidecar already stamped by the scheduler keeps its schedule_id.

    Guards the ordering-independence of the two producers: whichever writes
    second must not drop the other's keys.
    """
    report = tmp_path / "Illumio_Report.html"
    report.write_text("<html></html>", encoding="utf-8")
    side = tmp_path / "Illumio_Report.html.metadata.json"
    side.write_text(json.dumps({"schedule_id": "sched-42"}), encoding="utf-8")

    write_metadata_sidecar(str(report), {"report_type": "ven_status",
                                         "summary": "VEN total 3"})

    data = json.loads(side.read_text(encoding="utf-8"))
    assert data["schedule_id"] == "sched-42", \
        "merge clobbered the scheduler's schedule_id — per-schedule retention breaks"
    assert data["report_type"] == "ven_status"
    assert data["summary"] == "VEN total 3"


def test_helper_overwrites_its_own_keys(tmp_path):
    """Merge is not append: the payload wins on shared keys."""
    report = tmp_path / "r.html"
    side = tmp_path / "r.html.metadata.json"
    side.write_text(json.dumps({"report_type": "stale", "schedule_id": "s1"}),
                    encoding="utf-8")
    write_metadata_sidecar(str(report), {"report_type": "policy_diff"})
    data = json.loads(side.read_text(encoding="utf-8"))
    assert data["report_type"] == "policy_diff"
    assert data["schedule_id"] == "s1"


def test_helper_tolerates_corrupt_existing_sidecar(tmp_path):
    """An unreadable sidecar is replaced, not propagated as an exception.

    /api/reports already treats a bad sidecar as {}; the writer matches.
    """
    report = tmp_path / "r.html"
    side = tmp_path / "r.html.metadata.json"
    side.write_text("{not json", encoding="utf-8")
    write_metadata_sidecar(str(report), {"report_type": "app_summary"})
    assert json.loads(side.read_text(encoding="utf-8"))["report_type"] == "app_summary"


# ── ven_status ──────────────────────────────────────────────────────────────

def _ven_workload(host="ven-1", minutes_ago=5):
    hb = datetime.datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {
        "hostname": host,
        "interfaces": [{"address": "10.0.0.5"}],
        "labels": [],
        "agent": {"status": {
            "status": "active",
            "security_policy_sync_state": "synced",
            "last_heartbeat_on": hb.isoformat(),
            "security_policy_refresh_at": hb.isoformat(),
            "managed_since": "2024-01-01T00:00:00Z",
            "agent_version": "21.5.35",
        }},
    }


def _ven_result():
    from src.report.ven_status_generator import VenStatusGenerator, VenStatusResult
    cm = types.SimpleNamespace(config={"settings": {"timezone": "UTC"}})
    gen = VenStatusGenerator(cm, api_client=object())
    gen._lang = "en"
    gen._detail_level = "full"
    df = gen._build_dataframe([_ven_workload("ven-1"), _ven_workload("ven-2")])
    return gen, VenStatusResult(record_count=len(df), module_results=gen._analyze(df),
                                dataframe=df)


def test_ven_status_export_writes_sidecar_for_every_format(tmp_path):
    gen, result = _ven_result()
    paths = gen.export(result, fmt="all", output_dir=str(tmp_path), lang="en")
    assert paths, "ven export produced no files"
    for path in paths:
        meta = _sidecar(path)
        assert meta["report_type"] == "ven_status", path
        assert meta["summary"], path
    html = next(p for p in paths if p.endswith(".html"))
    assert _sidecar(html)["record_count"] == 2
    assert _sidecar(html)["file_format"] == "html"


# ── policy_diff ─────────────────────────────────────────────────────────────

def _diff_results():
    rs = pd.DataFrame([{
        "change_type": "modified", "ruleset_name": "RS-A", "ruleset_id": "1",
        "field": "enabled", "draft_value": "False", "active_value": "True",
        "last_actor": "bob", "last_changed": "2026-06-05T12:00:00Z",
    }])
    return {"ruleset_changes": rs, "rule_changes": pd.DataFrame(),
            "summary": {"rulesets_added": 0, "rulesets_removed": 0,
                        "rulesets_modified": 1, "rules_added": 2,
                        "rules_removed": 0, "rules_modified": 0,
                        "total_changes": 3}}


def test_policy_diff_export_writes_sidecar(tmp_path):
    from src.report.exporters.policy_diff_html_exporter import PolicyDiffHtmlExporter
    path = PolicyDiffHtmlExporter(_diff_results(), lang="en").export(str(tmp_path))
    meta = _sidecar(path)
    assert meta["report_type"] == "policy_diff"
    assert meta["summary"]
    assert meta["record_count"] == 3


# ── policy_resolver ─────────────────────────────────────────────────────────

def _resolver_results():
    return {
        "rulesets": {"App-Tier": [
            {"ruleset_name": "App-Tier", "rule_href": "/sec_rules/1",
             "src_ip": "10.0.1.5", "dst_ip": "10.0.2.7", "port": 443,
             "protocol": "TCP", "src_kind": "label", "dst_kind": "label",
             "service_name": ""},
        ]},
        "record_count": 1,
    }


def test_policy_resolver_export_writes_sidecar_for_json_and_csv(tmp_path):
    from src.report.exporters.policy_resolver_exporter import PolicyResolverExporter
    paths = PolicyResolverExporter(_resolver_results(), lang="en").export(str(tmp_path))
    assert len(paths) == 2
    for path in paths:
        meta = _sidecar(path)
        assert meta["report_type"] == "policy_resolver", path
        assert meta["summary"], path
        assert meta["record_count"] == 1, path


def test_policy_resolver_sidecar_discloses_truncation(tmp_path):
    """Row-cap truncation must be visible in the summary, not silent."""
    from src.report.exporters.policy_resolver_exporter import PolicyResolverExporter
    results = _resolver_results()
    results.update({"truncated": True, "rows_omitted": 12, "row_cap": 50000,
                    "truncated_rulesets": ["App-Tier"]})
    path = PolicyResolverExporter(results, lang="en").export_json(str(tmp_path))
    meta = _sidecar(path)
    assert meta["truncated"] is True
    assert "12" in meta["summary"], meta["summary"]


# ── app_summary ─────────────────────────────────────────────────────────────

def test_app_summary_export_writes_sidecar(tmp_path):
    from src.report.exporters.app_summary_html_exporter import AppSummaryHtmlExporter
    results = {"app": "DB", "env": "prod", "empty": True}
    path = AppSummaryHtmlExporter(results, lang="en").export(str(tmp_path))
    meta = _sidecar(path)
    assert meta["report_type"] == "app_summary"
    assert "DB" in meta["summary"], meta["summary"]


def test_app_summary_sidecar_carries_flow_count(tmp_path):
    from src.report.app_summary_report import AppSummaryReport
    from src.report.exporters.app_summary_html_exporter import AppSummaryHtmlExporter
    # Column set mirrors tests/test_app_summary_report.py::_row — the module
    # subset (mod01/02/03 + app_baseline) requires all of them.
    df = pd.DataFrame([{
        "src_app": "Web", "src_env": "P", "dst_app": "DB", "dst_env": "P",
        "port": 3306, "proto": "TCP", "policy_decision": "allowed",
        "num_connections": 5, "src_ip": "10.0.0.1", "dst_ip": "10.0.0.5",
        "src_managed": True, "dst_managed": True, "bytes_total": 0,
        "first_detected": pd.Timestamp("2026-01-01"),
        "last_detected": pd.Timestamp("2026-01-02"),
    }])
    rep = AppSummaryReport(cm=MagicMock(), api_client=MagicMock())
    with patch.object(rep, "_fetch_estate_df", return_value=df):
        results = rep.build(app="DB", lang="en")
    path = AppSummaryHtmlExporter(results, lang="en").export(str(tmp_path))
    meta = _sidecar(path)
    assert meta["report_type"] == "app_summary"
    assert meta["record_count"] == 1, meta


# ── end-to-end merge: real exporter over a scheduler-stamped sidecar ─────────

def test_policy_diff_export_merges_over_existing_schedule_id(tmp_path, monkeypatch):
    """The real call site (not just the helper) must merge.

    Pins the scheduler-stamps-first ordering as safe, so a future reordering of
    _stamp_schedule_id relative to generation cannot silently drop the stamp.
    """
    from src.report.exporters.policy_diff_html_exporter import PolicyDiffHtmlExporter
    exporter = PolicyDiffHtmlExporter(_diff_results(), lang="en")
    real_write = write_metadata_sidecar

    def _stamp_then_write(report_path, payload):
        side = report_path + ".metadata.json"
        with open(side, "w", encoding="utf-8") as fh:
            json.dump({"schedule_id": "sched-7"}, fh)
        real_write(report_path, payload)

    monkeypatch.setattr(
        "src.report.exporters.policy_diff_html_exporter.write_metadata_sidecar",
        _stamp_then_write)
    path = exporter.export(str(tmp_path))
    meta = _sidecar(path)
    assert meta["schedule_id"] == "sched-7"
    assert meta["report_type"] == "policy_diff"
