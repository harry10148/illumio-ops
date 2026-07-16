"""整合頁 Job 健康表格卡（靜態字串斷言，比照本 repo JS 測試慣例）。"""
from pathlib import Path

_JS = Path("src/static/js/integrations.js")
_EN = Path("src/i18n_en.json")
_ZH = Path("src/i18n_zh_TW.json")


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
