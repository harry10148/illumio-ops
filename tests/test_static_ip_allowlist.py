import re
from pathlib import Path


def test_security_check_does_not_unconditionally_skip_static():
    src = (Path(__file__).resolve().parent.parent / "src" / "gui" / "__init__.py").read_text()

    sc_match = re.search(r"def\s+security_check.*?(?=\n\s*@app\.|\n\s*def\s|\Z)", src, re.DOTALL)
    assert sc_match, "security_check not found in gui/__init__.py"
    body = sc_match.group(0)

    lines = [l.strip() for l in body.splitlines() if l.strip() and not l.strip().startswith("#")]

    # Look for the early-return guarded by the is_static flag (not its assignment)
    static_skip_idx = next(
        (i for i, l in enumerate(lines)
         if re.match(r"if\s+is_static\s*:", l) or l in ("if is_static:", "return  # static")),
        -1,
    )
    if static_skip_idx < 0:
        # Fallback: any bare early-return associated with the static path
        static_skip_idx = next(
            (i for i, l in enumerate(lines)
             if "/static/" in l and "return" in l),
            -1,
        )
    ip_check_idx = next(
        (i for i, l in enumerate(lines) if "_check_ip_allowed" in l),
        -1,
    )

    assert ip_check_idx >= 0, "_check_ip_allowed call not found inside security_check"
    assert static_skip_idx >= 0, "static path reference not found inside security_check"
    assert ip_check_idx < static_skip_idx, (
        "IP allowlist check (_check_ip_allowed) must appear BEFORE the static-path skip"
    )
