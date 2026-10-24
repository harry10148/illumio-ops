import datetime as dt
import os
import ssl

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from illumio_ops.settings.schema import default_settings
from illumio_ops.web import tls
from tests_v6.settings.conftest import HASH, KEY


def _tls(**kw):
    return default_settings(password_hash=HASH, secret_key=KEY).web.tls.model_copy(update=kw)


def _sign_with_own_ca(key_path, cn="server.local"):
    """Sign a cert for the CSR key (as a CA would)."""
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
    now = dt.datetime.now(dt.UTC)
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
            .issuer_name(ca).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now + dt.timedelta(days=90)).sign(ca_key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_ssl_context_defaults_match_5x():
    ctx = tls.build_ssl_context(_tls())
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2
    assert ctx.options & ssl.OP_NO_COMPRESSION
    assert tls.DEFAULT_CIPHERS == "ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:!aNULL:!MD5:!DSS:!RC4:!3DES:!EXPORT"
    assert tls.build_ssl_context(_tls(min_version="TLSv1.3")).minimum_version == ssl.TLSVersion.TLSv1_3


def test_self_signed_is_created_with_san_and_0600_key(tmp_path):
    cert, key = tls.ensure_self_signed(tmp_path, _tls())
    assert (key.stat().st_mode & 0o777) == 0o600
    c = x509.load_pem_x509_certificate(cert.read_bytes())
    san = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "localhost" in san.get_values_for_type(x509.DNSName)
    assert 396 <= tls.cert_days_remaining(cert) <= 397
    assert isinstance(c.public_key(), ec.EllipticCurvePublicKey)


def test_existing_valid_cert_is_kept(tmp_path):
    cert, _ = tls.ensure_self_signed(tmp_path, _tls())
    before = cert.read_bytes()
    tls.ensure_self_signed(tmp_path, _tls())
    assert cert.read_bytes() == before


def test_cert_without_san_is_regenerated(tmp_path):
    cert, _ = tls.ensure_self_signed(tmp_path, _tls())
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "old")])
    now = dt.datetime.now(dt.UTC)
    old = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
           .serial_number(1).not_valid_before(now).not_valid_after(now + dt.timedelta(days=300))
           .sign(key, hashes.SHA256()))
    cert.write_bytes(old.public_bytes(serialization.Encoding.PEM))
    tls.ensure_self_signed(tmp_path, _tls())
    assert tls.cert_has_san(cert) is True


def test_auto_renew_uses_configured_days_and_algorithm(tmp_path):
    cert, _ = tls.ensure_self_signed(tmp_path, _tls(validity_days=10))
    assert tls.cert_days_remaining(cert) <= 10
    tls.ensure_self_signed(tmp_path, _tls(validity_days=200, key_algorithm="rsa-2048", auto_renew_days=30))
    c = x509.load_pem_x509_certificate(cert.read_bytes())
    assert 199 <= tls.cert_days_remaining(cert) <= 200
    assert c.public_key().key_size == 2048


def test_no_renewal_when_auto_renew_off(tmp_path):
    cert, _ = tls.ensure_self_signed(tmp_path, _tls(validity_days=10))
    before = cert.read_bytes()
    tls.ensure_self_signed(tmp_path, _tls(validity_days=200, auto_renew=False))
    assert cert.read_bytes() == before


def test_generate_csr_subject_san_and_key_mode(tmp_path):
    pem, key_path = tls.generate_csr(tmp_path, cn="my.host", o="Acme", ou="", c="US",
                                     san_dns=["a.example.com"], san_ip=["10.0.0.1"], key_algorithm="rsa-2048")
    assert "BEGIN CERTIFICATE REQUEST" in pem and (key_path.stat().st_mode & 0o777) == 0o600
    csr = x509.load_pem_x509_csr(pem.encode())
    assert csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "my.host"
    assert csr.subject.get_attributes_for_oid(NameOID.COUNTRY_NAME)[0].value == "US"
    san = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.DNSName) == ["a.example.com"]


def test_import_signed_cert_ok(tmp_path):
    _, key_path = tls.generate_csr(tmp_path, cn="server.local")
    info = tls.import_signed_cert(tmp_path, _sign_with_own_ca(key_path))
    assert (tmp_path / "ca_signed.pem").is_file() and info.subject_cn == "server.local"
    assert 89 <= info.days_remaining <= 90


def test_import_signed_cert_key_mismatch(tmp_path):
    _, first_key = tls.generate_csr(tmp_path, cn="one")
    first_key_copy = tmp_path / "first.pem"
    first_key_copy.write_bytes(first_key.read_bytes())
    tls.generate_csr(tmp_path, cn="two")  # replaces csr_key.pem
    with pytest.raises(tls.CertificateError, match="key"):
        tls.import_signed_cert(tmp_path, _sign_with_own_ca(first_key_copy))
    assert not (tmp_path / "ca_signed.pem").exists()


def test_import_signed_cert_without_csr_key(tmp_path):
    with pytest.raises(tls.CertificateError):
        tls.import_signed_cert(tmp_path, "-----BEGIN CERTIFICATE-----\n-----END CERTIFICATE-----")


def test_import_garbage_is_rejected(tmp_path):
    tls.generate_csr(tmp_path, cn="x")
    with pytest.raises(tls.CertificateError):
        tls.import_signed_cert(tmp_path, "not a certificate")


def test_cert_info_for_missing_file_is_none(tmp_path):
    assert tls.cert_info(tmp_path / "nope.pem") is None
    assert tls.cert_days_remaining(tmp_path / "nope.pem") is None


def test_files_are_written_without_world_access(tmp_path):
    old = os.umask(0o022)
    try:
        _cert, key = tls.ensure_self_signed(tmp_path, _tls())
    finally:
        os.umask(old)
    assert (key.stat().st_mode & 0o077) == 0
