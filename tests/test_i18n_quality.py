"""i18n quality regression tests.

Enforces the project's localization contract so that accidental regressions
(empty keys, placeholder leaks, glossary drift) fail CI instead of landing
silently in a release.

Policy:
  - UI surface (GUI / CLI / report): fully English under ``lang=en``,
    fully Chinese under ``lang=zh_TW`` except for the glossary whitelist.
  - Whitelisted English terms that stay English in both locales:
      PCE, VEN, Workload(s), Enforcement, Port(s), Service(s),
      Policy (policies), Allow, Deny, Blocked, Potentially Blocked.
  - Log / low-level event layer: English-only (see test_log_layer_english.py).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src import i18n


CJK_RE = re.compile(r"[\u4e00-\u9fff]")
PLACEHOLDER_PREFIX_RE = re.compile(r"^(?:Rpt|GUI|Gui|Sched)\b")
STRICT_PREFIXES = (
    "gui_", "sched_", "rs_", "wgs_", "login_", "cli_", "main_",
    "settings_", "rpt_", "menu_", "ven_", "pu_", "report_",
    "error_", "alert_", "daemon_", "line_", "mail_", "webhook_",
    "event_", "confirm_", "select_", "step_", "metric_", "pd_",
    "filter_", "ex_", "rule_", "trigger_", "pill_",
)


# ---------------------------------------------------------------------------
# Email key regression (existing coverage)
# ---------------------------------------------------------------------------

_EMAIL_KEYS = [
    "rpt_email_key_metrics",
    "rpt_email_kpi_title",
    "rpt_email_scheduled_report",
    "rpt_email_ven_subject",
    "rpt_email_pu_subject",
    "rpt_email_attached_files",
    "rpt_email_security_findings",
    "rpt_email_audit_subject",
    "rpt_email_traffic_subject",
    "rpt_email_records",
    "rpt_email_period",
    "rpt_email_key_findings",
    "rpt_email_no_findings",
    "rpt_email_source_api",
    "rpt_email_footer",
    "rpt_email_sent",
    "rpt_email_failed",
]


def test_report_email_keys_are_not_placeholder_text_in_english():
    prev = i18n.get_language()
    i18n.set_language("en")
    try:
        for key in _EMAIL_KEYS:
            text = i18n.t(key)
            assert not text.startswith("Rpt ")
            assert "GUI " not in text
    finally:
        i18n.set_language(prev)


def test_dashboard_no_policy_usage_summary_message_is_localized():
    prev = i18n.get_language()
    try:
        i18n.set_language("en")
        assert i18n.t("gui_dashboard_no_policy_usage_summary").startswith(
            "No policy usage report summary found"
        )

        i18n.set_language("zh_TW")
        assert "Policy 使用報表摘要" in i18n.t("gui_dashboard_no_policy_usage_summary")
    finally:
        i18n.set_language(prev)


def test_report_email_keys_are_explicitly_localized_in_zh_tw():
    prev = i18n.get_language()
    i18n.set_language("zh_TW")
    try:
        for key in _EMAIL_KEYS[:-5]:  # excludes subject-only keys
            text = i18n.t(key)
            assert "Rpt " not in text
            assert "GUI " not in text
    finally:
        i18n.set_language(prev)


# ---------------------------------------------------------------------------
# EN sweep — every known key produces placeholder-free English
# ---------------------------------------------------------------------------

def test_every_english_value_is_not_a_placeholder():
    """No EN value should start with the ``Gui /Rpt /Sched `` placeholder
    prefix (leftover from earlier humanize fallbacks)."""
    messages = i18n.get_messages("en")
    offenders = sorted(
        (key, value)
        for key, value in messages.items()
        if isinstance(value, str) and PLACEHOLDER_PREFIX_RE.match(value.strip())
    )
    assert not offenders, (
        "Placeholder EN values leaked into lang=en:\n"
        + "\n".join(f"  {k}: {v!r}" for k, v in offenders[:20])
    )


# ---------------------------------------------------------------------------
# Glossary preservation — whitelist terms stay English in zh_TW
# ---------------------------------------------------------------------------

_GLOSSARY_TERMS = [
    ("PCE",                 re.compile(r"(?<![A-Za-z])PCE(?![A-Za-z])")),
    ("VEN",                 re.compile(r"(?<![A-Za-z])VENs?(?![A-Za-z])")),
    ("Workload",            re.compile(r"(?<![A-Za-z])Workloads?(?![A-Za-z])")),
    ("Enforcement",         re.compile(r"(?<![A-Za-z])Enforcement(?![A-Za-z])")),
    ("Port",                re.compile(r"(?<![A-Za-z])Ports?(?![A-Za-z])")),
    ("Service",             re.compile(r"(?<![A-Za-z])Services?(?![A-Za-z])")),
    ("Policy",              re.compile(r"(?<![A-Za-z])Polic(?:y|ies)(?![A-Za-z])")),
    ("Allow",               re.compile(r"(?<![A-Za-z])Allow(?![A-Za-z])")),
    ("Deny",                re.compile(r"(?<![A-Za-z])Deny(?![A-Za-z])")),
    ("Blocked",             re.compile(r"(?<![A-Za-z])Blocked(?![A-Za-z])")),
    ("Potentially Blocked", re.compile(r"(?<![A-Za-z])Potentially Blocked(?![A-Za-z])")),
]


def _glossary_exempt_keys() -> dict:
    """Per-key exemptions, read from the same glossary.json field that
    tests/test_i18n_glossary.py and scripts/audit_i18n_usage.py read.

    Three checkers enforce this rule and they do not share a term list — the
    one above is hardcoded here, the other two are derived from glossary.json —
    so an exemption honoured by two of them and not the third is a green local
    run and a red full suite, which is exactly what happened. The list of terms
    stays where it is; only the exemption is shared.
    """
    path = Path(__file__).resolve().parents[1] / "src" / "i18n" / "data" / "glossary.json"
    return json.loads(path.read_text(encoding="utf-8")).get("exempt_keys", {})


def test_glossary_terms_stay_english_in_zh_tw():
    """For every key whose EN value contains a whitelist term, the zh_TW
    value must also contain that term (not a Chinese translation)."""
    en_messages = i18n.get_messages("en")
    zh_messages = i18n.get_messages("zh_TW")
    from src.report.exporters.report_i18n import STRINGS

    exempt = _glossary_exempt_keys()

    offenders: list[tuple[str, str, str, str]] = []
    for key, en in en_messages.items():
        if not isinstance(en, str):
            continue
        # rpt_* keys are canonically sourced from report_i18n.STRINGS.
        if key.startswith("rpt_") and key in STRINGS:
            entry = STRINGS[key]
            if isinstance(entry, dict) and entry.get("en") and entry.get("zh_TW"):
                continue
        zh = zh_messages.get(key, "")
        if not isinstance(zh, str):
            continue
        exempt_terms = exempt.get(key, [])
        for term, pattern in _GLOSSARY_TERMS:
            if term in exempt_terms:
                continue
            if pattern.search(en) and not pattern.search(zh):
                offenders.append((term, key, en, zh))

    if offenders:
        lines = ["Glossary terms should remain English in zh_TW:"]
        for term, key, en, zh in offenders[:20]:
            lines.append(f"  [{term}] {key}\n    en={en!r}\n    zh={zh!r}")
        pytest.fail("\n".join(lines))


# ---------------------------------------------------------------------------
# Report STRINGS coverage
# ---------------------------------------------------------------------------

def test_report_strings_have_both_en_and_zh():
    """Every entry in ``report_i18n.STRINGS`` carries an en and zh_TW value,
    both non-empty. This is the canonical source for HTML report text."""
    from src.report.exporters.report_i18n import STRINGS

    missing: list[tuple[str, str]] = []
    for key, entry in STRINGS.items():
        if not isinstance(entry, dict):
            missing.append((key, "(not a dict)"))
            continue
        en = entry.get("en", "")
        zh = entry.get("zh_TW", "")
        if not en or not en.strip():
            missing.append((key, "en missing"))
        if not zh or not zh.strip():
            missing.append((key, "zh_TW missing"))
    assert not missing, (
        "report_i18n.STRINGS has incomplete entries:\n"
        + "\n".join(f"  {k}: {reason}" for k, reason in missing[:20])
    )


def test_language_native_labels_are_stable():
    """Language selector labels show their own native name in both modes."""
    prev = i18n.get_language()
    try:
        for lang in ("en", "zh_TW"):
            i18n.set_language(lang)
            assert i18n.t("gui_lang_en") == "English"
            assert i18n.t("gui_lang_zh") == "繁體中文"
    finally:
        i18n.set_language(prev)


def test_zh_tw_json_has_tracked_key_parity_with_en_json():
    root = Path(__file__).resolve().parents[1]
    en_path = root / "src" / "i18n_en.json"
    zh_path = root / "src" / "i18n_zh_TW.json"
    en = json.loads(en_path.read_text(encoding="utf-8"))
    zh = json.loads(zh_path.read_text(encoding="utf-8"))

    missing = [
        key for key in en
        if key.startswith(STRICT_PREFIXES)
        and (key not in zh or not str(zh.get(key, "")).strip())
    ]
    assert not missing, (
        "i18n_zh_TW.json is missing tracked keys from i18n_en.json:\n"
        + "\n".join(f"  {k}" for k in missing[:50])
    )


def test_tracked_keys_do_not_render_missing_markers():
    en = i18n.get_messages("en")
    zh = i18n.get_messages("zh_TW")
    offenders: list[tuple[str, str, str]] = []

    for key in sorted(i18n.EN_MESSAGES):
        if not key.startswith(STRICT_PREFIXES):
            continue
        en_text = en.get(key, "")
        zh_text = zh.get(key, "")
        if isinstance(en_text, str) and en_text.startswith("[MISSING:"):
            offenders.append(("en", key, en_text))
        if isinstance(zh_text, str) and zh_text.startswith("[MISSING:"):
            offenders.append(("zh_TW", key, zh_text))

    assert not offenders, (
        "Tracked i18n keys rendered missing markers:\n"
        + "\n".join(f"  [{lang}] {key}: {text}" for lang, key, text in offenders[:50])
    )


# ── 佔位符不得與 t() 自己的參數同名 ──────────────────────────────────────────

#: 只有這些鍵可以帶保留字佔位符，且必須寫明「為什麼 Python 端不會渲染它」。
_RESERVED_PLACEHOLDER_EXEMPT = {
    "gui_rp_lang_set": (
        "只有 JS 用（reports.mjs 的 tf()）。JS 端的 tf(key, params) 沒有保留參數，"
        "`{lang}` 在那裡填得進去；Python 的 t() 從來不渲染這個鍵。"
    ),
}


def _reserved_placeholder_names() -> set[str]:
    """t() 自己吃掉的關鍵字參數名，從簽章推導而不是手打。"""
    import inspect

    from src.i18n import t as _t

    return {
        name for name, p in inspect.signature(_t).parameters.items()
        if p.kind is inspect.Parameter.KEYWORD_ONLY
    }


def test_no_translation_uses_a_placeholder_t_would_swallow():
    """`t(key, *, lang=..., default=..., **kwargs)`：`{lang}` 永遠填不進去。

    `t()` 會先吃掉 `lang=`／`default=`，剩下的才進 `format()`，所以帶這種佔位符的
    句子在呼叫端無論怎麼傳都會 `KeyError`，而 `t()` 的 except 會**吞掉錯誤、回傳
    原始樣板**——畫面上就出現 `語言: {lang} | 佈景: {theme}`，沒有例外、沒有測試
    失敗，只有一行 WARNING。首頁就這樣印了一段樣板，是 Phase 3C Task 3「真跑一次
    互動選單」才看到的。

    repo 為同一個成因記過一次教訓（`t()` 的第一個參數叫 key，所以佔位符不可叫
    `{key}`）。這條把它變成可執行的規則，且保留字從簽章推導，簽章加參數時自動涵蓋。
    """
    import json
    import re
    from pathlib import Path

    reserved = _reserved_placeholder_names()
    assert reserved, "t() 的簽章沒有 keyword-only 參數？推導壞了"

    root = Path(__file__).parent.parent
    offenders = []
    for name in ("src/i18n_en.json", "src/i18n_zh_TW.json"):
        data = json.loads((root / name).read_text(encoding="utf-8"))
        for key, value in data.items():
            if not isinstance(value, str) or key in _RESERVED_PLACEHOLDER_EXEMPT:
                continue
            clash = sorted(set(re.findall(r"\{(\w+)\}", value)) & reserved)
            if clash:
                offenders.append(f"{name}:{key} 用了 {clash}")
    assert not offenders, (
        "翻譯字串用了 t() 會吃掉的佔位符名，Python 端永遠填不進去（而且會靜默"
        "回傳原始樣板）。改個名字，或加進 _RESERVED_PLACEHOLDER_EXEMPT 並寫明"
        "為什麼 Python 不渲染它：\n  " + "\n  ".join(offenders))
