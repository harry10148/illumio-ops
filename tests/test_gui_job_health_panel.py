"""整合頁 Job 健康表格卡（靜態字串斷言，比照本 repo JS 測試慣例）。"""
from pathlib import Path

_JS = Path("src/static/js/integrations.js")
_EN = Path("src/i18n_en.json")
_ZH = Path("src/i18n_zh_TW.json")
_RS_JS = Path("src/static/js/rule-scheduler.js")
_HTML = Path("src/templates/index.html")
_DASH_JS = Path("src/static/js/dashboard.js")


def test_overview_pane_fetches_dashboard_overview():
    js = _JS.read_text(encoding="utf-8")
    assert "/api/dashboard/overview" in js


def test_job_health_table_card_present():
    js = _JS.read_text(encoding="utf-8")
    fn = js.split("function _buildOvJobHealth(", 1)[1].split("\nfunction ", 1)[0]
    for frag in ("gui_ov_job_health", "gui_jh_th_job", "gui_jh_th_last_run",
                 "gui_jh_th_status", "gui_jh_never_ran",
                 "table-container", "rule-table"):
        assert frag in fn, frag


def test_tls_card_present():
    js = _JS.read_text(encoding="utf-8")
    fn = js.split("function _buildOvTlsCard(", 1)[1].split("\nfunction ", 1)[0]
    assert "gui_ov_tls_cert" in fn
    assert "card-warn" in fn


def test_job_health_i18n_bilingual():
    import json
    en = json.loads(_EN.read_text(encoding="utf-8"))
    zh = json.loads(_ZH.read_text(encoding="utf-8"))
    for k in ("gui_ov_job_health", "gui_jh_th_job", "gui_jh_th_last_run",
              "gui_jh_th_status", "gui_jh_th_interval", "gui_jh_th_detail",
              "gui_jh_never_ran", "gui_jh_overdue", "gui_ov_tls_cert",
              "gui_ov_tls_days", "gui_ov_tls_expiring"):
        assert k in en and k in zh, k


def test_dashboard_tiles_show_staleness():
    """2026-07-13 觀測性 backlog task 6：ven/posture tile 需以 computed_at/
    generated_at 判斷 stale，凍結資料不能看起來像新鮮的。"""
    js = _DASH_JS.read_text(encoding="utf-8")
    assert "computed_at" in js
    assert "_ovStale" in js


def test_rule_scheduler_list_shows_last_run():
    """Rule scheduler table gets a per-schedule last-run column, mirroring the
    job health panel's never-ran/last-run treatment above."""
    js = _RS_JS.read_text(encoding="utf-8")
    html = _HTML.read_text(encoding="utf-8")
    assert "last_checked" in js
    assert "gui_rs_th_last_run" in html
    # Old 12-column colspan must be gone everywhere the schedules table's
    # placeholder rows are rendered (loading/error states), now 13 columns
    # after the last-run <th> was added.
    assert 'colspan="12"' not in js
    assert 'colspan="13"' in js
