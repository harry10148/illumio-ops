"""System › Certificate: the web UI's TLS certificate (status, settings, renew, CSR, import)."""
from __future__ import annotations

import ssl
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from flask import Blueprint
from flask_limiter import Limiter
from pydantic import BaseModel, Field

from illumio_ops.services.context import AppContext
from illumio_ops.web import tls
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, api_route, operation


class CertView(BaseModel):
    subject_cn: str
    issuer_cn: str
    not_before: datetime
    not_after: datetime
    days_remaining: int
    san: list[str]
    self_signed: bool


class TlsStatus(BaseModel):
    revision: int
    enabled: bool
    mode: Literal["self_signed", "provided"]
    cert_file: str
    key_file: str
    auto_renew: bool
    auto_renew_days: int
    validity_days: int
    key_algorithm: Literal["ecdsa-p256", "rsa-2048"]
    min_version: Literal["TLSv1.2", "TLSv1.3"]
    cert: CertView | None
    restart_required: bool


class TlsUpdate(BaseModel):
    revision: int
    enabled: bool
    mode: Literal["self_signed", "provided"]
    cert_file: str = Field(max_length=4096)
    key_file: str = Field(max_length=4096)
    auto_renew: bool
    auto_renew_days: int = Field(ge=1, le=365)
    validity_days: int = Field(ge=1, le=825)
    key_algorithm: Literal["ecdsa-p256", "rsa-2048"]
    min_version: Literal["TLSv1.2", "TLSv1.3"]


class CsrRequest(BaseModel):
    cn: str = Field(min_length=1, max_length=253)
    o: str = Field(max_length=64)
    ou: str = Field(max_length=64)
    c: str = Field(max_length=2)
    san_dns: list[str] = Field(max_length=50)
    san_ip: list[str] = Field(max_length=50)
    key_algorithm: Literal["ecdsa-p256", "rsa-2048"]


class CsrResult(BaseModel):
    csr_pem: str


class ImportRequest(BaseModel):
    cert_pem: str = Field(min_length=1, max_length=65536)


OP_STATUS = operation("system.tls.status", "GET", "/api/system/tls", None, TlsStatus)
OP_UPDATE = operation("system.tls.update", "PUT", "/api/system/tls", TlsUpdate, TlsStatus)
OP_RENEW = operation("system.tls.renew", "POST", "/api/system/tls/renew", None, TlsStatus)
OP_CSR = operation("system.tls.csr", "POST", "/api/system/tls/csr", CsrRequest, CsrResult)
OP_IMPORT = operation("system.tls.import", "POST", "/api/system/tls/import", ImportRequest, TlsStatus)


def _cert_path(ctx: AppContext) -> Path:
    t = ctx.settings.current().web.tls
    return ctx.paths.tls_dir / tls.SELF_SIGNED_CERT if t.mode == "self_signed" else Path(t.cert_file)


def _status(ctx: AppContext) -> TlsStatus:
    s = ctx.settings.current()
    t = s.web.tls
    info = tls.cert_info(_cert_path(ctx))
    restart = ctx.served_tls is not None and (
        t != ctx.served_tls
        or (t.enabled and (info.fingerprint_sha256 if info else None) != ctx.served_cert_fingerprint)
    )
    cert = None if info is None else CertView(
        subject_cn=info.subject_cn, issuer_cn=info.issuer_cn, not_before=info.not_before,
        not_after=info.not_after, days_remaining=info.days_remaining, san=info.san, self_signed=info.self_signed)
    return TlsStatus(revision=s.revision, enabled=t.enabled, mode=t.mode, cert_file=t.cert_file,
                     key_file=t.key_file, auto_renew=t.auto_renew, auto_renew_days=t.auto_renew_days,
                     validity_days=t.validity_days, key_algorithm=t.key_algorithm, min_version=t.min_version,
                     cert=cert, restart_required=restart)


def _check_pair(cert_file: str, key_file: str) -> None:
    for field, value in (("cert_file", cert_file), ("key_file", key_file)):
        if not (value.startswith("/") and Path(value).is_file()):
            raise ApiFailure(400, "tls_file_missing", "err_tls_file_missing", field=field)
    try:
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert_file, key_file)
    except (ssl.SSLError, OSError):
        raise ApiFailure(400, "tls_pair_invalid", "err_tls_pair_invalid", field="cert_file") from None


def make_blueprint(limiter: Limiter) -> Blueprint:
    bp = Blueprint("system_tls", __name__)

    @api_route(bp, OP_STATUS)
    def status() -> TlsStatus:
        return _status(get_ctx())

    @api_route(bp, OP_UPDATE, decorators=[limiter.limit("10 per hour")])
    def update(body: TlsUpdate) -> TlsStatus:
        if body.enabled and body.mode == "provided":
            _check_pair(body.cert_file, body.key_file)
        fields = body.model_dump(exclude={"revision"})

        def mutate(d: dict[str, Any]) -> None:
            d["web"]["tls"].update(fields)

        ctx = get_ctx()
        ctx.settings.update(body.revision, mutate)
        return _status(ctx)

    @api_route(bp, OP_RENEW, decorators=[limiter.limit("10 per hour")])
    def renew() -> TlsStatus:
        ctx = get_ctx()
        t = ctx.settings.current().web.tls
        if t.mode != "self_signed":
            raise ApiFailure(400, "renew_self_signed_only", "err_renew_self_signed_only")
        tls.generate_self_signed(ctx.paths.tls_dir, days=t.validity_days, key_algorithm=t.key_algorithm)
        return _status(ctx)

    @api_route(bp, OP_CSR, decorators=[limiter.limit("20 per hour")])
    def csr(body: CsrRequest) -> CsrResult:
        try:
            pem, _key = tls.generate_csr(get_ctx().paths.tls_dir, cn=body.cn.strip(), o=body.o.strip(),
                                         ou=body.ou.strip(), c=body.c.strip(), san_dns=body.san_dns,
                                         san_ip=body.san_ip, key_algorithm=body.key_algorithm)
        except tls.CertificateError:
            raise ApiFailure(400, "invalid_input", "err_invalid_input", field="san_ip") from None
        return CsrResult(csr_pem=pem)

    @api_route(bp, OP_IMPORT, decorators=[limiter.limit("20 per hour")])
    def import_cert(body: ImportRequest) -> TlsStatus:
        ctx = get_ctx()
        try:
            tls.import_signed_cert(ctx.paths.tls_dir, body.cert_pem)
        except tls.CertificateError:
            raise ApiFailure(400, "certificate_rejected", "err_certificate_rejected", field="cert_pem") from None
        cert_file = str(ctx.paths.tls_dir / tls.CA_SIGNED_CERT)
        key_file = str(ctx.paths.tls_dir / tls.CA_SIGNED_KEY)

        def mutate(d: dict[str, Any]) -> None:
            d["web"]["tls"].update(mode="provided", cert_file=cert_file, key_file=key_file)

        ctx.settings.update(ctx.settings.current().revision, mutate)
        return _status(ctx)

    return bp
