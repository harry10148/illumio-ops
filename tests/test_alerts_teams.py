"""TeamsAlertPlugin: POSTs an Adaptive Card; redacts the secret webhook URL (L-12)."""
import json
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

from src.alerts import build_output_plugin, get_output_registry

_URL = ("https://prod-12.westus.logic.azure.com/workflows/abc/"
        "triggers/manual/paths/invoke?sig=SUPERSECRETSIG")


def _make_cm(url=_URL):
    cm = MagicMock()
    cm.config = {"alerts": {"teams_webhook_url": url}, "settings": {"language": "en"}}
    return cm


def _reporter_stub():
    r = MagicMock()
    r._build_teams_card.return_value = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {"type": "AdaptiveCard", "version": "1.4", "body": []},
        }],
    }
    return r


def test_teams_plugin_registered():
    assert "teams" in get_output_registry()


def test_teams_plugin_skipped_when_unconfigured():
    plug = build_output_plugin("teams", _make_cm(url=""))
    res = plug.send(_reporter_stub(), "subj")
    assert res == {"channel": "teams", "status": "skipped", "target": "", "error": "missing configuration"}


def test_teams_plugin_posts_card_on_success_and_redacts_target():
    plug = build_output_plugin("teams", _make_cm())
    fake_resp = MagicMock(status=202)
    fake_resp.__enter__ = lambda self: self
    fake_resp.__exit__ = lambda self, *a: False
    with patch("urllib.request.urlopen", return_value=fake_resp) as mock_open:
        res = plug.send(_reporter_stub(), "subj")
    assert res["channel"] == "teams"
    assert res["status"] == "success"
    assert "SUPERSECRETSIG" not in res["target"]
    assert "sig=" not in res["target"]
    assert res["target"].startswith("https://prod-12.westus.logic.azure.com")
    req = mock_open.call_args[0][0]
    assert req.full_url == _URL
    body = json.loads(req.data.decode())
    assert body["attachments"][0]["contentType"] == "application/vnd.microsoft.card.adaptive"


def test_teams_plugin_fails_on_4xx_without_leaking_secret():
    plug = build_output_plugin("teams", _make_cm())
    err = urllib.error.HTTPError(_URL, 400, "Bad Request", {},
                                 MagicMock(read=lambda: b'{"error":"bad"}'))
    with patch("urllib.request.urlopen", side_effect=err):
        res = plug.send(_reporter_stub(), "subj")
    assert res["status"] == "failed"
    assert "SUPERSECRETSIG" not in res["target"]
    assert "SUPERSECRETSIG" not in res["error"]
    assert "400" in res["error"] or "Bad Request" in res["error"]


def test_teams_plugin_fails_on_url_error():
    plug = build_output_plugin("teams", _make_cm())
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        res = plug.send(_reporter_stub(), "subj")
    assert res["status"] == "failed"
    assert "timeout" in res["error"]


def test_teams_plugin_fails_on_5xx():
    plug = build_output_plugin("teams", _make_cm())
    err = urllib.error.HTTPError(_URL, 500, "Internal Server Error", {},
                                 MagicMock(read=lambda: b'{"error":"flow_failed"}'))
    with patch("urllib.request.urlopen", side_effect=err):
        res = plug.send(_reporter_stub(), "subj")
    assert res["status"] == "failed"
    assert "500" in res["error"] or "flow_failed" in res["error"]
    assert "SUPERSECRETSIG" not in res["target"]
    assert "SUPERSECRETSIG" not in res["error"]
