"""同 key label OR 展開：native payload 需產生 OR-of-AND 巢狀群組。

實測基準（2026-07-03 真實 PCE）：[[A,B]] 同組=AND（0 筆）、[[A],[B]] 分組=OR。
"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from src.api_client import ApiClient


def _mk_client():
    cm = MagicMock()
    cm.config = {"api": {"url": "https://pce.example.com:8443", "org_id": "1",
                         "key": "k", "secret": "s", "verify_ssl": True}}
    c = ApiClient(cm)
    c._label_href_cache = {
        "app:erp": "/orgs/1/labels/11",
        "app:web": "/orgs/1/labels/12",
        "env:prod": "/orgs/1/labels/21",
    }
    c.update_label_cache = MagicMock(return_value=None)
    td = tempfile.TemporaryDirectory()
    c._state_file = os.path.join(td.name, "state.json")
    c._td = td  # 保活
    return c


class TestSameKeyLabelOrExpansion(unittest.TestCase):
    def setUp(self):
        self.client = _mk_client()

    def _build(self, filters):
        payload, spec = self.client._build_native_traffic_payload(
            "2026-04-01T00:00:00Z", "2026-04-01T01:00:00Z", ["allowed"], filters=filters)
        return payload, spec

    def test_same_key_two_labels_expand_to_or_groups(self):
        payload, _ = self._build({"src_labels": ["app=erp", "app=web"]})
        self.assertEqual(payload["sources"]["include"], [
            [{"label": {"href": "/orgs/1/labels/11"}}],
            [{"label": {"href": "/orgs/1/labels/12"}}],
        ])

    def test_cross_key_stays_and_within_group(self):
        payload, _ = self._build({"src_labels": ["app=erp", "env=prod"]})
        self.assertEqual(payload["sources"]["include"], [
            [{"label": {"href": "/orgs/1/labels/11"}},
             {"label": {"href": "/orgs/1/labels/21"}}],
        ])

    def test_mixed_same_and_cross_key_cartesian(self):
        payload, _ = self._build({"src_labels": ["app=erp", "app=web", "env=prod"]})
        self.assertEqual(payload["sources"]["include"], [
            [{"label": {"href": "/orgs/1/labels/11"}},
             {"label": {"href": "/orgs/1/labels/21"}}],
            [{"label": {"href": "/orgs/1/labels/12"}},
             {"label": {"href": "/orgs/1/labels/21"}}],
        ])

    def test_dst_side_expands_too(self):
        payload, _ = self._build({"dst_labels": ["app=erp", "app=web"]})
        self.assertEqual(len(payload["destinations"]["include"]), 2)

    def test_unresolvable_label_still_falls_back_whole_family(self):
        payload, spec = self._build({"src_labels": ["app=erp", "app=nosuch"]})
        self.assertEqual(payload["sources"]["include"], [])
        self.assertIn("src_labels", spec.fallback_filters)

    def test_cartesian_cap_falls_back(self):
        # 超過 100 組合 → 整個 family 降級 fallback，不送爆量 payload
        cache = {f"k{i}:v{j}": f"/orgs/1/labels/{i*100+j}" for i in range(3) for j in range(6)}
        self.client._label_href_cache = cache
        vals = [f"k{i}=v{j}" for i in range(3) for j in range(6)]  # 6*6*6=216 組合
        payload, spec = self._build({"src_labels": vals})
        self.assertEqual(payload["sources"]["include"], [])
        self.assertIn("src_labels", spec.fallback_filters)
