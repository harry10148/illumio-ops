"""Task 6: PCE 契約小修包——POST 冪等重試、cancel 狀態、unknown decision、
CSV timeout、href 防護。每個測試對應 task-6-brief.md 規格條目。"""
from __future__ import annotations

import gzip
import io
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import orjson

from src.api.async_jobs import AsyncJobManager
from src.api.traffic_query import TrafficQueryBuilder


def _make_client(verify_ssl=False):
    from src.api_client import ApiClient
    cm = MagicMock()
    cm.config = {
        "api": {
            "url": "https://pce.example.com:8443",
            "org_id": "1",
            "key": "key",
            "secret": "secret",
            "verify_ssl": verify_ssl,
        }
    }
    return ApiClient(cm)


class TestRetryExcludesPost(unittest.TestCase):
    def test_retry_excludes_post(self):
        """urllib3 Retry adapter must not auto-retry POST (idempotency risk:
        provision/create 类端點在 read-timeout 後自動重試會重複執行)。"""
        client = _make_client()
        adapter = client._session.get_adapter("https://pce.example.com:8443")
        self.assertNotIn("POST", adapter.max_retries.allowed_methods)
        # 其餘方法仍應保留自動重試
        for m in ("GET", "HEAD", "PUT", "DELETE"):
            self.assertIn(m, adapter.max_retries.allowed_methods)


class TestPost429SingleRetry(unittest.TestCase):
    def _fake_resp(self, status, content=b"{}", headers=None):
        resp = MagicMock()
        resp.status_code = status
        resp.content = content
        resp.headers = headers or {}
        return resp

    def test_post_429_single_retry(self):
        """POST 收到 429 時讀 Retry-After 後單次重試；最終回傳重試後的回應。"""
        client = _make_client()
        resp_429 = self._fake_resp(429, headers={"Retry-After": "0"})
        resp_200 = self._fake_resp(200, content=b'{"ok":true}')
        client._session.request = MagicMock(side_effect=[resp_429, resp_200])

        with patch("time.sleep") as mock_sleep:
            status, body = client._request(
                "https://pce.example.com:8443/api/v2/orgs/1/traffic_flows/async_queries",
                method="POST",
                data={"a": 1},
                timeout=10,
            )

        self.assertEqual(status, 200)
        self.assertEqual(body, b'{"ok":true}')
        self.assertEqual(client._session.request.call_count, 2)
        mock_sleep.assert_called_once()

    def test_post_429_stream_not_retried(self):
        """stream=True 的 POST 不涉入 429 手動重試（stream 只用於大檔下載路徑）。"""
        client = _make_client()
        resp_429 = self._fake_resp(429, headers={"Retry-After": "0"})
        client._session.request = MagicMock(return_value=resp_429)

        with patch("time.sleep") as mock_sleep:
            status, _ = client._request(
                "https://pce.example.com:8443/api/v2/whatever",
                method="POST",
                stream=True,
                timeout=10,
            )

        self.assertEqual(status, 429)
        self.assertEqual(client._session.request.call_count, 1)
        mock_sleep.assert_not_called()

    def test_post_429_second_429_not_retried_again(self):
        """重試恰一次：第二次仍 429 就回傳 429，不再有第三發。"""
        client = _make_client()
        resp_429a = self._fake_resp(429, headers={"Retry-After": "0"})
        resp_429b = self._fake_resp(429, content=b"still limited", headers={"Retry-After": "0"})
        client._session.request = MagicMock(side_effect=[resp_429a, resp_429b])

        with patch("time.sleep"):
            status, body = client._request(
                "https://pce.example.com:8443/api/v2/orgs/1/sec_policy",
                method="POST",
                data={"a": 1},
                timeout=10,
            )

        self.assertEqual(status, 429)
        self.assertEqual(body, b"still limited")
        self.assertEqual(client._session.request.call_count, 2)

    def test_post_429_retry_sends_same_body_and_headers(self):
        """重試必須帶與第一發完全相同的 body 與 headers（同一請求重送）。"""
        client = _make_client()
        resp_429 = self._fake_resp(429, headers={"Retry-After": "0"})
        resp_200 = self._fake_resp(200)
        client._session.request = MagicMock(side_effect=[resp_429, resp_200])

        with patch("time.sleep"):
            client._request(
                "https://pce.example.com:8443/api/v2/orgs/1/sec_policy",
                method="POST",
                data={"a": 1},
                headers={"X-Custom": "v"},
                timeout=10,
            )

        first, second = client._session.request.call_args_list
        self.assertEqual(first.kwargs["data"], second.kwargs["data"])
        self.assertEqual(first.kwargs["headers"], second.kwargs["headers"])

    def test_post_429_retry_after_clamped(self):
        """Retry-After 解析須夾限：inf/nan/非數值 fallback 2s、過大值上限 30s、
        負值下限 0——否則 time.sleep 會拋例外（違反 _request 不拋契約）或
        同步阻塞 GUI worker。"""
        cases = [
            ("0", 0.0),
            ("3600", 30.0),
            ("-5", 0.0),
            ("inf", 2.0),
            ("nan", 2.0),
            ("Wed, 21 Oct 2026 07:28:00 GMT", 2.0),
            (None, 2.0),
        ]
        for header_val, expected_sleep in cases:
            with self.subTest(retry_after=header_val):
                client = _make_client()
                headers = {} if header_val is None else {"Retry-After": header_val}
                resp_429 = self._fake_resp(429, headers=headers)
                resp_200 = self._fake_resp(200)
                client._session.request = MagicMock(side_effect=[resp_429, resp_200])

                with patch("time.sleep") as mock_sleep:
                    status, _ = client._request(
                        "https://pce.example.com:8443/api/v2/orgs/1/sec_policy",
                        method="POST",
                        data={"a": 1},
                        timeout=10,
                    )

                self.assertEqual(status, 200)
                mock_sleep.assert_called_once_with(expected_sleep)

    def test_get_429_not_retried_in_request_layer(self):
        """GET 的 429 重試交給 urllib3 Retry adapter；_request 本地邏輯不涉入，
        單一 mock 回應即代表只呼叫一次 session.request。"""
        client = _make_client()
        resp_429 = self._fake_resp(429, headers={"Retry-After": "0"})
        client._session.request = MagicMock(return_value=resp_429)

        with patch("time.sleep") as mock_sleep:
            status, _ = client._request(
                "https://pce.example.com:8443/api/v2/health",
                method="GET",
                timeout=10,
            )

        self.assertEqual(status, 429)
        self.assertEqual(client._session.request.call_count, 1)
        mock_sleep.assert_not_called()


class _FakeTrafficClient:
    """Minimal ApiClient stand-in for TrafficQueryBuilder poll tests
    (same shape as tests/test_traffic_query_async_poll.py::_FakeClient)."""

    def __init__(self, poll_states):
        self.base_url = "https://pce.test/api/v2/orgs/1"
        self.api_cfg = {"url": "https://pce.test"}
        self._poll_states = list(poll_states)
        self._poll_i = 0

    def _gz(self, records):
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as f:
            f.write(orjson.dumps(records))
        return buf.getvalue()

    def _request(self, url, method="GET", data=None, timeout=None, rate_limit=False):
        if method == "POST" and url.endswith("/async_queries"):
            return 202, orjson.dumps(
                {"href": "/orgs/1/traffic_flows/async_queries/1", "status": "queued"}
            )
        if url.endswith("/download"):
            return 200, self._gz([{"flow": 1}])
        state = self._poll_states[min(self._poll_i, len(self._poll_states) - 1)]
        self._poll_i += 1
        return 200, orjson.dumps({"status": state})


class TestPollTreatsCancelledAsFailure(unittest.TestCase):
    def test_poll_treats_cancelled_as_failure(self):
        """traffic_query.py 的 poll 迴圈遇到 status=cancelled 應立即視為失敗結束，
        不應一路等到 wall-clock deadline。monotonic 只給有限幾個時間點——若未修好、
        cancelled 沒被當作終態，迴圈會耗盡序列拋 StopIteration（快速失敗而非真的
        等 900 秒 wall-clock 才 timeout）。"""
        client = _FakeTrafficClient(["cancelled"])
        builder = TrafficQueryBuilder(client)
        times = iter([0.0, 1.0, 2.0, 3.0, 4.0])
        with patch("time.sleep"), patch(
            "src.api.traffic_query.time.monotonic", lambda: next(times)
        ):
            out = list(builder._submit_and_stream_async_query({"sources": {}}))
        self.assertEqual(out, [])
        # 只 poll 了一次就結束（未落到 deadline 迴圈裡繼續打轉）
        self.assertEqual(client._poll_i, 1)
        self.assertIn("cancelled", client.last_fetch_error)

    def test_async_jobs_wait_treats_cancel_requested_as_failure(self):
        """async_jobs.py 的 _wait_for_async_query 同型 poll 分支也要視
        cancel_requested 為失敗終態（修類不修点）。"""
        client = _make_client()
        with tempfile.TemporaryDirectory() as tmp_dir:
            client._state_file = f"{tmp_dir}/state.json"
            jobs_mgr = AsyncJobManager(client)
            poll_body = orjson.dumps({"status": "cancel_requested"})
            client._request = MagicMock(return_value=(200, poll_body))
            with patch("time.sleep"):
                result = jobs_mgr._wait_for_async_query("/orgs/1/traffic_flows/async_queries/1")
        self.assertEqual(result.get("status"), "cancel_requested")
        # 第一次 poll 就中止，不應繼續打到 max_polls
        self.assertEqual(client._request.call_count, 1)


class TestDefaultPolicyDecisionsIncludeUnknown(unittest.TestCase):
    def test_default_policy_decisions_include_unknown(self):
        """不帶 policy_decisions 呼叫 fetch_traffic_for_report 時，預設值須含
        unknown（vendor 四值域：idle/快照模式與 Flowlink 未管理流量）。"""
        client = _FakeTrafficClient(["completed"])
        client.last_traffic_query_diagnostics = {}
        client.last_rule_usage_batch_stats = {}
        builder = TrafficQueryBuilder(client)

        captured = {}

        def fake_stream(start, end, pds, filters=None, compute_draft=False, rate_limit=False):
            captured["pds"] = pds
            return iter([])

        builder.execute_traffic_query_stream = fake_stream
        builder.fetch_traffic_for_report("2026-04-01T00:00:00Z", "2026-04-02T00:00:00Z")

        self.assertIn("unknown", captured["pds"])

    def test_export_csv_default_policy_decisions_include_unknown(self):
        """export_traffic_query_csv 不帶 policy_decisions 時，傳給
        _build_native_traffic_payload 的預設值也須含 unknown。"""
        client = _FakeTrafficClient(["completed"])
        client._jobs = MagicMock()  # 只取用不呼叫——capture 後即中止
        builder = TrafficQueryBuilder(client)
        builder.build_traffic_query_spec = MagicMock(
            return_value=MagicMock(fallback_filters={}, report_only_filters={})
        )
        captured = {}

        def fake_build(start, end, pds, filters=None):
            captured["pds"] = pds
            raise RuntimeError("stop-after-capture")

        builder._build_native_traffic_payload = fake_build
        with self.assertRaises(RuntimeError):
            builder.export_traffic_query_csv("2026-04-01T00:00:00Z", "2026-04-02T00:00:00Z")

        self.assertIn("unknown", captured["pds"])

    def test_query_flows_default_includes_unknown_and_keeps_unknown_flows(self):
        """analyzer.query_flows 不帶 policy_decisions 時：(1) 送往 fetch 的預設
        pds 含 unknown；(2) strict_pd 辨識集合含 unknown——抓回的 unknown flow
        不得在 client 端過濾（analyzer.py ~1509）被丟棄。"""
        from unittest.mock import MagicMock as _MM
        from src.analyzer import Analyzer

        cm = _MM()
        cm.config = {"rules": []}
        az = Analyzer(cm, _MM(), _MM())
        az.load_state = _MM()
        az.save_state = _MM()
        az.api.last_fetch_error = None
        spec = _MM(report_only_filters={}, requires_draft_pd=False,
                   native_filters={}, fallback_filters={})
        az.api.build_traffic_query_spec = _MM(return_value=spec)

        flows = [
            {"policy_decision": "unknown", "src": {"ip": "10.0.0.1"},
             "dst": {"ip": "10.0.0.2"}, "service": {"port": 443, "proto": 6},
             "num_connections": 1},
            {"policy_decision": "allowed", "src": {"ip": "10.0.0.3"},
             "dst": {"ip": "10.0.0.4"}, "service": {"port": 80, "proto": 6},
             "num_connections": 1},
        ]
        az._fetch_query_flows = _MM(return_value=(flows, "api"))

        results = az.query_flows(
            {"start_time": "2026-01-01T00:00:00Z", "end_time": "2026-01-02T00:00:00Z"}
        )

        self.assertIn("unknown", az._fetch_query_flows.call_args[0][2])
        self.assertEqual(
            sorted(r.get("policy_decision") for r in results),
            ["allowed", "unknown"],
        )


class TestLabelCacheSkipsEntryWithoutHref(unittest.TestCase):
    def test_label_cache_skips_entry_without_href(self):
        """d_labels 混入無 href 條目時，其餘正常條目仍應寫入，且不得觸發
        rollback（現況裸 i['href'] KeyError 會清空整批快取且 silent=True 下無聲失敗）。"""
        client = _make_client()

        def fake_get_collection(path, *, timeout=15):
            if path.endswith("/labels"):
                return 200, [
                    {"href": "/orgs/1/labels/1", "key": "role", "value": "web"},
                    {"key": "role", "value": "missing-href"},  # 無 href，應跳過
                ], None
            if path.endswith("/label_groups"):
                return 200, [], None
            if path.endswith("/ip_lists"):
                return 200, [], None
            if path.endswith("/services"):
                return 200, [], None
            return 200, [], None

        client._get_collection = MagicMock(side_effect=fake_get_collection)
        client.update_label_cache(silent=True)

        self.assertEqual(client.label_cache.get("/orgs/1/labels/1"), "role:web")


if __name__ == "__main__":
    unittest.main()
