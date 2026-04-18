#!/usr/bin/env python3
"""Verify all production + dev dependencies can be imported and report versions.

Exits 0 if all packages import successfully, 1 otherwise.
Run after `pip install -r requirements.txt -r requirements-dev.txt`.
"""
from __future__ import annotations

import importlib
import sys
from typing import NamedTuple


class Pkg(NamedTuple):
    """A package to verify: distribution name, import name, optional version attr path."""
    dist: str
    module: str
    version_attr: str = "__version__"


# Production packages (must match requirements.txt)
PRODUCTION = [
    # Existing core
    Pkg("flask", "flask"),
    Pkg("pandas", "pandas"),
    Pkg("pyyaml", "yaml"),
    # Phase 1
    Pkg("rich", "rich"),
    Pkg("questionary", "questionary"),
    Pkg("click", "click"),
    Pkg("humanize", "humanize"),
    # Phase 2
    Pkg("requests", "requests"),
    Pkg("orjson", "orjson"),
    Pkg("cachetools", "cachetools"),
    # Phase 3
    Pkg("pydantic", "pydantic", "VERSION"),
    Pkg("pydantic-settings", "pydantic_settings"),
    # Phase 4
    Pkg("flask-wtf", "flask_wtf"),
    Pkg("flask-limiter", "flask_limiter"),
    Pkg("flask-talisman", "flask_talisman"),
    Pkg("flask-login", "flask_login"),
    Pkg("argon2-cffi", "argon2"),
    # Phase 5
    Pkg("openpyxl", "openpyxl"),
    Pkg("weasyprint", "weasyprint"),
    Pkg("matplotlib", "matplotlib"),
    Pkg("plotly", "plotly"),
    Pkg("pygments", "pygments"),
    # Phase 6
    Pkg("APScheduler", "apscheduler"),
    # Phase 7
    Pkg("loguru", "loguru"),
]

# Dev packages (optional — checked but not fatal if missing)
DEV = [
    Pkg("pytest", "pytest"),
    Pkg("pytest-cov", "pytest_cov"),
    Pkg("responses", "responses"),
    Pkg("freezegun", "freezegun"),
    Pkg("ruff", "ruff", ""),  # ruff has no __version__ exported; just check import
    Pkg("mypy", "mypy"),
    Pkg("build", "build"),
    Pkg("pyinstaller", "PyInstaller"),
]


def _get_version(mod, attr: str) -> str:
    """Resolve a possibly-dotted version attribute path; return 'unknown' if missing."""
    if not attr:
        return "(no version attr)"
    obj = mod
    for part in attr.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return "unknown"
    return str(obj)


def verify(pkgs: list[Pkg], category: str, fatal: bool) -> list[str]:
    """Try to import each package; print a status line; return failed dist names."""
    print(f"\n=== {category} ({len(pkgs)} packages) ===")
    failed: list[str] = []
    for pkg in pkgs:
        try:
            mod = importlib.import_module(pkg.module)
            version = _get_version(mod, pkg.version_attr)
            print(f"  OK    {pkg.dist:<22} {version}")
        except ImportError as exc:
            mark = "FAIL" if fatal else "SKIP"
            print(f"  {mark}  {pkg.dist:<22} -- {exc}")
            if fatal:
                failed.append(pkg.dist)
    return failed


def main() -> int:
    print("illumio_ops dependency baseline verification")
    print(f"Python: {sys.version}")
    failed = verify(PRODUCTION, "Production", fatal=True)
    verify(DEV, "Development (non-fatal)", fatal=False)
    if failed:
        print(f"\nFAILED: {len(failed)} production package(s) missing: {', '.join(failed)}")
        print("Run: pip install -r requirements.txt")
        return 1
    print("\nAll production packages imported successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
