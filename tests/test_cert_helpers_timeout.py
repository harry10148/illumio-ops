"""openssl subprocess 呼叫必須帶 timeout 且逾時不得炸出（2026-07-16
Phase A 殘債：_cert_days_remaining 無 timeout，openssl 卡住會吊死
TLS 日更 job 與 dashboard overview）。"""
from __future__ import annotations

import subprocess

from src.gui import _helpers


def _hang_run(*args, **kwargs):
    assert kwargs.get("timeout"), "openssl calls must carry a timeout"
    raise subprocess.TimeoutExpired(cmd="openssl", timeout=kwargs["timeout"])


def test_cert_days_remaining_survives_openssl_hang(tmp_path, monkeypatch):
    cert = tmp_path / "x.pem"
    cert.write_text("dummy")
    monkeypatch.setattr(subprocess, "run", _hang_run)
    assert _helpers._cert_days_remaining(str(cert)) is None


def test_get_cert_info_survives_openssl_hang(tmp_path, monkeypatch):
    cert = tmp_path / "x.pem"
    cert.write_text("dummy")
    monkeypatch.setattr(subprocess, "run", _hang_run)
    info = _helpers._get_cert_info(str(cert))
    assert info["exists"] is True
    assert "error" in info


def test_cert_has_san_survives_openssl_hang(tmp_path, monkeypatch):
    cert = tmp_path / "x.pem"
    cert.write_text("dummy")
    monkeypatch.setattr(subprocess, "run", _hang_run)
    assert _helpers._cert_has_san(str(cert)) is False
