"""Tests for the policy-resolver API fetch wrappers (mocked _get_collection).

Task 1 (API layer hardening)：get_ip_lists/get_label_groups/get_services 改
走 _get_collection（固定 500 上限 + 截斷偵測），故 mock 對象與呼叫斷言隨之改。
"""
from __future__ import annotations

from unittest.mock import MagicMock

from src.api_client import ApiClient


def _client():
    c = ApiClient.__new__(ApiClient)          # bypass __init__/network
    c.api_cfg = {"org_id": "1"}
    return c


def test_get_ip_lists_returns_definitions():
    c = _client()
    payload = [{"href": "/orgs/1/sec_policy/active/ip_lists/5", "name": "DC-Nets",
                "ip_ranges": [{"from_ip": "10.0.0.0", "to_ip": "10.0.255.255"}]}]
    c._get_collection = MagicMock(return_value=(200, payload, None))
    out = c.get_ip_lists()
    assert out == payload
    c._get_collection.assert_called_once_with(
        "/orgs/1/sec_policy/active/ip_lists")


def test_get_label_groups_returns_members():
    c = _client()
    payload = [{"href": "/orgs/1/sec_policy/active/label_groups/9", "name": "Prod-Apps",
                "labels": [{"href": "/orgs/1/labels/3"}], "sub_groups": []}]
    c._get_collection = MagicMock(return_value=(200, payload, None))
    out = c.get_label_groups()
    assert out == payload
    c._get_collection.assert_called_once_with(
        "/orgs/1/sec_policy/active/label_groups")


def test_get_services_returns_definitions():
    c = _client()
    payload = [{"href": "/orgs/1/sec_policy/active/services/2", "name": "HTTPS",
                "service_ports": [{"port": 443, "proto": 6}]}]
    c._get_collection = MagicMock(return_value=(200, payload, None))
    out = c.get_services()
    assert out == payload
    c._get_collection.assert_called_once_with(
        "/orgs/1/sec_policy/active/services")


def test_get_ip_lists_empty_on_error():
    c = _client()
    c._get_collection = MagicMock(return_value=(403, None, None))
    assert c.get_ip_lists() == []
