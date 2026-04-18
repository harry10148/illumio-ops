"""Pydantic v2 schemas for illumio_ops config.json.

Validation happens at ConfigManager.load() time — malformed config
surfaces clear errors instead of blowing up later with a KeyError
deep inside business logic.

The models preserve the exact field names and nesting of the legacy
_DEFAULT_CONFIG dict so ConfigSchema.model_validate(dict).model_dump()
produces an identical dict, keeping 70+ existing cm.config[...] call
sites working unchanged.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

class _Base(BaseModel):
    """Base class that rejects unknown keys (catches typos in config.json)."""
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

class ApiSettings(_Base):
    # url is stored as plain str to avoid pydantic's trailing-slash normalization
    # (HttpUrl validates the scheme; the validator strips any trailing slash).
    url: str = Field(default="https://pce.example.com:8443")
    org_id: str = Field(default="1", min_length=1)
    key: str = Field(default="")
    secret: str = Field(default="")
    verify_ssl: bool = True

    @field_validator("url", mode="before")
    @classmethod
    def validate_url_scheme(cls, v: object) -> str:
        """Accept only http/https URLs; reject ftp:// and other schemes."""
        if v is None or str(v).strip() == "":
            raise ValueError("url must be a non-empty http(s) URL")
        raw = str(v).strip().rstrip("/")
        # Use HttpUrl as an oracle for scheme/structure, but keep the original string
        try:
            HttpUrl(raw)
        except Exception:
            raise ValueError(
                "url must use http or https scheme (e.g. https://pce.example.com:8443)"
            ) from None
        return raw

class AlertsSettings(_Base):
    active: list[str] = Field(default_factory=lambda: ["mail"])
    line_channel_access_token: str = ""
    line_target_id: str = ""
    webhook_url: str = ""

class EmailSettings(_Base):
    sender: str = "monitor@localhost"
    recipients: list[str] = Field(default_factory=lambda: ["admin@example.com"])

class SmtpSettings(_Base):
    host: str = "localhost"
    port: int = Field(default=25, ge=1, le=65535)
    user: str = ""
    password: str = ""
    enable_auth: bool = False
    enable_tls: bool = False

class GeneralSettings(_Base):
    language: Literal["en", "zh_TW"] = "en"
    theme: Literal["light", "dark"] = "light"
    timezone: str = "local"
    enable_health_check: bool = True
    dashboard_queries: list[dict] = Field(default_factory=list)

class ReportApiQuery(_Base):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    max_results: int = Field(default=200000, ge=1, le=1_000_000)

class ReportSettings(_Base):
    enabled: bool = False
    schedule: Literal["daily", "weekly", "monthly"] = "weekly"
    day_of_week: Literal["monday", "tuesday", "wednesday", "thursday",
                         "friday", "saturday", "sunday"] = "monday"
    hour: int = Field(default=8, ge=0, le=23)
    source: Literal["api", "csv"] = "api"
    format: list[Literal["html", "csv", "pdf", "xlsx", "all"]] = Field(default_factory=lambda: ["html"])
    email_report: bool = False
    output_dir: str = "reports/"
    retention_days: int = Field(default=30, ge=1)
    include_raw_data: bool = False
    max_top_n: int = Field(default=20, ge=1, le=100)
    api_query: ReportApiQuery = Field(default_factory=ReportApiQuery)

class LoggingSettings(_Base):
    level: str = "INFO"
    json_sink: bool = False
    rotation: str = "10 MB"
    retention: int = 10

class RuleSchedulerSettings(_Base):
    enabled: bool = True
    check_interval_seconds: int = Field(default=300, ge=60)   # min 1 minute

class WebGuiTls(_Base):
    enabled: bool = False
    cert_file: str = ""
    key_file: str = ""
    self_signed: bool = False

class WebGuiSettings(_Base):
    username: str = "illumio"
    password_hash: str = ""
    password_salt: str = ""
    secret_key: str = ""
    allowed_ips: list[str] = Field(default_factory=list)
    tls: WebGuiTls = Field(default_factory=WebGuiTls)

class PceProfile(_Base):
    """Extra=allow since PCE profile shape may evolve; only require id + url."""
    model_config = ConfigDict(extra="allow")
    id: int = Field(ge=1)
    url: str
    org_id: str = "1"
    key: str = ""
    secret: str = ""
    name: str = ""

class ReportSchedule(_Base):
    """Report schedule entries; extra=allow because schedule shape
    may evolve during Phase 6 APScheduler migration."""
    model_config = ConfigDict(extra="allow")
    id: Optional[int] = None
    name: str = ""

class Rule(_Base):
    """Runtime rule — shape varies by type. Keep flexible."""
    model_config = ConfigDict(extra="allow")
    type: str
    name: str = ""

class ConfigSchema(_Base):
    api: ApiSettings = Field(default_factory=ApiSettings)
    alerts: AlertsSettings = Field(default_factory=AlertsSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    smtp: SmtpSettings = Field(default_factory=SmtpSettings)
    settings: GeneralSettings = Field(default_factory=GeneralSettings)
    rules: list[Rule] = Field(default_factory=list)
    report: ReportSettings = Field(default_factory=ReportSettings)
    report_schedules: list[ReportSchedule] = Field(default_factory=list)
    pce_profiles: list[PceProfile] = Field(default_factory=list)
    active_pce_id: Optional[int] = None
    rule_scheduler: RuleSchedulerSettings = Field(default_factory=RuleSchedulerSettings)
    web_gui: WebGuiSettings = Field(default_factory=WebGuiSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    # Written by apply_best_practices(); must survive pydantic round-trips.
    rule_backups: list = Field(default_factory=list)
