"""The five notification channels (5.x src/alerts/plugins.py, 5.x 035f7519): LINE push, Telegram, a Teams card,
a generic webhook and SMTP. Standard library only. Whatever a failure reports passes through scrub(): tokens,
passwords and the secret part of webhook URLs never reach a delivery record, a log or the GUI (5.x L-12)."""
from __future__ import annotations

import http.client
import json
import smtplib
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlsplit

from illumio_ops.domain.values import ChannelKind
from illumio_ops.services.alerts.messages import Rendered
from illumio_ops.settings.schema import AlertChannels, SmtpChannel

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
TELEGRAM_API = "https://api.telegram.org"
_OK = {200, 201, 202, 204}
_ERROR_BODY = 300  # characters of a receiver's error body kept in the record


@dataclass(frozen=True)
class SendResult:
    ok: bool
    error: str | None  # already scrubbed


def enabled_channels(cfg: AlertChannels) -> list[str]:
    """The channels new alerts are queued for, in a fixed order."""
    on = {"smtp": cfg.smtp.enabled, "line": cfg.line.enabled, "telegram": cfg.telegram.enabled,
          "teams": cfg.teams.enabled, "webhook": cfg.webhook.enabled}
    return [name for name, enabled in on.items() if enabled]


def _secrets(cfg: AlertChannels) -> list[str]:
    values = [cfg.smtp.password, cfg.line.access_token, cfg.telegram.bot_token, cfg.teams.webhook_url, cfg.webhook.url]
    for url in (cfg.teams.webhook_url, cfg.webhook.url):
        if url:
            parts = urlsplit(url)
            tail = parts.path + (f"?{parts.query}" if parts.query else "")
            values += [tail, parts.path, parts.query]
    # An exception message may hold a secret escaped (repr) or without the whitespace around it.
    values += [form for v in list(values) if v for form in (v.strip(), repr(v)[1:-1])]
    return sorted({v for v in values if v and len(v) > 1}, key=len, reverse=True)


def scrub(text: str, cfg: AlertChannels) -> str:
    """Remove every channel secret from a text: the values themselves and the path and query of webhook URLs."""
    out = str(text)
    for secret in _secrets(cfg):
        out = out.replace(secret, "...")
    return out


def _https_only(url: str) -> None:
    if not url.startswith("https://"):
        raise ValueError("only https:// URLs are sent to")


def _post(url: str, body: dict[str, object], *, headers: dict[str, str], timeout: float) -> tuple[bool, str | None]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return (True, None) if resp.status in _OK else (False, f"status={resp.status}")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - an unreadable error body must not hide the status
            detail = ""
        return False, f"status={exc.code} {detail}".strip()
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError, ValueError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _header(value: str) -> str:
    """CR/LF in a header is header injection (5.x _sanitize_header)."""
    return value.replace("\r", " ").replace("\n", " ")


def _smtp(cfg: SmtpChannel, rendered: Rendered, *, timeout: float) -> tuple[bool, str | None]:
    msg = MIMEMultipart("alternative")
    sender = _header(cfg.sender)
    recipients = [_header(r).strip() for r in cfg.recipients]
    msg["Subject"], msg["From"], msg["To"] = _header(rendered.subject), sender, ", ".join(recipients)
    msg.attach(MIMEText(rendered.text, "plain", "utf-8"))  # plain first: clients show the last part they can
    if rendered.html:
        msg.attach(MIMEText(rendered.html, "html", "utf-8"))
    try:
        context = ssl.create_default_context()
        if cfg.security == "tls":
            server: smtplib.SMTP = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=timeout, context=context)
        else:
            server = smtplib.SMTP(cfg.host, cfg.port, timeout=timeout)
        with server:
            server.ehlo()
            if cfg.security == "starttls":
                server.starttls(context=context)
                server.ehlo()
            if cfg.username:
                server.login(cfg.username, cfg.password)
            refused = server.sendmail(sender, recipients, msg.as_string())
    except (smtplib.SMTPException, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if refused:
        return False, "refused: " + ", ".join(sorted(refused))
    return True, None


def send(channel: ChannelKind, cfg: AlertChannels, rendered: Rendered, *, timeout: float = 10.0) -> SendResult:
    if channel is ChannelKind.SMTP:
        ok, error = _smtp(cfg.smtp, rendered, timeout=timeout)
    elif channel is ChannelKind.LINE:
        ok, error = _post(LINE_PUSH_URL, {"to": cfg.line.target_id, "messages": [{"type": "text", "text": rendered.text}]},
                          headers={"Authorization": f"Bearer {cfg.line.access_token}"}, timeout=timeout)
    elif channel is ChannelKind.TELEGRAM:
        ok, error = _post(f"{TELEGRAM_API}/bot{cfg.telegram.bot_token}/sendMessage",
                          {"chat_id": cfg.telegram.chat_id, "text": rendered.text, "parse_mode": "HTML",
                           "disable_web_page_preview": True}, headers={}, timeout=timeout)
    else:
        url = cfg.teams.webhook_url if channel is ChannelKind.TEAMS else cfg.webhook.url
        body = rendered.card if channel is ChannelKind.TEAMS else rendered.payload
        try:
            _https_only(url)
        except ValueError as exc:
            return SendResult(ok=False, error=str(exc))
        ok, error = _post(url, body or {}, headers={}, timeout=timeout)
    # Scrubbed before it is cut: a secret straddling the cut would otherwise survive as a prefix.
    return SendResult(ok=ok, error=None if ok else scrub(error or "failed", cfg)[:_ERROR_BODY])


# ── saving and testing channel settings from the settings page ───────────────

SECRET_FIELD_OF: dict[str, str] = {"smtp": "password", "line": "access_token", "telegram": "bot_token",
                               "teams": "webhook_url", "webhook": "url"}
_SMTP_DESTINATION = ("host", "port", "security", "username")


class CredentialsRequired(Exception):
    """A saved secret would go to a destination the operator changed without typing the secret again."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(field)


def merge_channels(saved: AlertChannels, submitted: dict[str, dict[str, object]], *, mask: str) -> dict[str, object]:
    """The submitted channel settings with each blank or masked secret replaced by the saved one: the page never
    receives the secrets, so it cannot send them back. The SMTP password is kept only while the server and the
    account stay the same — otherwise anyone holding a session could point it at their own mail server (the same
    rule as the PCE connection page)."""
    out: dict[str, dict[str, object]] = {name: dict(values) for name, values in submitted.items()}
    for name, key in SECRET_FIELD_OF.items():
        if out.get(name, {}).get(key) in ("", mask):
            out.setdefault(name, {})[key] = getattr(getattr(saved, name), key)
    smtp = out.get("smtp", {})
    kept = submitted.get("smtp", {}).get("password") in ("", mask) and bool(saved.smtp.password)
    moved = any(smtp.get(f) != getattr(saved.smtp, f) for f in _SMTP_DESTINATION)
    if kept and moved:
        raise CredentialsRequired("channels.smtp.password")
    return dict(out)
