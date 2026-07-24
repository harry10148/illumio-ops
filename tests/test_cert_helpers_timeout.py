"""openssl subprocess 呼叫必須帶 timeout 且逾時不得炸出（2026-07-16
Phase A 殘債：_cert_days_remaining 無 timeout，openssl 卡住會吊死
TLS 日更 job 與 dashboard overview）。"""
from __future__ import annotations

import subprocess
import sys

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


def test_cert_has_san_corrupt_cert_is_false(tmp_path, monkeypatch):
    # cryptography 讀不出的憑證＝壞檔，回 False（重簽是正確行為）
    cert = tmp_path / "x.pem"
    cert.write_text("dummy")
    monkeypatch.setattr(subprocess, "run", _hang_run)
    assert _helpers._cert_has_san(str(cert)) is False


def test_cert_has_san_openssl_fallback_hang_returns_unknown(tmp_path, monkeypatch):
    """openssl fallback 路徑（cryptography 不可用）逾時/缺 CLI 時必須回
    None（無法判斷），不得回 False——False 會逼 _generate_self_signed_cert
    在每次啟動時重簽一張本來完全有效的憑證。"""
    cert = tmp_path / "x.pem"
    cert.write_text("dummy")
    monkeypatch.setattr(subprocess, "run", _hang_run)
    monkeypatch.setitem(sys.modules, "cryptography", None)  # 強制走 openssl fallback
    assert _helpers._cert_has_san(str(cert)) is None
