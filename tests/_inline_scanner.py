"""Reusable scanners for inline-styled hand-rolled UI patterns.

Each scanner returns the *count* of legacy instances. Per-component tests
import these and assert `count <= threshold`. Threshold goes down as each
Task N.B migrates instances to the new unified class.
"""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).parent.parent
INDEX_HTML = ROOT / "src" / "templates" / "index.html"
JS_DIR = ROOT / "src" / "static" / "js"
CSS = ROOT / "src" / "static" / "css" / "app.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_all_js() -> str:
    """Concatenate every .js file under src/static/js with line markers."""
    parts = []
    for p in sorted(JS_DIR.glob("*.js")):
        parts.append(f"// === {p.name} ===\n{_read(p)}\n")
    return "\n".join(parts)


# --- 1. KPI cards (inline-styled, not using .kpi-card) ---
_KPI_INLINE_RE = re.compile(
    r"style=['\"]background:var\(--bg2\);border:1px solid var\(--border\);"
    r"border-radius:8px;padding:10px 14px;?['\"]",
    re.IGNORECASE,
)

def count_inline_kpi_cards() -> int:
    return len(_KPI_INLINE_RE.findall(_read_all_js())) + len(
        _KPI_INLINE_RE.findall(_read(INDEX_HTML))
    )


# --- 2. Severity / status pills (inline color, not .status-pill) ---
_SEV_INLINE_RE = re.compile(
    r"style=['\"]background:\$\{?\w*sevColor\w*\}?[^'\"]*color:#fff[^'\"]*['\"]",
    re.IGNORECASE,
)
# Also catch `style="color:var(--success);font-weight:600;"` etc. on policy decisions
_PD_INLINE_RE = re.compile(
    r"style=['\"]color:\$\{?\w*dColor\w*\}?;font-weight:600;?['\"]",
    re.IGNORECASE,
)

def count_inline_status_pills() -> int:
    js = _read_all_js()
    return len(_SEV_INLINE_RE.findall(js)) + len(_PD_INLINE_RE.findall(js))


# --- 3. Filter bars (toolbar w/ inline alignment hack) ---
# Heuristic: a <div class="toolbar"> that contains form-group children
# AND inline align-self/height fixes on its buttons.
_FILTER_BAR_INLINE_RE = re.compile(
    r'style=[\'"]height:\s*42px;\s*align-self:\s*flex-end;?[\'"]',
    re.IGNORECASE,
)

def count_inline_filter_bar_buttons() -> int:
    return len(_FILTER_BAR_INLINE_RE.findall(_read(INDEX_HTML)))


# --- 4. Empty-state rows (colspan + inline text-align:center;color:var(--dim);) ---
_EMPTY_TD_RE = re.compile(
    r'<td\s+colspan=["\']\d+["\']\s+style=["\']text-align:center;[^"\']*color:var\(--dim\)[^"\']*["\']',
    re.IGNORECASE,
)

def count_inline_empty_states() -> int:
    return len(_EMPTY_TD_RE.findall(_read(INDEX_HTML))) + len(
        _EMPTY_TD_RE.findall(_read_all_js())
    )


# --- 5. Section cards (raw <fieldset> with inline style) ---
_FIELDSET_INLINE_RE = re.compile(
    r"<fieldset[^>]*style=['\"][^'\"]+['\"]",
    re.IGNORECASE,
)

def count_inline_fieldset_sections() -> int:
    return len(_FIELDSET_INLINE_RE.findall(_read(INDEX_HTML))) + len(
        _FIELDSET_INLINE_RE.findall(_read_all_js())
    )


# --- 6. Data tables (<table class="rule-table" style="...font-size...">) ---
_TABLE_INLINE_RE = re.compile(
    r'<table[^>]+class=["\']rule-table["\'][^>]*style=["\'][^"\']+["\']',
    re.IGNORECASE,
)

def count_inline_styled_tables() -> int:
    return len(_TABLE_INLINE_RE.findall(_read(INDEX_HTML))) + len(
        _TABLE_INLINE_RE.findall(_read_all_js())
    )
