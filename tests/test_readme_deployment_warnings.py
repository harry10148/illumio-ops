"""T3.7: Verify installation.md documents the four deployment warnings (L-11 to L-14)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _installation_content():
    """Return content of docs/guide/installation.md."""
    return (ROOT / "docs" / "guide" / "installation.md").read_text()


def test_installation_documents_proxyfix_requirement():
    content = _installation_content()
    assert "ProxyFix" in content, "installation.md must document ProxyFix requirement for reverse proxy deployments"
    assert "reverse proxy" in content.lower() or "代理" in content


def test_installation_documents_telegram_token_proxy_risk():
    content = _installation_content()
    assert "Telegram" in content
    # Must mention the path/proxy/log risk
    has_warning = (
        "URL path" in content
        or "access log" in content.lower()
        or ("token" in content.lower() and ("proxy" in content.lower() or "代理" in content))
    )
    assert has_warning, "installation.md must warn about Telegram token leaking via proxy access logs"


def test_installation_documents_cheroot_server_header():
    content = _installation_content()
    assert "Cheroot" in content or "Server header" in content or "Server:" in content
    assert "proxy_hide_header" in content or "server header" in content.lower()


def test_installation_documents_autostash_warning():
    content = _installation_content()
    assert "autoStash" in content or "auto_stash" in content or "autostash" in content.lower()
    assert "reproducible" in content.lower() or "stash list" in content.lower()
