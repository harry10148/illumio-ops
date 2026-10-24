"""AppContext: what every request handler and job needs, passed down explicitly."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from illumio_ops.paths import InstallPaths
from illumio_ops.pce.client import PceClient, client_from_settings
from illumio_ops.pce.rate_limit import RateLimiter
from illumio_ops.settings.schema import TlsSettings
from illumio_ops.settings.store import SettingsStore
from illumio_ops.store.db import connect
from illumio_ops.store.flowdb.db import FlowDb

if TYPE_CHECKING:
    from apscheduler.schedulers.background import BackgroundScheduler


@dataclass
class AppContext:
    paths: InstallPaths
    settings: SettingsStore
    # (pce settings, *, rate_limiter) -> client; tests swap in a fake PCE here.
    pce_factory: Callable[..., PceClient] = field(default=client_from_settings)
    # What the running listener was started with; None when not serving (tests, tools).
    # A difference from the current settings/certificate means a restart is needed.
    served_tls: TlsSettings | None = None
    served_cert_fingerprint: str | None = None
    flowdb: FlowDb | None = None
    # The one outbound PCE budget for the whole process (5.x had two that ignored each other).
    rate_limiter: RateLimiter | None = None
    scheduler: BackgroundScheduler | None = None

    def __post_init__(self) -> None:
        if self.flowdb is None:
            self.flowdb = FlowDb(self.paths.flows_db)
        if self.rate_limiter is None:
            self.rate_limiter = RateLimiter(self.settings.current().collection.rate_limit_per_minute)

    def db(self) -> sqlite3.Connection:
        return connect(self.paths.app_db)

    def flows(self) -> FlowDb:
        assert self.flowdb is not None  # set in __post_init__
        return self.flowdb

    def pce_client(self) -> PceClient:
        """A client for the configured PCE that spends the shared rate budget."""
        return self.pce_factory(self.settings.current().pce, rate_limiter=self.rate_limiter)
