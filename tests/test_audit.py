import datetime
from unittest.mock import MagicMock

from src.report.audit_generator import AuditGenerator


def _sample_events():
    now = datetime.datetime.now(datetime.timezone.utc)
    return [
        {
            "timestamp": (now - datetime.timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "event_type": "agent.tampering",
            "severity": "error",
            "status": "failure",
            "created_by": {"agent": {"hostname": "web-01"}},
            "resource": {"workload": {"hostname": "web-01"}},
            "action": {"api_method": "POST", "api_endpoint": "/orgs/1/agents/22/tampering", "src_ip": "10.10.10.10"},
        },
        {
            "timestamp": (now - datetime.timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            "event_type": "user.update",
            "severity": "info",
            "status": "success",
            "created_by": {"user": {"username": "admin@lab.local"}},
            "resource": {"user": {"username": "analyst@lab.local"}},
            "action": {"api_method": "PUT", "api_endpoint": "/orgs/1/users/2", "src_ip": "10.10.10.20"},
        },
        {
            "timestamp": (now - datetime.timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
            "event_type": "request.authentication_failed",
            "severity": "error",
            "status": "failure",
            "created_by": {"system": True},
            "action": {"api_method": "POST", "api_endpoint": "/orgs/1/users/login", "src_ip": "203.0.113.10"},
            "notifications": [
                {
                    "notification_type": "request.authentication_failed",
                    "info": {"supplied_username": "analyst@lab.local"},
                }
            ],
        },
        {
            "timestamp": (now - datetime.timedelta(minutes=20)).isoformat().replace("+00:00", "Z"),
            "event_type": "sec_policy.create",
            "severity": "warning",
            "status": "success",
            "created_by": {"user": {"username": "admin@lab.local"}},
            "action": {"api_method": "POST", "api_endpoint": "/orgs/1/sec_policy", "src_ip": "10.10.10.30"},
            "resource_changes": [
                {
                    "change_type": "create",
                    "resource": {
                        "sec_policy": {
                            "href": "/orgs/1/sec_policy/516",
                            "commit_message": "Promote rule changes",
                            "modified_objects": {
                                "rule_sets": {"/orgs/1/sec_policy/draft/rule_sets/471": {}},
                                "sec_rules": {"/orgs/1/sec_policy/draft/rule_sets/471/sec_rules/9": {}},
                            },
                        }
                    },
                    "changes": {
                        "version": {"before": 516, "after": 517},
                        "commit_message": {"before": "", "after": "Promote rule changes"},
                        "workloads_affected": {"before": 0, "after": 88},
                        "object_counts": {"before": {}, "after": {"rule_sets": 1, "sec_rules": 2}},
                    },
                }
            ],
        },
    ]


def _generator():
    cm = MagicMock()
    cm.config = {"report": {"output_dir": "reports"}}
    return AuditGenerator(cm, api_client=None, config_dir="config")


def test_audit_build_dataframe_uses_normalized_parser_fields():
    df = _generator()._build_dataframe(_sample_events())

    assert {"actor", "target_name", "resource_name", "action", "parser_notes", "parser_note_count", "known_event_type", "supplied_username"}.issubset(df.columns)

    user_update = df[df["event_type"] == "user.update"].iloc[0]
    assert user_update["actor"] == "admin@lab.local"
    assert user_update["created_by"] == "admin@lab.local"
    assert user_update["target_name"] == "analyst@lab.local"
    assert user_update["action"] == "PUT /users/2"
    assert user_update["src_ip"] == "10.10.10.20"

    auth_failed = df[df["event_type"] == "request.authentication_failed"].iloc[0]
    assert auth_failed["supplied_username"] == "analyst@lab.local"
    assert auth_failed["notification_detail"]
    assert auth_failed["parser_note_count"] >= 0

    provision = df[df["event_type"] == "sec_policy.create"].iloc[0]
    assert int(provision["workloads_affected"]) == 88
    assert "Promote rule changes" in provision["change_detail"]
    assert provision["resource_name"]


def test_audit_pipeline_surfaces_parser_enrichment_in_modules():
    generator = _generator()
    df = generator._build_dataframe(_sample_events())
    result = generator._run_pipeline(df, "2026-04-01T00:00:00Z", "2026-04-08T00:00:00Z")

    mod00 = result.module_results["mod00"]
    mod02 = result.module_results["mod02"]
    mod03 = result.module_results["mod03"]

    per_user = mod02["per_user"]
    assert not per_user.empty
    assert "analyst@lab.local" in per_user["User"].tolist()

    failed_detail = mod02["failed_login_detail"]
    assert not failed_detail.empty
    assert "supplied_username" in failed_detail.columns
    assert "action" in failed_detail.columns

    provisions = mod03["provisions"]
    assert not provisions.empty
    assert "resource_name" in provisions.columns
    assert "change_detail" in provisions.columns
    assert mod03["high_impact_provisions"][0]["resource_name"]

    kpi_labels = {item["label"] for item in mod00["kpis"]}
    assert "Unknown Event Types" in kpi_labels
    assert "Parser Notes" in kpi_labels
