from __future__ import annotations

import json
from typing import Any

from illumio_ops.siem.formatters.base import Formatter
from illumio_ops.siem.formatters.cef import _extract_actor, _format_resource_changes
from illumio_ops.siem.formatters.ops import ops_json
from illumio_ops.siem.records import SiemRecord


def _omit_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None and v != ""}


def dumps(obj: object) -> str:
    """Compact JSON, non-ASCII kept (5.x used orjson: same bytes)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


class NormalizedJSONFormatter(Formatter):
    """Flat JSON using official Illumio field names: one object with no nested keys, suitable for syslog_json and
    Splunk HEC auto-indexing."""

    def format_event(self, event: dict[str, Any]) -> str:
        action = event.get("action") or {}
        rc = event.get("resource_changes") or []

        out: dict[str, Any] = {
            "timestamp":    event.get("timestamp", ""),
            "pce_fqdn":     event.get("pce_fqdn", ""),
            "event_type":   event.get("event_type", "unknown"),
            "severity":     event.get("severity", "info"),
            "status":       event.get("status", ""),
            "pce_event_id": (event.get("pce_event_id")
                             or event.get("uuid")
                             or event.get("href") or ""),
        }

        actor = _extract_actor(event.get("created_by") or {})
        if actor:
            out["suser"] = actor

        if action.get("src_ip"):
            out["src_ip"] = action["src_ip"]
        if action.get("api_method"):
            out["request_method"] = action["api_method"]
        if action.get("api_endpoint"):
            out["request"] = action["api_endpoint"]
        if action.get("http_status_code") is not None:
            out["http_status_code"] = action["http_status_code"]

        if rc:
            msg = _format_resource_changes(rc)
            if msg:
                out["resource_changes"] = msg

        return dumps(_omit_none(out))

    def format_ops(self, rec: SiemRecord) -> str:
        return ops_json(rec)
