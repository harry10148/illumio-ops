"""R2 gate：cache 部署上 event_overflow 不得是死碼。

背景：PCE 同步事件 API 碰到 max_results 時只回「最新」那批，較舊的事件永久
漏失。這個訊號原本只有 legacy pull（Analyzer._fetch_event_batch）會寫，而
pce_cache.enabled=true 的部署根本不走那條路——EventsIngestor 是唯一看得到
截斷的地方，卻只記一行 INFO，meta-alert 從來不會發。

本檔把整條鏈釘住：
  1. EventsIngestor 碰頂 → last_run_overflow（含 source 標記）＋ WARNING。
  2. async 補抓真的抽乾整個視窗 → 撤回訊號（不算資料遺失）。
  3. run_events_ingest → state.json 的 event_overflow。
  4. Analyzer 的 cache 分支只清 legacy 殘留，不得清掉 ingest 寫的訊號。
  5. save_state 不得用 cycle 起始快照把 ingest 剛寫的訊號整包蓋回去。
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest


# ─── 1/2: EventsIngestor 端的訊號 ───────────────────────────────────────────

def _ingestor(api, **kw):
    from src.pce_cache.ingestor_events import EventsIngestor
    ing = EventsIngestor(api=api, session_factory=MagicMock(),
                         watermark=MagicMock(), async_threshold=2, **kw)
    ing._insert_batch = MagicMock(return_value=0)
    return ing


def _events(n):
    return [{"href": f"/orgs/1/events/{i}", "timestamp": "2026-05-01T12:00:00Z"}
            for i in range(n)]


def test_events_cap_hit_records_overflow_and_warns(caplog):
    api = MagicMock()
    api.last_fetch_error = None
    api.get_events.return_value = _events(2)      # == async_threshold → 碰頂
    api.get_events_async.return_value = []        # stub（Phase 13 未實作）
    ing = _ingestor(api)

    with caplog.at_level(logging.WARNING, logger="src.pce_cache.ingestor_events"):
        ing.run_once()

    ovf = ing.last_run_overflow
    assert ovf, "碰頂未留下 overflow 訊號 → meta-alert 永遠不會發"
    assert ovf["raw_count"] == 2 and ovf["max_results"] == 2
    assert ovf["query_since"] and ovf["query_until"]
    assert ovf["source"] == "cache_ingest"
    assert any("hit cap" in r.message for r in caplog.records), \
        f"碰頂必須是 WARNING（資料遺失）；實得：{[r.message for r in caplog.records]}"


def test_events_cap_hit_cleared_when_async_drains_window():
    api = MagicMock()
    api.last_fetch_error = None
    api.get_events.return_value = _events(2)
    api.get_events_async.return_value = _events(9)   # async 沒有上限 → 真的抽乾
    ing = _ingestor(api)
    ing.run_once()
    assert ing.last_run_overflow is None


def test_events_no_cap_no_overflow():
    api = MagicMock()
    api.last_fetch_error = None
    api.get_events.return_value = _events(1)
    ing = _ingestor(api)
    ing.run_once()
    assert ing.last_run_overflow is None


# ─── 3: 排程 job 落盤 ───────────────────────────────────────────────────────

def _cm(tmp_path):
    cm = MagicMock()
    cfg = cm.models.pce_cache
    cfg.db_path = str(tmp_path / "cache.sqlite")
    cfg.async_threshold_events = 10000
    cm.models.siem.enabled = False
    return cm


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    import src.scheduler.jobs as jobs_mod
    sf = str(tmp_path / "logs" / "state.json")
    monkeypatch.setattr(jobs_mod, "_resolve_state_file", lambda: sf)
    return sf


def _run_events_ingest(cm, *, overflow, last_status="ok"):
    from src.scheduler.jobs import run_events_ingest
    with patch("src.scheduler.jobs._get_cache_engine"), \
         patch("sqlalchemy.orm.sessionmaker"), \
         patch("src.scheduler.jobs.ApiClient") as mock_api, \
         patch("src.pce_cache.watermark.WatermarkStore") as mock_wm_cls:
        mock_api.return_value.__enter__.return_value = MagicMock()
        mock_wm_cls.return_value.get.return_value = MagicMock(
            last_status=last_status, last_error="boom")
        with patch("src.pce_cache.ingestor_events.EventsIngestor") as mock_ing:
            mock_ing.return_value.run_once.return_value = 0
            mock_ing.return_value.last_run_overflow = overflow
            run_events_ingest(cm)


def test_run_events_ingest_persists_event_overflow(tmp_path, state_file):
    from src.state_store import load_state_file

    ovf = {"raw_count": 10000, "max_results": 10000, "query_since": "a",
           "query_until": "b", "source": "cache_ingest"}
    _run_events_ingest(_cm(tmp_path), overflow=ovf)
    assert load_state_file(state_file)["event_overflow"] == ovf


def test_run_events_ingest_clears_resolved_overflow(tmp_path, state_file):
    from src.state_store import load_state_file, update_state_file

    update_state_file(state_file, lambda s: {**s, "event_overflow": {"raw_count": 1}})
    _run_events_ingest(_cm(tmp_path), overflow=None)
    assert load_state_file(state_file)["event_overflow"] == {}


def test_failed_events_ingest_does_not_clobber_overflow(tmp_path, state_file):
    """抓取失敗對「有沒有截斷」毫無資訊，不得把未解除的紀錄清掉。"""
    from src.state_store import load_state_file, update_state_file

    live = {"raw_count": 10000, "source": "cache_ingest"}
    update_state_file(state_file, lambda s: {**s, "event_overflow": live})
    _run_events_ingest(_cm(tmp_path), overflow=None, last_status="error")
    assert load_state_file(state_file)["event_overflow"] == live


# ─── 4/5: Analyzer 端不得吃掉這個訊號 ──────────────────────────────────────

@pytest.fixture
def analyzer_state_file(tmp_path, monkeypatch):
    import src.analyzer as analyzer_mod
    sf = str(tmp_path / "state.json")
    monkeypatch.setattr(analyzer_mod, "STATE_FILE", sf)
    return sf


def _cache_analyzer():
    from src.analyzer import Analyzer
    sub = MagicMock()
    sub.poll_new_rows.side_effect = lambda limit=1000, processor=None: (
        processor([]) if processor else [])
    cm = MagicMock()
    cm.config = {"rules": []}
    return Analyzer(cm, MagicMock(), MagicMock(), subscriber_events=sub)


def test_cache_branch_keeps_ingest_written_overflow(analyzer_state_file):
    az = _cache_analyzer()
    az.save_state = MagicMock()
    ovf = {"raw_count": 10000, "max_results": 10000, "source": "cache_ingest"}
    az.state["event_overflow"] = dict(ovf)
    az._run_event_analysis()
    assert az.state["event_overflow"] == ovf, \
        "ingest 觀測到的截斷被 cache 分支清掉了 → meta-alert 永遠不會發"


def test_cache_branch_still_clears_legacy_overflow(analyzer_state_file):
    az = _cache_analyzer()
    az.save_state = MagicMock()
    az.state["event_overflow"] = {"raw_count": 5000, "source": "legacy_pull"}
    az._run_event_analysis()
    assert az.state["event_overflow"] == {}


def test_save_state_defers_event_overflow_to_disk(analyzer_state_file):
    """cycle 沒寫過 event_overflow 時必須讓給磁碟：ingest job 在本 cycle 期間
    寫入的訊號，不可以被 cycle 起始的快照整包回滾。"""
    from src.analyzer import Analyzer
    from src.state_store import load_state_file, update_state_file

    az = _cache_analyzer()   # 載入時磁碟上還沒有 event_overflow
    ovf = {"raw_count": 10000, "source": "cache_ingest"}
    update_state_file(analyzer_state_file, lambda s: {**s, "event_overflow": ovf})

    Analyzer.save_state(az)
    assert load_state_file(analyzer_state_file)["event_overflow"] == ovf


def test_save_state_writes_own_event_overflow_clear(analyzer_state_file):
    """反向：本 cycle 真的清掉了 legacy 殘留，就必須落盤（否則每小時重發）。"""
    from src.analyzer import Analyzer
    from src.state_store import load_state_file, update_state_file

    update_state_file(analyzer_state_file,
                      lambda s: {**s, "event_overflow": {"raw_count": 5000}})
    az = _cache_analyzer()
    az._run_event_analysis()
    Analyzer.save_state(az)
    assert load_state_file(analyzer_state_file)["event_overflow"] == {}
