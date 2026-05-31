import types
import pandas as pd


def test_ven_generate_produces_trend_deltas(tmp_path):
    from src.report.ven_status_generator import VenStatusGenerator
    cm = types.SimpleNamespace(config={"settings": {"timezone": "UTC"}})

    class _Api:
        def fetch_managed_workloads(self):
            return [{"hostname": "h1", "interfaces": [{"address": "10.0.0.1"}], "labels": [],
                     "agent": {"status": {"status": "active", "hours_since_last_heartbeat": 0.1,
                                          "security_policy_sync_state": "active",
                                          "last_heartbeat_on": "2026-05-31T00:00:00Z",
                                          "agent_version": "21.5"}}}]
    g = VenStatusGenerator(cm, api_client=_Api())
    # First run: establishes baseline (no prior → deltas may be empty)
    r1 = g.generate(lang="en", output_dir=str(tmp_path))
    # Second run: a prior snapshot now exists → deltas computed
    r2 = g.generate(lang="en", output_dir=str(tmp_path))
    assert "_trend_deltas" in r2.module_results
    assert isinstance(r2.module_results["_trend_deltas"], list)
