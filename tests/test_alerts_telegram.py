"""TelegramAlertPlugin + digest template tests."""
import html as _html
from unittest.mock import MagicMock

from src.alerts import render_alert_template


def _make_reporter_with_alerts():
    """Build a minimal Reporter with one health alert + one event alert queued."""
    from src.config import ConfigManager
    from src.reporter import Reporter

    cm = MagicMock(spec=ConfigManager)
    cm.config = {
        "alerts": {"active": ["telegram"], "telegram_bot_token": "T", "telegram_chat_id": "C"},
        "settings": {"language": "en"},
        "gui_base_url": "",
    }
    r = Reporter(cm)
    r.add_health_alert({
        "rule": "API Health",
        "status": "503",
        "time": "2026-05-16 06:00",
        "details": "PCE unreachable",
    })
    r.event_alerts = []  # default
    r.traffic_alerts = []
    r.metric_alerts = []
    return r


def test_build_telegram_message_includes_subject_and_alert(monkeypatch):
    r = _make_reporter_with_alerts()
    body = r._build_telegram_message("Daily Digest")
    assert "Daily Digest" in body
    assert "API Health" in body
    assert "<b>" in body  # title is bold


def test_build_telegram_message_escapes_html_in_dynamic_fields(monkeypatch):
    r = _make_reporter_with_alerts()
    r.health_alerts[0]["details"] = "<script>alert(1)</script>"
    body = r._build_telegram_message("S")
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_build_telegram_message_truncates_above_3500_chars(monkeypatch):
    r = _make_reporter_with_alerts()
    # Stuff in 50 fat health alerts
    for i in range(50):
        r.add_health_alert({
            "rule": f"r{i}",
            "status": "error",
            "time": "t",
            "details": "X" * 200,
        })
    body = r._build_telegram_message("Bulk")
    assert len(body) <= 3500
    # Footer marks truncation
    assert "more" in body.lower() or "…" in body


def test_build_telegram_message_truncation_cuts_on_line_boundary_no_tag_split(monkeypatch):
    """Oversized digests must truncate on a line boundary so an HTML tag is never
    split. Telegram sendMessage(parse_mode=HTML) rejects unbalanced/partial markup
    with HTTP 400 and drops the whole message. A single event whose PCE deep-link
    is longer than the truncation budget would, under a naive byte-cut at offset
    3300, leave a dangling <a href="..."> with no closing </a>.
    """
    from src.config import ConfigManager
    from src.reporter import Reporter

    cm = MagicMock(spec=ConfigManager)
    cm.config = {
        "alerts": {"active": ["telegram"], "telegram_bot_token": "T", "telegram_chat_id": "C"},
        "settings": {"language": "en"},
        "api": {"url": "https://pce.example.com"},
    }
    r = Reporter(cm)
    # pce_link far exceeds the 3300-char cut budget -> its <a href="..."> opening
    # tag straddles offset 3300, so a byte-offset cut would split the tag.
    r.add_event_alert({
        "rule": "Suspicious",
        "desc": "d",
        "severity": "info",
        "count": 1,
        "time": "t",
        "raw_data": [{"href": "/x" + "a" * 5000, "event_type": "agent.tampering", "timestamp": "t"}],
    })
    body = r._build_telegram_message("Bulk")

    # Truncation ran (the giant <a> line was dropped, not byte-sliced).
    assert len(body) <= 3500
    assert "a" * 100 not in body
    # No split tag: every opened markup tag is also closed in the kept body.
    assert body.count("<a ") == body.count("</a>"), "dangling <a> tag — truncation split a tag"
    assert body.count("<b>") == body.count("</b>")
    assert body.count("<code>") == body.count("</code>")


def test_telegram_digest_template_renders_sections():
    rendered = render_alert_template(
        "telegram_digest.html.tmpl",
        subject="Test Alert",
        generated_at="2026-05-16 14:23 (UTC+8)",
        total_issues=3,
        health_count=1,
        event_count=2,
        traffic_count=0,
        metric_count=0,
        health_section="<b>health item</b>",
        event_section="<b>event item</b>",
        traffic_section="",
        metric_section="",
    )
    # Title from auto-injected alert_tpl_telegram_title
    assert "Illumio" in rendered
    assert "Test Alert" in rendered
    assert "<b>health item</b>" in rendered
    assert "<b>event item</b>" in rendered
    # No literal $placeholder leakage
    assert "$" not in rendered


# ---------------------------------------------------------------------------
# TelegramAlertPlugin tests (Task 6)
# ---------------------------------------------------------------------------
import json
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

from src.alerts import build_output_plugin, get_output_registry


def _make_cm(token="T", chat="C"):
    cm = MagicMock()
    cm.config = {
        "alerts": {"telegram_bot_token": token, "telegram_chat_id": chat},
        "settings": {"language": "en"},
    }
    return cm


def _reporter_stub():
    r = MagicMock()
    r._build_telegram_message.return_value = "<b>hi</b>"
    return r


def test_telegram_plugin_registered():
    assert "telegram" in get_output_registry()


def test_telegram_plugin_skipped_when_unconfigured():
    plug = build_output_plugin("telegram", _make_cm(token="", chat=""))
    res = plug.send(_reporter_stub(), "subj")
    assert res == {"channel": "telegram", "status": "skipped", "target": "", "error": "missing configuration"}


def test_telegram_plugin_posts_payload_on_success():
    plug = build_output_plugin("telegram", _make_cm())
    fake_resp = MagicMock(status=200)
    fake_resp.__enter__ = lambda self: self
    fake_resp.__exit__ = lambda self, *a: False
    with patch("urllib.request.urlopen", return_value=fake_resp) as mock_open:
        res = plug.send(_reporter_stub(), "subj")
    assert res["channel"] == "telegram"
    assert res["status"] == "success"
    assert res["target"] == "C"
    # Inspect outgoing request
    req = mock_open.call_args[0][0]
    assert req.full_url == "https://api.telegram.org/botT/sendMessage"
    payload = json.loads(req.data.decode())
    assert payload["chat_id"] == "C"
    assert payload["text"] == "<b>hi</b>"
    assert payload["parse_mode"] == "HTML"
    assert payload["disable_web_page_preview"] is True


def test_telegram_plugin_fails_on_4xx():
    plug = build_output_plugin("telegram", _make_cm())
    err = urllib.error.HTTPError("https://x", 400, "Bad Request", {}, MagicMock(read=lambda: b'{"description":"bad"}'))
    with patch("urllib.request.urlopen", side_effect=err):
        res = plug.send(_reporter_stub(), "subj")
    assert res["status"] == "failed"
    assert res["target"] == "C"
    assert "400" in res["error"] or "Bad Request" in res["error"]


def test_telegram_plugin_fails_on_url_error():
    plug = build_output_plugin("telegram", _make_cm())
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        res = plug.send(_reporter_stub(), "subj")
    assert res["status"] == "failed"
    assert "timeout" in res["error"]


def test_telegram_plugin_metadata_present():
    from src.alerts.metadata import PLUGIN_METADATA
    assert "telegram" in PLUGIN_METADATA
    meta = PLUGIN_METADATA["telegram"]
    assert meta.display_name == "Telegram Bot"
    assert "alerts.telegram_bot_token" in meta.fields
    assert "alerts.telegram_chat_id" in meta.fields
    assert meta.fields["alerts.telegram_bot_token"].secret is True
    assert meta.fields["alerts.telegram_bot_token"].required is True
    assert meta.fields["alerts.telegram_chat_id"].required is True


def test_send_alerts_routes_through_telegram_plugin(monkeypatch):
    """Reporter.send_alerts must route an active telegram channel through TelegramAlertPlugin."""
    from src.reporter import Reporter
    cm = MagicMock()
    cm.config = {
        "alerts": {"active": ["telegram"], "telegram_bot_token": "T", "telegram_chat_id": "C"},
        "settings": {"language": "en"},
        "gui_base_url": "",
    }
    r = Reporter(cm)
    r.add_health_alert({"rule": "X", "status": "503", "time": "t", "details": "d"})
    fake_resp = MagicMock(status=200)
    fake_resp.__enter__ = lambda self: self
    fake_resp.__exit__ = lambda self, *a: False
    with patch("urllib.request.urlopen", return_value=fake_resp), \
         patch("src.events.persist_dispatch_results"):
        results = r.send_alerts(force_test=False)
    chans = [x["channel"] for x in results]
    assert "telegram" in chans
    tg = next(x for x in results if x["channel"] == "telegram")
    assert tg["status"] == "success"
    assert tg["target"] == "C"
