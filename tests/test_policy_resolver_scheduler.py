"""Scheduler must recognise the policy_resolver report type (prune + subject)."""
from __future__ import annotations

import os

import src.report_scheduler as rs
from src.report_scheduler import ReportScheduler


def test_prefix_registered():
    assert ReportScheduler._REPORT_PREFIXES["policy_resolver"] == \
        "Illumio_Policy_Resolver_"


def test_prune_by_count_handles_policy_resolver(tmp_path):
    # Create 3 matching files; keep 1.
    for i in range(3):
        (tmp_path / f"Illumio_Policy_Resolver_2026-06-0{i+1}_0900.html").write_text("{}")
    sched = rs.ReportScheduler.__new__(rs.ReportScheduler)
    sched._prune_by_count(str(tmp_path), "policy_resolver", 1)
    remaining = [f for f in os.listdir(tmp_path)
                 if f.startswith("Illumio_Policy_Resolver_")]
    assert len(remaining) == 1
