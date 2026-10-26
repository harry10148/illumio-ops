"""Alert messages per channel: the same facts in five shapes, each within its channel's limit, cut visibly."""
import json
from datetime import UTC, datetime, timedelta, timezone

from illumio_ops.domain.values import ChannelKind, Language, Severity
from illumio_ops.services.alerts.messages import AlertView, console_url, render

NOW = datetime(2026, 10, 26, 4, 0, tzinfo=UTC)


def view(i=1, *, late=False, gaps=(), pack_key="rule_agent_tampering", name="", severity=Severity.HIGH, hosts=None):
    return AlertView(id=i, rule_name=name, pack_key=pack_key, severity=severity, subject_key="h", fired_at=NOW,
                     late=late, message_key="alert_event_immediate",
                     params={"event_types": ["agent.tampering"], "hosts": hosts or ["web-01"], "hosts_total": 1},
                     facts={"matches": 3, "threshold": 1},
                     confidence={"incomplete_gaps": [list(g) for g in gaps], "field": None, "covered": None,
                                 "total": None, "latency_seconds": None, "window": None})


def test_line_truncates_with_remaining_count():
    many = [view(i, hosts=["x" * 400]) for i in range(40)]
    r = render(many, ChannelKind.LINE, lang=Language.EN, tz=UTC, console_url=None)
    assert len(r.text) <= 4500
    assert "more alerts" in r.text.splitlines()[-1]  # says what was left out


def test_single_alert_over_the_limit_is_marked_truncated():
    r = render([view(hosts=["y" * 6000])], ChannelKind.LINE, lang=Language.EN, tz=UTC, console_url=None)
    assert len(r.text) <= 4500 and "(truncated)" in r.text


def test_telegram_limit_counts_markup():
    r = render([view(i, hosts=["<b>&" * 300]) for i in range(30)], ChannelKind.TELEGRAM, lang=Language.EN, tz=UTC,
               console_url=None)
    assert len(r.text) <= 3800 and "<b>&<b>" not in r.text  # escaped, and the escaped length is what counts


def test_mail_has_plain_and_html():
    r = render([view(), view(2)], ChannelKind.SMTP, lang=Language.EN, tz=UTC, console_url="https://pce:8443")
    assert r.html and "<html" in r.html and "Agent Tampering Detected" in r.html and r.text
    assert r.subject.startswith("[illumio-ops] HIGH Agent Tampering Detected") and "+1" in r.subject


def test_teams_card_caps_items():
    r = render([view(i) for i in range(25)], ChannelKind.TEAMS, lang=Language.EN, tz=UTC, console_url=None)
    body = json.dumps(r.card)
    assert r.card["type"] == "message" and body.count("Agent Tampering Detected") == 10 and "15 more" in body


def test_webhook_payload_fields():
    r = render([view()], ChannelKind.WEBHOOK, lang=Language.EN, tz=UTC, console_url=None)
    [a] = r.payload["alerts"]
    assert a["id"] == 1 and a["severity"] == "high" and a["rule"] == "Agent Tampering Detected"
    assert a["facts"] == {"matches": 3, "threshold": 1} and a["late"] is False and r.payload["truncated"] == 0


def test_time_in_display_timezone():
    r = render([view()], ChannelKind.LINE, lang=Language.EN, tz=timezone(timedelta(hours=8)), console_url=None)
    assert "2026-10-26 12:00" in r.text


def test_zh_tw_and_en_rendered():
    zh = render([view()], ChannelKind.LINE, lang=Language.ZH_TW, tz=UTC, console_url=None)
    en = render([view()], ChannelKind.LINE, lang=Language.EN, tz=UTC, console_url=None)
    assert "Agent 遭竄改" in zh.text and "web-01 發生 agent.tampering（3 筆）" in zh.text
    assert "agent.tampering on web-01 (3)" in en.text


def test_late_and_confidence_caveats_shown():
    gap = (NOW - timedelta(minutes=30), NOW, "ingest_failed")
    r = render([view(late=True, gaps=[gap])], ChannelKind.LINE, lang=Language.EN, tz=UTC, console_url=None)
    assert "arrived late" in r.text and "incomplete" in r.text


def test_custom_rule_name_used():
    r = render([view(name="My rule", pack_key=None)], ChannelKind.LINE, lang=Language.EN, tz=UTC, console_url=None)
    assert "My rule" in r.text


def test_console_url_defaults_by_deployment():
    from illumio_ops.settings.schema import PceSettings
    base = {"url": "https://pce.example:8443", "org_id": "1", "api_key": "", "api_secret": "", "console_url": None,
            "verify_tls": True, "events_timeout_seconds": None}
    assert console_url(PceSettings(**base, deployment_type="on_prem")) == "https://pce.example:8443"
    assert console_url(PceSettings(**base, deployment_type="saas")) == "https://console.illum.io"
    custom = base | {"console_url": "https://acme.illumio.ai"}
    assert console_url(PceSettings(**custom, deployment_type="saas")) == "https://acme.illumio.ai"


def test_teams_card_does_not_interpret_markdown_from_alert_data():
    # Hostnames, users and processes come from the PCE; in a Markdown TextBlock "[x](https://evil)" becomes a link.
    r = render([view(hosts=["[click](https://evil.example)"])], ChannelKind.TEAMS, lang=Language.EN, tz=UTC,
               console_url=None)
    blocks = r.card["attachments"][0]["content"]["body"]
    data = [b for b in blocks if "evil.example" in json.dumps(b)]
    assert data and all(b["type"] == "RichTextBlock" and b["inlines"][0]["type"] == "TextRun" for b in data)
