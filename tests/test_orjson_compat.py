"""orjson.loads output must equal json.loads for all existing fixture payloads."""
from __future__ import annotations

import json
import orjson


def test_orjson_matches_stdlib_on_small_object():
    payload = b'{"a": 1, "b": [1, 2, 3], "c": {"d": "x"}}'
    assert orjson.loads(payload) == json.loads(payload)


def test_orjson_handles_unicode_strings():
    payload = '{"name": "工作負載", "type": "Workload"}'.encode("utf-8")
    assert orjson.loads(payload) == json.loads(payload)


def test_orjson_handles_nested_arrays():
    payload = b'[[1,2],[3,4],[5,6,[7,8]]]'
    assert orjson.loads(payload) == json.loads(payload)


def test_orjson_raises_on_malformed_json():
    import pytest
    with pytest.raises(orjson.JSONDecodeError):
        orjson.loads(b'{"bad":,}')


def test_orjson_handles_large_traffic_payload():
    # Simulates a 10k-flow traffic response
    payload = json.dumps([
        {"src": {"ip": "10.0.0.1"}, "dst": {"ip": "10.0.0.2"}, "port": p}
        for p in range(10_000)
    ]).encode("utf-8")
    parsed = orjson.loads(payload)
    assert len(parsed) == 10_000
    assert parsed[0]["src"]["ip"] == "10.0.0.1"
