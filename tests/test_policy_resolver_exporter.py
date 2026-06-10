"""Tests for the policy-resolver JSON + CSV exporter."""
from __future__ import annotations

import json
import os
import zipfile

from src.report.exporters.policy_resolver_exporter import PolicyResolverExporter


def _results():
    return {
        "rulesets": {
            "App-Tier": [
                {"ruleset_name": "App-Tier", "rule_href": "/sec_rules/1",
                 "src_ip": "10.0.1.5", "dst_ip": "10.0.2.7", "port": 443,
                 "protocol": "TCP", "src_kind": "label", "dst_kind": "label",
                 "service_name": ""},
            ],
        },
        "record_count": 1,
    }


def test_json_export_writes_per_ruleset_list(tmp_path):
    out = PolicyResolverExporter(_results(), lang="en").export_json(str(tmp_path))
    assert os.path.exists(out)
    data = json.load(open(out))
    assert data["rulesets"]["App-Tier"][0]["dst_ip"] == "10.0.2.7"


def test_csv_export_writes_zip_with_rows(tmp_path):
    out = PolicyResolverExporter(_results(), lang="en").export_csv(str(tmp_path))
    assert out.endswith(".zip")
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert any(n.endswith(".csv") for n in names)
        body = zf.read(names[0]).decode()
        assert "10.0.2.7" in body and "443" in body


def test_export_default_returns_both(tmp_path):
    paths = PolicyResolverExporter(_results(), lang="en").export(str(tmp_path))
    # export() returns the JSON path (primary); CSV alongside.
    assert os.path.exists(paths)
