"""告警要說自己是誰發的。

2026-09-12：使用者收到一則「PCE 連線看門狗」LINE 告警，接下來一個小時都花在
「這是哪一台發的」上——多台 instance 共用同一個 LINE 目的地時，訊息裡沒有任何
一個字能區分來源，連「是不是我們自己這套」都要靠翻遍五台機器的 log 才能排除。

判讀成本完全來自一行缺席的頁首。斷言對準「收件人看得到來源」，不是對準某個
method 回傳了什麼。
"""
from __future__ import annotations

import pytest

from src.reporter import Reporter


@pytest.fixture
def rep(monkeypatch):
    monkeypatch.setattr("socket.gethostname", lambda: "illumio-ops-test")
    from src.config import ConfigManager
    cm = ConfigManager()
    cm.config.setdefault("api", {})
    cm.config["api"]["url"] = "https://pce.lab.example.com:8443"
    cm.config["api"]["org_id"] = "7"
    cm.config["api"]["key"] = "api_1234567890abcdef"
    cm.config["api"]["secret"] = "s3cr3t-should-never-ship"
    r = Reporter(cm)
    r.add_health_alert({"time": "2026-09-12 03:02:00", "rule": "PCE 連線看門狗",
                        "status": "critical", "details": "盲區"})
    return r


def test_the_line_digest_says_which_host_and_which_pce(rep):
    message = rep._build_line_message("[重大] 測試")
    assert "illumio-ops-test" in message, "多台共用同一個 LINE 目的地時，這是唯一的區分"
    assert "pce.lab.example.com" in message
    assert "7" in message


def test_the_plain_mail_carries_it_too(rep):
    # _build_mail_plain 走的是同一個 LINE 樣板，這支守的是那個共用關係沒被拆掉。
    assert "illumio-ops-test" in rep._build_mail_plain("[重大] 測試")


def test_the_html_mail_says_it_in_the_header(rep):
    html_body = rep._build_mail_html("[重大] 測試")
    assert "illumio-ops-test" in html_body
    assert "pce.lab.example.com" in html_body


def test_the_telegram_digest_says_it(rep):
    assert "illumio-ops-test" in rep._build_telegram_message("[重大] 測試")


def test_the_label_never_carries_the_credentials(rep):
    """來源識別只需要「哪一台、對哪個 PCE」；憑證不得隨告警外送。"""
    label = rep._instance_label()
    assert "api_1234567890abcdef" not in label
    assert "s3cr3t-should-never-ship" not in label
    for message in (rep._build_line_message("s"), rep._build_mail_html("s"),
                    rep._build_telegram_message("s")):
        assert "s3cr3t-should-never-ship" not in message
        assert "api_1234567890abcdef" not in message


def test_the_label_degrades_instead_of_raising(monkeypatch):
    """設定不完整（新機器、還沒填 PCE）時只是少一段，不是整封信發不出去。"""
    monkeypatch.setattr("socket.gethostname", lambda: "fresh-box")
    from src.config import ConfigManager
    cm = ConfigManager()
    cm.config["api"] = {}
    r = Reporter(cm)
    label = r._instance_label()
    assert "fresh-box" in label
    assert "{" not in label and "}" not in label


def test_a_broken_hostname_lookup_does_not_break_the_dispatch(rep, monkeypatch):
    def _boom():
        raise OSError("no hostname")
    monkeypatch.setattr("socket.gethostname", _boom)
    label = rep._instance_label()
    assert "pce.lab.example.com" in label, "主機名拿不到時，PCE 那半仍然要在"
    assert "{" not in label and "}" not in label
