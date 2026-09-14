"""PCE URL 裡的密碼不得出現在任何給人看的地方。

`api.url` 可以合法帶 `user:password@`，而 `pce_target.normalize_pce_url`
**刻意保留**它（「the userinfo half of the authority … is a credential — none of
them are ours to fold」）。於是每一個把這個 URL 渲染出來的表面，其實都在渲染憑證。

2026-09-13 查到四個表面。告警那兩個（摘要的來源行、信件 CTA 的 `<a href>`）由
`tests/test_alert_instance_identity.py` 守；這一支守剩下兩個：

  · `config show` —— 它的 docstring 就寫著「never prints credentials in
    plaintext」，但 `_mask_secrets` 是**按鍵名**遮蔽
    （`{"key","secret","password","token"}`），`url` 不在名單裡。2026-07-24 的
    CLI 審查把「config show 明文憑證」列為 High 修過一次，只修了按鍵名那條路，
    **藏在非機密欄位值裡的憑證這條漏了**。
  · GUI `/api/status` 的 `api_url`，以及兩條 CLI 狀態列。

`config show` 與其他表面的處置刻意不同：設定傾印要讓操作者知道「這個 URL 裡**有**
內嵌憑證」（否則查不出登入為什麼失敗），所以換成 `[REDACTED]@host`；身分顯示用的
狀態列與 GUI 外框不需要這個資訊，整段拿掉。

斷言對準**渲染出來的字串**，不是「有沒有呼叫某個函式」。
"""
from __future__ import annotations

import pytest

from src.pce_target import redact_userinfo, strip_userinfo

SECRET = "hunter2"
URL_WITH_CRED = f"https://admin:{SECRET}@pce.lab.example.com:8443"
URL_PLAIN = "https://pce.lab.example.com:8443"


# ── 兩個 helper ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [URL_WITH_CRED, URL_PLAIN, "", "not a url", "pce.lab.local"])
def test_neither_helper_ever_emits_the_password(url):
    assert SECRET not in strip_userinfo(url)
    assert SECRET not in redact_userinfo(url)


def test_strip_removes_the_userinfo_entirely():
    assert strip_userinfo(URL_WITH_CRED) == URL_PLAIN


def test_redact_keeps_the_fact_that_a_credential_is_embedded():
    """操作者要看得出「這個 URL 裡有憑證」，否則查不出登入為什麼失敗。"""
    out = redact_userinfo(URL_WITH_CRED)
    assert "[REDACTED]@" in out
    assert "pce.lab.example.com:8443" in out
    assert "admin" not in out


# URL 的 authority 有幾種形狀會讓「找 @ 然後切掉」這種寫法出錯：IPv6 字面值自帶
# 中括號、path 與 query 裡可以合法出現 @、使用者名可以是 %40 編碼。這幾條釘住的是
# 「遮蔽不得弄壞合法輸入，也不得漏掉帶憑證的輸入」。
@pytest.mark.parametrize("url, stripped, redacted", [
    ("https://[2001:db8::1]:8443",
     "https://[2001:db8::1]:8443", "https://[2001:db8::1]:8443"),
    ("https://u:p@[2001:db8::1]:8443",
     "https://[2001:db8::1]:8443", "https://[REDACTED]@[2001:db8::1]:8443"),
    # path/query 裡的 @ 不是 userinfo，一個字都不該動
    ("https://pce.local:8443/p/with@sign?q=a@b",
     "https://pce.local:8443/p/with@sign?q=a@b", "https://pce.local:8443/p/with@sign?q=a@b"),
    ("https://u:p@pce.local:8443/p/with@sign?q=a@b",
     "https://pce.local:8443/p/with@sign?q=a@b",
     "https://[REDACTED]@pce.local:8443/p/with@sign?q=a@b"),
    ("https://u%40dom:p@pce.local:8443",
     "https://pce.local:8443", "https://[REDACTED]@pce.local:8443"),
    ("https://u:p@pce.local", "https://pce.local", "https://[REDACTED]@pce.local"),
    ("not-a-url", "not-a-url", "not-a-url"),
    ("", "", ""),
])
def test_the_helpers_handle_the_awkward_authorities(url, stripped, redacted):
    assert strip_userinfo(url) == stripped
    assert redact_userinfo(url) == redacted


def test_a_url_without_userinfo_is_left_alone():
    assert redact_userinfo(URL_PLAIN) == URL_PLAIN
    assert strip_userinfo(URL_PLAIN) == URL_PLAIN


# ── config show ───────────────────────────────────────────────────────────

def test_config_show_does_not_print_a_password_hidden_in_the_url():
    from src.cli.config import _mask_secrets

    masked = _mask_secrets({"api": {"url": URL_WITH_CRED, "key": "k", "secret": "s"}})
    assert SECRET not in str(masked), (
        "_mask_secrets 按鍵名遮蔽，而憑證藏在 url 這個非機密欄位的**值**裡"
    )
    assert "pce.lab.example.com:8443" in masked["api"]["url"], "主機與埠仍要看得到"


def test_config_show_still_redacts_the_secret_named_fields():
    """既有契約不得被上面那條改掉。"""
    from src.cli.config import _mask_secrets

    masked = _mask_secrets({"api": {"key": "k", "secret": "s", "token": "t"}})
    assert masked["api"] == {"key": "[REDACTED]", "secret": "[REDACTED]",
                             "token": "[REDACTED]"}


def test_config_show_leaves_a_plain_url_readable():
    from src.cli.config import _mask_secrets

    assert _mask_secrets({"api": {"url": URL_PLAIN}})["api"]["url"] == URL_PLAIN


# ── GUI /api/status ───────────────────────────────────────────────────────

def test_the_status_endpoint_does_not_ship_the_password(monkeypatch):
    """前端只 strip 掉 `https?://`（shell.mjs / cards.mjs），所以送出去就會顯示。"""
    from src.config import ConfigManager
    from src.gui._helpers import _get_active_pce_url

    cm = ConfigManager()
    cm.config.setdefault("api", {})["url"] = URL_WITH_CRED
    shown = _get_active_pce_url(cm)
    assert SECRET not in shown
    assert "pce.lab.example.com:8443" in shown


# ── CLI 狀態列 ────────────────────────────────────────────────────────────

def test_no_status_line_interpolates_the_raw_api_url():
    """兩條狀態列是直接 f-string 塞 `config['api']['url']`。

    斷言原始碼是代理指標，但這兩行沒有可呼叫的純函式出口（它們在互動式選單的
    渲染中間），而錯誤的形狀剛好是可辨識的字面量。看到這支紅，改成先過
    `strip_userinfo()` 再插值。
    """
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    offenders = []
    for rel in ("src/main.py", "src/cli/menus/areas.py"):
        for num, line in enumerate(
                (root / rel).read_text(encoding="utf-8").splitlines(), start=1):
            if "cli_status_api" not in line:
                continue
            if "strip_userinfo" not in line:
                offenders.append(f"{rel}:{num}")
    assert not offenders, (
        f"這些狀態列直接印出 api.url，內嵌憑證會跟著出現在終端機：{offenders}"
    )


def test_the_status_line_modules_can_actually_call_it():
    """上面那支只看得到原始碼有沒有那個名字——引用了卻沒 import 一樣是綠的。

    真的 import 模組，問那個名字解不解析得到。少了 import 的話，狀態列會在
    操作者面前 NameError，而只查字面的閘門對此無感。
    """
    import importlib

    for mod_name in ("src.main", "src.cli.menus.areas"):
        mod = importlib.import_module(mod_name)
        assert callable(getattr(mod, "strip_userinfo", None)), (
            f"{mod_name} 的狀態列用了 strip_userinfo 卻沒有 import 它"
        )
