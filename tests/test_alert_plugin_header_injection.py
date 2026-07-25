"""殘項 R2：MailAlertPlugin 的郵件標頭必須清洗 CR/LF。

src/reporter.py 兩條寄信路徑已有 _sanitize_header，src/alerts/plugins.py 的
MailAlertPlugin 沒有。subject / sender / recipients 都可能來自 GUI 設定頁的自由
文字，夾帶 CR/LF 即可注入額外標頭；而且 CR/LF 進標頭會讓 as_string() 丟
HeaderParseError（非 SMTPException），穿透本外掛的錯誤分類、破壞 dict 回傳契約。
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from src.alerts.plugins import MailAlertPlugin, _sanitize_header


class _FakeSMTP:
    """記錄 sendmail 參數的最小 smtplib.SMTP 替身。"""

    last = None

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        _FakeSMTP.last = self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        pass

    def sendmail(self, sender, recipients, message):
        self.sender = sender
        self.recipients = recipients
        self.message = message


class TestSanitizeHeader(unittest.TestCase):
    def test_cr_and_lf_become_spaces(self):
        self.assertEqual(_sanitize_header("a\r\nb"), "a  b")
        self.assertEqual(_sanitize_header("a\nBcc: x@evil.test"), "a Bcc: x@evil.test")

    def test_none_and_non_str_are_tolerated(self):
        self.assertEqual(_sanitize_header(None), "")
        self.assertEqual(_sanitize_header(123), "123")


class TestMailPluginSanitizesHeaders(unittest.TestCase):
    def setUp(self):
        self.cm = MagicMock()
        self.cm.config = {
            "email": {
                "sender": "ops@example.com\r\nBcc: attacker@evil.test",
                "recipients": ["dst@example.com\nBcc: attacker2@evil.test"],
            },
            "smtp": {"host": "localhost", "port": 25},
        }
        self.plugin = MailAlertPlugin(self.cm)
        self.reporter = MagicMock()
        self.reporter._build_mail_html.return_value = "<p>body</p>"
        self.reporter._build_mail_plain.return_value = "body"

    def _send(self, subject):
        import src.alerts.plugins as plugins_mod
        original = plugins_mod.smtplib.SMTP
        plugins_mod.smtplib.SMTP = _FakeSMTP
        try:
            return self.plugin.send(self.reporter, subject)
        finally:
            plugins_mod.smtplib.SMTP = original

    def test_no_bare_newline_survives_into_the_message(self):
        result = self._send("Alert\r\nBcc: attacker3@evil.test")

        self.assertEqual(result["status"], "success")
        raw = _FakeSMTP.last.message
        headers = raw.split("\n\n", 1)[0]
        for injected in ("attacker@evil.test", "attacker2@evil.test",
                         "attacker3@evil.test"):
            # 注入字串本身會被留在原標頭的值裡，但不得自成一行 Bcc 標頭。
            self.assertNotIn(f"\nBcc: {injected}", headers)
        self.assertNotIn("Bcc:", raw.split("\n")[0])

    def test_envelope_recipients_are_sanitized_too(self):
        self._send("Alert")

        self.assertEqual(_FakeSMTP.last.sender,
                         "ops@example.com  Bcc: attacker@evil.test")
        for r in _FakeSMTP.last.recipients:
            self.assertNotIn("\r", r)
            self.assertNotIn("\n", r)

    def test_clean_values_are_unchanged(self):
        self.cm.config["email"] = {
            "sender": "ops@example.com",
            "recipients": ["a@example.com", "b@example.com"],
        }
        result = self._send("Nightly report")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["target"], "a@example.com,b@example.com")
        self.assertEqual(_FakeSMTP.last.sender, "ops@example.com")
        self.assertEqual(_FakeSMTP.last.recipients,
                         ["a@example.com", "b@example.com"])
        self.assertIn("Subject: Nightly report", _FakeSMTP.last.message)


if __name__ == "__main__":
    unittest.main()
