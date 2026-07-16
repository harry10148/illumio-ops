import os, tempfile, unittest
from unittest.mock import MagicMock
from src.api_client import ApiClient


class TestGetAllLabels(unittest.TestCase):
    def setUp(self):
        cm = MagicMock()
        cm.config = {"api": {"url": "https://pce.example.com:8443", "org_id": "1",
                             "key": "k", "secret": "s", "verify_ssl": True}}
        self.client = ApiClient(cm)
        self._td = tempfile.TemporaryDirectory()
        self.client._state_file = os.path.join(self._td.name, "state.json")

    def tearDown(self):
        self._td.cleanup()

    def test_get_all_labels_fetches_unscoped(self):
        # Task 1 (API layer hardening)：get_all_labels 改走 _get_collection
        # （固定 500 上限 + 截斷偵測），不再直接呼叫 _api_get。
        captured = {}
        def fake_get_collection(path, *, timeout=15):
            captured["path"] = path
            return 200, [{"key": "Net", "value": "Server-A", "href": "/orgs/1/labels/1"}], None
        self.client._get_collection = fake_get_collection
        out = self.client.get_all_labels()
        assert captured["path"] == "/orgs/1/labels"
        assert "key=" not in captured["path"]  # 不分 key
        assert out[0]["key"] == "Net"

    def test_get_all_labels_empty_on_error(self):
        self.client._get_collection = lambda path, *, timeout=15: (500, None, None)
        assert self.client.get_all_labels() == []
