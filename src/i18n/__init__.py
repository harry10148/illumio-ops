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
    # Engine internals re-exported for read-only access by `from src.i18n import ...`
    # callers — currently scripts/audit_i18n_usage.py and tests/test_i18n_quality.py.
    # Tests that need to MONKEY-PATCH private engine state import `src.i18n.engine`
    # directly (see tests/test_reader_guide_render.py for the pattern).
    EN_MESSAGES,
    ZH_MESSAGES,
    _ZH_EXPLICIT,
    _humanize_key_en,
    _humanize_key_zh,
)
