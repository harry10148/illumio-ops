"""i18n subsystem (refactored from src/i18n.py per H4).

Public API:
- t(key, **kwargs)
- get_messages(lang=None)
- set_language(lang)
- get_language()
"""
from src.i18n.engine import (  # noqa: F401
    t,
    get_messages,
    set_language,
    get_language,
    EN_MESSAGES,
    ZH_MESSAGES,
    _ZH_EXPLICIT,
    _humanize_key_en,
    _humanize_key_zh,
)
