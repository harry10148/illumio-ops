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

from urllib.parse import urlsplit, urlunsplit


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
