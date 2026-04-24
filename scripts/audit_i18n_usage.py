"""Comprehensive i18n audit (Phase 1).

Runs nine categories of checks across the whole codebase and emits:

  - a compact summary on stdout
  - a detailed Markdown report at ``scripts/audit_i18n_report.md``

Categories:

  A  EN placeholder leaks — t(key) at lang=en falls through to humanize fallback
  B  ZH placeholder leaks — t(key) at lang=zh_TW falls through to humanize fallback
  C  Hardcoded CJK in non-i18n Python/JS/HTML source files
  D  Auto-translate residue — zh_TW strings containing suspicious English words
  E  Glossary violations — whitelisted English terms translated to Chinese in zh_TW
  F  Placeholder English values in i18n_en.json — EN starts with Rpt/GUI/Sched prefix
  G  Keys referenced in code but missing from i18n_en.json
  H  JS translation fallback literals — `_translations[key] || 'English text'`
  I  EN/zh_TW parity — tracked keys in i18n_en.json missing from i18n_zh_TW.json

Usage:
    python scripts/audit_i18n_usage.py           # all categories
    python scripts/audit_i18n_usage.py --only A  # just category A

Exit code: 0 if no findings, 1 otherwise (CI-friendly).
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import i18n as _i18n
from src.i18n import (
    EN_MESSAGES,
    ZH_MESSAGES,
    _ZH_EXPLICIT,
    _humanize_key_en,
    _humanize_key_zh,
    get_messages,
)
from src.report.exporters.report_i18n import STRINGS as REPORT_STRINGS

# ---------------------------------------------------------------------------
# Configuration

REPORT_PATH = Path(__file__).resolve().parent / "audit_i18n_report.md"

# Files that ARE the translation tables — scanning them for CJK would be noise.
I18N_SOURCE_FILES = {
    SRC / "i18n.py",
    SRC / "i18n_en.json",
    SRC / "i18n_zh_TW.json",
    SRC / "report" / "exporters" / "report_i18n.py",
}

# Files containing intentional bilingual data resources (not UI strings).
# Excluded from category C scanning entirely.
BILINGUAL_DATA_FILES = {
    # Bilingual recommendation templates keyed by action_code; consumers pick
    # the right lang via `resolve_recommendation(code, lang)`.
    SRC / "report" / "analysis" / "attack_posture.py",
}

# (file_relpath, needle) pairs — specific intentional CJK spots that
# should not count as findings. `needle` is a substring we expect on the line.
BILINGUAL_DATA_LINES: set[tuple[str, str]] = {
    # Email section headers use deliberately bilingual format "EN / ZH".
    ("src/report_scheduler.py", "Boundary Breaches"),
    ("src/report_scheduler.py", "Suspicious Pivot Behavior"),
    ("src/report_scheduler.py", "Blast Radius"),
    ("src/report_scheduler.py", "Blind Spots"),
    ("src/report_scheduler.py", "Action Matrix"),
    ("src/report_scheduler.py", "Attack Summary"),
    ("src/report_scheduler.py", "Finding"),
    # Email attack summary brief is also intentionally bilingual.
    ("src/report/report_metadata.py", "Attack/"),
    ("src/report/report_generator.py", "Attack Summary"),
    # Settings input parser accepts zh confirmations so a TW user can answer
    # 是/好 in addition to y/yes.
    ("src/settings.py", '"是"'),
    # Column-name match keyword, not a display string.
    ("src/report/exporters/html_exporter.py", "_INT_COL_KEYWORDS"),
    # JS lang selector shows native names ("English" / "繁體中文") in both modes.
    ("src/static/js/settings.js", "gui_lang_zh"),
    # Injected CSS/JS literal that happens to contain CJK code points for
    # pattern matching — not a display string.
    ("src/report/exporters/report_css.py", "normalizeCellValue"),
    # Policy usage overview: hit/unused labels resolved via col_i18n; kept
    # as zh so the pandas column name maps to the HTML header translation.
    ("src/report/analysis/policy_usage/pu_mod01_overview.py", "已命中"),
    ("src/report/analysis/policy_usage/pu_mod01_overview.py", "未使用"),
}

# Files skipped entirely (tests, caches, third-party).
SKIP_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "node_modules",
    ".git",
    ".claude",
}

# Key prefixes considered part of the GUI/CLI/report translation surface.
# Only keys with these prefixes are subject to placeholder-leak checks (A, B).
TRACKED_PREFIXES = (
    "gui_", "sched_", "rs_", "wgs_", "login_", "cli_", "main_",
    "settings_", "rpt_", "menu_", "ven_", "pu_", "report_",
    "error_", "alert_", "daemon_", "line_", "mail_", "webhook_",
    "event_", "confirm_", "select_", "step_", "metric_", "pd_",
    "filter_", "ex_", "rule_", "trigger_", "pill_",
)

# Words that flag auto-translate residue in zh_TW text — generic English
# tokens that should normally be translated or explicitly overridden.
#
# Product-feature terms ("Audit Report", "Traffic Analysis", "Policy Usage",
# "Audit Flags", "Status", "Events", "Count") are intentionally excluded:
# these are proper nouns inside the Illumio product surface and stay English
# even inside Chinese UI text.
AUTOTRANSLATE_RESIDUE_TOKENS = (
    "Detail",
    "Generate",
    "Loading",
    "Search",
    "Filter",
)

# Glossary: whitelist terms that MUST remain English in zh_TW output.
# Each entry: (english_term, ascii-aware word-boundary regex).
# Use explicit (?<![A-Za-z])term(?![A-Za-z]) because Python's \b treats CJK
# characters as "word" under Unicode \w, so plain \bPolicy\b fails to match
# inside "檢查Policy".
_ASCII_BOUNDARY_START = r"(?<![A-Za-z])"
_ASCII_BOUNDARY_END = r"(?![A-Za-z])"


def _term_re(core: str) -> re.Pattern:
    return re.compile(_ASCII_BOUNDARY_START + core + _ASCII_BOUNDARY_END)


GLOSSARY = [
    ("PCE",                _term_re(r"PCE")),
    ("VEN",                _term_re(r"VENs?")),
    ("Workload",           _term_re(r"Workloads?")),
    ("Enforcement",        _term_re(r"Enforcement")),
    ("Port",               _term_re(r"Ports?")),
    ("Service",            _term_re(r"Services?")),
    ("Policy",             _term_re(r"Polic(?:y|ies)")),
    ("Allow",              _term_re(r"Allow")),
    ("Deny",               _term_re(r"Deny")),
    ("Blocked",            _term_re(r"Blocked")),
    ("Potentially Blocked", _term_re(r"Potentially Blocked")),
]

# Known Chinese localizations of glossary terms — presence in zh_TW is
# a glossary violation even if the English term is also absent.
GLOSSARY_ZH_LOCALIZATIONS = {
    "Workload": ["工作負載"],
    "Port": ["連接埠"],
    "Service": ["服務"],
    "Policy": ["策略"],
    "Enforcement": ["強制執行", "強制"],
    "Allow": ["允許"],
    "Deny": ["拒絕"],
    "Blocked": ["已封鎖", "封鎖"],
    "Potentially Blocked": ["潛在封鎖", "可能封鎖"],
}

CJK_RE = re.compile(r"[\u4e00-\u9fff]")

GUI_KEY_PATTERNS = [
    re.compile(r'data-i18n=["\']([A-Za-z0-9_&]+)["\']'),
    re.compile(r"""_translations\[['"]([A-Za-z0-9_&]+)['"]\]"""),
    # Require a non-identifier character before _?t(, otherwise .get("x"),
    # set("x"), assert("x") would all falsely match the "t(" suffix.
    re.compile(r"""(?<![A-Za-z0-9_])_?t\(\s*["\']([A-Za-z0-9_&]+)["\']"""),
]

PLACEHOLDER_PREFIX_RE = re.compile(r"^(?:Rpt|GUI|Gui|Sched)\b")


@dataclass
class Finding:
    category: str
    file: str
    line: int | None
    key: str
    detail: str

    def md_row(self) -> str:
        where = f"{self.file}:{self.line}" if self.line else self.file
        return f"| `{where}` | `{self.key}` | {self.detail} |"


# ---------------------------------------------------------------------------
# File enumeration

def _iter_files(exts: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    for path in SRC.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in exts:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        out.append(path)
    return out


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Key collection

def collect_referenced_keys() -> dict[str, list[tuple[str, int]]]:
    """Return {key: [(file, line), ...]} for every i18n key referenced in code."""
    refs: dict[str, list[tuple[str, int]]] = {}
    for path in _iter_files((".py", ".html", ".js")):
        if path in I18N_SOURCE_FILES:
            continue
        text = _read(path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            for pattern in GUI_KEY_PATTERNS:
                for key in pattern.findall(line):
                    refs.setdefault(key, []).append((_rel(path), line_no))
    return refs


# ---------------------------------------------------------------------------
# Category A + B — placeholder leaks

def audit_placeholder_leaks(refs: dict[str, list[tuple[str, int]]]) -> tuple[list[Finding], list[Finding]]:
    a_findings: list[Finding] = []
    b_findings: list[Finding] = []

    en_messages = get_messages("en")
    zh_messages = get_messages("zh_TW")

    for key, locations in sorted(refs.items()):
        if not key.startswith(TRACKED_PREFIXES):
            continue

        # rpt_* keys resolved via report_i18n.STRINGS in HTML never touch json;
        # their placeholder entries in i18n_en.json are harmless for HTML but
        # become real bugs only when Python code calls t("rpt_*") directly.
        # Treat STRINGS as authoritative: skip the leak check when the key has
        # a non-empty STRINGS entry.
        if key in REPORT_STRINGS:
            entry = REPORT_STRINGS[key]
            if isinstance(entry, dict) and entry.get("en") and entry.get("zh_TW"):
                continue

        en_value = en_messages.get(key, "")
        en_json = EN_MESSAGES.get(key, "")
        en_fallback = _humanize_key_en(key)
        # A leak when any of:
        #   - key is entirely missing from json (get_messages falls back)
        #   - json value is empty or a "Gui/Rpt/Sched " placeholder prefix
        # An explicit json value that *happens to equal* the humanize output
        # is fine — e.g. json "Severity" matching humanize("event_severity").
        if not en_json or not en_json.strip() or PLACEHOLDER_PREFIX_RE.match(en_json.strip()):
            src_file, src_line = locations[0]
            a_findings.append(Finding(
                category="A",
                file=src_file,
                line=src_line,
                key=key,
                detail=f'en="{en_value}" (humanize→"{en_fallback}")',
            ))

        zh_value = zh_messages.get(key, "")
        zh_fallback = _humanize_key_zh(key)
        # A ZH leak when any of:
        #   - zh_value is empty
        #   - zh_value starts with a placeholder prefix (Gui/Rpt/Sched/Gui)
        #   - zh_value equals the EN json value (no translation happened)
        # When zh_value equals the humanize output *and* contains CJK, that's
        # actually fine — the key-name humanizer produced proper Chinese via
        # _TOKEN_MAP_ZH. Only flag if humanize produced an ASCII-only string
        # (meaning translation failed AND humanize has no token mapping).
        en_text = en_messages.get(key, "")
        zh_explicit = _ZH_EXPLICIT.get(key)
        is_leak = False
        if not zh_value:
            is_leak = True
        elif zh_value.startswith("[MISSING:"):
            is_leak = True
        elif PLACEHOLDER_PREFIX_RE.match(zh_value):
            is_leak = True
        elif zh_explicit is not None and zh_explicit == zh_value:
            # Intentional override in _ZH_EXPLICIT — author chose this text
            # (e.g., "English" stays "English" in zh_TW; TCP/UDP unchanged).
            pass
        elif en_text and zh_value == en_text and CJK_RE.search(en_text) is None:
            # ZH just echoed the English literally with no translation.
            is_leak = True
        elif zh_value == zh_fallback and CJK_RE.search(zh_fallback) is None:
            # humanize fallback produced ASCII-only output (no token mapping).
            is_leak = True
        if is_leak:
            src_file, src_line = locations[0]
            b_findings.append(Finding(
                category="B",
                file=src_file,
                line=src_line,
                key=key,
                detail=f'zh="{zh_value}" (humanize→"{zh_fallback}")',
            ))

    return a_findings, b_findings


# ---------------------------------------------------------------------------
# Category C — hardcoded CJK in non-i18n files

def _python_cjk_literals(path: Path) -> list[tuple[int, int, str, str]]:
    """Return [(start_line, end_line, snippet, full_value)] for string literals
    containing CJK.

    Uses AST so comments and docstring context are distinguishable. Returns
    the full literal text so downstream checks (whitelisting, filtering) can
    inspect the whole multiline value, not just the first source line.
    """
    try:
        tree = ast.parse(_read(path))
    except SyntaxError:
        return []
    out: list[tuple[int, int, str, str]] = []
    # Collect module/class/function docstrings to skip (allowed to be CJK).
    docstring_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc and node.body and isinstance(node.body[0], ast.Expr):
                val = node.body[0].value
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    docstring_nodes.add(id(val))

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstring_nodes:
                continue
            if CJK_RE.search(node.value):
                snippet = node.value.strip().replace("\n", " ⏎ ")
                if len(snippet) > 80:
                    snippet = snippet[:77] + "..."
                end_line = getattr(node, "end_lineno", node.lineno) or node.lineno
                out.append((node.lineno, end_line, snippet, node.value))
    return out


def _js_html_cjk_literals(path: Path) -> list[tuple[int, str]]:
    """Find CJK appearing in string literals or text content in JS/HTML."""
    out: list[tuple[int, str]] = []
    text = _read(path)
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not CJK_RE.search(line):
            continue
        stripped = line.strip()
        if not stripped:
            continue
        # Skip obvious comment-only lines
        if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
            continue
        # HTML comment
        if stripped.startswith("<!--"):
            continue
        snippet = stripped
        if len(snippet) > 100:
            snippet = snippet[:97] + "..."
        out.append((line_no, snippet))
    return out


def _is_bilingual_allowed(rel: str, full_line: str) -> bool:
    """True if this CJK hit is an intentional bilingual data/tooltip/etc.

    Tests against the *full* source line, not the truncated snippet, so that
    needles placed anywhere on the line still match.
    """
    for wh_rel, needle in BILINGUAL_DATA_LINES:
        if rel == wh_rel and needle in full_line:
            return True
    return False


def audit_hardcoded_cjk() -> list[Finding]:
    findings: list[Finding] = []
    for path in _iter_files((".py",)):
        if path in I18N_SOURCE_FILES or path in BILINGUAL_DATA_FILES:
            continue
        rel = _rel(path)
        src_lines = _read(path).splitlines()
        for start_line, end_line, snippet, full_value in _python_cjk_literals(path):
            # Consider both the source line range AND the literal's full value
            # so multi-line strings match whitelist needles placed deep inside.
            range_text = "\n".join(
                src_lines[(start_line - 1):min(end_line, len(src_lines))]
            )
            if _is_bilingual_allowed(rel, range_text + "\n" + full_value):
                continue
            findings.append(Finding(
                category="C",
                file=rel,
                line=start_line,
                key="—",
                detail=snippet,
            ))
    for path in _iter_files((".js", ".html")):
        if path in I18N_SOURCE_FILES or path in BILINGUAL_DATA_FILES:
            continue
        rel = _rel(path)
        src_lines = _read(path).splitlines()
        for line_no, snippet in _js_html_cjk_literals(path):
            full_line = src_lines[line_no - 1] if 0 < line_no <= len(src_lines) else ""
            if _is_bilingual_allowed(rel, full_line):
                continue
            findings.append(Finding(
                category="C",
                file=rel,
                line=line_no,
                key="—",
                detail=snippet,
            ))
    return findings


# ---------------------------------------------------------------------------
# Category D — auto-translate residue

def audit_autotranslate_residue() -> list[Finding]:
    """zh_TW values that still contain suspicious untranslated English words.

    This is the regex-translator's blind spot: phrases it didn't recognize get
    echoed through unchanged and land as mixed zh+en text in the UI.
    """
    findings: list[Finding] = []
    zh_messages = get_messages("zh_TW")
    token_re = re.compile(r"\b(?:" + "|".join(AUTOTRANSLATE_RESIDUE_TOKENS) + r")\b")

    for key, zh_val in sorted(zh_messages.items()):
        if not isinstance(zh_val, str):
            continue
        # Skip rpt_* keys whose canonical source is report_i18n.STRINGS — the
        # zh_messages value is a humanize-fallback that never reaches the UI.
        if key.startswith("rpt_") and key in REPORT_STRINGS:
            entry = REPORT_STRINGS[key]
            if isinstance(entry, dict) and entry.get("zh_TW"):
                continue
        # Skip keys without any CJK — those are intentionally English-only.
        if not CJK_RE.search(zh_val):
            continue
        hits = token_re.findall(zh_val)
        if not hits:
            continue
        findings.append(Finding(
            category="D",
            file="src/i18n.py",
            line=None,
            key=key,
            detail=f'zh="{zh_val}" (untranslated: {", ".join(sorted(set(hits)))})',
        ))

    # report_i18n.STRINGS
    for key, entry in sorted(REPORT_STRINGS.items()):
        if not isinstance(entry, dict):
            continue
        zh_val = entry.get("zh_TW", "")
        if not isinstance(zh_val, str) or not CJK_RE.search(zh_val):
            continue
        hits = token_re.findall(zh_val)
        if not hits:
            continue
        findings.append(Finding(
            category="D",
            file="src/report/exporters/report_i18n.py",
            line=None,
            key=key,
            detail=f'zh="{zh_val}" (untranslated: {", ".join(sorted(set(hits)))})',
        ))
    return findings


# ---------------------------------------------------------------------------
# Category E — glossary violations (whitelist terms translated to Chinese)

def audit_glossary_violations() -> list[Finding]:
    findings: list[Finding] = []
    en_messages = get_messages("en")
    zh_messages = get_messages("zh_TW")

    def check(key: str, en_val: str, zh_val: str, source: str) -> None:
        if not isinstance(en_val, str) or not isinstance(zh_val, str):
            return
        for term, term_re in GLOSSARY:
            if not term_re.search(en_val):
                continue
            # Violation if zh_TW does NOT contain the English term verbatim …
            if term_re.search(zh_val):
                continue
            # … unless the zh side happens to contain a localized variant.
            # (Either way, the term should stay English per the whitelist.)
            localizations = GLOSSARY_ZH_LOCALIZATIONS.get(term, [])
            hit_local = next((l for l in localizations if l in zh_val), None)
            detail = f'[{term}] en="{en_val}" zh="{zh_val}"'
            if hit_local:
                detail += f' (localized as "{hit_local}")'
            findings.append(Finding(
                category="E",
                file=source,
                line=None,
                key=key,
                detail=detail,
            ))

    # Check all i18n.py-derived zh values
    for key in sorted(set(en_messages) | set(zh_messages)):
        # rpt_* keys resolved by report_i18n.STRINGS should use STRINGS as
        # canonical source for glossary checks.
        if key.startswith("rpt_") and key in REPORT_STRINGS:
            entry = REPORT_STRINGS[key]
            if isinstance(entry, dict) and entry.get("en") and entry.get("zh_TW"):
                continue
        en_val = en_messages.get(key, "")
        zh_val = zh_messages.get(key, "")
        check(key, en_val, zh_val, "src/i18n.py")

    # Check report i18n entries
    for key, entry in sorted(REPORT_STRINGS.items()):
        if not isinstance(entry, dict):
            continue
        check(key, entry.get("en", ""), entry.get("zh_TW", ""),
              "src/report/exporters/report_i18n.py")
    return findings


# ---------------------------------------------------------------------------
# Category F — placeholder values in i18n_en.json

def audit_en_json_placeholders() -> list[Finding]:
    findings: list[Finding] = []
    for key, value in sorted(EN_MESSAGES.items()):
        if not isinstance(value, str):
            continue
        # rpt_* keys whose canonical source is report_i18n.STRINGS: a placeholder
        # value in json is a no-op for HTML and is never shown, so skip.
        if key.startswith("rpt_") and key in REPORT_STRINGS:
            entry = REPORT_STRINGS[key]
            if isinstance(entry, dict) and entry.get("en"):
                continue
        stripped = value.strip()
        if not stripped:
            findings.append(Finding(
                category="F", file="src/i18n_en.json", line=None,
                key=key, detail='(empty string)',
            ))
            continue
        if PLACEHOLDER_PREFIX_RE.match(stripped):
            findings.append(Finding(
                category="F", file="src/i18n_en.json", line=None,
                key=key, detail=f'value="{stripped}"',
            ))
    return findings


# ---------------------------------------------------------------------------
# Category G — referenced keys missing from i18n_en.json

def audit_missing_en_keys(refs: dict[str, list[tuple[str, int]]]) -> list[Finding]:
    findings: list[Finding] = []
    en_keys = set(EN_MESSAGES)
    for key, locations in sorted(refs.items()):
        if not key.startswith(TRACKED_PREFIXES):
            continue
        if key in en_keys:
            continue
        # Skip report-layer keys — those live in report_i18n.STRINGS, not json.
        if key.startswith("rpt_") and key in REPORT_STRINGS:
            continue
        src_file, src_line = locations[0]
        findings.append(Finding(
            category="G", file=src_file, line=src_line, key=key,
            detail=f'referenced in {len(locations)} location(s)',
        ))
    return findings


# ---------------------------------------------------------------------------
# Category H — JS fallback literals

def audit_js_translation_fallback_literals() -> list[Finding]:
    """Find `_translations[...] || 'English text'` patterns in UI JS/HTML.

    These literals hide missing translations in production and let CI pass
    while users still see mixed-language UI.
    """
    findings: list[Finding] = []
    pattern = re.compile(
        r"_translations\[[^\]]+\]\s*\|\|\s*(['\"])(?P<text>[^'\"]*[A-Za-z][^'\"]*)\1"
    )
    for path in _iter_files((".js", ".html")):
        if path in I18N_SOURCE_FILES:
            continue
        rel = _rel(path)
        text = _read(path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            m = pattern.search(line)
            if not m:
                continue
            findings.append(Finding(
                category="H",
                file=rel,
                line=line_no,
                key="—",
                detail=f"fallback literal: {m.group('text')}",
            ))
    return findings


# ---------------------------------------------------------------------------
# Category I — EN/zh_TW parity

def audit_zh_parity_against_en() -> list[Finding]:
    """Tracked keys in EN json must exist with non-empty zh_TW entries."""
    findings: list[Finding] = []
    for key in sorted(EN_MESSAGES):
        if not key.startswith(TRACKED_PREFIXES):
            continue
        zh_val = ZH_MESSAGES.get(key)
        if isinstance(zh_val, str) and zh_val.strip():
            continue
        findings.append(Finding(
            category="I",
            file="src/i18n_zh_TW.json",
            line=None,
            key=key,
            detail="missing or empty zh_TW value",
        ))
    return findings


# ---------------------------------------------------------------------------
# Reporting

CATEGORY_TITLES = {
    "A": "EN placeholder leaks (key resolved to humanize fallback at lang=en)",
    "B": "ZH placeholder leaks (key resolved to humanize fallback at lang=zh_TW)",
    "C": "Hardcoded CJK in non-i18n Python/JS/HTML source files",
    "D": "Auto-translate residue (zh_TW values with suspicious English words)",
    "E": "Glossary violations (whitelist terms translated to Chinese in zh_TW)",
    "F": "Placeholder English values in i18n_en.json",
    "G": "Keys referenced in code but missing from i18n_en.json",
    "H": "JS/HTML fallback literals (`_translations[key] || 'English text'`)",
    "I": "Tracked EN keys missing/empty in i18n_zh_TW.json",
}


def write_markdown_report(groups: dict[str, list[Finding]]) -> None:
    lines = ["# i18n Audit Report (Phase 1)", ""]
    lines.append("Run `python scripts/audit_i18n_usage.py` to regenerate.")
    lines.append("")

    total = sum(len(v) for v in groups.values())
    lines.append(f"**Total findings:** {total}")
    lines.append("")
    lines.append("| Category | Description | Count |")
    lines.append("|---|---|---|")
    for cat in "ABCDEFGHI":
        lines.append(f"| {cat} | {CATEGORY_TITLES[cat]} | {len(groups.get(cat, []))} |")
    lines.append("")

    for cat in "ABCDEFGHI":
        findings = groups.get(cat, [])
        lines.append(f"## [{cat}] {CATEGORY_TITLES[cat]}")
        lines.append("")
        if not findings:
            lines.append("_No findings._")
            lines.append("")
            continue
        lines.append(f"**{len(findings)} finding(s).**")
        lines.append("")
        lines.append("| Location | Key | Detail |")
        lines.append("|---|---|---|")
        for f in findings:
            # Escape pipe in detail
            detail = f.detail.replace("|", "\\|")
            where = f"`{f.file}:{f.line}`" if f.line else f"`{f.file}`"
            key = f"`{f.key}`" if f.key != "—" else "—"
            lines.append(f"| {where} | {key} | {detail} |")
        lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def print_summary(groups: dict[str, list[Finding]]) -> None:
    total = sum(len(v) for v in groups.values())
    print("=" * 70)
    print("i18n audit summary")
    print("=" * 70)
    for cat in "ABCDEFGHI":
        count = len(groups.get(cat, []))
        marker = "FAIL" if count else " ok "
        print(f"  [{cat}] {marker} {count:4d}  {CATEGORY_TITLES[cat]}")
    print("-" * 70)
    print(f"  Total: {total} finding(s)")
    print(f"  Full report: {_rel(REPORT_PATH)}")


# ---------------------------------------------------------------------------
# Main

def main() -> int:
    parser = argparse.ArgumentParser(description="Comprehensive i18n audit")
    parser.add_argument("--only", choices=list("ABCDEFGHI"), help="Only run one category")
    args = parser.parse_args()

    refs = collect_referenced_keys()
    groups: dict[str, list[Finding]] = {}

    wanted = args.only or "ABCDEFGHI"

    if "A" in wanted or "B" in wanted:
        a, b = audit_placeholder_leaks(refs)
        if "A" in wanted:
            groups["A"] = a
        if "B" in wanted:
            groups["B"] = b
    if "C" in wanted:
        groups["C"] = audit_hardcoded_cjk()
    if "D" in wanted:
        groups["D"] = audit_autotranslate_residue()
    if "E" in wanted:
        groups["E"] = audit_glossary_violations()
    if "F" in wanted:
        groups["F"] = audit_en_json_placeholders()
    if "G" in wanted:
        groups["G"] = audit_missing_en_keys(refs)
    if "H" in wanted:
        groups["H"] = audit_js_translation_fallback_literals()
    if "I" in wanted:
        groups["I"] = audit_zh_parity_against_en()

    write_markdown_report(groups)
    print_summary(groups)
    total = sum(len(v) for v in groups.values())
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
