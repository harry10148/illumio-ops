"""Is this edit re-pointing the appliance at a different PCE?

The cache, the ingestion watermarks, the archive files and the alert cooldowns
all carry one PCE's data with nothing marking them as such, so this question
has to be asked wherever the connection can be edited — the GUI and both CLI
paths. One definition, so the three cannot drift apart.

Only url and org_id answer it. Rotating the key or the secret is still the
same PCE.

Normalization lives here too, and the three write paths run their values
through it before storing them. Comparing what was typed against what was
stored made the guard wrong in both directions: a stored
"https://pce.example.com:8443/" retyped without the trailing slash fired the
guard and offered to destroy a cache that was fine, while
"  https://pce.example.com:8443  " compared as unchanged and was then stored
with its whitespace intact for the next comparison to trip over.
"""
from __future__ import annotations

from typing import Literal, Mapping
from urllib.parse import urlsplit, urlunsplit


DEFAULT_SAAS_CONSOLE_URL = "https://console.illum.io"


def normalize_pce_url(value: object) -> str:
    """Strip, drop a trailing slash, and lowercase the scheme and the host.

    Everything else is left exactly as typed. The path, query and fragment are
    case-sensitive to the server, and the userinfo half of the authority (if an
    operator ever writes one) is a credential — none of them are ours to fold.

    A value urlsplit does not read as absolute (a bare hostname, a typo) comes
    back stripped only: there is no host to lowercase and guessing where one
    ends would corrupt it.
    """
    raw = str(value if value is not None else "").strip().rstrip("/")
    if not raw:
        return raw
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return raw
    netloc = parts.netloc
    at = netloc.rfind("@")
    userinfo, hostport = (netloc[:at + 1], netloc[at + 1:]) if at >= 0 else ("", netloc)
    return urlunsplit((parts.scheme.lower(), userinfo + hostport.lower(),
                       parts.path, parts.query, parts.fragment))


def normalize_org_id(value: object) -> str:
    """Whitespace around an org id is never meaningful."""
    return str(value if value is not None else "").strip()


def pce_deployment_type(api_cfg: Mapping[str, object]) -> Literal["saas", "on_prem"]:
    """Return the validated deployment type, defaulting legacy configs to on-prem."""
    return "saas" if str(api_cfg.get("deployment_type") or "on_prem") == "saas" else "on_prem"


def strip_userinfo(url: str) -> str:
    """Drop any ``user:password@`` from a URL's authority.

    normalize_pce_url keeps userinfo on purpose — it is part of the credential
    we authenticate the API with, and folding it would corrupt it. A **console**
    URL is the opposite case: it is handed to a person to click, and on 2026-09-13
    one was being written into alert emails as an ``<a href>``, mailing the PCE
    password to every alert recipient. Nothing that renders a link wants it.
    """
    if not url:
        return url
    parts = urlsplit(url)
    if not parts.netloc or "@" not in parts.netloc:
        return url
    return urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[1],
                       parts.path, parts.query, parts.fragment))


def resolve_pce_console_url(api_cfg: Mapping[str, object]) -> str:
    """Resolve an explicit console URL or the deployment-appropriate default.

    Always userinfo-free: the result is rendered as a clickable link (alert
    emails, the GUI), never used to authenticate.
    """
    explicit = normalize_pce_url(api_cfg.get("console_url", ""))
    if explicit:
        return strip_userinfo(explicit)
    if pce_deployment_type(api_cfg) == "saas":
        return DEFAULT_SAAS_CONSOLE_URL
    base = strip_userinfo(normalize_pce_url(api_cfg.get("url", "")))
    for suffix in ("/api/v2", "/api/v1", "/api"):
        if base.endswith(suffix):
            return base[:-len(suffix)]
    return base


def pce_target_changed(old_api: dict, new_url: str | None, new_org_id: str | None) -> bool:
    """True when *new_url* or *new_org_id* names a different PCE than *old_api*.

    A None means "not being changed", not "changed to empty".

    Both sides are normalized before comparing — the stored side too, because
    values written before this normalization existed are on disk exactly as
    they were typed.
    """
    if new_url is not None and normalize_pce_url(new_url) != normalize_pce_url(old_api.get("url", "")):
        return True
    if new_org_id is not None and normalize_org_id(new_org_id) != normalize_org_id(old_api.get("org_id", "")):
        return True
    return False
