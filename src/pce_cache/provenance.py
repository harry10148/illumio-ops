"""Which PCE does this cache belong to?

`flush.py` opens by saying the cache carries no tenant dimension. This module is
that dimension: one row naming the PCE whose data the cache holds, checked before
every ingest and at startup.

`pce_target_changed()` already asks the same question, but only where the product
itself edits the connection — the GUI and the two CLI paths. On 2026-08-30 the
appliance was re-pointed by editing `config/config.json` directly, so none of the
three ran, no flush happened, and 11 events from a second PCE landed beside 11,535
from the first. A check on the write path cannot see an edit that never uses it.
This one is on the *read* path of the config, so it fires however the value got
there.

**Why not compare `pce_events.pce_fqdn` to the configured host.** That column is
the PCE *node* that recorded the event, taken from the event payload
(`ingestor_events.py`), and a multi-node PCE legitimately reports several distinct
FQDNs, none of which need equal the configured URL. Asserting equality there would
go red on a healthy cluster — a guard that fails on real data is worse than none,
because it is the moment operators learn to ignore it. Binding to the configured
target instead is independent of payload contents, and it covers the traffic tables
too, which carry no FQDN at all.

Fail-closed on purpose. A version that logged and carried on would be
indistinguishable from having no check, and this repository has already shipped
that shape once (config fail-open, three call sites).
"""
from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

# The model lives in models.py so `schema.init_schema()` creates the table from
# Base alone — see its docstring. Re-exported here because this module is where
# callers reason about it.
from src.pce_cache.models import CacheBinding
from src.pce_target import normalize_org_id, normalize_pce_url

__all__ = ["CacheBinding", "CacheTargetMismatch", "bind_or_verify", "verify_at_startup"]


class CacheTargetMismatch(RuntimeError):
    """The cache holds another PCE's data and must not be written to.

    Carries both targets so the operator is told what to do rather than only
    that something is wrong: either point the config back, or flush the cache
    deliberately.
    """

    def __init__(self, bound: tuple[str, str], configured: tuple[str, str]) -> None:
        self.bound = bound
        self.configured = configured
        # Only remedies that actually work. The first draft of this message
        # offered two that do not: `cache flush` without --confirm exits with a
        # usage error, and "Settings → save offers a flush" is false in the very
        # case that produces this error — after a direct edit of config.json the
        # stored value already IS the new target, so pce_target_changed() returns
        # False and nothing is offered. A wrong instruction costs the operator
        # more than no instruction, because they spend the time before finding out.
        super().__init__(
            f"PCE cache belongs to {bound[0]} (org {bound[1]}) but the configuration "
            f"now points at {configured[0]} (org {configured[1]}). Refusing to write: "
            f"mixing two PCEs' data leaves both wrong.\n"
            f"  To keep the cached data: set the connection back to {bound[0]} "
            f"(org {bound[1]}).\n"
            f"  To move to {configured[0]}: `illumio-ops cache flush --confirm` "
            f"discards the cached rows, after which the next ingest binds the new PCE.\n"
            f"  If this IS the same PCE at a new address, re-run the connection "
            f"change through Settings (or `illumio-ops config login`) and answer "
            f"'same-pce', which keeps the data and updates the binding."
        )


def _configured_target(api_cfg) -> tuple[str, str]:
    """Normalize through the same functions the edit-time guard uses.

    Sharing them is the point: if the two normalized differently, a value stored
    by one would look changed to the other, and the guard would fire on a
    connection nobody touched.
    """
    get = api_cfg.get if hasattr(api_cfg, "get") else lambda k, d=None: getattr(api_cfg, k, d)
    return normalize_pce_url(get("url", "")), normalize_org_id(get("org_id", ""))


def bind_or_verify(session_factory, api_cfg) -> tuple[str, str]:
    """Bind the cache to the configured PCE, or confirm it already is.

    Returns the target in force. Raises :class:`CacheTargetMismatch` when the
    cache is bound to a different one.

    An unbound cache is bound here rather than treated as an error, for two
    reasons. Appliances upgrading into this check have a populated cache and no
    binding, and the configuration they are running is the right answer for them.
    And `flush_pce_derived_state` clears the binding along with the rows, so
    "empty and unbound" is the normal state directly after a deliberate re-point —
    there is nothing left to protect at that moment, which is what makes adopting
    the configured target safe there.

    The gap this leaves is narrow and worth naming: an appliance re-pointed
    *before* it ever ran this check would bind the new target over the old data.
    Only the first run after upgrading is exposed, and `verify_at_startup` is
    where that is caught, because it reports rather than adopts.
    """
    configured = _configured_target(api_cfg)
    with session_factory() as session:
        row = session.execute(select(CacheBinding).where(CacheBinding.id == 1)).scalar_one_or_none()
        if row is None:
            # INSERT .. ON CONFLICT DO NOTHING, then re-read, rather than
            # read-then-insert. The events and traffic jobs fire on the same
            # scheduler kick from different executors, so both can see None and
            # both try to write id=1; the loser of a plain insert gets an
            # IntegrityError or "database is locked" and its first ingest fails —
            # for traffic, up to a poll interval of delay. Whoever wins, the
            # re-read below is what decides, so both callers agree.
            session.execute(
                sqlite_insert(CacheBinding)
                .values(id=1, pce_url=configured[0], org_id=configured[1],
                        bound_at=datetime.now(timezone.utc))
                .on_conflict_do_nothing(index_elements=["id"])
            )
            session.commit()
            row = session.execute(
                select(CacheBinding).where(CacheBinding.id == 1)).scalar_one()
            logger.info("PCE cache bound to {} (org {})", row.pce_url, row.org_id)

        bound = (normalize_pce_url(row.pce_url), normalize_org_id(row.org_id))
        if bound != configured:
            raise CacheTargetMismatch(bound, configured)
        return bound


def rebind(db_path: str, api_cfg) -> tuple[str, str]:
    """Move the binding to *api_cfg*'s target, keeping every cached row.

    This is the `same-pce` answer: one PCE reachable at a new address, where the
    operator has told us the data is still theirs. Without it the binding keeps
    naming the old address and every ingest afterwards raises
    :class:`CacheTargetMismatch` — a supported option would silently stop
    monitoring, which is how this function came to exist (Codex adversarial
    review of 0449c36b).

    Takes a path rather than a session factory because its three callers are the
    config write paths, which hold `pce_cache.db_path` and no engine. A missing
    database is not an error: nothing has been cached yet, so there is no binding
    to move.
    """
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.pce_cache.models import Base

    configured = _configured_target(api_cfg)
    # `isinstance(..., str)` before os.path.exists, and not the other way round.
    # A MagicMock grows a `__fspath__` on demand, so `os.path.exists(mock)`
    # returns **True** — the existence check alone let a test double through and
    # `create_engine(f"sqlite:///{mock}")` wrote a real 172KB database named
    # after the Mock's repr into the repository root. os.path.exists is not a
    # type check. The same idiom, for the same reason, is in backfill.py's
    # _raise_on_fetch_error.
    if not isinstance(db_path, str) or not os.path.exists(db_path):
        return configured

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as session:
            row = session.execute(
                select(CacheBinding).where(CacheBinding.id == 1)).scalar_one_or_none()
            if row is None:
                session.add(CacheBinding(id=1, pce_url=configured[0], org_id=configured[1],
                                         bound_at=datetime.now(timezone.utc)))
            else:
                row.pce_url, row.org_id = configured
                row.bound_at = datetime.now(timezone.utc)
            session.commit()
    finally:
        engine.dispose()
    logger.warning("PCE cache re-bound to {} (org {}) — same PCE, new address; "
                   "cached rows kept", configured[0], configured[1])
    return configured


def verify_at_startup(session_factory, api_cfg) -> str:
    """Report the cache's provenance once, at start, without changing it.

    Returns one of ``"match"``, ``"mismatch"``, ``"adopting"`` or ``"empty"``.

    Deliberately does not bind and does not raise. Binding belongs to the ingest
    path, where refusing is meaningful because there is a write to refuse; a
    process that exits on startup would take the GUI and the schedulers down with
    it over a condition the operator can fix in the settings page. What this adds
    is the one thing the ingest path cannot: telling the operator *before* the
    first ingest adopts a target, which is the only window in which the
    upgrade-after-an-undetected-re-point case is visible.

    Counting rows is what separates "adopting" from "empty" — a populated cache
    with no binding is the case worth a warning, an empty one is a fresh install.

    Every provenance-bearing table is counted, not just events and raw flows.
    Raw has a 7-day retention while aggregates, observations and the ingestion
    watermarks live far longer, so a database whose raw rows had aged out would
    otherwise report "empty", skip the warning, and let the next ingest bind a new
    PCE to a cache still full of the old one's derived data. The binding itself is
    excluded for the obvious reason: this branch only runs when there isn't one.
    """
    from src.pce_cache.flush import _MODELS

    configured = _configured_target(api_cfg)
    with session_factory() as session:
        row = session.execute(select(CacheBinding).where(CacheBinding.id == 1)).scalar_one_or_none()
        if row is not None:
            bound = (normalize_pce_url(row.pce_url), normalize_org_id(row.org_id))
            if bound == configured:
                return "match"
            logger.error(
                "PCE cache belongs to {} (org {}) but the configuration points at {} (org {}). "
                "Ingest will refuse to write until the connection is restored or the cache is "
                "flushed.", bound[0], bound[1], configured[0], configured[1])
            return "mismatch"

        rows = sum(
            session.execute(select(func.count()).select_from(m)).scalar_one()
            for m in _MODELS if m is not CacheBinding
        )
        if rows == 0:
            return "empty"
        logger.warning(
            "PCE cache holds {} rows with no recorded PCE; the next ingest will bind it to {} "
            "(org {}). If this appliance was re-pointed, flush the cache first — otherwise the "
            "old estate's data is adopted by the new connection.",
            rows, configured[0], configured[1])
        return "adopting"
