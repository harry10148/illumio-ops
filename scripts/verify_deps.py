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
    Pkg("cheroot", "cheroot"),
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
    # Phase 2 TLS
    Pkg("cryptography", "cryptography"),
    # Phase 4
    Pkg("flask-wtf", "flask_wtf"),
    Pkg("flask-limiter", "flask_limiter"),
    Pkg("flask-talisman", "flask_talisman"),
    Pkg("flask-login", "flask_login"),
    # Phase 5
    Pkg("openpyxl", "openpyxl"),
    Pkg("reportlab", "reportlab"),
    Pkg("matplotlib", "matplotlib"),
    Pkg("plotly", "plotly"),
    Pkg("pygments", "pygments"),
    # Phase 6
    Pkg("APScheduler", "apscheduler"),
    Pkg("SQLAlchemy", "sqlalchemy"),
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
        # Suppress deprecation warnings raised by getattr(mod, '__version__')
        # for packages (Flask/Click) that deprecate the attribute.
        import warnings
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                mod = importlib.import_module(pkg.module)
                version = _get_version(mod, pkg.version_attr)
            print(f"  OK    {pkg.dist:<22} {version}")
        except (ImportError, OSError) as exc:
            mark = "SKIP" if not fatal else "FAIL"
            print(f"  {mark}  {pkg.dist:<22} -- {type(exc).__name__}: {exc}")
            if fatal:
                failed.append(pkg.dist)
    return failed


def check_pip_audit() -> bool:
    """Run pip-audit to check for known vulnerabilities (non-blocking)."""
    import subprocess
    requirements_path = (
        __import__("pathlib").Path(__file__).parent.parent / "requirements.txt"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip_audit", "-r", str(requirements_path)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"WARNING: pip-audit found vulnerabilities:\n{result.stdout}")
            return False
        print("pip-audit: no known vulnerabilities found")
        return True
    except FileNotFoundError:
        print("WARNING: pip-audit not installed (pip install pip-audit to enable)")
        return True  # non-blocking
    except subprocess.TimeoutExpired:
        print("WARNING: pip-audit timed out")
        return True  # non-blocking


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Verify illumio_ops dependencies can be imported."
    )
    parser.add_argument(
        "--offline-bundle",
        action="store_true",
        help="Verify offline bundle: same production package set (ReportLab ships pure-Python).",
    )
    args = parser.parse_args()

    print("illumio_ops dependency baseline verification")
    print(f"Python: {sys.version}")

    if args.offline_bundle:
        failed = verify(PRODUCTION, "Production (offline bundle)", fatal=True)
        if failed:
            print(f"\nFAILED: {len(failed)} package(s): {', '.join(failed)}")
            return 1
        print("\nOffline bundle dependency check passed.")
        return 0

    failed = verify(PRODUCTION, "Production", fatal=True)
    verify(DEV, "Development (non-fatal)", fatal=False)
    check_pip_audit()
    if failed:
        print(f"\nFAILED: {len(failed)} production package(s) missing: {', '.join(failed)}")
        print("Run: pip install -r requirements.txt")
        return 1
    print("\nAll production packages imported successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
