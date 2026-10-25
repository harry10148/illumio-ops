"""The one place error envelopes are built (same shape as contract.Envelope)."""
from __future__ import annotations

from typing import Any

from flask import Response, jsonify


def envelope(*, ok: bool, data: Any = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": ok, "data": data, "error": error,
            "meta": {"partial": False, "truncated": False, "notes": []}}


def api_error(status: int, code: str, message_key: str, *, params: dict[str, str] | None = None,
              field: str | None = None, data: Any = None) -> tuple[Response, int]:
    err = {"code": code, "message_key": message_key, "params": params or {}, "field": field}
    return jsonify(envelope(ok=False, data=data, error=err)), status


def api_ok(data: Any) -> tuple[Response, int]:
    return jsonify(envelope(ok=True, data=data)), 200
