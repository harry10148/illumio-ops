"""Settings › Notification channels: the five channels, secrets masked; a test message with the values on the
page, saved or not (spec §6.5 告警: per-channel test)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from flask import Blueprint
from pydantic import BaseModel, ValidationError

from illumio_ops.domain.values import ChannelKind
from illumio_ops.services.alerts.channels import CredentialsRequired, merge_channels
from illumio_ops.services.alerts.dispatch import send_test
from illumio_ops.settings.schema import AlertChannels
from illumio_ops.settings.secrets import MASK, redact
from illumio_ops.store import alerts as store
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, api_route, operation


# The page's copy of AlertChannels: the same fields as plain values, because a masked URL is not a URL. What is
# saved or sent is validated as AlertChannels after the secrets are merged back in.
class SmtpInput(BaseModel):
    enabled: bool
    host: str
    port: int
    security: Literal["none", "starttls", "tls"]
    username: str
    password: str
    sender: str
    recipients: list[str]


class LineInput(BaseModel):
    enabled: bool
    access_token: str
    target_id: str


class TelegramInput(BaseModel):
    enabled: bool
    bot_token: str
    chat_id: str


class TeamsInput(BaseModel):
    enabled: bool
    webhook_url: str


class WebhookInput(BaseModel):
    enabled: bool
    url: str


class ChannelsInput(BaseModel):
    smtp: SmtpInput
    line: LineInput
    telegram: TelegramInput
    teams: TeamsInput
    webhook: WebhookInput


class ChannelState(BaseModel):
    channel: str
    consecutive_failures: int
    cooldown_until: datetime | None
    last_error: str | None
    last_ok_at: datetime | None


class ChannelsView(BaseModel):
    revision: int
    channels: ChannelsInput
    state: list[ChannelState]


class ChannelsUpdate(BaseModel):
    revision: int
    channels: ChannelsInput


class ChannelTest(BaseModel):
    channel: ChannelKind
    channels: ChannelsInput | None = None


class ChannelTestResult(BaseModel):
    ok: bool
    error: str | None


OP_GET = operation("system.channels.get", "GET", "/api/system/channels", None, ChannelsView)
OP_UPDATE = operation("system.channels.update", "PUT", "/api/system/channels", ChannelsUpdate, ChannelsView)
OP_TEST = operation("system.channels.test", "POST", "/api/system/channels/test", ChannelTest, ChannelTestResult)

bp = Blueprint("system_channels", __name__)


def _t(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _view() -> ChannelsView:
    ctx = get_ctx()
    s = ctx.settings.current()
    with ctx.db() as conn:
        rows = store.channel_state(conn)
    state = [ChannelState(channel=c, consecutive_failures=r["consecutive_failures"], cooldown_until=_t(r["cooldown_until"]),
                          last_error=r["last_error"], last_ok_at=_t(r["last_ok_at"])) for c, r in sorted(rows.items())]
    return ChannelsView(revision=s.revision, channels=ChannelsInput.model_validate(redact(s)["alerts"]["channels"]),
                        state=state)


def _merged(channels: ChannelsInput) -> dict[str, Any]:
    try:
        return merge_channels(get_ctx().settings.current().alerts.channels, channels.model_dump(), mask=MASK)
    except CredentialsRequired as exc:
        raise ApiFailure(400, "credentials_required", "err_channel_credentials_required", field=exc.field) from None


@api_route(bp, OP_GET)
def get_channels() -> ChannelsView:
    return _view()


@api_route(bp, OP_UPDATE)
def update_channels(body: ChannelsUpdate) -> ChannelsView:
    merged = _merged(body.channels)
    get_ctx().settings.update(body.revision, lambda d: d["alerts"].__setitem__("channels", merged))
    return _view()


@api_route(bp, OP_TEST)
def test_channel(body: ChannelTest) -> ChannelTestResult:
    ctx = get_ctx()
    cfg = None
    if body.channels is not None:
        try:
            cfg = AlertChannels.model_validate(_merged(body.channels))
        except ValidationError as exc:
            errs = exc.errors(include_input=False)
            raise ApiFailure(400, "invalid_input", "err_invalid_input",
                             field=".".join(str(p) for p in errs[0]["loc"]) if errs else None) from None
    r = send_test(ctx, body.channel, cfg=cfg)
    return ChannelTestResult(ok=r.ok, error=r.error)
