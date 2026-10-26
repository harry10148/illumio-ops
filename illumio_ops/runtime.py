"""Process start-up shared by `serve` and the rescue commands: the service lock,
settings (fail-closed), logging, the app database and the TLS material."""
from __future__ import annotations

import fcntl
import os
import ssl
import sys
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from illumio_ops.paths import InstallPaths, resolve_paths
from illumio_ops.services.context import AppContext
from illumio_ops.settings.schema import Settings
from illumio_ops.settings.secrets import (
    DEFAULT_ADMIN_PASSWORD,
    hash_password,
    new_secret_key,
)
from illumio_ops.settings.store import SettingsInvalid, SettingsStore
from illumio_ops.store.db import connect, migrate, pending_migrations
from illumio_ops.store.flowdb.db import MIGRATIONS_PACKAGE as FLOW_MIGRATIONS
from illumio_ops.web.tls import build_ssl_context, cert_info, ensure_self_signed

EXIT_LOCKED = 75   # EX_TEMPFAIL: another instance holds the lock
EXIT_CONFIG = 78   # EX_CONFIG: settings or TLS material unusable
EXIT_UNAVAILABLE = 69


class StartupError(Exception):
    def __init__(self, exit_code: int, message: str) -> None:
        self.exit_code = exit_code
        self.message = message
        super().__init__(message)


def acquire_service_lock(paths: InstallPaths) -> int:
    fd = os.open(paths.service_lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise StartupError(EXIT_LOCKED, "illumio-ops is already running for this installation "
                                        "(stop the service first).") from None
    return fd


def configure_logging(paths: InstallPaths | None, level: str) -> None:
    """stderr only while paths is None (before the settings are known to be valid)."""
    logger.remove()
    logger.add(sys.stderr, level=level)
    if paths is not None:
        logger.add(paths.logs_dir / "illumio-ops.log", level=level, rotation="10 MB", retention=10, enqueue=True)


def load_settings(store: SettingsStore) -> Settings:
    try:
        return store.load()
    except SettingsInvalid as exc:
        lines = "\n".join(f"  {loc or '(file)'}: {msg}" for loc, msg in exc.errors)
        raise StartupError(EXIT_CONFIG, f"The settings file {store.path} is not valid; nothing was changed.\n"
                                        f"{lines}") from None


@dataclass
class Runtime:
    paths: InstallPaths
    ctx: AppContext
    ssl_ctx: ssl.SSLContext | None
    lock_fd: int

    def release(self) -> None:
        os.close(self.lock_fd)


def _tls_material(paths: InstallPaths, s: Settings) -> tuple[ssl.SSLContext | None, str | None]:
    tls = s.web.tls
    if not tls.enabled:
        return None, None
    if tls.mode == "self_signed":
        try:
            cert, key = ensure_self_signed(paths.tls_dir, tls)
        except OSError as exc:
            raise StartupError(EXIT_CONFIG, f"Cannot write the self-signed certificate in {paths.tls_dir} "
                                            f"({exc.strerror or type(exc).__name__}).") from None
    else:
        cert, key = Path(tls.cert_file), Path(tls.key_file)
        if not (cert.is_file() and key.is_file()):
            raise StartupError(EXIT_CONFIG, f"TLS certificate or key file not found ({cert}, {key}).")
    try:
        ctx = build_ssl_context(tls)
    except ssl.SSLError:
        raise StartupError(EXIT_CONFIG, "The TLS cipher list in the settings is not accepted "
                                        "(web.tls.ciphers).") from None
    try:
        ctx.load_cert_chain(cert, key)
    except (ssl.SSLError, OSError) as exc:
        raise StartupError(EXIT_CONFIG, f"The TLS certificate and key cannot be used together "
                                        f"({type(exc).__name__}).") from None
    info = cert_info(cert)
    return ctx, info.fingerprint_sha256 if info else None


def prepare(root: Path | None) -> Runtime:
    paths = resolve_paths(root)
    # An existing but invalid settings file stops us before anything is written
    # (no directories, no lock file, no log file).
    if paths.settings_file.exists():
        load_settings(SettingsStore(paths.settings_file))
    paths.ensure_dirs()
    lock_fd = acquire_service_lock(paths)
    try:
        store = SettingsStore(paths.settings_file)
        try:
            s = load_settings(store)
        except FileNotFoundError:
            # Only a brand-new root gets first-start settings. If this installation already
            # has a database or certificates, the file was lost: starting on defaults would
            # reopen it with the default sign-in and no address restriction.
            if paths.app_db.exists() or any(paths.tls_dir.iterdir()):
                raise StartupError(EXIT_CONFIG, f"The settings file {store.path} is missing from an existing "
                                                "installation. Restore it from a backup, or run "
                                                "`python -m illumio_ops.rescue init` to start over.") from None
            s = store.create_initial(password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
                                     secret_key=new_secret_key())
            logger.warning("no settings file found: created {} with the default sign-in", store.path)
        with connect(paths.app_db) as conn:
            try:
                migrate(conn)
            except RuntimeError as exc:
                raise StartupError(EXIT_CONFIG, str(exc)) from None
        ssl_ctx, fingerprint = _tls_material(paths, s)
        ctx = AppContext(paths=paths, settings=store, served_tls=s.web.tls, served_cert_fingerprint=fingerprint)
        # The flow database is migrated here, before the listener, as the app database is: on the first job's
        # connection an upgrade's one-off migration (0002: 20 min at 1,000 workloads) held up every job and GUI
        # request opening the store (D1, .106). A database newer than this program stops the start.
        conn = connect(paths.flows_db)
        try:
            pending = pending_migrations(conn, FLOW_MIGRATIONS)
        finally:
            conn.close()  # a reset deletes this file; no connection outside FlowDb may stay open on it
        if pending:
            logger.warning("upgrading the flow database ({} migration(s)) before serving; at 1,000 workloads "
                           "this can take 20 minutes", pending)
        try:
            ctx.flows().connect().close()
        except RuntimeError as exc:
            raise StartupError(EXIT_CONFIG, str(exc)) from None
        return Runtime(paths, ctx, ssl_ctx, lock_fd)
    except BaseException:
        os.close(lock_fd)
        raise
