"""Bring a settings file written by an older v6 up to the current schema, in memory only.

validate_settings() calls upgrade() first, so the service, the rescue command, the 5.x
migrator and the installer preflight all read old files the same way. Nothing here writes:
the upgraded shape reaches disk on the next SettingsStore.update().
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from illumio_ops.settings.schema import SCHEMA_VERSION, default_collection


class NewerSchema(Exception):
    """The file was written by a newer program than this one."""


def _v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    data["collection"] = default_collection().model_dump(mode="json")
    return data


# source version -> function producing source version + 1
UPGRADES: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _v1_to_v2,
}


def upgrade(data: Any) -> Any:
    """Return data at SCHEMA_VERSION; anything that is not an upgradable file passes through
    unchanged so validation reports it."""
    if not isinstance(data, dict):
        return data
    version = data.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        return data
    if version > SCHEMA_VERSION:
        raise NewerSchema()
    if version == SCHEMA_VERSION:
        return data
    out = copy.deepcopy(data)
    while version < SCHEMA_VERSION:
        step = UPGRADES.get(version)
        if step is None:
            return data  # no path from this version: let validation report it
        out = step(out)
        version += 1
        out["schema_version"] = version
    return out
