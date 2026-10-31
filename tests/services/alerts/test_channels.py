"""The five channels against local stand-ins: success, failure, and no secret in what a failure reports."""
import json
import socketserver
import threading
import typing
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from illumio_ops.domain.values import ChannelKind
from illumio_ops.services.alerts import channels
from illumio_ops.services.alerts.channels import scrub, send
from illumio_ops.services.alerts.messages import Rendered
from illumio_ops.settings.schema import default_alerts

TOKEN = "LINE-SECRET-TOKEN-123"
BOT = "123456:TELEGRAM-SECRET"
HOOK_PATH = "/workflows/abc/triggers/manual?sig=TEAMS-SECRET-SIG"
RENDERED = Rendered(subject="[illumio-ops] HIGH x\r\nBcc: evil@x", text="hello", html="<p>hello</p>", card={"type": "message"},
                    payload={"alerts": []})


class _Handler(BaseHTTPRequestHandler):
    status = 200
    seen: typing.ClassVar[list] = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        _Handler.seen.append((self.path, dict(self.headers), json.loads(body)))
        self.send_response(_Handler.status)
        self.end_headers()
        # Some receivers echo the request line or the token back in their error body.
        self.wfile.write(f"rejected {self.path} {self.headers.get('Authorization', '')}".encode())

    def log_message(self, *a):
        pass


@pytest.fixture
def server(monkeypatch):
    _Handler.status, _Handler.seen = 200, []
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    monkeypatch.setattr(channels, "LINE_PUSH_URL", f"{base}/v2/bot/message/push")
    monkeypatch.setattr(channels, "TELEGRAM_API", base)
    monkeypatch.setattr(channels, "_https_only", lambda url: None)  # the stand-in speaks plain HTTP
    yield base
    srv.shutdown()


def cfg(**overrides):
    c = default_alerts(notify_new_defaults=True).channels.model_dump()
    c["line"].update(enabled=True, access_token=TOKEN, target_id="U1")
    c["telegram"].update(enabled=True, bot_token=BOT, chat_id="42")
    c["teams"].update(enabled=True, webhook_url=f"https://teams.example{HOOK_PATH}")
    c["webhook"].update(enabled=True, url="https://hook.example/in/WEBHOOK-SECRET")
    from illumio_ops.settings.schema import AlertChannels
    out = AlertChannels.model_validate(c)
    for k, v in overrides.items():  # copies skip validation: the local stand-ins speak plain HTTP
        out = out.model_copy(update={k: getattr(out, k).model_copy(update=v)})
    return out


def test_line_success_and_failure(server):
    r = send(ChannelKind.LINE, cfg(), RENDERED)
    assert r.ok and r.error is None
    _, headers, body = _Handler.seen[-1]
    assert headers["Authorization"] == f"Bearer {TOKEN}" and body["to"] == "U1" and body["messages"][0]["text"] == "hello"
    _Handler.status = 400
    r = send(ChannelKind.LINE, cfg(), RENDERED)
    assert not r.ok and "400" in r.error and TOKEN not in r.error


@pytest.mark.parametrize("kind", [ChannelKind.LINE, ChannelKind.TELEGRAM, ChannelKind.TEAMS, ChannelKind.WEBHOOK])
def test_delivery_error_scrubs_secrets(server, kind):
    _Handler.status = 403
    c = cfg(teams={"webhook_url": f"{server}{HOOK_PATH}"}, webhook={"url": f"{server}/in/WEBHOOK-SECRET"})
    r = send(kind, c, RENDERED)
    assert not r.ok
    for secret in (TOKEN, BOT, "TEAMS-SECRET-SIG", "WEBHOOK-SECRET", "/workflows/abc"):
        assert secret not in r.error, (kind, r.error)


def test_unreachable_error_scrubbed():
    c = cfg(webhook={"url": "https://127.0.0.1:1/in/WEBHOOK-SECRET"})
    r = send(ChannelKind.WEBHOOK, c, RENDERED, timeout=2)
    assert not r.ok and "WEBHOOK-SECRET" not in r.error


def test_telegram_sends_html(server):
    assert send(ChannelKind.TELEGRAM, cfg(), RENDERED).ok
    path, _, body = _Handler.seen[-1]
    assert path == f"/bot{BOT}/sendMessage" and body["parse_mode"] == "HTML" and body["chat_id"] == "42"


def test_scrub_removes_every_channel_secret():
    c = cfg(smtp={"password": "SMTP-PASSWORD"})
    text = f"x {TOKEN} {BOT} SMTP-PASSWORD https://teams.example{HOOK_PATH} https://hook.example/in/WEBHOOK-SECRET"
    out = scrub(text, c)
    for secret in (TOKEN, BOT, "SMTP-PASSWORD", "TEAMS-SECRET-SIG", "WEBHOOK-SECRET"):
        assert secret not in out


# ── SMTP against a minimal local server ──

class _Smtp(socketserver.StreamRequestHandler):
    log: typing.ClassVar[list] = []
    refuse = False

    def handle(self):
        def say(line):
            self.wfile.write((line + "\r\n").encode())
        say("220 test")
        data = False
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode().rstrip("\r\n")
            if data:
                if line == ".":
                    data = False
                    say("250 queued")
                else:
                    _Smtp.log.append(("DATA", line))
                continue
            _Smtp.log.append(("CMD", line))
            verb = line.split(" ", 1)[0].upper()
            if verb in ("EHLO", "HELO"):
                say("250-test")
                say("250 AUTH PLAIN LOGIN")
            elif verb == "AUTH":
                say("235 ok")
            elif verb == "RCPT":
                say("550 no such user" if _Smtp.refuse and "bad@" in line else "250 ok")
            elif verb == "DATA":
                data = True
                say("354 go")
            elif verb == "QUIT":
                say("221 bye")
                return
            else:
                say("250 ok")


@pytest.fixture
def smtp():
    _Smtp.log, _Smtp.refuse = [], False
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Smtp)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def smtp_cfg(port, **kw):
    return cfg(smtp={"enabled": True, "host": "127.0.0.1", "port": port, "security": "none", "username": "",
                     "password": "", "sender": "ops@example.com", "recipients": ["sec@example.com"], **kw})


def test_smtp_sends_plain_and_html(smtp):
    assert send(ChannelKind.SMTP, smtp_cfg(smtp), RENDERED).ok
    cmds = [line for kind, line in _Smtp.log if kind == "CMD"]
    assert any(c.upper().startswith("MAIL FROM:<OPS@EXAMPLE.COM>") for c in cmds)
    assert not any(c.upper().startswith("AUTH") for c in cmds)
    data = "\n".join(line for kind, line in _Smtp.log if kind == "DATA")
    assert "text/plain" in data and "text/html" in data


def test_smtp_auth_when_username_set(smtp):
    assert send(ChannelKind.SMTP, smtp_cfg(smtp, username="ops", password="SMTP-PASSWORD"), RENDERED).ok
    assert any(line.upper().startswith("AUTH") for kind, line in _Smtp.log if kind == "CMD")


def test_smtp_refused_recipient_is_failure(smtp):
    _Smtp.refuse = True
    r = send(ChannelKind.SMTP, smtp_cfg(smtp, recipients=["sec@example.com", "bad@example.com"]), RENDERED)
    assert not r.ok and "bad@example.com" in r.error


def test_header_injection_sanitized(smtp):
    assert send(ChannelKind.SMTP, smtp_cfg(smtp), RENDERED).ok
    data = [line for kind, line in _Smtp.log if kind == "DATA"]
    assert not any(line.lower().startswith("bcc:") for line in data)


def test_error_body_scrubbed_before_it_is_cut(server, monkeypatch):
    """A secret straddling the kept length must not survive as a prefix (review: cut first, scrub after)."""
    _Handler.status = 400
    echoed = "rejected /v2/bot/message/push Bearer "
    monkeypatch.setattr(channels, "_ERROR_BODY", len(echoed) + 12)  # the cut falls inside the token
    r = send(ChannelKind.LINE, cfg(), RENDERED)
    assert not r.ok and TOKEN[:8] not in r.error


def test_send_reports_any_transport_error_scrubbed(server):
    """A token that breaks the request line raises http.client.InvalidURL with the whole URL in it."""
    r = send(ChannelKind.TELEGRAM, cfg(telegram={"bot_token": BOT + "\n"}), RENDERED)
    assert not r.ok and BOT not in r.error


@pytest.mark.parametrize("model,field", [("LineChannel", "access_token"), ("TelegramChannel", "bot_token"),
                                         ("SmtpChannel", "password")])
def test_secrets_with_control_characters_rejected(model, field):
    from pydantic import ValidationError

    from illumio_ops.settings import schema
    base = default_alerts(notify_new_defaults=True).channels.model_dump()[model.removesuffix("Channel").lower()]
    base[field] = "abc\ndef"
    with pytest.raises(ValidationError):
        getattr(schema, model).model_validate(base)
