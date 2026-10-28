"""Bring a settings file written by an older v6 up to the current schema, in memory only.

validate_settings() calls upgrade() first, so the service, the rescue command, the 5.x
migrator and the installer preflight all read old files the same way. Nothing here writes:
the upgraded shape reaches disk on the next SettingsStore.update().
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from illumio_ops.domain.alertpack import anomaly_rules
from illumio_ops.settings.schema import (
    SCHEMA_VERSION,
    default_alerts,
    default_collection,
    default_lateral,
    default_reports,
)


class NewerSchema(Exception):
    """The file was written by a newer program than this one."""


def _v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    data["collection"] = default_collection().model_dump(mode="json")
    return data


def _v2_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    data["lateral"] = default_lateral().model_dump(mode="json")
    return data


def _v3_to_v4(data: dict[str, Any]) -> dict[str, Any]:
    # A v3 file is a v6 install, not a 5.x upgrade: the new default rules notify (spec §7 is about 5.x).
    data["alerts"] = default_alerts(notify_new_defaults=True).model_dump(mode="json")
    return data


def _v4_to_v5(data: dict[str, Any]) -> dict[str, Any]:
    # The anomaly detectors' settings (spec §6.5.8); what the file has stays as it is.
    fresh = default_lateral().model_dump(mode="json")
    lateral = data.setdefault("lateral", fresh)
    if isinstance(lateral, dict):
        for key, value in fresh.items():
            lateral.setdefault(key, value)
        if isinstance(lateral.get("detectors"), dict):
            for key, value in fresh["detectors"].items():
                lateral["detectors"].setdefault(key, value)
    # The anomaly rules join the pack recording only: an upgraded install turns each on (as for 5.x, spec §7).
    alerts = data.get("alerts")
    if isinstance(alerts, dict) and isinstance(alerts.get("rules"), list):
        have = {r.get("pack_key") for r in alerts["rules"] if isinstance(r, dict)}
        alerts["rules"] += [r.model_dump(mode="json") for r in anomaly_rules(notify=False) if r.pack_key not in have]
    return data


def _v5_to_v6(data: dict[str, Any]) -> dict[str, Any]:
    data["reports"] = default_reports().model_dump(mode="json")
    return data


def _v6_to_v7(data: dict[str, Any]) -> dict[str, Any]:
    # The findings rules' thresholds (P5b-1); the rest of the reports section stays as it is.
    reports = data.get("reports")
    if isinstance(reports, dict):
        reports.setdefault("rule_thresholds", default_reports().rule_thresholds.model_dump(mode="json"))
    return data


def _v7_to_v8(data: dict[str, Any]) -> dict[str, Any]:
    # "Events only" became "lightweight" (spec §6.4, 2026-10-29); every other mode stays as installed.
    collection = data.get("collection")
    if isinstance(collection, dict) and collection.get("mode") == "events_only":
        collection["mode"] = "lightweight"
    return data


# source version -> function producing source version + 1
UPGRADES: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _v1_to_v2,
    2: _v2_to_v3,
    3: _v3_to_v4,
    4: _v4_to_v5,
    5: _v5_to_v6,
    6: _v6_to_v7,
    7: _v7_to_v8,
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
