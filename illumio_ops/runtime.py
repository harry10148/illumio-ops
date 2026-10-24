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
from illumio_ops.store.db import connect, migrate
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


def configure_logging(paths: InstallPaths, level: str) -> None:
    logger.remove()
    logger.add(sys.stderr, level=level)
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
        cert, key = ensure_self_signed(paths.tls_dir, tls)
    else:
        cert, key = Path(tls.cert_file), Path(tls.key_file)
        if not (cert.is_file() and key.is_file()):
            raise StartupError(EXIT_CONFIG, f"TLS certificate or key file not found ({cert}, {key}).")
    ctx = build_ssl_context(tls)
    try:
        ctx.load_cert_chain(cert, key)
    except (ssl.SSLError, OSError) as exc:
        raise StartupError(EXIT_CONFIG, f"The TLS certificate and key cannot be used together "
                                        f"({type(exc).__name__}).") from None
    info = cert_info(cert)
    return ctx, info.fingerprint_sha256 if info else None


def prepare(root: Path | None) -> Runtime:
    paths = resolve_paths(root)
    paths.ensure_dirs()
    lock_fd = acquire_service_lock(paths)
    try:
        store = SettingsStore(paths.settings_file)
        try:
            s = load_settings(store)
        except FileNotFoundError:
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
        return Runtime(paths, ctx, ssl_ctx, lock_fd)
    except BaseException:
        os.close(lock_fd)
        raise
