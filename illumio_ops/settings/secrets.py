"""Which settings are secret, and how they leave the process (masked)."""
from __future__ import annotations

from typing import Any

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
