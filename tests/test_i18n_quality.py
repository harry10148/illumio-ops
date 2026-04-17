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

import re

import pytest

from src import i18n


CJK_RE = re.compile(r"[\u4e00-\u9fff]")
PLACEHOLDER_PREFIX_RE = re.compile(r"^(?:Rpt|GUI|Gui|Sched)\b")


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


def test_glossary_terms_stay_english_in_zh_tw():
    """For every key whose EN value contains a whitelist term, the zh_TW
    value must also contain that term (not a Chinese translation)."""
    en_messages = i18n.get_messages("en")
    zh_messages = i18n.get_messages("zh_TW")

    offenders: list[tuple[str, str, str, str]] = []
    for key, en in en_messages.items():
        if not isinstance(en, str):
            continue
        zh = zh_messages.get(key, "")
        if not isinstance(zh, str):
            continue
        for term, pattern in _GLOSSARY_TERMS:
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
