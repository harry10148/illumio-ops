"""Phase 3: t(key, lang=...) must work without mutating global state."""
from __future__ import annotations

import threading

from src.i18n import t, get_language, set_language


def test_t_accepts_lang_kwarg() -> None:
    set_language("en")
    val_en = t("rpt_kicker_traffic", lang="en")
    val_zh = t("rpt_kicker_traffic", lang="zh_TW")
    assert val_en == "Traffic Analytics Report"
    assert "流量" in val_zh
    assert get_language() == "en", "lang= kwarg must NOT mutate global state"


def test_t_default_uses_global_when_lang_omitted() -> None:
    set_language("zh_TW")
    try:
        val = t("rpt_kicker_traffic")
        assert "流量" in val
    finally:
        set_language("en")


def test_t_concurrent_lang_calls_independent() -> None:
    """Two threads asking for different langs must not interleave."""
    set_language("en")
    results: dict[str, list[str]] = {"en": [], "zh_TW": []}

    def worker(lang: str) -> None:
        for _ in range(50):
            results[lang].append(t("rpt_kicker_traffic", lang=lang))

    threads = [threading.Thread(target=worker, args=(lang,)) for lang in ("en", "zh_TW")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert all(v == "Traffic Analytics Report" for v in results["en"])
    assert all("流量" in v for v in results["zh_TW"])


def test_t_invalid_lang_falls_back_to_global() -> None:
    """Unknown lang values fall back to the global lang (defensive)."""
    set_language("en")
    val = t("rpt_kicker_traffic", lang="xx_YY")
    assert val == "Traffic Analytics Report"  # global is en
