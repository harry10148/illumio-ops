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

import ipaddress
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, HttpUrl, field_validator

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
    line_channel_access_token: str = Field(
        default="",
        validation_alias=AliasChoices("line_channel_access_token", "line_token"),
    )
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
    snapshot_retention_days: int = Field(default=90, ge=1, le=3650)
    draft_actions_enabled: bool = True

class LoggingSettings(_Base):
    level: str = "INFO"
    json_sink: bool = False
    rotation: str = "10 MB"
    retention: int = 10

class RuleSchedulerSettings(_Base):
    enabled: bool = True
    check_interval_seconds: int = Field(default=300, ge=60)   # min 1 minute

class SchedulerSettings(_Base):
    persist: bool = False          # enable SQLAlchemy job store for daemon restart durability
    db_path: str = "config/scheduler.db"

class WebGuiTls(_Base):
    enabled: bool = True
    cert_file: str = ""
    key_file: str = ""
    self_signed: bool = False
    auto_renew: bool = True
    auto_renew_days: int = Field(default=30, ge=1)
    min_version: str = "TLSv1.2"
    ciphers: Optional[str] = None
    key_algorithm: str = "ecdsa-p256"
    validity_days: int = Field(default=397, ge=1)
    http_redirect_port: int = Field(default=80, ge=1, le=65535)

class WebGuiSettings(_Base):
    # extra="ignore" for forward-compat: new keys added in future config
    # versions are silently ignored rather than causing validation failure.
    model_config = ConfigDict(extra="ignore")
    username: str = "illumio"
    password: str = "illumio"
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
    cron_expr: Optional[str] = None  # e.g. "0 8 * * MON-FRI"
    timezone: Optional[str] = None   # e.g. "Asia/Taipei", "UTC", "UTC+8"

class Rule(_Base):
    """Runtime rule — shape varies by type. Keep flexible."""
    model_config = ConfigDict(extra="allow")
    type: str
    name: str = ""

class TrafficFilterSettings(_Base):
    model_config = ConfigDict(extra="ignore")
    actions: list[str] = Field(default_factory=lambda: ["blocked", "potentially_blocked"])
    workload_label_env: list[str] = Field(default_factory=list)
    ports: list[int] = Field(default_factory=list)
    protocols: list[str] = Field(default_factory=list)
    exclude_src_ips: list[str] = Field(default_factory=list)

    @field_validator("exclude_src_ips")
    @classmethod
    def _validate_ips(cls, v: list[str]) -> list[str]:
        for ip in v:
            try:
                ipaddress.ip_address(ip)
            except ValueError as e:
                raise ValueError(f"exclude_src_ips: {ip!r} is not a valid IP address") from e
        return v

    @field_validator("ports")
    @classmethod
    def _validate_ports(cls, v: list[int]) -> list[int]:
        for p in v:
            if not (1 <= p <= 65535):
                raise ValueError(f"ports: {p} is out of range (1-65535)")
        return v


class TrafficSamplingSettings(_Base):
    model_config = ConfigDict(extra="ignore")
    sample_ratio_allowed: int = Field(default=1, ge=1)
    max_rows_per_batch: int = Field(default=200000, ge=1, le=200000)


class PceCacheSettings(_Base):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = False
    db_path: str = "data/pce_cache.sqlite"
    events_retention_days: int = Field(default=90, ge=1)
    traffic_raw_retention_days: int = Field(default=7, ge=1)
    traffic_agg_retention_days: int = Field(default=90, ge=1)
    events_poll_interval_seconds: int = Field(default=300, ge=30)
    traffic_poll_interval_seconds: int = Field(default=3600, ge=60)
    rate_limit_per_minute: int = Field(default=400, ge=10, le=500)
    async_threshold_events: int = Field(default=10000, ge=1, le=10000)
    traffic_filter: TrafficFilterSettings = Field(default_factory=TrafficFilterSettings)
    traffic_sampling: TrafficSamplingSettings = Field(default_factory=TrafficSamplingSettings)


class SiemDestinationSettings(_Base):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(min_length=1, max_length=64)
    enabled: bool = True
    transport: str = "udp"  # udp|tcp|tls|hec
    format: str = "cef"    # cef|json|syslog_cef|syslog_json
    endpoint: str = ""
    tls_verify: bool = True
    tls_ca_bundle: Optional[str] = None
    hec_token: Optional[str] = None
    batch_size: int = Field(default=100, ge=1, le=10000)
    source_types: list[str] = Field(default_factory=lambda: ["audit", "traffic"])
    max_retries: int = Field(default=10, ge=0)


class SiemForwarderSettings(_Base):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = False
    destinations: list[SiemDestinationSettings] = Field(default_factory=list)
    dlq_max_per_dest: int = Field(default=10000, ge=100)
    dispatch_tick_seconds: int = Field(default=5, ge=1)


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
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    web_gui: WebGuiSettings = Field(default_factory=WebGuiSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    # Written by apply_best_practices(); must survive pydantic round-trips.
    rule_backups: list = Field(default_factory=list)
    pce_cache: PceCacheSettings = Field(default_factory=PceCacheSettings)
    siem: SiemForwarderSettings = Field(default_factory=SiemForwarderSettings)
