"""發現與行動單章（spec B1）：行動矩陣為主軸、三層舊章移除。"""
from src.report.exporters.html_exporter import SecurityRiskHtmlExporter
from src.report.exporters.report_i18n import STRINGS


def _results():
    return {
        "mod12": {
            "kpis": [],
            "key_findings": [{"severity": "HIGH", "finding": "Coverage 40% (gap 12%)",
                              "action": "Prioritise policy authoring"}],
            "action_matrix": [{"action_code": "LOCK_BOUNDARY_PORTS", "count": 3,
                               "action": "Lock down boundary ports", "severity": "CRITICAL",
                               "apps": ["web (prod)", "db (prod)"], "flow_total": 450}],
            "boundary_breaches": [{"severity": "CRITICAL", "finding": "x", "action": "y"}],
            "suspicious_pivot_behavior": [], "blast_radius": [], "blind_spots": [],
        },
        "findings": [],
    }


def test_single_actions_chapter_renders():
    html = SecurityRiskHtmlExporter(_results(), lang="en").build()
    assert 'id="findings"' in html                       # 錨點沿用
    assert STRINGS["rpt_tr_findings_actions"]["en"] in html
    assert "LOCK_BOUNDARY_PORTS" in html
    assert "CRITICAL" in html                            # severity 掛在行動列
    assert "web (prod)" in html                          # 影響範圍
    assert "450" in html                                 # 量化證據
    assert "Coverage 40%" in html                        # key_findings 併入為行動列


def test_old_three_layers_gone():
    html = SecurityRiskHtmlExporter(_results(), lang="en").build()
    assert STRINGS["rpt_tr_attack_summary"]["en"] not in html      # 五區塊章移除
    assert STRINGS["rpt_key_findings"]["en"] not in html           # hero 關鍵發現移除
