import types
import pandas as pd


def test_concern_card_renders_severity_and_recommendation():
    from src.report.exporters.concern_card import render_concern_cards
    items = [{"risk": "CRITICAL", "event_type": "agent.tampering", "count": 3,
              "summary": "Firewall tampered", "actors": ["admin@lab"], "targets": [],
              "resources": [], "src_ips": ["10.0.0.1"],
              "recommendation": "Investigate workload compromise"}]
    html = render_concern_cards(items, lang="en")
    assert "risk-CRITICAL" in html
    assert "agent.tampering" in html
    assert "Investigate workload compromise" in html
    assert render_concern_cards([], lang="en") == ""   # empty → no markup


def test_concern_card_sort_order():
    """CRITICAL sorts before HIGH sorts before LOW."""
    from src.report.exporters.concern_card import render_concern_cards
    items = [
        {"risk": "LOW", "event_type": "low.event", "count": 1, "summary": "", "actors": [], "src_ips": []},
        {"risk": "CRITICAL", "event_type": "critical.event", "count": 2, "summary": "", "actors": [], "src_ips": []},
        {"risk": "HIGH", "event_type": "high.event", "count": 3, "summary": "", "actors": [], "src_ips": []},
    ]
    html = render_concern_cards(items, lang="en")
    assert html.index("critical.event") < html.index("high.event") < html.index("low.event")


def test_concern_card_unknown_risk_does_not_raise():
    """Unknown risk level falls back gracefully."""
    from src.report.exporters.concern_card import render_concern_cards
    items = [{"risk": "UNKNOWN_LEVEL", "event_type": "x", "count": 1, "summary": "", "actors": [], "src_ips": []}]
    html = render_concern_cards(items, lang="en")
    assert "x" in html  # rendered without raising


def test_ven_status_chart_is_bar_not_pie(tmp_path):
    """VEN Status Distribution chart must be bar, not pie.

    Plotly serialises trace data before layout (which contains the title), so we
    search the Plotly.newPlot call block rather than the text after the title.
    """
    import re
    import pandas as pd
    from src.report.exporters.ven_html_exporter import VenHtmlExporter

    results = {
        "kpis": [],
        "generated_at": "2026-05-31T00:00:00Z",
        "online": pd.DataFrame([{"hostname": f"h{i}", "ip": "10.0.0.1"} for i in range(15)]),
        "offline": pd.DataFrame([{"hostname": "off1", "ip": "10.0.0.2"}]),
        "lost_today": pd.DataFrame(),
        "lost_yesterday": pd.DataFrame(),
        "_trend_deltas": [],
    }
    html_out = VenHtmlExporter(results, lang="en")._build()
    assert "VEN Status Distribution" in html_out

    # Plotly serialises trace data at the START of Plotly.newPlot() — within
    # the first ~1000 chars of the call.  The layout title follows after.
    # The Plotly JS bundle contains schema entries like "pie":[{"type":"pie"}]
    # which are NOT trace data; those appear thousands of chars after newPlot.
    # We therefore search only the first 1000 chars of each newPlot block for
    # the actual trace type.
    newplot_blocks = [html_out[m.start(): m.start() + 1000]
                      for m in re.finditer(r"Plotly\.newPlot\(", html_out)]
    # At least one block must declare a bar trace (the VEN Status chart)
    assert any('"type":"bar"' in b or '"type": "bar"' in b for b in newplot_blocks), \
        "No bar chart found in any Plotly.newPlot block"
    # No newPlot block should declare a pie trace as the first/primary trace
    for b in newplot_blocks:
        assert '"type":"pie"' not in b and '"type": "pie"' not in b, \
            f"A pie trace was found in a Plotly.newPlot block: {b[:200]}"


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


def test_network_inventory_cover_distinct_and_no_grade(monkeypatch):
    # Build the traffic report with profile=network_inventory and assert the cover
    # title differs from security and no maturity grade block is emitted.
    from src.report.exporters.cover_page import build_cover_page
    inv = build_cover_page(title="Network Inventory", report_type="Network Inventory",
                           lang="en")   # no maturity_grade kwarg
    assert "Network Inventory" in inv
    assert "report-cover-grade" not in inv   # grade block suppressed when no grade passed
