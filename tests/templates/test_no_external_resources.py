"""
Regression test for a7 P0 hard-gate.
Ensures no template loads external (CDN) resources at runtime, which
would violate C1 offline 硬約束 and the CSP font-src='self' policy.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
TEMPLATE_DIR = REPO_ROOT / "src" / "templates"
STATIC_DIR = REPO_ROOT / "src" / "static"

# URL patterns that ARE allowed (not browser-loaded):
ALLOW_PATTERNS = [
    re.compile(r'http://www\.w3\.org/'),  # XML namespaces
    re.compile(r'pce\.example\.com'),     # placeholder text
    re.compile(r'hooks\.example\.com'),   # placeholder text
]

URL_RE = re.compile(r'https?://[^\s"\'<>)]+')


def _scan_file(path: Path) -> list[tuple[int, str]]:
    violations = []
    try:
        text = path.read_text(encoding='utf-8', errors='ignore')
    except (OSError, UnicodeDecodeError):
        return []
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith(('#', '//', '/*', '*')):
            continue
        for m in URL_RE.finditer(line):
            url = m.group(0)
            if any(p.search(url) for p in ALLOW_PATTERNS):
                continue
            violations.append((i, url))
    return violations


def test_no_external_urls_in_templates():
    failures = []
    for tmpl in TEMPLATE_DIR.rglob('*.html'):
        for line, url in _scan_file(tmpl):
            failures.append(f'{tmpl.relative_to(REPO_ROOT)}:{line}: {url}')
    assert not failures, (
        'External URLs found in templates (violates a7 P0 hard-gate / C1 offline):\n'
        + '\n'.join(failures)
    )


def test_no_external_urls_in_static_css_js():
    failures = []
    for ext in ('*.css', '*.js'):
        for f in STATIC_DIR.rglob(ext):
            for line, url in _scan_file(f):
                failures.append(f'{f.relative_to(REPO_ROOT)}:{line}: {url}')
    assert not failures, (
        'External URLs found in static assets:\n' + '\n'.join(failures)
    )
