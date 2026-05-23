"""CI lint: block naive datetime.now() usage outside the legacy allowlist.

Exits non-zero if any new naive datetime.now() calls are found in src/
outside the directories/files that are explicitly allowed.

Allowlist rationale:
  src/report/           — report generation timestamps; not scheduler logic;
                          scheduled for a separate cleanup pass
  src/humanize_ext.py   — intentionally preserves caller tzinfo when present,
                          falls back to naive only for naive inputs
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"

# Files/directories allowed to keep naive datetime.now() (legacy, not scheduler logic)
ALLOW_PREFIXES = (
    "src/report/",
    "src/humanize_ext.py",
)

# Match datetime.now() without a timezone argument
PATTERN = re.compile(r'datetime\.(?:datetime\.)?now\(\)')


def _is_allowed(rel: str) -> bool:
    return any(rel.startswith(p) or rel == p for p in ALLOW_PREFIXES)


def main() -> int:
    hits = []
    for py in sorted(SRC.rglob("*.py")):
        rel = str(py.relative_to(ROOT))
        if _is_allowed(rel):
            continue
        content = py.read_text(encoding="utf-8")
        for ln_no, line in enumerate(content.splitlines(), 1):
            if PATTERN.search(line) and "timezone" not in line and "tz" not in line:
                hits.append(f"{rel}:{ln_no}: {line.strip()}")
    if hits:
        print("ERROR: naive datetime.now() found outside allowlist:", file=sys.stderr)
        for h in hits:
            print(f"  {h}", file=sys.stderr)
        return 1
    print("OK: no naive datetime.now() outside the allowlist.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
