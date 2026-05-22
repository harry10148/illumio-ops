"""T3.7: Verify README documents the four deployment warnings (L-11 to L-14)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _readme_content():
    """Return concatenated content of README.md and README_zh.md (if exists)."""
    paths = list(ROOT.glob("README*.md"))
    return "\n".join(p.read_text() for p in paths)


def test_readme_documents_proxyfix_requirement():
    content = _readme_content()
    assert "ProxyFix" in content, "README must document ProxyFix requirement for reverse proxy deployments"
    assert "reverse proxy" in content.lower() or "代理" in content


def test_readme_documents_telegram_token_proxy_risk():
    content = _readme_content()
    assert "Telegram" in content
    # Must mention the path/proxy/log risk
    has_warning = (
        "URL path" in content
        or "access log" in content.lower()
        or ("token" in content.lower() and ("proxy" in content.lower() or "代理" in content))
    )
    assert has_warning, "README must warn about Telegram token leaking via proxy access logs"


def test_readme_documents_cheroot_server_header():
    content = _readme_content()
    assert "Cheroot" in content or "Server header" in content or "Server:" in content
    assert "proxy_hide_header" in content or "server header" in content.lower()


def test_readme_documents_autostash_warning():
    content = _readme_content()
    assert "autoStash" in content or "auto_stash" in content or "autostash" in content.lower()
    assert "reproducible" in content.lower() or "stash list" in content.lower()
