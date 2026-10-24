"""`python -m illumio_ops serve [--root PATH]` — the service entry point."""
from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path
from types import FrameType

from loguru import logger

from illumio_ops.jobs.scheduler import build_scheduler
from illumio_ops.paths import resolve_paths
from illumio_ops.runtime import (
    EXIT_UNAVAILABLE,
    StartupError,
    configure_logging,
    prepare,
)
from illumio_ops.web.app import create_app
from illumio_ops.web.ipallow import is_allowed
from illumio_ops.web.server import serve


def cmd_serve(root: Path | None) -> int:
    paths = resolve_paths(root)
    try:
        paths.ensure_dirs()
    except OSError as exc:
        sys.stderr.write(f"cannot create the data directories under {paths.root}: {exc.strerror}\n")
        return EXIT_UNAVAILABLE
    configure_logging(paths, "INFO")
    try:
        rt = prepare(root)
    except StartupError as exc:
        logger.error("not starting: {}", exc.message)
        sys.stderr.write(exc.message + "\n")
        return exc.exit_code
    s = rt.ctx.settings.current()
    configure_logging(paths, s.logging.level)
    stop = threading.Event()

    def on_signal(signum: int, _frame: FrameType | None) -> None:
        logger.info("signal {} received; shutting down", signum)
        stop.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    app = create_app(rt.ctx, use_https=rt.ssl_ctx is not None)
    scheduler = build_scheduler(rt.ctx)
    scheduler.start()
    try:
        serve(app, s.web.host, s.web.port, rt.ssl_ctx, stop,
              peer_allowed=lambda ip: is_allowed(rt.ctx.settings.current().web.allowed_ips, ip))
    except OSError as exc:
        logger.error("cannot listen on {}:{}: {}", s.web.host, s.web.port, exc.strerror)
        sys.stderr.write(f"cannot listen on {s.web.host}:{s.web.port}: {exc.strerror}\n")
        return EXIT_UNAVAILABLE
    finally:
        scheduler.shutdown(wait=False)
        rt.release()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m illumio_ops")
    sub = ap.add_subparsers(dest="command", required=True)
    sp = sub.add_parser("serve", help="run the web UI and background jobs")
    sp.add_argument("--root", type=Path, default=None, help="installation root (default: $ILLUMIO_OPS_ROOT)")
    args = ap.parse_args(argv)
    return cmd_serve(args.root)


if __name__ == "__main__":
    raise SystemExit(main())
