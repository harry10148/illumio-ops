"""Every filesystem location v6 uses, derived from one install root.

Nothing in the package may depend on the process working directory; callers
resolve an InstallPaths once and pass it down.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT_ENV = "ILLUMIO_OPS_ROOT"


@dataclass(frozen=True)
class InstallPaths:
    root: Path

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def settings_file(self) -> Path:
        return self.config_dir / "settings.json"

    @property
    def tls_dir(self) -> Path:
        return self.config_dir / "tls"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def app_db(self) -> Path:
        return self.data_dir / "app.sqlite"

    @property
    def service_lock(self) -> Path:
        return self.data_dir / "service.lock"

    @property
    def limiter_dir(self) -> Path:
        return self.data_dir / "limiter"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    def ensure_dirs(self) -> None:
        """Create every directory v6 writes to (mode 0700); existing ones keep their mode.

        Entry points call this before taking the service lock or opening a
        database, so a fresh root without data/ does not fail on first start.
        """
        for d in (self.config_dir, self.tls_dir, self.data_dir, self.limiter_dir,
                  self.logs_dir, self.reports_dir):
            if not d.is_dir():
                d.mkdir(mode=0o700, parents=True, exist_ok=True)
                d.chmod(0o700)  # mkdir's mode is filtered by umask


def resolve_paths(root: Path | None = None) -> InstallPaths:
    """Explicit root, then $ILLUMIO_OPS_ROOT, then the directory holding the package."""
    if root is not None:
        return InstallPaths(Path(root))
    env = os.environ.get(ROOT_ENV)
    if env:
        return InstallPaths(Path(env))
    return InstallPaths(Path(__file__).resolve().parent.parent)
