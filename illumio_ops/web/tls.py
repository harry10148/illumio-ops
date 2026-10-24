"""Certificates for the web UI: self-signed lifecycle, CSR, CA-signed import, SSL context.

Ported from 5.x src/gui/_helpers.py (TLS section). The openssl CLI fallbacks are
gone: cryptography is a locked dependency.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import os
import socket
import ssl
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.types import (
    CertificateIssuerPrivateKeyTypes,
)
from cryptography.x509.oid import NameOID
from loguru import logger

from illumio_ops.settings.schema import TlsSettings

DEFAULT_CIPHERS = "ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:!aNULL:!MD5:!DSS:!RC4:!3DES:!EXPORT"
SELF_SIGNED_CERT = "self_signed.pem"
SELF_SIGNED_KEY = "self_signed_key.pem"
CSR_KEY = "csr_key.pem"
CA_SIGNED_CERT = "ca_signed.pem"


class CertificateError(ValueError):
    """A certificate or key could not be used (message is safe to show)."""


@dataclass(frozen=True)
class CertInfo:
    subject_cn: str
    issuer_cn: str
    not_before: dt.datetime
    not_after: dt.datetime
    days_remaining: int
    san: list[str]
    fingerprint_sha256: str
    self_signed: bool


def build_ssl_context(tls: TlsSettings) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3 if tls.min_version == "TLSv1.3" else ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers(tls.ciphers or DEFAULT_CIPHERS)
    ctx.options |= ssl.OP_NO_COMPRESSION | ssl.OP_SINGLE_DH_USE | ssl.OP_SINGLE_ECDH_USE
    return ctx


def _load(path: Path) -> x509.Certificate | None:
    try:
        return x509.load_pem_x509_certificate(path.read_bytes())
    except (OSError, ValueError):
        return None


def cert_has_san(path: Path) -> bool:
    """False for a missing, unreadable or corrupt cert too: regenerating is right then."""
    cert = _load(path)
    if cert is None:
        return False
    try:
        cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        return True
    except x509.ExtensionNotFound:
        return False


def cert_days_remaining(path: Path) -> int | None:
    cert = _load(path)
    if cert is None:
        return None
    return int((cert.not_valid_after_utc - dt.datetime.now(dt.UTC)).total_seconds() // 86400)


def _cn(name: x509.Name) -> str:
    attrs = name.get_attributes_for_oid(NameOID.COMMON_NAME)
    return str(attrs[0].value) if attrs else ""


def cert_info(path: Path) -> CertInfo | None:
    cert = _load(path)
    if cert is None:
        return None
    try:
        san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        san = [*san_ext.get_values_for_type(x509.DNSName),
               *(str(ip) for ip in san_ext.get_values_for_type(x509.IPAddress))]
    except x509.ExtensionNotFound:
        san = []
    return CertInfo(
        subject_cn=_cn(cert.subject),
        issuer_cn=_cn(cert.issuer),
        not_before=cert.not_valid_before_utc,
        not_after=cert.not_valid_after_utc,
        days_remaining=int((cert.not_valid_after_utc - dt.datetime.now(dt.UTC)).total_seconds() // 86400),
        san=san,
        fingerprint_sha256=cert.fingerprint(hashes.SHA256()).hex(),
        self_signed=cert.subject == cert.issuer,
    )


def local_ips() -> list[str]:
    """Every non-link-local address of this host, plus loopback."""
    ips = {"127.0.0.1", "::1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = str(info[4][0])
            if not ip.startswith(("fe80", "169.254")):
                ips.add(ip)
    except OSError:
        logger.warning("could not list local addresses; the certificate covers loopback only")
    return sorted(ips)


def _new_key(algorithm: str) -> CertificateIssuerPrivateKeyTypes:
    if algorithm == "rsa-2048":
        return rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return ec.generate_private_key(ec.SECP256R1())


def _write_private(path: Path, key: CertificateIssuerPrivateKeyTypes) -> None:
    # 0600 from creation: open() would honour the umask and leave a readable window.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                   serialization.NoEncryption()))
    os.chmod(path, 0o600)


def _write_public(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.chmod(path, 0o600)


def generate_self_signed(tls_dir: Path, *, days: int, key_algorithm: str) -> tuple[Path, Path]:
    tls_dir.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = tls_dir / SELF_SIGNED_CERT, tls_dir / SELF_SIGNED_KEY
    ips = local_ips()
    logger.info("generating a self-signed certificate ({} days, {}) for localhost and {} addresses",
                days, key_algorithm, len(ips))
    key = _new_key(key_algorithm)
    name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "TW"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "IllumioPCEOps"),
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])
    san: list[x509.GeneralName] = [x509.DNSName("localhost")]
    san += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips]
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    _write_private(key_path, key)
    _write_public(cert_path, cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def ensure_self_signed(tls_dir: Path, tls: TlsSettings) -> tuple[Path, Path]:
    """The self-signed pair, regenerated when missing, without SAN, or due for renewal."""
    cert_path, key_path = tls_dir / SELF_SIGNED_CERT, tls_dir / SELF_SIGNED_KEY
    reason = None
    if not (cert_path.is_file() and key_path.is_file()):
        reason = "missing"
    elif not cert_has_san(cert_path):
        reason = "no subject alternative name"
    elif tls.auto_renew:
        left = cert_days_remaining(cert_path)
        if left is not None and left <= tls.auto_renew_days:
            reason = f"expires in {left} days"
    if reason is None:
        return cert_path, key_path
    logger.info("{} the self-signed certificate: {}", "creating" if reason == "missing" else "renewing", reason)
    return generate_self_signed(tls_dir, days=tls.validity_days, key_algorithm=tls.key_algorithm)


def generate_csr(tls_dir: Path, *, cn: str, o: str = "", ou: str = "", c: str = "",
                 san_dns: list[str] | None = None, san_ip: list[str] | None = None,
                 key_algorithm: str = "rsa-2048") -> tuple[str, Path]:
    tls_dir.mkdir(parents=True, exist_ok=True)
    key_path = tls_dir / CSR_KEY
    key = _new_key(key_algorithm)
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, cn or "localhost")]
    for oid, value in ((NameOID.ORGANIZATION_NAME, o), (NameOID.ORGANIZATIONAL_UNIT_NAME, ou),
                       (NameOID.COUNTRY_NAME, c)):
        if value:
            attrs.append(x509.NameAttribute(oid, value))
    san: list[x509.GeneralName] = [x509.DNSName(d.strip()) for d in (san_dns or []) if d.strip()]
    for ip in san_ip or []:
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(ip.strip())))
        except ValueError:
            raise CertificateError(f"not an IP address: {ip.strip()}") from None
    builder = x509.CertificateSigningRequestBuilder().subject_name(x509.Name(attrs))
    if san:
        builder = builder.add_extension(x509.SubjectAlternativeName(san), critical=False)
    csr = builder.sign(key, hashes.SHA256())
    _write_private(key_path, key)
    return csr.public_bytes(serialization.Encoding.PEM).decode(), key_path


def import_signed_cert(tls_dir: Path, cert_pem: str) -> CertInfo:
    """Store a CA-signed certificate after checking it matches the stored CSR key."""
    key_path = tls_dir / CSR_KEY
    if not key_path.is_file():
        raise CertificateError("no certificate request key found; generate a CSR first")
    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode())
    except ValueError:
        raise CertificateError("not a PEM certificate") from None
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    spki = serialization.PublicFormat.SubjectPublicKeyInfo
    if (cert.public_key().public_bytes(serialization.Encoding.PEM, spki)
            != key.public_key().public_bytes(serialization.Encoding.PEM, spki)):
        raise CertificateError("the certificate does not match the stored request key")
    path = tls_dir / CA_SIGNED_CERT
    _write_public(path, cert.public_bytes(serialization.Encoding.PEM))
    info = cert_info(path)
    assert info is not None
    return info
