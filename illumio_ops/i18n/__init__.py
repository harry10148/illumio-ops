"""UI dictionaries (en, zh_TW). Keys are flat; placeholders are {name}."""
from __future__ import annotations

import json
from functools import cache
from importlib import resources

from illumio_ops.domain.values import Language


@cache
def dictionary(lang: Language) -> dict[str, str]:
    raw = resources.files("illumio_ops.i18n").joinpath(f"{lang.value}.json").read_text(encoding="utf-8")
    data: dict[str, str] = json.loads(raw)
    return data
