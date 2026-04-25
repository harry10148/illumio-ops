"""IP address validation for TrafficFilterSettings.exclude_src_ips."""
from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.config_models import TrafficFilterSettings


def test_exclude_src_ips_accepts_ipv4():
    cfg = TrafficFilterSettings(exclude_src_ips=["10.0.0.1", "192.168.1.5"])
    assert cfg.exclude_src_ips == ["10.0.0.1", "192.168.1.5"]


def test_exclude_src_ips_accepts_ipv6():
    cfg = TrafficFilterSettings(exclude_src_ips=["::1", "2001:db8::1"])
    assert cfg.exclude_src_ips == ["::1", "2001:db8::1"]


def test_exclude_src_ips_rejects_garbage():
    with pytest.raises(ValidationError) as excinfo:
        TrafficFilterSettings(exclude_src_ips=["not-an-ip"])
    assert "exclude_src_ips" in str(excinfo.value)


def test_exclude_src_ips_rejects_partial_ip():
    with pytest.raises(ValidationError):
        TrafficFilterSettings(exclude_src_ips=["10.0.0"])


def test_exclude_src_ips_empty_list_ok():
    cfg = TrafficFilterSettings(exclude_src_ips=[])
    assert cfg.exclude_src_ips == []


def test_ports_accepts_valid_range():
    cfg = TrafficFilterSettings(ports=[22, 443, 65535, 1])
    assert cfg.ports == [22, 443, 65535, 1]


def test_ports_rejects_zero():
    with pytest.raises(ValidationError):
        TrafficFilterSettings(ports=[0, 80])


def test_ports_rejects_too_high():
    with pytest.raises(ValidationError):
        TrafficFilterSettings(ports=[65536])


def test_ports_rejects_negative():
    with pytest.raises(ValidationError):
        TrafficFilterSettings(ports=[-1])
