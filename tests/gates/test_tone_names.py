"""Every literal UI tone must have a carrier rule in the token stylesheet."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "web" / "src"
TOKENS = SRC / "styles" / "tokens.css"


def test_every_used_tone_is_defined_in_tokens() -> None:
    tones: set[str] = set()
    tone_attr = re.compile(r"\b(?:data-)?tone\s*=\s*['\"]([a-z_]+)['\"]")
    tone_map = re.compile(r"\b[A-Z][A-Z0-9_]*TONE[A-Z0-9_]*\s*(?::[^=]+)?=\s*\{([^}]*)\}")
    literal = re.compile(r"['\"]([a-z_]+)['\"]")
    tone_expr = re.compile(r"\b(?:data-)?tone\s*=\s*\{([^}]*)\}")
    # a value the expression can give: alone, or after ?, :, ?? or || (not the operand of a comparison)
    result = re.compile(r"(?:^\s*|\?\??\s*|:\s*|\|\|\s*)['\"]([a-z_]+)['\"]")

    for path in SRC.rglob("*"):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        source = path.read_text(encoding="utf-8")
        tones.update(tone_attr.findall(source))
        for expr in tone_expr.findall(source):
            tones.update(result.findall(expr))
        for body in tone_map.findall(source):
            tones.update(literal.findall(body))

    css = TOKENS.read_text(encoding="utf-8")
    defined = set(re.findall(r'\[data-tone="([a-z_]+)"\]', css))
    missing = sorted(tones - defined)
    assert not missing, f"undefined data-tone values: {missing}"
