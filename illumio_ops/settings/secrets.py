"""Secret settings: which they are, how they leave the process (masked), and the admin password hash."""
from __future__ import annotations

import secrets as _secrets
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from illumio_ops.settings.schema import Settings, SiemSettings

MASK = "********"
SECRET_FIELDS: frozenset[str] = frozenset(
    {"pce.api_key", "pce.api_secret", "pce.write_api_key", "pce.write_api_secret", "web.password_hash", "web.secret_key",
     # Channel secrets; the webhook URLs carry their secret in the path or query (5.x L-12).
     "alerts.channels.smtp.password", "alerts.channels.line.access_token", "alerts.channels.telegram.bot_token",
     "alerts.channels.teams.webhook_url", "alerts.channels.webhook.url"}
)

# A secret in every item of a list: (path of the list, field).
LIST_SECRET_FIELDS: frozenset[tuple[str, str]] = frozenset({("siem.destinations", "hec_token")})
# What a SIEM destination's saved HEC token may not follow without being typed again (verify_tls: turning
# verification off would hand it to anyone in the path).
_SIEM_DESTINATION = ("transport", "host", "port", "verify_tls")


class CredentialsRequired(Exception):
    """A saved secret would go to a destination the operator changed without typing the secret again."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(field)


def _node(d: dict[str, Any], path: str) -> Any:
    node: Any = d
    for p in path.split("."):
        node = node[p]
    return node


def redact(s: Settings) -> dict[str, Any]:
    """JSON-ready dump with every non-empty secret replaced by MASK (empty means 'not set')."""
    d = s.model_dump(mode="json")
    for path in SECRET_FIELDS:
        *parents, leaf = path.split(".")
        node = _node(d, ".".join(parents))
        if node[leaf]:
            node[leaf] = MASK
    for path, leaf in LIST_SECRET_FIELDS:
        for item in _node(d, path):
            if item[leaf]:
                item[leaf] = MASK
    return d


def merge_siem_destinations(saved: SiemSettings, submitted: list[dict[str, Any]], *, mask: str) -> list[dict[str, Any]]:
    """The submitted destinations with each blank or masked HEC token replaced by the saved one of the same
    destination (by id) — kept only while it still goes to the same transport, host and port, else anyone holding a
    session could point it at their own server (the SMTP password rule). A new destination has no saved token."""
    by_id = {d.id: d for d in saved.destinations}
    out = []
    for item in submitted:
        d = dict(item)
        if d.get("hec_token") in ("", mask):
            old = by_id.get(str(d.get("id")))
            if old is None or not old.hec_token:
                d["hec_token"] = ""
            elif any(str(d.get(f)) != str(getattr(old, f)) for f in _SIEM_DESTINATION):
                raise CredentialsRequired(f"siem.destinations.{old.id}.hec_token")
            else:
                d["hec_token"] = old.hec_token
        out.append(d)
    return out


# ── Admin password (argon2id, same parameters as 5.x so migrated hashes verify) ──
# First-start credentials, as in 5.x (the operator is not forced to change them).
DEFAULT_ADMIN_USERNAME = "illumio"
DEFAULT_ADMIN_PASSWORD = "illumio"
PASSWORD_MIN_LEN = 12
PASSWORD_MAX_LEN = 512
_PH = PasswordHasher(time_cost=4, memory_cost=131072, parallelism=4)


def hash_password(plain: str) -> str:
    return _PH.hash(plain)


def verify_password(plain: str, stored: str) -> bool:
    if not stored:
        return False
    try:
        return _PH.verify(stored, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_secret_key() -> str:
    """64 hex characters, the format WebSettings.secret_key requires."""
    return _secrets.token_hex(32)
