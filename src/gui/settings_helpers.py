"""Shared helper for per-module settings endpoints."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ValidationError


def save_section(cm, section_key: str, data: dict[str, Any],
                 pydantic_model: type[BaseModel]) -> dict[str, Any]:
    """Validate, merge into cm.config[section_key], atomic-write config.json."""
    try:
        validated = pydantic_model(**data)
    except ValidationError as e:
        return {"ok": False, "errors": _flatten_errors(e)}
    # Serialize load-mutate-save under the shared config lock (RLock — safe if
    # the caller already holds it) and reload first, mirroring the GUI config
    # routes: cheroot's thread pool allows concurrent writers, and saving the
    # stale in-memory cm.config would silently drop their updates.
    with cm.write_lock:
        cm.load()
        cm.config.setdefault(section_key, {})
        cm.config[section_key].update(validated.model_dump(mode="json"))
        cm.save()
    return {"ok": True, "requires_restart": True}


def _flatten_errors(exc: ValidationError) -> dict[str, str]:
    return {".".join(str(p) for p in err["loc"]): err["msg"] for err in exc.errors()}
