"""Tests for ApiClient.set_flow_reporting_frequency."""
import unittest
from unittest.mock import MagicMock

from src.api_client import ApiClient


def _make_client() -> ApiClient:
    cm = MagicMock()
    cm.config = {
        "api": {
            "url": "https://pce.example.com:8443",
            "org_id": "1",
            "key": "k",
            "secret": "s",
            "verify_ssl": True,
        }
    }
    return ApiClient(cm)


class TestSetFlowReportingFrequency(unittest.TestCase):
    def test_empty_hrefs_returns_zero(self):
        client = _make_client()
        client._api_post = MagicMock()
        success, fail = client.set_flow_reporting_frequency([])
        self.assertEqual((success, fail), (0, 0))
        client._api_post.assert_not_called()

    def test_single_batch_under_50(self):
        client = _make_client()
        client._api_post = MagicMock(return_value=(204, None))
        hrefs = [f"/orgs/1/workloads/{i}" for i in range(10)]

        success, fail = client.set_flow_reporting_frequency(hrefs)

        self.assertEqual((success, fail), (10, 0))
        self.assertEqual(client._api_post.call_count, 1)
        endpoint, payload = client._api_post.call_args[0][0], client._api_post.call_args[0][1]
        self.assertEqual(endpoint, "/orgs/1/workloads/set_flow_reporting_frequency")
        self.assertEqual(payload, {"workloads": [{"href": h} for h in hrefs]})

    def test_batches_at_50_boundary(self):
        client = _make_client()
        client._api_post = MagicMock(return_value=(200, None))
        hrefs = [f"/orgs/1/workloads/{i}" for i in range(125)]

        success, fail = client.set_flow_reporting_frequency(hrefs)

        self.assertEqual((success, fail), (125, 0))
        self.assertEqual(client._api_post.call_count, 3)
        sizes = [len(call.args[1]["workloads"]) for call in client._api_post.call_args_list]
        self.assertEqual(sizes, [50, 50, 25])

    def test_failure_status_counts_as_fail(self):
        client = _make_client()
        client._api_post = MagicMock(return_value=(403, None))
        hrefs = [f"/orgs/1/workloads/{i}" for i in range(5)]

        success, fail = client.set_flow_reporting_frequency(hrefs)

        self.assertEqual((success, fail), (0, 5))

    def test_partial_failure_across_batches(self):
        client = _make_client()
        client._api_post = MagicMock(side_effect=[(204, None), (500, None)])
        hrefs = [f"/orgs/1/workloads/{i}" for i in range(60)]

        success, fail = client.set_flow_reporting_frequency(hrefs)

        self.assertEqual((success, fail), (50, 10))


if __name__ == "__main__":
    unittest.main()
