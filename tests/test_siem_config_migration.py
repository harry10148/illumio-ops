"""Tests for SiemDestinationSettings host/port migration from legacy endpoint field."""
import pytest


def _make(raw: dict):
    from src.config_models import SiemDestinationSettings
    return SiemDestinationSettings.model_validate(raw)


def test_new_config_host_port():
    d = _make({"name": "s", "transport": "udp", "host": "10.0.0.1", "port": 514})
    assert d.host == "10.0.0.1"
    assert d.port == 514


def test_migrate_endpoint_host_port():
    d = _make({"name": "s", "transport": "udp", "endpoint": "10.0.0.1:514"})
    assert d.host == "10.0.0.1"
    assert d.port == 514


def test_migrate_endpoint_host_only():
    d = _make({"name": "s", "transport": "udp", "endpoint": "10.0.0.1"})
    assert d.host == "10.0.0.1"
    assert d.port == 514


def test_migrate_endpoint_hec_url():
    d = _make({"name": "h", "transport": "hec", "endpoint": "https://splunk.corp:8088/services/collector"})
    assert d.host == "splunk.corp"
    assert d.port == 8088


def test_migrate_endpoint_hec_url_no_port():
    d = _make({"name": "h", "transport": "hec", "endpoint": "https://splunk.corp/services/collector"})
    assert d.host == "splunk.corp"
    assert d.port == 8088


def test_port_default_is_514():
    d = _make({"name": "s", "transport": "udp", "host": "10.0.0.1"})
    assert d.port == 514


def test_host_new_wins_over_endpoint():
    d = _make({"name": "s", "transport": "udp", "host": "10.0.0.2", "port": 999, "endpoint": "10.0.0.1:514"})
    assert d.host == "10.0.0.2"
    assert d.port == 999
