"""Write a 5.x installation's settings into a new v6 root and continue where the stopped 5.x got to (P8, spec §7).

The installer stops 5.x first: its progress (illumio_ops.migrate.v5_handover) no longer moves while it is read.
Then, in the new root only (the 5.x installation is read, never written):

- settings.json from the migrated settings; config/tls/* copied (keys 0600), and a provided certificate inside the
  5.x root pointed at its copy (the 5.x root may be moved aside);
- each migrated SIEM destination's cursors, the audit one with the floor 5.x had sent through (no floor: the upgrade);
- the event-alert watermark at the floor 5.x had evaluated through (no floor: the upgrade);
- the first events (and traffic) cycle starting at the earliest floor, at most COLD_START_CAP back, so the downtime is
  collected as live data — sent and alerted once, after the floors;
- logs/migration-report.txt: the report and what the handover did.
"""
from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from illumio_ops.domain.values import IngestSource, Language
from illumio_ops.i18n import translate
from illumio_ops.migrate import v5_rule_schedules
from illumio_ops.migrate.report import render
from illumio_ops.migrate.v5 import MigrationResult, migrate_v5, read_v5
from illumio_ops.migrate.v5_alerts import read_v5_rules
from illumio_ops.migrate.v5_handover import Handover, cache_store, read_handover
from illumio_ops.paths import InstallPaths
from illumio_ops.services.collect.cycle import COLD_START_KEY
from illumio_ops.services.collect.mode import collects
from illumio_ops.services.context import AppContext
from illumio_ops.services.siem.cursors import place_new_cursors
from illumio_ops.services.siem.sources import AUDIT
from illumio_ops.settings.schema import Settings
from illumio_ops.settings.store import SettingsStore
from illumio_ops.store import alerts as alert_store
from illumio_ops.store import siem as siem_store
from illumio_ops.store.db import connect, migrate
from illumio_ops.store.flowdb import ingest_state

COLD_START_CAP = timedelta(days=7)
REPORT_FILE = "migration-report.txt"


class AlreadyInstalled(Exception):
    """The v6 root already has settings: an upgrade never overwrites an installation."""


class UnsafeSource(Exception):
    """A 5.x file the upgrade reads (as root) is a link: refused rather than followed (security review)."""


# What the upgrade reads from 5.x, relative to its root (the cache database's own path is checked as configured).
_READ = ("config", "config/config.json", "config/alerts.json", "data", "logs", "logs/state.json")


def _no_links(v5_root: Path, raw_db: Path) -> None:
    for p in (*(v5_root / r for r in _READ), raw_db):
        if p.is_symlink():
            raise UnsafeSource(str(p))


def _reader(v5_root: Path) -> Callable[[Path], str]:
    """Read a 5.x file by descriptor (as the TLS copy does): a link, a swapped-in link or anything but a regular
    file with one link is refused, not followed (security review: a check then a read by path can be raced)."""
    def read(path: Path) -> str:
        try:
            fd = _open_beneath(v5_root, path.relative_to(v5_root))
        except FileNotFoundError:
            raise
        except (OSError, ValueError) as exc:
            raise UnsafeSource(str(path)) from exc
        with os.fdopen(fd, "rb") as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                raise UnsafeSource(str(path))
            return f.read().decode("utf-8")
    return read


class MigrationBlocked(Exception):
    def __init__(self, result: MigrationResult) -> None:
        super().__init__("5.x values that cannot become v6 settings")
        self.result = result


def _open_beneath(root: Path, rel: Path) -> int:
    """A read descriptor for root/rel, walked one directory at a time without following a link anywhere beneath
    root (security review: a check, then an open by path, can be raced)."""
    if rel.is_absolute() or not rel.parts or any(part in ("", ".", "..") for part in rel.parts):
        raise ValueError(f"{rel} does not name a file beneath {root}")  # ".." would walk out (security review)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in rel.parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        # O_NONBLOCK: a FIFO planted there would otherwise hold the open forever; the caller checks the type
        return os.open(rel.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY, dir_fd=fd)
    finally:
        os.close(fd)


def _copy_file(src: Path, dst: Path, *, inside: Path, mode: int) -> bool:
    """Copy one file of the 5.x directory: a regular file with one link, reached without following a link; False
    (nothing copied) for anything else. The upgrade runs as root and the 5.x directory may be the service
    account's: what it planted there must not make root copy what the account could not read (security review)."""
    try:
        fd = _open_beneath(inside, src.relative_to(inside))
    except (OSError, ValueError):
        return False
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            return False
        data = f.read()
    out = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    with os.fdopen(out, "wb") as f:
        f.write(data)
    os.chmod(dst, mode)
    return True


def _copy_tls(v5_root: Path, paths: InstallPaths, s: Settings, original: Path) -> tuple[Settings, list[str]]:
    """original: where 5.x ran (its settings name files there); v5_root: where it is now (moved aside when v6 takes
    its directory). Returns the settings and the files not copied."""
    src = v5_root / "config" / "tls"
    paths.tls_dir.mkdir(parents=True, exist_ok=True)
    paths.tls_dir.chmod(0o700)
    skipped: list[str] = []
    if src.is_dir() and not src.is_symlink():
        for f in sorted(src.iterdir()):
            mode = 0o600 if "key" in f.name.lower() else 0o644
            if not _copy_file(f, paths.tls_dir / f.name, inside=v5_root, mode=mode):
                skipped.append(f.name)
    tls, moved = s.web.tls, {}
    for field in ("cert_file", "key_file"):
        value = getattr(tls, field)
        if value and Path(value).is_relative_to(original):
            dst = paths.tls_dir / Path(value).name
            if not dst.exists() and not _copy_file(v5_root / Path(value).relative_to(original), dst, inside=v5_root,
                                                   mode=0o600 if field == "key_file" else 0o644):
                skipped.append(Path(value).name)
                continue
            moved[field] = str(dst)
    if moved:
        s = s.model_copy(update={"web": s.web.model_copy(update={"tls": tls.model_copy(update=moved)})})
    return s, skipped


def _handover(ctx: AppContext, s: Settings, result: MigrationResult, h: Handover, now: datetime,
              lang: Language) -> list[str]:
    lines: list[str] = []
    place_new_cursors(ctx)  # an empty store: every source of every enabled destination starts at 0
    active = {d.id for d in s.siem.destinations if s.siem.enabled and d.enabled}
    floors: list[datetime] = []
    for name, ids in sorted(result.siem_origins.items()):
        floor = h.audit_floors.get(name)
        for dest_id in ids:
            if dest_id not in active:
                continue
            with ctx.db() as conn:
                siem_store.set_floor(conn, dest_id, AUDIT, floor or now)
            if floor is not None:
                floors.append(floor)
            lines.append(translate(lang, "migrate_handover_siem" if floor else "migrate_handover_siem_none",
                                   {"name": name, "time": floor.isoformat() if floor else ""}))
        if h.dlq_counts.get(name):
            lines.append(translate(lang, "migrate_handover_siem_dlq", {"name": name, "n": str(h.dlq_counts[name])}))
    alert_floor = h.event_alert_floor
    with ctx.db() as conn:
        alert_store.set_eval_watermark(conn, "events", "t:" + (alert_floor or now).isoformat(),
                                       pce_url=s.pce.url, org_id=s.pce.org_id)
    lines.append(translate(lang, "migrate_handover_alerts" if alert_floor else "migrate_handover_alerts_none",
                           {"time": alert_floor.isoformat() if alert_floor else ""}))
    if alert_floor is not None:
        floors.append(alert_floor)
    # Live collection starts at the earliest floor, or at the upgrade without one — recorded either way, so a backfill
    # running before the first cycle never takes that stretch as history (final review).
    earliest = min(floors, default=now)
    start = max(earliest, now - COLD_START_CAP)
    if start > earliest:
        lines.append(translate(lang, "migrate_handover_capped", {"days": str(COLD_START_CAP.days),
                                                                  "from": earliest.isoformat(), "to": start.isoformat()}))
    with ctx.flows().connect() as conn:
        for src in (IngestSource.EVENTS, IngestSource.TRAFFIC):
            if collects(s, src):
                ingest_state.set_progress(conn, src, {COLD_START_KEY: start.isoformat()})
        conn.commit()
    return lines


def _rule_schedules(v5_root: Path, read: Callable[[Path], str]) -> dict[str, Any] | None:
    """config/rule_schedules.json, read like every 5.x file (no links); None when 5.x had none."""
    try:
        data = json.loads(read(v5_root / v5_rule_schedules.FILE))
    except FileNotFoundError:
        return None
    return data if isinstance(data, dict) else None


def upgrade(v5_root: Path, root: Path, *, now: datetime, lang: Language = Language.EN,
            original_root: Path | None = None) -> list[str]:
    """Write v6 at root from the stopped 5.x at v5_root (moved there from original_root, when given); returns what the
    handover did, one line each."""
    paths = InstallPaths(root)
    if paths.settings_file.exists():
        raise AlreadyInstalled(str(paths.settings_file))
    read = _reader(v5_root)
    raw = read_v5(v5_root, read)
    _no_links(v5_root, cache_store(v5_root, raw, original_root))
    rules, legacy_channels = read_v5_rules(v5_root, read)
    result = migrate_v5(raw, rules=rules, legacy_channels=legacy_channels)
    if result.blocking or result.settings is None:
        raise MigrationBlocked(result)
    h = read_handover(v5_root, raw, original_root)
    for d in (paths.config_dir, paths.data_dir, root / "logs"):
        d.mkdir(parents=True, exist_ok=True)
    s, skipped = _copy_tls(v5_root, paths, result.settings, original_root or v5_root)
    store = SettingsStore(paths.settings_file)
    store.create(s)
    schedules, schedule_items = v5_rule_schedules.convert(_rule_schedules(v5_root, read),
                                                          local_zone=v5_rule_schedules.host_zone())
    result.report.items.extend(schedule_items)
    with connect(paths.app_db) as conn:  # as the service's start does (runtime.prepare)
        migrate(conn)
        v5_rule_schedules.write(conn, schedules, pce_url=s.pce.url, org_id=s.pce.org_id, now=now)
        conn.commit()
    lines = [translate(lang, "migrate_tls_skipped", {"file": name}) for name in skipped]
    lines += _handover(AppContext(paths=paths, settings=store), s, result, h, now, lang)
    (root / "logs" / REPORT_FILE).write_text(render(result.report, lang) + "\n" + "\n".join(lines) + "\n",
                                             encoding="utf-8")
    return lines
