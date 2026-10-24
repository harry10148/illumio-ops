"""The parts of the 5.x settings model the P1 migration reads, with 5.x's own parsing:
strings stripped, "true"/"false" coerced, and 5.x defaults for missing keys
(src/config_models.py, identical in v5.0.0 and v5.2.x for these fields). Unknown keys are
ignored here; the migration report accounts for every key separately.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _V5(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")


class V5Api(_V5):
    url: str = "https://pce.example.com:8443"
    org_id: str = "1"
    key: str = ""
    secret: str = ""
    profile: str = "production"
    verify_ssl: bool = True
    deployment_type: str = "on_prem"
    console_url: str = ""
    events_timeout_seconds: int | None = None


class V5Tls(_V5):
    enabled: bool = True
    cert_file: str = ""
    key_file: str = ""
    self_signed: bool = True
    auto_renew: bool = True
    auto_renew_days: int = 30
    min_version: str = "TLSv1.2"
    ciphers: str | None = None
    key_algorithm: str = "ecdsa-p256"
    validity_days: int = 397


class V5WebGui(_V5):
    username: str = "illumio"
    password: str = ""
    secret_key: str = ""
    allowed_ips: list[str] = Field(default_factory=list)
    session_lifetime_seconds: int = 28800
    must_change_password: bool = False
    tls: V5Tls = Field(default_factory=V5Tls)


class V5General(_V5):
    language: str = "en"
    timezone: str = "local"


class V5Logging(_V5):
    level: str = "INFO"


class V5Config(_V5):
    api: V5Api = Field(default_factory=V5Api)
    web_gui: V5WebGui = Field(default_factory=V5WebGui)
    settings: V5General = Field(default_factory=V5General)
    logging: V5Logging = Field(default_factory=V5Logging)
