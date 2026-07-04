"""VEN report HTML Online 章：明細改為計數摘要 + online 桶限定版本分布。

spec K2 範圍裁決：只改 HTML Online 章渲染；_analyze 的 online DataFrame、
XLSX Online sheet、CSV 全列明細保持不動（見 test_xlsx_content_ven.py 護欄）。
"""
import types
from unittest.mock import MagicMock


def _workload(host, minutes_ago, version):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    hb = now - timedelta(minutes=minutes_ago)
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
            "agent_version": version,
        }},
    }


# 3 台 online：2 台 21.5.35、1 台 21.5.40；1 台 offline（心跳 2 小時前）。
_WORKLOADS = [
    _workload("online-a", minutes_ago=5, version="21.5.35"),
    _workload("online-b", minutes_ago=6, version="21.5.35"),
    _workload("online-c", minutes_ago=7, version="21.5.40"),
    _workload("offline-x", minutes_ago=120, version="21.5.35"),
]


def _make_cm():
    return types.SimpleNamespace(config={"settings": {"timezone": "UTC"}})


def _generate(tmp_path):
    from src.report.ven_status_generator import VenStatusGenerator
    api = MagicMock()
    api.fetch_managed_workloads.return_value = _WORKLOADS
    gen = VenStatusGenerator(_make_cm(), api_client=api)
    return gen.generate(output_dir=str(tmp_path))


def _render(tmp_path):
    from src.report.exporters.ven_html_exporter import VenHtmlExporter
    result = _generate(tmp_path)
    html_out = VenHtmlExporter(result.module_results, df=result.dataframe,
                               lang="en").export(str(tmp_path))
    return open(html_out, encoding="utf-8").read()


def test_online_chapter_shows_version_counts_not_hostnames(tmp_path):
    page = _render(tmp_path)
    online_start = page.index('id="online"')
    offline_start = page.index('id="offline"')
    online_section = page[online_start:offline_start]

    # 計數摘要：兩個版本各自的計數都要出現
    assert "21.5.35" in online_section
    assert "21.5.40" in online_section
    assert "2" in online_section  # 21.5.35 count
    assert "1" in online_section  # 21.5.40 count

    # 判別性斷言：online 主機的逐台明細（hostname）不應再出現在 Online 章
    assert "online-a" not in online_section
    assert "online-b" not in online_section
    assert "online-c" not in online_section


def test_offline_chapter_still_has_hostnames(tmp_path):
    page = _render(tmp_path)
    offline_start = page.index('id="offline"')
    lost_today_start = page.index('id="lost-today"')
    offline_section = page[offline_start:lost_today_start]
    assert "offline-x" in offline_section


def test_online_chapter_has_detail_note(tmp_path):
    page = _render(tmp_path)
    assert "Per-host online detail is available in the XLSX/CSV export." in page
