"""Phase 2: TLS default-enable and hardening tests."""
import ssl
import sys
import os
import tempfile

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def _fresh_config():
    """Return a ConfigManager loaded with only built-in defaults (no config.json)."""
    from unittest.mock import patch
    from src.config import ConfigManager
    # Prevent loading any real config.json from disk
    with patch.object(ConfigManager, "load", lambda self: None):
        cm = ConfigManager()
    return cm


def test_default_tls_config_enabled():
    """tls.enabled must default to True so new deployments use HTTPS out of the box."""
    from src.config import _DEFAULT_CONFIG
    tls = _DEFAULT_CONFIG["web_gui"]["tls"]
    assert tls["enabled"] is True


def test_default_validity_days_397():
    """tls.validity_days must default to 397 (browser-accepted maximum)."""
    from src.config import _DEFAULT_CONFIG
    tls = _DEFAULT_CONFIG["web_gui"]["tls"]
    assert tls["validity_days"] == 397


def test_default_key_algorithm_ecdsa():
    """tls.key_algorithm must default to 'ecdsa-p256'."""
    from src.config import _DEFAULT_CONFIG
    tls = _DEFAULT_CONFIG["web_gui"]["tls"]
    assert tls["key_algorithm"] == "ecdsa-p256"


def test_ssl_context_min_tls12():
    """_build_ssl_context() must produce a context with TLS 1.2 as the minimum version."""
    from src.gui import _build_ssl_context
    ctx = _build_ssl_context({"min_version": "TLSv1.2", "ciphers": None})
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2


# ── CSR generation ────────────────────────────────────────────────────────────

cryptography = pytest.importorskip("cryptography", reason="cryptography library required")


def _make_signed_cert(key_path: str, cn: str = "test") -> str:
    """Sign a cert with the private key at key_path (simulates CA signing for tests)."""
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    import datetime

    with open(key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365))
        .sign(private_key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_generate_csr_returns_pem_and_key():
    from src.gui._helpers import _generate_csr
    with tempfile.TemporaryDirectory() as d:
        csr_pem, key_path = _generate_csr(d, cn="pce.example.com", o="Example", c="TW")
        assert "BEGIN CERTIFICATE REQUEST" in csr_pem
        assert os.path.exists(key_path)


def test_generate_csr_key_permissions():
    from src.gui._helpers import _generate_csr
    with tempfile.TemporaryDirectory() as d:
        _, key_path = _generate_csr(d, cn="test.example.com")
        assert oct(os.stat(key_path).st_mode)[-3:] == "600"


def test_generate_csr_subject_fields():
    from src.gui._helpers import _generate_csr
    from cryptography import x509
    with tempfile.TemporaryDirectory() as d:
        csr_pem, _ = _generate_csr(d, cn="my.host", o="Acme", c="US")
        csr = x509.load_pem_x509_csr(csr_pem.encode())
        subject = {a.oid.dotted_string: a.value for a in csr.subject}
        assert subject["2.5.4.3"] == "my.host"   # CN
        assert subject["2.5.4.10"] == "Acme"      # O
        assert subject["2.5.4.6"] == "US"          # C


def test_generate_csr_san_entries():
    from src.gui._helpers import _generate_csr
    from cryptography import x509
    with tempfile.TemporaryDirectory() as d:
        csr_pem, _ = _generate_csr(d, cn="svc", san_dns=["a.example.com", "b.example.com"], san_ip=["10.0.0.1"])
        csr = x509.load_pem_x509_csr(csr_pem.encode())
        san = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        dns_names = san.value.get_values_for_type(x509.DNSName)
        assert "a.example.com" in dns_names
        assert "b.example.com" in dns_names


def test_import_signed_cert_ok():
    from src.gui._helpers import _generate_csr, _import_signed_cert
    with tempfile.TemporaryDirectory() as d:
        _, key_path = _generate_csr(d, cn="server.local")
        signed_pem = _make_signed_cert(key_path, cn="server.local")
        info = _import_signed_cert(d, signed_pem)
        assert info.get("exists") is True
        assert os.path.exists(os.path.join(d, "ca_signed.pem"))


def test_import_signed_cert_key_mismatch():
    from src.gui._helpers import _generate_csr, _import_signed_cert
    with tempfile.TemporaryDirectory() as d:
        # Generate two CSRs so we have two different keys
        _, key_path1 = _generate_csr(d, cn="server1")
        import shutil
        shutil.copy(os.path.join(d, "csr_key.pem"), os.path.join(d, "other_key.pem"))
        _generate_csr(d, cn="server2")  # overwrites csr_key.pem
        # Try to import a cert signed with the first key
        signed_pem = _make_signed_cert(os.path.join(d, "other_key.pem"))
        with pytest.raises(ValueError, match="does not match"):
            _import_signed_cert(d, signed_pem)


def test_import_signed_cert_no_csr_key():
    from src.gui._helpers import _import_signed_cert
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(ValueError, match="generate a CSR first"):
            _import_signed_cert(d, "-----BEGIN CERTIFICATE-----\n-----END CERTIFICATE-----")
