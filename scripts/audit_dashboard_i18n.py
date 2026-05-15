"""Dashboard-scope zh_TW translation quality audit.

Flags keys whose Chinese value:
  R1 mixed_language     - contains a Latin-letter word AND CJK in same value,
                          where the Latin word is NOT in the glossary whitelist.
  R2 low_han_ratio      - Han-char ratio < 0.5 (excluding ASCII punctuation,
                          digits, and decoration).
  R3 too_short_vs_english - zh length < 30% of en length AND en length >= 8.
  R4 known_typo         - matches any string in _KNOWN_TYPOS list.
  R5 untranslated       - zh value equals en value (case-insensitive, when value
                          contains Latin letters so legit identical short
                          glyphs are not flagged).

Scope: only keys referenced from
  - <div id="p-dashboard"> ... </div> in src/templates/index.html
  - any _t('...') call in src/static/js/dashboard.js or dashboard_v2.js
  - Action Matrix recommendation strings in
    src/report/analysis/mod12_executive_summary.py (_KF dict, en/zh_TW pairs).

Outputs:
  default          -> docs/ux-review-2026-05-14/dashboard_i18n_flagged.md
  --format=json    -> structured JSON on stdout (used by pytest)

Exit code: 0 if no findings, 1 otherwise.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN_PATH = ROOT / "src" / "i18n_en.json"
ZH_PATH = ROOT / "src" / "i18n_zh_TW.json"
INDEX_HTML = ROOT / "src" / "templates" / "index.html"
DASHBOARD_JS = ROOT / "src" / "static" / "js" / "dashboard.js"
DASHBOARD_V2_JS = ROOT / "src" / "static" / "js" / "dashboard_v2.js"
MOD12_PY = ROOT / "src" / "report" / "analysis" / "mod12_executive_summary.py"
GLOSSARY = ROOT / "src" / "i18n" / "data" / "glossary.json"
REPORT_OUT = ROOT / "docs" / "ux-review-2026-05-14" / "dashboard_i18n_flagged.md"

_HAN_RE = re.compile(r"[一-鿿]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]*")
_PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")

_KNOWN_TYPOS = (
    "寛察",  # should be 觀察
    "整分點",
    "截切",
    "補抓",  # should be 捕抓 / 抓取
    "日越短長",
    "日誌記送無",
    "盲察",
    "寬察",
)

_RULES_APPLIED = [
    "mixed_language",
    "low_han_ratio",
    "too_short_vs_english",
    "known_typo",
    "untranslated",
]


@dataclass
class Finding:
    key: str
    rule: str
    en: str
    zh: str
    detail: str


# ---------------------------------------------------------------------------
# Scope discovery
# ---------------------------------------------------------------------------

def _load_dashboard_scope_keys() -> set[str]:
    """Collect i18n keys reachable from the dashboard surface."""
    keys: set[str] = set()

    # 1. <div id="p-dashboard"> ... </div> block in index.html
    if INDEX_HTML.exists():
        html = INDEX_HTML.read_text(encoding="utf-8")
        start = html.find('id="p-dashboard"')
        if start >= 0:
            rest = html[start:]
            # Find the next sibling panel block.
            next_panel = re.search(r'id="p-(?!dashboard)[a-z\-]+"', rest[40:])
            block = rest[: 40 + next_panel.start()] if next_panel else rest
            for m in re.finditer(
                r'data-i18n(?:-placeholder|-title)?="([a-z0-9_]+)"', block
            ):
                keys.add(m.group(1))

    # 2. _t('...') / _t("...") calls in dashboard JS files
    for js_path in (DASHBOARD_JS, DASHBOARD_V2_JS):
        if not js_path.exists():
            continue
        js = js_path.read_text(encoding="utf-8")
        for m in re.finditer(r"_t\(\s*['\"]([a-z0-9_]+)['\"]", js):
            keys.add(m.group(1))

    return keys


def _load_action_matrix_pairs() -> list[tuple[str, str, str]]:
    """Return [(synthetic_key, en_value, zh_value)] for mod12 _KF entries.

    These strings live in a Python dict, not in i18n_*.json. We surface them
    so the same 5 quality rules apply.
    """
    pairs: list[tuple[str, str, str]] = []
    if not MOD12_PY.exists():
        return pairs

    src = MOD12_PY.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return pairs

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t for t in node.targets if isinstance(t, ast.Name)]
        if not any(t.id == "_KF" for t in targets):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        kf_dict = node.value
        for action_key_node, lang_dict_node in zip(kf_dict.keys, kf_dict.values):
            if not isinstance(action_key_node, ast.Constant):
                continue
            if not isinstance(action_key_node.value, str):
                continue
            action_id = action_key_node.value
            if not isinstance(lang_dict_node, ast.Dict):
                continue
            lang_map: dict[str, tuple[str, str]] = {}
            for lang_node, tup_node in zip(
                lang_dict_node.keys, lang_dict_node.values
            ):
                if not (
                    isinstance(lang_node, ast.Constant)
                    and isinstance(lang_node.value, str)
                ):
                    continue
                if not isinstance(tup_node, ast.Tuple) or len(tup_node.elts) != 2:
                    continue
                if not all(
                    isinstance(e, ast.Constant) and isinstance(e.value, str)
                    for e in tup_node.elts
                ):
                    continue
                lang_map[lang_node.value] = (
                    tup_node.elts[0].value,
                    tup_node.elts[1].value,
                )
            en_pair = lang_map.get("en")
            zh_pair = lang_map.get("zh_TW")
            if not en_pair or not zh_pair:
                continue
            pairs.append((f"actmtx_{action_id}_msg", en_pair[0], zh_pair[0]))
            pairs.append((f"actmtx_{action_id}_reco", en_pair[1], zh_pair[1]))
        break

    return pairs


def _glossary_preserve() -> set[str]:
    if not GLOSSARY.exists():
        return set()
    data = json.loads(GLOSSARY.read_text(encoding="utf-8"))
    return set(data.get("preserve_in_zh_tw", []))


# ---------------------------------------------------------------------------
# Helpers / per-rule checks
# ---------------------------------------------------------------------------

def _strip_decor(value: str) -> str:
    """Drop placeholders / digits / ASCII punct/space/underscore."""
    value = _PLACEHOLDER_RE.sub("", value)
    return re.sub(r"[0-9\s\W_]+", "", value, flags=re.UNICODE)


def _han_ratio(value: str) -> float:
    stripped = _strip_decor(value)
    if not stripped:
        return 1.0
    han = sum(1 for ch in stripped if _HAN_RE.match(ch))
    return han / len(stripped)


def _check_mixed_language(
    en: str, zh: str, preserve: set[str]
) -> Finding | None:
    if not _HAN_RE.search(zh):
        return None
    # Strip placeholders like {var} so variable names don't count as Latin words.
    cleaned = _PLACEHOLDER_RE.sub("", zh)
    latin_words = _LATIN_WORD_RE.findall(cleaned)
    non_glossary = [
        w for w in latin_words
        if w not in preserve and not w.isdigit() and len(w) >= 2
    ]
    if not non_glossary:
        return None
    return Finding(
        key="", rule="mixed_language", en=en, zh=zh,
        detail=f"non-glossary Latin tokens: {non_glossary}",
    )


def _check_low_han_ratio(en: str, zh: str) -> Finding | None:
    if not _HAN_RE.search(zh):
        return None
    ratio = _han_ratio(zh)
    if ratio >= 0.5:
        return None
    return Finding(
        key="", rule="low_han_ratio", en=en, zh=zh,
        detail=f"han_ratio={ratio:.2f}",
    )


def _check_too_short(en: str, zh: str) -> Finding | None:
    en_s = en.strip()
    zh_s = zh.strip()
    if len(en_s) < 8:
        return None
    if len(zh_s) >= 0.3 * len(en_s):
        return None
    return Finding(
        key="", rule="too_short_vs_english", en=en, zh=zh,
        detail=f"en_len={len(en_s)} zh_len={len(zh_s)}",
    )


def _check_known_typo(en: str, zh: str) -> Finding | None:
    hits = [t for t in _KNOWN_TYPOS if t in zh]
    if not hits:
        return None
    return Finding(
        key="", rule="known_typo", en=en, zh=zh,
        detail=f"contains: {hits}",
    )


def _check_untranslated(en: str, zh: str) -> Finding | None:
    if zh.strip().lower() != en.strip().lower():
        return None
    # Skip pure-number or punctuation-only equality cases; only flag when value
    # actually contains Latin letters that ought to be translated.
    if not _LATIN_WORD_RE.search(en):
        return None
    return Finding(
        key="", rule="untranslated", en=en, zh=zh,
        detail="zh equals en (case-insensitive)",
    )


# ---------------------------------------------------------------------------
# Audit driver
# ---------------------------------------------------------------------------

def audit() -> tuple[list[Finding], int]:
    en = json.loads(EN_PATH.read_text(encoding="utf-8"))
    zh = json.loads(ZH_PATH.read_text(encoding="utf-8"))
    preserve = _glossary_preserve()

    scope_keys = _load_dashboard_scope_keys()
    action_pairs = _load_action_matrix_pairs()
    total_scope = len(scope_keys) + len(action_pairs)

    findings: list[Finding] = []

    def _apply_rules(key: str, en_val: str, zh_val: str) -> None:
        if not isinstance(en_val, str) or not isinstance(zh_val, str):
            return
        if not en_val or not zh_val:
            return
        for check in (
            _check_known_typo,
            _check_untranslated,
            _check_mixed_language,
            _check_low_han_ratio,
            _check_too_short,
        ):
            if check is _check_mixed_language:
                f = check(en_val, zh_val, preserve)  # type: ignore[call-arg]
            else:
                f = check(en_val, zh_val)  # type: ignore[call-arg]
            if f is not None:
                f.key = key
                findings.append(f)

    for key in sorted(scope_keys):
        _apply_rules(key, en.get(key, ""), zh.get(key, ""))

    for key, en_val, zh_val in action_pairs:
        _apply_rules(key, en_val, zh_val)

    return findings, total_scope


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _markdown_report(findings: list[Finding], scope_count: int) -> str:
    by_rule: dict[str, list[Finding]] = {}
    for f in findings:
        by_rule.setdefault(f.rule, []).append(f)

    lines: list[str] = []
    lines.append("# Dashboard i18n Audit")
    lines.append("")
    lines.append(f"**Scope keys:** {scope_count}")
    lines.append(f"**Findings:** {len(findings)}")
    lines.append("")

    if not findings:
        lines.append("_No findings — dashboard zh_TW translations look clean._")
        lines.append("")
        return "\n".join(lines)

    for rule in _RULES_APPLIED:
        bucket = by_rule.get(rule, [])
        if not bucket:
            continue
        lines.append(f"## Rule: {rule} ({len(bucket)})")
        lines.append("")
        lines.append("| Key | EN | ZH | Detail |")
        lines.append("|---|---|---|---|")
        for f in sorted(bucket, key=lambda x: x.key):
            en = f.en.replace("|", "\\|").replace("\n", " ")[:80]
            zh = f.zh.replace("|", "\\|").replace("\n", " ")[:80]
            detail = f.detail.replace("|", "\\|")[:120]
            lines.append(f"| `{f.key}` | {en} | {zh} | {detail} |")
        lines.append("")

    return "\n".join(lines)


def _write_markdown(findings: list[Finding], scope_count: int) -> Path:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(
        _markdown_report(findings, scope_count), encoding="utf-8"
    )
    return REPORT_OUT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--format", choices=("md", "json"), default="md")
    args = parser.parse_args()

    findings, scope_count = audit()

    if args.format == "json":
        payload = {
            "rules_applied": _RULES_APPLIED,
            "scope_key_count": scope_count,
            "findings": [asdict(f) for f in findings],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        path = _write_markdown(findings, scope_count)
        rel = path.relative_to(ROOT)
        print(f"Wrote: {rel}")
        print(f"Scope keys: {scope_count}")
        print(f"Findings: {len(findings)}")

    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
