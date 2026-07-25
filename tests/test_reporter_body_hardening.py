"""Regression tests for report-email body/header hardening (review batch 3).

  - text/plain alternative must not carry <style>/<script> bodies
    (report HTML inlines ~184 KB of base64 woff2 font data)
  - an oversized inline body is replaced by an explicit notice, never
    silently truncated
  - msg["From"] is CRLF-sanitized like Subject/To (bool contract + header
    injection)
"""
from __future__ import annotations

from email import policy
from email.parser import Parser
from unittest.mock import MagicMock, patch

import pytest

from src.reporter import Reporter, _html_to_plain


class _FakeSMTP:
    captured: dict = {}

    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def starttls(self, context=None):
        pass

    def login(self, u, p):
        pass

    def sendmail(self, sender, recipients, raw):
        _FakeSMTP.captured["raw"] = raw
        return {}

    def quit(self):
        pass


def _reporter(sender="ops@x"):
    cm = MagicMock()
    cm.config = {
        "email": {"sender": sender, "recipients": ["a@x"]},
        "smtp": {"host": "localhost", "port": 25},
    }
    return Reporter(cm)


def _send(reporter, subject, html_body, attachment_path=None):
    _FakeSMTP.captured = {}
    with patch("smtplib.SMTP", _FakeSMTP):
        ok = reporter.send_report_email(subject, html_body,
                                        attachment_path=attachment_path)
    return ok, _FakeSMTP.captured.get("raw")


def _plain_part(raw: str) -> str:
    msg = Parser(policy=policy.default).parsestr(raw)
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            return part.get_content()
    raise AssertionError("no text/plain part")


# ── plain-text derivation ────────────────────────────────────────────────────

def test_html_to_plain_drops_style_and_script_bodies():
    html_body = (
        "<html><head><style>@font-face { src: url(data:font/woff2;base64,"
        "d09GMgABAAAAAMBoABQ); }</style><script>function sortTable(){}</script>"
        "</head><body><h1>Policy Diff</h1><p>3 &amp; 4 changes</p></body></html>"
    )
    plain = _html_to_plain(html_body)
    assert "base64" not in plain
    assert "sortTable" not in plain
    assert "@font-face" not in plain
    assert "Policy Diff" in plain
    assert "3 & 4 changes" in plain      # entities unescaped


def test_report_email_plain_part_excludes_font_payload():
    body = ("<html><head><style>" + "A" * 5000 + "</style></head>"
            "<body><p>Executive summary</p></body></html>")
    ok, raw = _send(_reporter(), "subj", body)
    assert ok is True
    plain = _plain_part(raw)
    assert "AAAA" not in plain
    assert "Executive summary" in plain


# ── oversized body ───────────────────────────────────────────────────────────

def test_oversized_body_is_replaced_by_an_explicit_notice(tmp_path):
    report = tmp_path / "Illumio_PolicyDiff_Report_2026-07-25_1030.html"
    report.write_text("x", encoding="utf-8")
    huge = "<html><body>" + ("<p>row</p>" * 300000) + "</body></html>"
    assert len(huge.encode()) > 2 * 1024 * 1024
    ok, raw = _send(_reporter(), "subj", huge, attachment_path=str(report))
    assert ok is True
    # 整封信不再夾帶整份報表本體（HTML + 由它推導的 plain 各一份）
    assert len(raw) < 200_000, f"message still carries the full body: {len(raw)} bytes"
    plain = _plain_part(raw)
    assert "row" not in plain
    assert report.name in plain          # 明確指向完整報表，不是無聲截斷


def test_normal_sized_body_is_untouched():
    body = "<html><body><p>Executive summary</p></body></html>"
    ok, raw = _send(_reporter(), "subj", body)
    assert ok is True
    assert "Executive summary" in _plain_part(raw)


# ── header sanitization ──────────────────────────────────────────────────────

def test_from_header_with_crlf_does_not_break_the_bool_contract():
    """as_string() 會對含 CR/LF 的標頭丟 HeaderParseError（非 SMTPException），
    穿過 except 清單、破壞 bool 回傳契約。"""
    r = _reporter(sender="ops@x\r\nX-Injected: 1")
    ok, raw = _send(r, "subj", "<html><body>hi</body></html>")
    assert ok is True
    msg = Parser(policy=policy.default).parsestr(raw)
    assert msg.get("X-Injected") is None, "CRLF in sender injected a header"
    assert "\n" not in msg["From"]


def test_subject_with_crlf_still_sanitized():
    ok, raw = _send(_reporter(), "subj\r\nX-Evil: 1", "<html><body>hi</body></html>")
    assert ok is True
    msg = Parser(policy=policy.default).parsestr(raw)
    assert msg.get("X-Evil") is None
