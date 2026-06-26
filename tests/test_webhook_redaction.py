"""WebhookAlertPlugin must redact the secret-bearing webhook URL in the
returned/persisted ``target`` (audit: reporter / alert dispatch HIGH).

Generic webhook URLs (Slack/Discord/incoming connectors) carry a secret token
in the path/query. Reporter.send_alerts -> persist_dispatch_results ->
StatsTracker.record_dispatch writes ``target`` verbatim into logs/state.json
(dispatch_history) AND the event timeline, so an un-redacted target leaks the
secret to disk. The real URL must still be used for the actual POST.
"""
import urllib.error
from unittest.mock import MagicMock, patch

from src.alerts import build_output_plugin

# Slack-style incoming webhook: the trailing path segment is the secret token.
_SECRET = "T00000000/B11111111/abcDEFsecretTOKEN0123456789"
_URL = f"https://hooks.slack.com/services/{_SECRET}"
_REDACTED = "https://hooks.slack.com/..."


def _make_cm(url=_URL):
    cm = MagicMock()
    cm.config = {"alerts": {"webhook_url": url}, "settings": {"language": "en"}}
    return cm


def _reporter_stub():
    r = MagicMock()
    r._build_webhook_payload.return_value = {"text": "hi"}
    return r


def _ok_resp(status=200):
    resp = MagicMock(status=status)
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda self, *a: False
    return resp


def test_webhook_success_target_is_redacted():
    plug = build_output_plugin("webhook", _make_cm())
    with patch("urllib.request.urlopen", return_value=_ok_resp(200)):
        res = plug.send(_reporter_stub(), "subj")
    assert res["status"] == "success"
    assert _SECRET not in res["target"]
    assert "/services/" not in res["target"]
    assert res["target"] == _REDACTED


def test_webhook_non_2xx_target_is_redacted():
    plug = build_output_plugin("webhook", _make_cm())
    with patch("urllib.request.urlopen", return_value=_ok_resp(500)):
        res = plug.send(_reporter_stub(), "subj")
    assert res["status"] == "failed"
    assert _SECRET not in res["target"]
    assert res["target"] == _REDACTED


def test_webhook_httperror_target_is_redacted():
    plug = build_output_plugin("webhook", _make_cm())
    err = urllib.error.HTTPError(_URL, 400, "Bad Request", {}, MagicMock(read=lambda: b'{"e":"x"}'))
    with patch("urllib.request.urlopen", side_effect=err):
        res = plug.send(_reporter_stub(), "subj")
    assert res["status"] == "failed"
    assert _SECRET not in res["target"]
    assert res["target"] == _REDACTED


def test_webhook_url_error_target_is_redacted():
    plug = build_output_plugin("webhook", _make_cm())
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        res = plug.send(_reporter_stub(), "subj")
    assert res["status"] == "failed"
    assert _SECRET not in res["target"]
    assert res["target"] == _REDACTED


def test_webhook_real_secret_url_used_for_the_post():
    """Redaction applies only to the stored/returned target — the actual HTTP
    request must still hit the real (secret) webhook URL."""
    plug = build_output_plugin("webhook", _make_cm())
    with patch("urllib.request.urlopen", return_value=_ok_resp(204)) as mock_open:
        plug.send(_reporter_stub(), "subj")
    req = mock_open.call_args[0][0]
    assert req.full_url == _URL


def test_webhook_persisted_dispatch_history_target_is_redacted():
    """record_dispatch writes result['target'] verbatim into dispatch_history +
    the timeline; the persisted value must be redacted, not the raw secret URL."""
    from src.events.stats import StatsTracker

    plug = build_output_plugin("webhook", _make_cm())
    with patch("urllib.request.urlopen", return_value=_ok_resp(200)):
        res = plug.send(_reporter_stub(), "subj")

    tracker = StatsTracker({})
    tracker.record_dispatch(res, subject="subj")

    hist = tracker.state["dispatch_history"][-1]
    assert _SECRET not in hist["target"]
    assert hist["target"] == _REDACTED
    # Timeline entry is written from the same result and must also be clean.
    timeline = tracker.state["event_timeline"][-1]
    assert _SECRET not in timeline["details"]["target"]
