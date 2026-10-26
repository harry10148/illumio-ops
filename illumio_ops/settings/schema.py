"""The settings file schema (config/settings.json).

Every model forbids unknown keys and has NO field defaults: a file missing a
field is invalid, never silently completed. Defaults live only in
default_settings(), used for a fresh install and by the 5.x migrator.
"""
from __future__ import annotations

import re
from datetime import UTC, timedelta, timezone, tzinfo
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

from illumio_ops.domain.alertpack import best_practice_rules
from illumio_ops.domain.alertrules import AlertRule
from illumio_ops.domain.identity import normalize_process
from illumio_ops.domain.netaddr import parse_ip_token
from illumio_ops.domain.values import (
    DEFAULT_SUSPICIOUS_TOOLS,
    CollectionMode,
    DeploymentType,
    Language,
    PortClass,
)

SCHEMA_VERSION: Literal[5] = 5
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

    def zone(self) -> tzinfo | None:
        """The zone the setting names; None is the server's own clock ('local')."""
        if self.timezone == "local":
            return None
        if self.timezone == "UTC":
            return UTC
        m = _UTC_OFFSET.fullmatch(self.timezone)
        if m:
            return timezone(timedelta(hours=float(m.group(1))))
        return ZoneInfo(self.timezone)


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


def _process_names(v: tuple[str, ...]) -> tuple[str, ...]:
    out = []
    for name in v:
        norm = normalize_process(name)
        if norm is None:
            raise ValueError("every entry must be a process name")
        out.append(norm)
    return tuple(out)


def _addresses(v: tuple[str, ...]) -> tuple[str, ...]:
    out = []
    for token in v:
        if "/" in token:
            raise ValueError("every entry must be one address, not a network")
        try:
            out.append(str(parse_ip_token(token)))
        except ValueError:
            raise ValueError("every entry must be an IP address") from None
    return tuple(out)


class PortEntry(StrictModel):
    port: int = Field(ge=0, le=65535)
    proto: int | None = Field(ge=0, le=255)  # None = any protocol
    # Which detectors an added port feeds (spec §6.5.8); a removal ignores it. Files before v5 have none.
    category: PortClass = PortClass.REMOTE


class LabelSelector(StrictModel):
    key: str = Field(min_length=1, max_length=255)
    value: str = Field(min_length=1, max_length=255)


class ExpectedInitiators(StrictModel):
    port: int = Field(ge=0, le=65535)
    proto: int | None = Field(ge=0, le=255)
    # Stored as normalize_process gives them, so the comparison with flow records is exact.
    processes: Annotated[tuple[str, ...], AfterValidator(_process_names)] = Field(min_length=1)


class DetectorSettings(StrictModel):
    fanout_targets: int = Field(ge=2, le=10000)
    fanout_window_minutes: int = Field(ge=10, le=1440)
    account_fanout_targets: int = Field(ge=2, le=10000)
    account_fanout_window_minutes: int = Field(ge=10, le=1440)
    chain_window_minutes: int = Field(ge=10, le=1440)
    blocked_targets: int = Field(ge=2, le=10000)
    blocked_window_minutes: int = Field(ge=10, le=1440)
    blocked_surge_factor: float = Field(ge=1.0, le=100.0)
    exclude_system_accounts: bool
    precursor_hours: int = Field(ge=1, le=168)
    # Anomalies in allowed traffic (spec §6.5.8)
    peer_min_group: int = Field(ge=3, le=1000)
    volume_surge_factor: float = Field(ge=1.5, le=100.0)
    volume_min_connections: int = Field(ge=10, le=10_000_000)
    volume_min_mb: int = Field(ge=1, le=10_000_000)
    directory_min_connections: int = Field(ge=10, le=10_000_000)
    account_history_days: int = Field(ge=1, le=90)
    process_history_days: int = Field(ge=1, le=90)
    directory_min_sources: int = Field(ge=2, le=1000)
    directory_followup_minutes: int = Field(ge=10, le=1440)


class LateralSettings(StrictModel):
    """Lateral-movement analysis (spec §6.5.1): which ports count as management, which hosts matter,
    and the detectors' thresholds."""
    extra_admin_ports: tuple[PortEntry, ...]
    removed_admin_ports: tuple[PortEntry, ...]
    include_pce_admin_services: bool
    critical_assets: tuple[LabelSelector, ...]
    admin_groups: tuple[LabelSelector, ...]
    environment_label_key: str = Field(min_length=1, max_length=255)
    graph_hops: int = Field(ge=1, le=6)
    observation_days: int = Field(ge=1, le=365)
    expected_initiators: tuple[ExpectedInitiators, ...]
    detectors: DetectorSettings
    # Peer groups are hosts sharing these label values (spec §6.5.8 A).
    peer_group_keys: tuple[Annotated[str, Field(min_length=1, max_length=255)], ...] = Field(min_length=1,
                                                                                             max_length=4)
    # Directory servers as declared; the detectors also infer them from traffic (spec §6.5.8 E).
    directory_servers: tuple[LabelSelector, ...]
    directory_server_ips: Annotated[tuple[str, ...], AfterValidator(_addresses)] = Field(max_length=100)
    suspicious_tools: Annotated[tuple[str, ...], AfterValidator(_process_names)]

    @field_validator("peer_group_keys")
    @classmethod
    def _distinct_keys(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(v) != len(set(v)):
            raise ValueError("each label key may be listed once")
        return v

    @field_validator("removed_admin_ports")
    @classmethod
    def _not_added_and_removed(cls, v: tuple[PortEntry, ...], info: ValidationInfo) -> tuple[PortEntry, ...]:
        added = {(e.port, e.proto) for e in info.data.get("extra_admin_ports", ())}
        if added & {(e.port, e.proto) for e in v}:
            raise ValueError("a port cannot be both added and removed")
        return v

    @field_validator("expected_initiators")
    @classmethod
    def _one_row_per_port(cls, v: tuple[ExpectedInitiators, ...]) -> tuple[ExpectedInitiators, ...]:
        keys = [(e.port, e.proto) for e in v]
        if len(keys) != len(set(keys)):
            raise ValueError("each port and protocol may be listed once")
        return v


def _https_or_empty(v: str) -> str:
    if v and not re.match(r"^https://[^/\s]+", v):
        raise ValueError("must be an https:// URL")
    return v


HttpsUrl = Annotated[str, AfterValidator(_https_or_empty)]


def _no_control(v: str) -> str:
    # A control character in a token breaks the request line, and the error the HTTP library raises holds it.
    if any(ord(c) < 32 or ord(c) == 127 for c in v):
        raise ValueError("must not contain control characters")
    return v


Secret = Annotated[str, AfterValidator(_no_control)]


def _require(enabled: bool, fields: dict[str, object]) -> None:
    missing = [name for name, value in fields.items() if not value]
    if enabled and missing:
        raise ValueError(f"an enabled channel needs {', '.join(missing)}")


class SmtpChannel(StrictModel):
    enabled: bool
    host: str
    port: int = Field(ge=1, le=65535)
    security: Literal["none", "starttls", "tls"]
    username: str  # empty: no sign-in
    password: Secret
    sender: str
    recipients: tuple[str, ...]

    @field_validator("recipients")
    @classmethod
    def _addresses(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        out = tuple(a.strip() for a in v)
        if any("@" not in a or any(c in a for c in "\r\n,; ") for a in out):
            raise ValueError("every recipient must be one email address")
        return out

    @model_validator(mode="after")
    def _complete(self) -> SmtpChannel:
        _require(self.enabled, {"host": self.host, "sender": self.sender, "recipients": self.recipients})
        return self


class LineChannel(StrictModel):
    enabled: bool
    access_token: Secret
    target_id: str

    @model_validator(mode="after")
    def _complete(self) -> LineChannel:
        _require(self.enabled, {"access_token": self.access_token, "target_id": self.target_id})
        return self


class TelegramChannel(StrictModel):
    enabled: bool
    bot_token: Secret
    chat_id: str

    @model_validator(mode="after")
    def _complete(self) -> TelegramChannel:
        _require(self.enabled, {"bot_token": self.bot_token, "chat_id": self.chat_id})
        return self


class TeamsChannel(StrictModel):
    enabled: bool
    webhook_url: HttpsUrl

    @model_validator(mode="after")
    def _complete(self) -> TeamsChannel:
        _require(self.enabled, {"webhook_url": self.webhook_url})
        return self


class WebhookChannel(StrictModel):
    enabled: bool
    url: HttpsUrl

    @model_validator(mode="after")
    def _complete(self) -> WebhookChannel:
        _require(self.enabled, {"url": self.url})
        return self


class AlertChannels(StrictModel):
    smtp: SmtpChannel
    line: LineChannel
    telegram: TelegramChannel
    teams: TeamsChannel
    webhook: WebhookChannel


class AlertSettings(StrictModel):
    """Notification channels, the alert rules (spec §6.5 告警) and how long alert records are kept."""
    channels: AlertChannels
    rules: tuple[AlertRule, ...] = Field(max_length=300)
    retention_days: int = Field(ge=1, le=3650)

    @field_validator("rules")
    @classmethod
    def _unique_ids(cls, v: tuple[AlertRule, ...]) -> tuple[AlertRule, ...]:
        ids = [r.id for r in v]
        if len(ids) != len(set(ids)):
            raise ValueError("rule ids must be unique")
        return v


class Settings(StrictModel):
    schema_version: Literal[5]
    revision: int = Field(ge=0)
    pce: PceSettings
    web: WebSettings
    display: DisplaySettings
    logging: LoggingSettings
    collection: CollectionSettings
    # observation_days is not checked against collection.retention.baseline_days here: lowering the
    # baseline on the data-collection page must not fail on a field of another page. The exposure
    # graph uses the smaller of the two and says so (P3 Task 1 ruling).
    lateral: LateralSettings
    alerts: AlertSettings


def default_alerts(*, notify_new_defaults: bool) -> AlertSettings:
    """Every channel off, alert records kept 90 days, the best-practice pack (spec §6.5.2)."""
    return AlertSettings(
        channels=AlertChannels(
            smtp=SmtpChannel(enabled=False, host="", port=25, security="none", username="", password="", sender="",
                             recipients=()),
            line=LineChannel(enabled=False, access_token="", target_id=""),
            telegram=TelegramChannel(enabled=False, bot_token="", chat_id=""),
            teams=TeamsChannel(enabled=False, webhook_url=""),
            webhook=WebhookChannel(enabled=False, url=""),
        ),
        rules=best_practice_rules(notify_new_defaults=notify_new_defaults),
        retention_days=90,
    )


def default_collection() -> CollectionSettings:
    """Defaults for a fresh install and for upgrading a schema-1 file (spec §6.5 data collection)."""
    return CollectionSettings(
        enabled=True, traffic_interval_seconds=600, events_interval_seconds=300,
        inventory_interval_seconds=3600, rate_limit_per_minute=400, backfill_days=30,
        disk_free_warn_gb=10,
        retention=RetentionSettings(flow_days=35, event_days=90, rollup_days=90, baseline_days=30),
        archive=ArchiveSettings(enabled=False, retention_days=0),
    )


def default_lateral() -> LateralSettings:
    """Defaults for a fresh install and for upgrading a schema-2 file. The expected initiators come from
    what lab showed on each port (P3 plan Task 0); LDAP and Kerberos have too many legitimate ones."""
    windows_remote = ("powershell.exe", "pwsh.exe", "pwsh", "wsmprovhost.exe", "svchost.exe")
    return LateralSettings(
        extra_admin_ports=(), removed_admin_ports=(), include_pce_admin_services=True,
        critical_assets=(), admin_groups=(), environment_label_key="env", graph_hops=3, observation_days=30,
        expected_initiators=(
            ExpectedInitiators(port=445, proto=6, processes=("system", "svchost.exe", "lsass.exe", "explorer.exe",
                                                             "services.exe", "mount.cifs", "smbclient")),
            ExpectedInitiators(port=3389, proto=6, processes=("mstsc.exe", "msrdc.exe", "rdcman.exe", "xfreerdp",
                                                              "remmina")),
            ExpectedInitiators(port=22, proto=6, processes=("ssh", "scp", "sftp", "rsync", "git", "ssh.exe",
                                                            "putty.exe", "plink.exe", "winscp.exe")),
            ExpectedInitiators(port=5985, proto=6, processes=windows_remote),
            ExpectedInitiators(port=5986, proto=6, processes=windows_remote),
            ExpectedInitiators(port=135, proto=6, processes=("lsass.exe", "svchost.exe", "services.exe",
                                                             "backgroundtaskhost.exe", "wmiprvse.exe", "dsregcmd.exe",
                                                             "mmc.exe")),
        ),
        detectors=DetectorSettings(
            fanout_targets=10, fanout_window_minutes=60, account_fanout_targets=10, account_fanout_window_minutes=60,
            chain_window_minutes=30, blocked_targets=5, blocked_window_minutes=60, blocked_surge_factor=3.0,
            exclude_system_accounts=True, precursor_hours=24, peer_min_group=5, volume_surge_factor=3.0,
            volume_min_connections=1000, volume_min_mb=1024, directory_min_connections=500, account_history_days=7,
            process_history_days=7, directory_min_sources=3, directory_followup_minutes=30,
        ),
        peer_group_keys=("app", "role"), directory_servers=(), directory_server_ips=(),
        suspicious_tools=DEFAULT_SUSPICIOUS_TOOLS,
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
        lateral=default_lateral(),
        alerts=default_alerts(notify_new_defaults=True),
    )
