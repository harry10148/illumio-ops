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
        captured = {}
        def fake_get(ep, timeout=15):
            captured["ep"] = ep
            return 200, [{"key": "Net", "value": "Server-A", "href": "/orgs/1/labels/1"}]
        self.client._api_get = fake_get
        out = self.client.get_all_labels()
        assert "/labels?max_results=" in captured["ep"]
        assert "key=" not in captured["ep"]  # 不分 key
        assert out[0]["key"] == "Net"

    def test_get_all_labels_empty_on_error(self):
        self.client._api_get = lambda ep, timeout=15: (500, None)
        assert self.client.get_all_labels() == []
