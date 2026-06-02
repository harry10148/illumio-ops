from __future__ import annotations
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_REF_PATH = Path(__file__).resolve().parents[2] / "docs" / "_meta" / "illumio-event-reference.json"

@dataclass(frozen=True)
class EventRef:
    category: str
    description: str
    severity: str
    remediation: str = ""
    doc_url: str = ""

@lru_cache(maxsize=1)
def load_reference() -> dict[str, EventRef]:
    raw = json.loads(_REF_PATH.read_text(encoding="utf-8"))
    return {k: EventRef(**v) for k, v in raw.items()}
