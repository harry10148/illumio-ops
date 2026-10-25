"""Secret settings: which they are, how they leave the process (masked), and the admin password hash."""
from __future__ import annotations

import secrets as _secrets
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from illumio_ops.settings.schema import Settings

MASK = "********"
SECRET_FIELDS: frozenset[str] = frozenset(
    {"pce.api_key", "pce.api_secret", "web.password_hash", "web.secret_key"}
)


def redact(s: Settings) -> dict[str, Any]:
    """JSON-ready dump with every non-empty secret replaced by MASK (empty means 'not set')."""
    d = s.model_dump(mode="json")
    for path in SECRET_FIELDS:
        *parents, leaf = path.split(".")
        node = d
        for p in parents:
            node = node[p]
        if node[leaf]:
            node[leaf] = MASK
    return d


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
