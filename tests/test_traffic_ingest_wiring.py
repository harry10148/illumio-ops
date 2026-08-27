"""run_traffic_ingest 必須把使用者設定的 traffic filter 與抽樣比例交給 ingestor。

這條守的是 **wiring**，不是 filter 本身的邏輯（那由 test_traffic_filter*.py 管）。
分開守的理由：`TrafficIngestor.__init__` 的 `traffic_filter` 是 Optional 且會落到
`traffic_filter or TrafficFilter()` 的空預設，所以呼叫端漏傳時**沒有任何東西會壞**
——沒有例外、沒有紅燈，只是使用者在 GUI/CLI 設定的過濾條件被靜默忽略。
2026-08-27 查證：這條 wiring 自始就不存在（`git log -S'traffic_filter=' -- src/scheduler/jobs.py`
為空），exclude_src_ips / ports / protocols / actions 全部從未在 production 生效。
"""
from unittest.mock import patch

import pytest

from src.config_models import TrafficFilterSettings, TrafficSamplingSettings


class _FakeIngestor:
    """記下建構參數，run_once 回 0。"""

    SOURCE = "traffic"
    last_kwargs: dict = {}

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs
        self.last_run_overflow = None

    def run_once(self):
        return 0


class _FakeApi:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _run(monkeypatch, tmp_path, tf: TrafficFilterSettings, ts: TrafficSamplingSettings):
    from src.scheduler import jobs

    class _Cfg:
        db_path = str(tmp_path / "cache.sqlite")
        traffic_filter = tf
        traffic_sampling = ts
        async_threshold_events = 1
        flow_delta_enabled = True
        flow_obs_retention_hours = 6

    class _CM:
        class models:
            pce_cache = _Cfg()

        config: dict = {}

    _FakeIngestor.last_kwargs = {}
    monkeypatch.setattr("src.pce_cache.ingestor_traffic.TrafficIngestor", _FakeIngestor)
    monkeypatch.setattr("src.api_client.ApiClient", lambda cm: _FakeApi())
    monkeypatch.setattr(jobs, "_enabled_siem_destinations", lambda cm, kind: [])
    monkeypatch.setattr(jobs, "_record_ingest_pce_result", lambda *a, **k: None)
    monkeypatch.setattr(jobs, "_record_traffic_overflow", lambda *a, **k: None)

    class _WM:
        def get(self, _src):
            return None

    monkeypatch.setattr("src.pce_cache.watermark.WatermarkStore", lambda sf: _WM())
    jobs.run_traffic_ingest(_CM())
    return _FakeIngestor.last_kwargs


def test_configured_traffic_filter_reaches_the_ingestor(monkeypatch, tmp_path):
    """使用者設定的排除 IP / 埠 / 協定必須真的到達 ingestor。"""
    tf = TrafficFilterSettings(
        exclude_src_ips=["10.9.9.9"], ports=[443], protocols=["TCP"], actions=["allowed"]
    )
    kwargs = _run(monkeypatch, tmp_path, tf, TrafficSamplingSettings())

    got = kwargs.get("traffic_filter")
    assert got is not None, (
        "run_traffic_ingest 未傳 traffic_filter：TrafficIngestor 會落到空預設，"
        "使用者在 GUI/CLI 設定的過濾條件被靜默忽略"
    )
    # 用行為驗證而非讀私有屬性：被排除的來源 IP 必須被擋下。
    assert got.passes({"src_ip": "10.9.9.9", "port": 443, "protocol": "TCP", "action": "allowed"}) is False
    assert got.passes({"src_ip": "10.1.1.1", "port": 443, "protocol": "TCP", "action": "allowed"}) is True


def test_configured_sample_ratio_reaches_the_ingestor(monkeypatch, tmp_path):
    kwargs = _run(
        monkeypatch,
        tmp_path,
        TrafficFilterSettings(),
        TrafficSamplingSettings(sample_ratio_allowed=7),
    )
    assert kwargs.get("sample_ratio_allowed") == 7, (
        "run_traffic_ingest 未傳 sample_ratio_allowed：設定的抽樣比例被忽略"
    )


def test_default_actions_do_not_filter_anything():
    """空預設＝不過濾。

    先前預設是 ["blocked", "potentially_blocked"]，在 wiring 修好的那一刻會讓
    每一台未曾動過該設定的機器開始丟棄 allowed 流量——而頻寬與 top-talker 分析
    全都建立在 allowed 之上。且該清單也不是 decision 全集：dashboard 用的全集
    含 "unknown"，另有 "potentially_blocked_by_boundary"，寫死清單註定漂移。
    """
    from src.pce_cache.traffic_filter import TrafficFilter

    assert TrafficFilterSettings().actions == []
    f = TrafficFilter(**TrafficFilterSettings().model_dump())
    for decision in ("allowed", "blocked", "potentially_blocked",
                     "potentially_blocked_by_boundary", "unknown"):
        assert f.passes({"src_ip": "10.0.0.1", "port": 1, "protocol": "TCP",
                         "action": decision}) is True, decision
