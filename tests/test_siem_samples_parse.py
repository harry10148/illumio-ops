"""Sanity tests for SIEM integration sample configs."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_filebeat_yaml_parses():
    data = yaml.safe_load(Path("deploy/filebeat.illumio_ops.yml").read_text(encoding="utf-8"))
    assert "filebeat.inputs" in data
    assert data["filebeat.inputs"][0]["json.keys_under_root"] is True


def test_logstash_has_input_filter_output():
    src = Path("deploy/logstash.illumio_ops.conf").read_text(encoding="utf-8")
    for block in ("input", "filter", "output"):
        assert f"{block} {{" in src, f"logstash pipeline missing {block} block"


def test_rsyslog_targets_remote_host():
    src = Path("deploy/rsyslog.illumio_ops.conf").read_text(encoding="utf-8")
    assert "omfwd" in src
    assert "siem.example.com" in src


def test_siem_doc_exists_with_four_options():
    # The 2026-07 docs overhaul moved the SIEM integration guide to
    # docs/guide/siem.md (SIEM transports are also documented in
    # docs/reference/cli.md). Transports are documented by their real config
    # keys (udp / tcp / tls / hec), which are what the user wires into
    # config/config.json under siem.destinations.transport.
    doc = Path("docs/guide/siem.md").read_text(encoding="utf-8")
    for transport in ("udp", "tcp", "tls", "hec"):
        assert f"`{transport}`" in doc, f"SIEM doc missing transport: {transport}"
