"""End-to-end: generate Traffic report twice from same fixture, once per profile.
Verify the two outputs differ in expected sections."""
import pytest
from src.report.exporters.html_exporter import HtmlExporter

# Markers unique to each gated section (taken directly from html_exporter._build):
#   mod04 ransomware section emits id="ransomware"
#   mod07 cross-label matrix section emits id="matrix"
_RANSOMWARE_MARKER = 'id="ransomware"'
_MATRIX_MARKER = 'id="matrix"'


@pytest.fixture
def security_risk_html():
    return HtmlExporter({}, profile="security_risk")._build()


@pytest.fixture
def network_inventory_html():
    return HtmlExporter({}, profile="network_inventory")._build()


def test_security_risk_includes_ransomware_section(security_risk_html):
    """mod04 is registered as security_risk only — must appear in security_risk output."""
    assert _RANSOMWARE_MARKER in security_risk_html


def test_network_inventory_omits_ransomware_section(network_inventory_html):
    """mod04 is not in network_inventory profile_visibility — must be absent."""
    assert _RANSOMWARE_MARKER not in network_inventory_html


def test_network_inventory_includes_cross_label_matrix(network_inventory_html):
    """mod07 is registered as network_inventory only — must appear in network_inventory output."""
    assert _MATRIX_MARKER in network_inventory_html


def test_security_risk_omits_cross_label_matrix(security_risk_html):
    """mod07 is not in security_risk profile_visibility — must be absent."""
    assert _MATRIX_MARKER not in security_risk_html
