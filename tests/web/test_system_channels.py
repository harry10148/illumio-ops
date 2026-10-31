"""Settings › Notification channels: secrets masked out, kept when the form sends the mask back, never sent to a
destination the operator just changed without retyping them."""
from illumio_ops.services.alerts import dispatch
from illumio_ops.services.alerts.channels import SendResult
from illumio_ops.settings.secrets import MASK

from .conftest import LOCAL, csrf, login, post

SECRETS = ("SMTP-PASSWORD", "LINE-TOKEN", "TG:BOT-TOKEN", "TEAMS-SIG", "HOOK-SECRET")


def view(client):
    return client.get("/api/system/channels", environ_overrides=LOCAL).get_json()["data"]


def put(client, body):
    return client.open("/api/system/channels", method="PUT", json=body, environ_overrides=LOCAL,
                       headers={"X-CSRFToken": csrf(client)})


def configured(client):
    v = view(client)
    ch = v["channels"]
    ch["smtp"].update(enabled=True, host="mail.example", port=587, security="starttls", username="ops",
                      password="SMTP-PASSWORD", sender="ops@example.com", recipients=["sec@example.com"])
    ch["line"].update(enabled=True, access_token="LINE-TOKEN", target_id="U1")
    ch["telegram"].update(enabled=True, bot_token="TG:BOT-TOKEN", chat_id="42")
    ch["teams"].update(enabled=True, webhook_url="https://teams.example/x?sig=TEAMS-SIG")
    ch["webhook"].update(enabled=True, url="https://hook.example/in/HOOK-SECRET")
    r = put(client, {"revision": v["revision"], "channels": ch})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]


def test_channels_get_masks_secrets(client):
    login(client)
    data = configured(client)
    text = str(view(client))
    assert not any(s in text for s in SECRETS) and data["channels"]["line"]["access_token"] == MASK
    assert data["channels"]["line"]["target_id"] == "U1" and data["channels"]["smtp"]["username"] == "ops"


def test_channels_put_mask_keeps_secret(client, ctx):
    login(client)
    data = configured(client)
    data["channels"]["line"]["target_id"] = "U2"
    r = put(client, {"revision": data["revision"], "channels": data["channels"]})  # every secret is the mask
    assert r.status_code == 200
    saved = ctx.settings.current().alerts.channels
    assert (saved.line.access_token, saved.line.target_id, saved.smtp.password) == ("LINE-TOKEN", "U2", "SMTP-PASSWORD")
    assert saved.teams.webhook_url == "https://teams.example/x?sig=TEAMS-SIG"


def test_changing_smtp_host_needs_the_password_again(client):
    # Otherwise anyone holding a session could point the saved password at their own mail server.
    login(client)
    data = configured(client)
    data["channels"]["smtp"]["host"] = "attacker.example"
    r = put(client, {"revision": data["revision"], "channels": data["channels"]})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "credentials_required"


def test_channels_invalid_400_with_field(client):
    login(client)
    v = view(client)
    v["channels"]["webhook"].update(enabled=True, url="http://plain.example/x")
    r = put(client, {"revision": v["revision"], "channels": v["channels"]})
    assert r.status_code == 400 and "webhook" in r.get_json()["error"]["field"]


def test_channels_test_uses_unsaved_values(client, monkeypatch):
    login(client)
    v = view(client)
    seen = []
    monkeypatch.setattr(dispatch, "send", lambda kind, cfg, rendered, **kw: seen.append(cfg) or SendResult(True, None))
    v["channels"]["line"].update(enabled=True, access_token="NEW-TOKEN", target_id="U9")
    r = post(client, "/api/system/channels/test", {"channel": "line", "channels": v["channels"]})
    assert r.get_json()["data"] == {"ok": True, "error": None} and seen[0].line.target_id == "U9"


def test_channels_test_mask_uses_stored_secret(client, monkeypatch):
    login(client)
    data = configured(client)
    seen = []
    monkeypatch.setattr(dispatch, "send", lambda kind, cfg, rendered, **kw: seen.append(cfg) or SendResult(False, "x"))
    r = post(client, "/api/system/channels/test", {"channel": "line", "channels": data["channels"]})
    assert r.get_json()["data"]["ok"] is False and seen[0].line.access_token == "LINE-TOKEN"
    data["channels"]["smtp"]["host"] = "attacker.example"
    r = post(client, "/api/system/channels/test", {"channel": "smtp", "channels": data["channels"]})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "credentials_required"
