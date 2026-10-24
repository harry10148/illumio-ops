"""The settings file schema (config/settings.json).

Every model forbids unknown keys and has NO field defaults: a file missing a
field is invalid, never silently completed. Defaults live only in
default_settings(), used for a fresh install and by the 5.x migrator.
"""
from __future__ import annotations

import re
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from illumio_ops.domain.values import DeploymentType, Language

SCHEMA_VERSION: Literal[1] = 1
_UTC_OFFSET = re.compile(r"UTC([+-]\d+(?:\.\d+)?)")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _http_url(v: str, *, allow_empty: bool) -> str:
    # Messages never echo the value: errors are shown in logs and on screen.
    if v == "" and allow_empty:
        return v
    if not re.match(r"^https?://[^/\s]+", v):
        raise ValueError("must be an http:// or https:// URL")
    return v.rstrip("/")


class PceSettings(StrictModel):
    url: str
    org_id: str
    api_key: str
    api_secret: str
    deployment_type: DeploymentType
    console_url: str | None
    verify_tls: bool | str  # str = path to a CA bundle
    events_timeout_seconds: int | None = Field(ge=5, le=600)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return _http_url(v, allow_empty=True)

    @field_validator("console_url")
    @classmethod
    def _console_url(cls, v: str | None) -> str | None:
        return None if v is None else _http_url(v, allow_empty=False)

    @field_validator("org_id")
    @classmethod
    def _org_id(cls, v: str) -> str:
        if v and not v.isdigit():
            raise ValueError("must be the numeric organization ID")
        return v

    @field_validator("verify_tls")
    @classmethod
    def _verify_tls(cls, v: bool | str) -> bool | str:
        if isinstance(v, str) and not v.startswith("/"):
            raise ValueError("a CA bundle must be an absolute path")
        return v


class TlsSettings(StrictModel):
    enabled: bool
    mode: Literal["self_signed", "provided"]
    cert_file: str
    key_file: str
    auto_renew: bool
    auto_renew_days: int = Field(ge=1)
    validity_days: int = Field(ge=1)
    key_algorithm: Literal["ecdsa-p256", "rsa-2048"]
    min_version: Literal["TLSv1.2", "TLSv1.3"]
    ciphers: str | None


class WebSettings(StrictModel):
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    username: str = Field(min_length=1)
    password_hash: str
    secret_key: str
    allowed_ips: tuple[str, ...]
    session_lifetime_seconds: int = Field(ge=60)
    must_change_password: bool
    tls: TlsSettings

    @field_validator("password_hash")
    @classmethod
    def _hash(cls, v: str) -> str:
        if not v.startswith("$argon2"):
            raise ValueError("must be an argon2 hash")
        return v

    @field_validator("secret_key")
    @classmethod
    def _secret_key(cls, v: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64,}", v):
            raise ValueError("must be at least 64 lowercase hex characters")
        return v


class DisplaySettings(StrictModel):
    language: Language
    timezone: str

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        # The formats 5.x accepted (src/tz_utils.py), so migrated values carry over as-is;
        # unlike 5.x an unknown value is rejected instead of silently becoming UTC.
        if v in ("local", "UTC"):
            return v
        m = _UTC_OFFSET.fullmatch(v)
        if m:
            if abs(float(m.group(1))) >= 24:
                raise ValueError("a UTC offset must be less than 24 hours")
            return v
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("must be 'local', 'UTC', 'UTC+N' or an IANA time zone name") from None
        return v


class LoggingSettings(StrictModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(StrictModel):
    schema_version: Literal[1]
    revision: int = Field(ge=0)
    pce: PceSettings
    web: WebSettings
    display: DisplaySettings
    logging: LoggingSettings


def default_settings(*, password_hash: str, secret_key: str, port: int = 5001) -> Settings:
    return Settings(
        schema_version=SCHEMA_VERSION,
        revision=0,
        pce=PceSettings(
            url="", org_id="", api_key="", api_secret="", deployment_type=DeploymentType.ON_PREM,
            console_url=None, verify_tls=True, events_timeout_seconds=None,
        ),
        web=WebSettings(
            host="0.0.0.0", port=port, username="illumio", password_hash=password_hash,
            secret_key=secret_key, allowed_ips=(), session_lifetime_seconds=28800,
            must_change_password=False,
            tls=TlsSettings(
                enabled=True, mode="self_signed", cert_file="", key_file="", auto_renew=True,
                auto_renew_days=30, validity_days=397, key_algorithm="ecdsa-p256",
                min_version="TLSv1.2", ciphers=None,
            ),
        ),
        display=DisplaySettings(language=Language.EN, timezone="local"),
        logging=LoggingSettings(level="INFO"),
    )
