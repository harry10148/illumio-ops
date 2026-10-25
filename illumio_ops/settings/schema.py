"""The settings file schema (config/settings.json).

Every model forbids unknown keys and has NO field defaults: a file missing a
field is invalid, never silently completed. Defaults live only in
default_settings(), used for a fresh install and by the 5.x migrator.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from illumio_ops.domain.netaddr import parse_ip_token
from illumio_ops.domain.values import CollectionMode, DeploymentType, Language

SCHEMA_VERSION: Literal[2] = 2
_UTC_OFFSET = re.compile(r"UTC([+-]\d+(?:\.\d+)?)")


def _ip_or_network(v: str) -> str:
    try:
        parse_ip_token(v)
    except ValueError:
        raise ValueError("must be an IP address or network") from None
    return v


def _absolute_or_empty(v: str) -> str:
    if v and not v.startswith("/"):
        raise ValueError("must be an absolute path")
    return v


AllowedIp = Annotated[str, AfterValidator(_ip_or_network)]
FilePath = Annotated[str, AfterValidator(_absolute_or_empty)]


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
    cert_file: FilePath
    key_file: FilePath
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
    allowed_ips: tuple[AllowedIp, ...]
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
    level: Literal["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"]  # loguru's levels


class RetentionSettings(StrictModel):
    flow_days: int = Field(ge=1, le=3650)
    event_days: int = Field(ge=1, le=3650)
    rollup_days: int = Field(ge=1, le=3650)
    baseline_days: int = Field(ge=7, le=365)

    @model_validator(mode="after")
    def _ordering(self) -> RetentionSettings:
        # Daily rollups feed period-over-period reports beyond the raw flows.
        if self.rollup_days < self.flow_days:
            raise ValueError("rollup_days must be at least flow_days")
        return self


class ArchiveSettings(StrictModel):
    enabled: bool
    retention_days: int = Field(ge=0, le=3650)  # 0 = keep archive files forever


class CollectionSettings(StrictModel):
    enabled: bool
    mode: CollectionMode = CollectionMode.FULL  # declared before retention: its validator reads it
    traffic_interval_seconds: int = Field(ge=300, le=86400)
    events_interval_seconds: int = Field(ge=60, le=3600)
    inventory_interval_seconds: int = Field(ge=900, le=86400)
    rate_limit_per_minute: int = Field(ge=10, le=1000)
    backfill_days: int = Field(ge=0, le=90)
    disk_free_warn_gb: int = Field(ge=1, le=100000)
    retention: RetentionSettings
    archive: ArchiveSettings

    # Field validators, so an error names the field it is about (the page explains each in words).
    @field_validator("retention")
    @classmethod
    def _raw_outlives_baseline(cls, v: RetentionSettings, info: ValidationInfo) -> RetentionSettings:
        # In full mode the workbench must be able to show the history of a "new connection",
        # so raw flows outlive the baseline window. Alert mode keeps traffic briefly by design;
        # the baseline table itself is kept for baseline_days either way (spec §6.4).
        if info.data.get("mode", CollectionMode.FULL) is CollectionMode.FULL and v.flow_days < v.baseline_days:
            raise ValueError("in full mode flow_days must be at least baseline_days")
        return v

    @field_validator("archive")
    @classmethod
    def _archive_outlives_raw(cls, v: ArchiveSettings, info: ValidationInfo) -> ArchiveSettings:
        # Retention drops a day only once it is archived; a file that expired first would leave the
        # day unarchived, its rows never dropped, and the file written and deleted again every day.
        r = info.data.get("retention")
        if r is not None and v.enabled and 0 < v.retention_days < max(r.flow_days, r.event_days):
            raise ValueError("archive retention_days must be 0 (keep) or at least flow_days and event_days")
        return v


class Settings(StrictModel):
    schema_version: Literal[2]
    revision: int = Field(ge=0)
    pce: PceSettings
    web: WebSettings
    display: DisplaySettings
    logging: LoggingSettings
    collection: CollectionSettings


def default_collection() -> CollectionSettings:
    """Defaults for a fresh install and for upgrading a schema-1 file (spec §6.5 data collection)."""
    return CollectionSettings(
        enabled=True, traffic_interval_seconds=600, events_interval_seconds=300,
        inventory_interval_seconds=3600, rate_limit_per_minute=400, backfill_days=30,
        disk_free_warn_gb=10,
        retention=RetentionSettings(flow_days=35, event_days=90, rollup_days=90, baseline_days=30),
        archive=ArchiveSettings(enabled=False, retention_days=0),
    )


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
        collection=default_collection(),
    )
