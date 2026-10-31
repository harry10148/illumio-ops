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

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from illumio_ops.domain.values import IngestSource, Language
from illumio_ops.i18n import translate
from illumio_ops.migrate.report import render
from illumio_ops.migrate.v5 import MigrationResult, migrate_v5, read_v5
from illumio_ops.migrate.v5_alerts import read_v5_rules
from illumio_ops.migrate.v5_handover import Handover, read_handover
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


class MigrationBlocked(Exception):
    def __init__(self, result: MigrationResult) -> None:
        super().__init__("5.x values that cannot become v6 settings")
        self.result = result


def _copy_tls(v5_root: Path, paths: InstallPaths, s: Settings) -> Settings:
    src = v5_root / "config" / "tls"
    paths.tls_dir.mkdir(parents=True, exist_ok=True)
    paths.tls_dir.chmod(0o700)
    if src.is_dir():
        for f in sorted(src.iterdir()):
            if f.is_file():
                dst = paths.tls_dir / f.name
                shutil.copyfile(f, dst)
                dst.chmod(0o600 if "key" in f.name.lower() else 0o644)
    tls, moved = s.web.tls, {}
    for field in ("cert_file", "key_file"):
        value = getattr(tls, field)
        if value and Path(value).resolve().is_relative_to(v5_root.resolve()):
            dst = paths.tls_dir / Path(value).name
            if not dst.exists():
                shutil.copyfile(value, dst)
                dst.chmod(0o600 if field == "key_file" else 0o644)
            moved[field] = str(dst)
    if not moved:
        return s
    return s.model_copy(update={"web": s.web.model_copy(update={"tls": tls.model_copy(update=moved)})})


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
    if floors:
        start = max(min(floors), now - COLD_START_CAP)
        if start > min(floors):
            lines.append(translate(lang, "migrate_handover_capped", {"days": str(COLD_START_CAP.days),
                                                                      "from": min(floors).isoformat(),
                                                                      "to": start.isoformat()}))
        with ctx.flows().connect() as conn:
            for src in (IngestSource.EVENTS, IngestSource.TRAFFIC):
                if collects(s, src):
                    ingest_state.set_progress(conn, src, {COLD_START_KEY: start.isoformat()})
            conn.commit()
    return lines


def upgrade(v5_root: Path, root: Path, *, now: datetime, lang: Language = Language.EN) -> list[str]:
    """Write v6 at root from the stopped 5.x at v5_root; returns what the handover did, one line each."""
    paths = InstallPaths(root)
    if paths.settings_file.exists():
        raise AlreadyInstalled(str(paths.settings_file))
    raw = read_v5(v5_root)
    rules, legacy_channels = read_v5_rules(v5_root)
    result = migrate_v5(raw, rules=rules, legacy_channels=legacy_channels)
    if result.blocking or result.settings is None:
        raise MigrationBlocked(result)
    h = read_handover(v5_root, raw)
    for d in (paths.config_dir, paths.data_dir, root / "logs"):
        d.mkdir(parents=True, exist_ok=True)
    s = _copy_tls(v5_root, paths, result.settings)
    store = SettingsStore(paths.settings_file)
    store.create(s)
    with connect(paths.app_db) as conn:  # as the service's start does (runtime.prepare)
        migrate(conn)
    lines = _handover(AppContext(paths=paths, settings=store), s, result, h, now, lang)
    (root / "logs" / REPORT_FILE).write_text(render(result.report, lang) + "\n" + "\n".join(lines) + "\n",
                                             encoding="utf-8")
    return lines
