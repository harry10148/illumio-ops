"""AppContext: what every request handler and job needs, passed down explicitly."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field

from illumio_ops.paths import InstallPaths
from illumio_ops.pce.client import PceClient, client_from_settings
from illumio_ops.settings.schema import PceSettings
from illumio_ops.settings.store import SettingsStore
from illumio_ops.store.db import connect


@dataclass
class AppContext:
    paths: InstallPaths
    settings: SettingsStore
    pce_factory: Callable[[PceSettings], PceClient] = field(default=client_from_settings)

    def db(self) -> sqlite3.Connection:
        return connect(self.paths.app_db)
