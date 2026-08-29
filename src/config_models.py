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
from urllib.parse import urlsplit

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

class _Base(BaseModel):
    """Base class that rejects unknown keys (catches typos in config.json)."""
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


def _validate_optional_http_url(value: object, field_name: str) -> str:
    """Normalize an optional HTTP(S) URL while keeping it as a plain string."""
    raw = str(value if value is not None else "").strip().rstrip("/")
    if not raw:
        return ""
    try:
        HttpUrl(raw)
    except Exception:
        raise ValueError(
            f"{field_name} must use http or https scheme (e.g. https://console.example.com)"
        ) from None
    if "@" in urlsplit(raw).netloc:
        raise ValueError(f"{field_name} must not include userinfo")
    return raw


class ApiSettings(_Base):
    # url is stored as plain str to avoid pydantic's trailing-slash normalization
    # (HttpUrl validates the scheme; the validator strips any trailing slash).
    url: str = Field(default="https://pce.example.com:8443")
    org_id: str = Field(default="1", min_length=1)
    key: str = Field(default="")
    secret: str = Field(default="")
    profile: Literal["production", "dev"] = "production"
    verify_ssl: bool = True
    deployment_type: Literal["saas", "on_prem"] = "on_prem"
    console_url: str = ""

    @field_validator("verify_ssl", mode="after")
    @classmethod
    def _verify_ssl_production_guard(cls, v: bool, info) -> bool:
        if info.data.get("profile") == "production" and v is False:
            raise ValueError(
                "verify_ssl=False is not allowed when profile='production'. "
                "Set profile='dev' explicitly to disable TLS verification."
            )
        return v

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
        if "@" in urlsplit(raw).netloc:
            raise ValueError("url must not include userinfo")
        return raw

    @field_validator("console_url", mode="before")
    @classmethod
    def validate_console_url(cls, v: object) -> str:
        return _validate_optional_http_url(v, "console_url")

class AlertsSettings(_Base):
    active: list[str] = Field(default_factory=lambda: ["mail"])
    line_channel_access_token: str = Field(
        default="",
        validation_alias=AliasChoices("line_channel_access_token", "line_token"),
    )
    line_target_id: str = ""
    webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    teams_webhook_url: str = ""

    @field_validator("webhook_url", mode="after")
    @classmethod
    def _require_https(cls, v: str) -> str:
        if v and not v.startswith("https://"):
            scheme = v.split("://")[0] if "://" in v else "no scheme"
            raise ValueError(
                "webhook_url must use https:// scheme (got: "
                f"{scheme}://...)"
            )
        return v

    @field_validator("teams_webhook_url", mode="after")
    @classmethod
    def _require_https_teams(cls, v: str) -> str:
        if v and not v.startswith("https://"):
            scheme = v.split("://")[0] if "://" in v else "no scheme"
            raise ValueError(
                "teams_webhook_url must use https:// scheme (got: "
                f"{scheme}://...)"
            )
        return v

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
    format: list[Literal["html", "csv", "xlsx", "all"]] = Field(default_factory=lambda: ["html"])
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
    """APScheduler 執行期設定。

    persist/db_path 已棄用：SQLAlchemy 持久化 job store 已移除——build_scheduler
    以 args=[cm] 註冊 job，ConfigManager 持有 RLock 無法 pickle；且所有 job 皆為
    interval 型、每次 build 時 replace_existing=True 全部重建，persist 對這類
    job 本就無收益。欄位保留只為向下相容舊 config：persist=true 時忽略並記一筆
    warning，不拒絕啟動。
    """
    persist: bool = False          # deprecated — 不再生效，見上方說明
    db_path: str = "config/scheduler.db"  # deprecated — persist 移除後不使用

class WebGuiTls(_Base):
    enabled: bool = True
    cert_file: str = ""
    key_file: str = ""
    self_signed: bool = True
    auto_renew: bool = True
    auto_renew_days: int = Field(default=30, ge=1)
    min_version: str = "TLSv1.2"
    ciphers: Optional[str] = None
    key_algorithm: str = "ecdsa-p256"
    validity_days: int = Field(default=397, ge=1)

class WebGuiSettings(_Base):
    # extra="allow" so that operational flags like ``_initial_password`` and
    # ``must_change_password`` (set during first-boot in ConfigManager) survive
    # schema validation round-trip. Previously this was extra="ignore", which
    # silently stripped both flags and made the force-change-password gate in
    # security_check dead code (M4).
    model_config = ConfigDict(extra="allow")
    username: str = "illumio"
    password: str = "illumio"
    secret_key: str = ""
    allowed_ips: list[str] = Field(default_factory=list)
    public_url: str = ""
    tls: WebGuiTls = Field(default_factory=WebGuiTls)
    must_change_password: bool = False
    # NOTE: `enable_v2_preview` used to live here (Task 1..10, default False).
    # Task 11 made v2 the only GUI, so the flag has no meaning any more. It is
    # deleted rather than deprecated-in-place: model_config is extra="allow"
    # above, so an installed config.json that still carries the key round-trips
    # untouched instead of failing validation.

    @field_validator("public_url", mode="before")
    @classmethod
    def validate_public_url(cls, v: object) -> str:
        return _validate_optional_http_url(v, "public_url")

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
    # 空＝不過濾，與本類別其餘四個欄位一致（TrafficFilter 對 falsy 值即關閉該條件）。
    # 不寫死 decision 清單的兩個理由：(1) 這條設定在 2026-08-27 之前從未接進
    # run_traffic_ingest，production 一直是「全收」，寫死清單會在 wiring 修好的
    # 那一刻讓每台未動過設定的機器開始丟棄 allowed 流量；(2) 清單也不是全集——
    # dashboard 用的是 ["blocked","potentially_blocked","allowed","unknown"]，
    # 另有 "potentially_blocked_by_boundary"，寫死註定隨 PCE 新增值而漂移。
    actions: list[str] = Field(default_factory=list)
    workload_label_env: list[str] = Field(default_factory=list)
    ports: list[int] = Field(default_factory=list)
    protocols: list[str] = Field(default_factory=list)
    exclude_src_ips: list[str] = Field(default_factory=list)

    @field_validator("exclude_src_ips")
    @classmethod
    def _validate_ips(cls, v: list[str]) -> list[str]:
        # 混合語意：含 "/" 視為 CIDR 網段，否則視為精確 IP。這條分類規則必須與
        # src/pce_cache/traffic_filter.py 的 TrafficFilter.__init__ 完全一致，
        # 否則驗證器放行的字串會在 filter 端被當成另一種東西。
        for ip in v:
            if "/" in ip:
                try:
                    ipaddress.ip_network(ip, strict=False)
                except ValueError as e:
                    raise ValueError(f"exclude_src_ips: {ip!r} is not a valid CIDR network") from e
            else:
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
    archive_enabled: bool = False
    archive_dir: str = "data/archive"
    archive_interval_hours: int = Field(default=24, ge=1)
    archive_gzip_after_days: int = Field(default=7, ge=1)
    archive_retention_days: int = Field(default=0, ge=0)  # 0 = 永久保留（不刪 archive 檔）
    disk_free_warn_gb: int = Field(default=10, ge=1)        # 磁碟剩餘低於此 GB 數告警
    siem_pending_warn_rows: int = Field(default=50000, ge=1000)  # SIEM 佇列積壓告警門檻
    cache_read_max_rows: int = Field(default=500000, ge=10000)  # cache 讀取單次視窗列數護欄
    # ── 視窗增量（window delta）──────────────────────────────────────────────
    # 本 PCE 回傳的是整個聚合 bucket 的累計值，不裁切到查詢視窗。開啟後
    # traffic ingest 會每次替每筆 flow 記一列「當下累計值」（pce_traffic_flow_obs），
    # 規則引擎再以「視窗起點前最近一筆觀測」相減得到真正的視窗增量；推導
    # 不出來時退回 phase-1 的聚合基準守門（規則不評估並告知操作者）。
    flow_delta_enabled: bool = True
    # 觀測保留時數。穩態列數 ≈ 活躍 flow 數 × 時數 × (3600 / traffic_poll_interval_seconds)，
    # 每列約 50 bytes。必須 ≥ 最長 threshold_window，否則該規則永遠取不到基準。
    flow_obs_retention_hours: int = Field(default=6, ge=1, le=168)


class SiemDestinationSettings(_Base):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(min_length=1, max_length=64)
    enabled: bool = True
    transport: Literal["udp", "tcp", "tls", "hec"] = "udp"
    format: Literal["cef", "json", "syslog_cef", "syslog_json"] = "cef"
    host: str = ""
    port: int = Field(default=514, ge=1, le=65535)
    profile: Literal["production", "dev"] = "production"
    tls_verify: bool = True

    @field_validator("tls_verify", mode="after")
    @classmethod
    def _tls_verify_production_guard(cls, v: bool, info) -> bool:
        if info.data.get("profile") == "production" and v is False:
            raise ValueError(
                "tls_verify=False is not allowed when profile='production'. "
                "Set profile='dev' explicitly to disable TLS verification."
            )
        return v
    tls_ca_bundle: Optional[str] = None
    hec_token: Optional[str] = None
    batch_size: int = Field(default=100, ge=1, le=10000)
    source_types: list[str] = Field(default_factory=lambda: ["audit", "traffic"])
    max_retries: int = Field(default=10, ge=0)
    mask_pii: bool = Field(
        default=False,
        description="When True, redact PII before formatting: created_by.user.username "
                    "(admin emails), action.src_ip (admin source IPs), and "
                    "resource_changes[].changes before/after (label / description text "
                    "that may carry internal project names). Per-destination opt-in "
                    "so external SaaS SIEMs can receive masked data while an internal "
                    "SOC destination gets the full payload.",
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_endpoint(cls, values: dict) -> dict:
        """Migrate legacy endpoint: "host:port" or HEC URL → host + port."""
        if not isinstance(values, dict):
            return values
        endpoint = values.get("endpoint", "")
        if not endpoint or values.get("host"):
            return values
        transport = values.get("transport", "udp")
        if transport == "hec":
            from urllib.parse import urlparse
            parsed = urlparse(endpoint)
            values["host"] = parsed.hostname or endpoint
            values["port"] = parsed.port or 8088
        else:
            host, _, port_str = endpoint.rpartition(":")
            if host and port_str.isdigit():
                values["host"] = host
                values["port"] = int(port_str)
            elif host:
                values["host"] = host
            else:
                values["host"] = endpoint
        return values


class SiemForwarderSettings(_Base):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = False
    destinations: list[SiemDestinationSettings] = Field(default_factory=list)
    dlq_max_per_dest: int = Field(default=10000, ge=100)
    dispatch_tick_seconds: int = Field(default=30, ge=1)


class ConfigSchema(_Base):
    api: ApiSettings = Field(default_factory=ApiSettings)
    alerts: AlertsSettings = Field(default_factory=AlertsSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    smtp: SmtpSettings = Field(default_factory=SmtpSettings)
    settings: GeneralSettings = Field(default_factory=GeneralSettings)
    rules: list[Rule] = Field(default_factory=list)
    report: ReportSettings = Field(default_factory=ReportSettings)
    report_schedules: list[ReportSchedule] = Field(default_factory=list)
    rule_scheduler: RuleSchedulerSettings = Field(default_factory=RuleSchedulerSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    web_gui: WebGuiSettings = Field(default_factory=WebGuiSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    # Written by apply_best_practices(); must survive pydantic round-trips.
    rule_backups: list = Field(default_factory=list)
    pce_cache: PceCacheSettings = Field(default_factory=PceCacheSettings)
    siem: SiemForwarderSettings = Field(default_factory=SiemForwarderSettings)
