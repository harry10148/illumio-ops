def test_get_traffic_flows_async_honors_until():
    from src.api_client import ApiClient

    captured = {}
    client = ApiClient.__new__(ApiClient)  # 跳過建構子（不碰網路/config）

    def fake_fetch(start_time_str, end_time_str, rate_limit=False, **kw):
        captured["start"] = start_time_str
        captured["end"] = end_time_str
        return []

    client.fetch_traffic_for_report = fake_fetch
    client.get_traffic_flows_async(
        since="2026-07-01T00:00:00+00:00", until="2026-07-02T00:00:00+00:00")
    assert captured["end"] == "2026-07-02T00:00:00+00:00"
    assert captured["start"] == "2026-07-01T00:00:00+00:00"
