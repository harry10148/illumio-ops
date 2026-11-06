"""Rescue commands for the shell, run while the service is stopped:

    python -m illumio_ops.rescue init [--port N] [--root PATH]   create the first settings file
    python -m illumio_ops.rescue reset-password [--root PATH]   set a new admin password
    python -m illumio_ops.rescue check-settings [--root PATH]   validate the settings file
    python -m illumio_ops.rescue clear-allowed-ips [--root PATH]   accept sign-ins from any address again
    python -m illumio_ops.rescue reset-tls [--root PATH]   go back to the self-signed certificate

This is the one module allowed to print.
"""
from __future__ import annotations

import argparse
import getpass
import os
import pwd
import sys
from pathlib import Path
from typing import Any

from illumio_ops.paths import InstallPaths, resolve_paths
from illumio_ops.runtime import (
    EXIT_CONFIG,
    EXIT_LOCKED,
    StartupError,
    acquire_service_lock,
)
from illumio_ops.settings.secrets import (
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    PASSWORD_MAX_LEN,
    PASSWORD_MIN_LEN,
    hash_password,
    new_secret_key,
)
from illumio_ops.settings.store import SettingsInvalid, SettingsStore

EXIT_DATAERR = 65
EXIT_NOINPUT = 66
EXIT_CANTCREAT = 73
EXIT_NOPERM = 77


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _init(paths: InstallPaths, port: int) -> int:
    store = SettingsStore(paths.settings_file)
    if paths.settings_file.exists():
        _err(f"{paths.settings_file} already exists; nothing was changed.")
        return EXIT_CANTCREAT
    store.create_initial(password_hash=hash_password(DEFAULT_ADMIN_PASSWORD), secret_key=new_secret_key(),
                         port=port)
    print(f"Created {paths.settings_file} (port {port}).")
    print(f"Sign in as '{DEFAULT_ADMIN_USERNAME}' with the default password, then change it.")
    return 0


def _load(store: SettingsStore) -> int | None:
    try:
        store.load()
    except FileNotFoundError:
        _err(f"no settings file at {store.path}")
        return EXIT_NOINPUT
    except SettingsInvalid as exc:
        _err(f"{store.path} is not valid:")
        for loc, msg in exc.errors:
            _err(f"  {loc or '(file)'}: {msg}")
        return EXIT_CONFIG
    return None


def _reset_password(paths: InstallPaths) -> int:
    store = SettingsStore(paths.settings_file)
    failed = _load(store)
    if failed is not None:
        return failed
    first = getpass.getpass("New admin password: ")
    second = getpass.getpass("Repeat it: ")
    if first != second:
        _err("The two passwords differ; nothing was changed.")
        return EXIT_DATAERR
    if not PASSWORD_MIN_LEN <= len(first) <= PASSWORD_MAX_LEN:
        _err(f"The password must be {PASSWORD_MIN_LEN}–{PASSWORD_MAX_LEN} characters; nothing was changed.")
        return EXIT_DATAERR
    new_hash, new_key = hash_password(first), new_secret_key()

    def mutate(d: dict[str, Any]) -> None:
        d["web"].update(password_hash=new_hash, secret_key=new_key, must_change_password=False)

    store.update(store.current().revision, mutate)
    print("Password changed. Everyone signed in before has been signed out.")
    return 0


def _clear_allowed_ips(paths: InstallPaths) -> int:
    store = SettingsStore(paths.settings_file)
    failed = _load(store)
    if failed is not None:
        return failed
    before = list(store.current().web.allowed_ips)
    if not before:
        print("No address restriction is set: sign-ins are accepted from any address. Nothing was changed.")
        return 0
    store.update(store.current().revision, lambda d: d["web"].update(allowed_ips=[]))
    print("Sign-ins are accepted from any address again. The list was:")
    for entry in before:
        print(f"  {entry}")
    print("Set it again in System › Security once you are signed in.")
    return 0


def _reset_tls(paths: InstallPaths) -> int:
    store = SettingsStore(paths.settings_file)
    failed = _load(store)
    if failed is not None:
        return failed
    tls = store.current().web.tls
    was = (f"a provided certificate ({tls.cert_file}, {tls.key_file})" if tls.mode == "provided"
           else "the self-signed certificate")

    def mutate(d: dict[str, Any]) -> None:
        d["web"]["tls"].update(enabled=True, mode="self_signed", cert_file="", key_file="", ciphers=None,
                               min_version="TLSv1.2")

    store.update(store.current().revision, mutate)
    print(f"TLS was using {was}" + (", ciphers " + tls.ciphers if tls.ciphers else "") + f", {tls.min_version} or newer.")
    print("It now uses the self-signed certificate (made at the next start when missing), TLS 1.2 or newer and the "
          "default ciphers. The provided files were not touched. Import a certificate again in System › Certificate.")
    return 0


def _check(paths: InstallPaths) -> int:
    store = SettingsStore(paths.settings_file)
    failed = _load(store)
    if failed is not None:
        return failed
    print(f"{paths.settings_file} is valid.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m illumio_ops.rescue")
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("init", "reset-password", "check-settings", "clear-allowed-ips", "reset-tls"):
        sp = sub.add_parser(name)
        sp.add_argument("--root", type=Path, default=None)
        if name == "init":
            sp.add_argument("--port", type=int, default=5001)
    args = ap.parse_args(argv)
    paths = resolve_paths(args.root)
    # Files written here must stay readable by the service: run as the account that owns
    # the installation (as root, a rewritten settings file would become root's 0600 file
    # and the service would no longer start).
    if paths.config_dir.is_dir():
        owner = paths.config_dir.stat().st_uid
        if os.geteuid() != owner:
            try:
                name = pwd.getpwuid(owner).pw_name
            except KeyError:
                name = str(owner)
            _err(f"Run this as the account that owns {paths.root}, for example:\n"
                 f"  runuser -u {name} -- env PYTHONPATH={paths.root} {sys.executable} -P -m illumio_ops.rescue "
                 f"{' '.join(argv if argv is not None else sys.argv[1:])}")
            return EXIT_NOPERM
    paths.ensure_dirs()
    try:
        fd = acquire_service_lock(paths)
    except StartupError:
        _err("illumio-ops is running for this installation; stop the service first.")
        return EXIT_LOCKED
    try:
        if args.command == "init":
            return _init(paths, args.port)
        if args.command == "reset-password":
            return _reset_password(paths)
        if args.command == "clear-allowed-ips":
            return _clear_allowed_ips(paths)
        if args.command == "reset-tls":
            return _reset_tls(paths)
        return _check(paths)
    finally:
        os.close(fd)


if __name__ == "__main__":
    raise SystemExit(main())
