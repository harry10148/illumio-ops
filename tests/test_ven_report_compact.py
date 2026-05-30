"""VEN status report: compact columns for print/PDF.

Verifies the column-slimming work:
  - Role / App dropped from the display tables (status report ≠ segmentation report)
  - last_heartbeat / policy_received rendered as compact relative time
  - paired_at rendered date-only
  - IP list truncated at the HTML display layer (full value preserved in title)
"""
import datetime
import re
import types

import pandas as pd

from src.report.ven_status_generator import VenStatusGenerator, _rel_time


def _gen(lang="zh_TW"):
    cm = types.SimpleNamespace(config={"settings": {"timezone": "Asia/Taipei"}})
    g = VenStatusGenerator(cm, api_client=object())
    g._lang = lang
    g._detail_level = "full"
    return g


def _workload(host, hb_iso, paired_iso="2024-07-03T11:43:00Z"):
    return {
        "hostname": host,
        "interfaces": [{"address": "192.168.10.20"}, {"address": "10.0.0.5"}],
        "labels": [{"key": "role", "value": "Web"}, {"key": "app", "value": "ops"},
                   {"key": "env", "value": "Kubernetes"}, {"key": "loc", "value": "TP"}],
        "agent": {"status": {
            "status": "active",
            "hours_since_last_heartbeat": 0.2,
            "security_policy_sync_state": "synced",
            "last_heartbeat_on": hb_iso,
            "security_policy_refresh_at": "2026-05-29T10:20:00Z",
            "managed_since": paired_iso,
            "agent_version": "21.5.35",
        }},
    }


def test_display_columns_drop_role_and_app():
    g = _gen()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    df = g._build_dataframe([_workload("k8s-node01", now)])
    res = g._analyze(df)
    online = res["online"]
    cols = list(online.columns)
    assert "Role" not in cols and "App" not in cols, cols
    assert cols == ["Hostname", "IP", "Env", "Loc", "Policy Sync",
                    "Last Heartbeat", "Policy Received", "Paired At", "VEN Version"], cols


def test_heartbeat_is_relative_and_paired_is_date_only():
    g = _gen()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    df = g._build_dataframe([_workload("k8s-node01", now, paired_iso="2024-07-03T11:43:00Z")])
    res = g._analyze(df)
    row = res["online"].iloc[0]
    # Relative time: compact unit-only (e.g. '3m', '2h', '19d'), no "(UTC", no full ISO
    hb = str(row["Last Heartbeat"])
    assert re.fullmatch(r"(now|\d+[mhd])", hb), hb
    assert "(UTC" not in hb and "T" not in hb, hb
    # Paired At: date-only YYYY-MM-DD
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row["Paired At"])), row["Paired At"]


def test_rel_time_units():
    now = datetime.datetime(2026, 5, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)
    f = lambda mins: _rel_time((now - datetime.timedelta(minutes=mins)).isoformat(), now)
    assert f(3) == "3m"
    assert f(180) == "3h"
    assert f(3 * 1440) == "3d"
    assert f(0) == "now"
    # empty / unparseable → ""
    assert _rel_time("", now) == ""
