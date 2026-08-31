"""The cache must refuse to hold two PCEs' data at once.

Written after 2026-08-30, when the appliance was re-pointed by editing
config/config.json directly: none of `pce_target_changed`'s three call sites ran,
no flush happened, and 11 events from a second PCE landed beside 11,535 from the
first. The edit-time guard cannot see an edit that bypasses it, so this one sits
on the ingest path instead.
"""
from __future__ import annotations

import threading

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import Base, PceEvent
from src.pce_cache.provenance import (
    CacheBinding, CacheTargetMismatch, bind_or_verify, verify_at_startup,
)

LAB = {"url": "https://pce.lab.local:8443", "org_id": "1"}
SAAS = {"url": "https://ap-scp45.illum.io", "org_id": "1"}


@pytest.fixture()
def sf(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cache.sqlite'}")
    Base.metadata.create_all(engine)
    return sessionmaker(engine)


def _seed_event(sf, href="/orgs/1/events/a"):
    from datetime import datetime, timezone
    with sf() as s:
        s.add(PceEvent(pce_href=href, pce_event_id="a", timestamp=datetime.now(timezone.utc),
                       event_type="x", severity="info", status="success",
                       pce_fqdn="pce.lab.local", raw_json="{}",
                       ingested_at=datetime.now(timezone.utc)))
        s.commit()


# ── binding ──────────────────────────────────────────────────────────────────

def test_an_unbound_cache_adopts_the_configured_pce(sf):
    assert bind_or_verify(sf, LAB) == ("https://pce.lab.local:8443", "1")
    with sf() as s:
        assert s.execute(select(func.count()).select_from(CacheBinding)).scalar_one() == 1


def test_the_same_pce_verifies_without_a_second_row(sf):
    bind_or_verify(sf, LAB)
    bind_or_verify(sf, LAB)
    with sf() as s:
        assert s.execute(select(func.count()).select_from(CacheBinding)).scalar_one() == 1


def test_a_different_pce_is_refused_rather_than_blended(sf):
    bind_or_verify(sf, LAB)
    with pytest.raises(CacheTargetMismatch) as e:
        bind_or_verify(sf, SAAS)
    # The operator has to be told which is which and what to do, or the refusal
    # just looks like a malfunction.
    msg = str(e.value)
    assert "pce.lab.local" in msg and "ap-scp45.illum.io" in msg
    assert "flush" in msg.lower()


def test_a_different_org_on_the_same_url_is_also_a_different_pce(sf):
    bind_or_verify(sf, LAB)
    with pytest.raises(CacheTargetMismatch):
        bind_or_verify(sf, {"url": LAB["url"], "org_id": "2"})


def test_rotating_a_credential_is_not_a_re_point(sf):
    bind_or_verify(sf, LAB)
    bind_or_verify(sf, {**LAB, "api_key": "new", "api_secret": "new"})


@pytest.mark.parametrize("variant", [
    "https://pce.lab.local:8443/",      # trailing slash
    "  https://pce.lab.local:8443  ",   # surrounding whitespace
    "HTTPS://PCE.LAB.LOCAL:8443",       # case in scheme and host
])
def test_cosmetic_differences_do_not_fire_the_guard(sf, variant):
    """The same normalization the edit-time guard uses, for the same reason.

    `pce_target.py` records both directions it got wrong before sharing these
    functions: a retyped trailing slash offering to destroy a healthy cache, and
    whitespace comparing equal and then being stored.
    """
    bind_or_verify(sf, LAB)
    bind_or_verify(sf, {"url": variant, "org_id": "1"})


# ── the ingest path actually calls it ────────────────────────────────────────

def test_the_ingest_guard_refuses_a_cache_bound_elsewhere(sf):
    """Guards the wiring, not the function: this is what would have caught 08-30."""
    from src.scheduler.jobs import _guard_cache_target

    class _CM:
        class models:
            class api:
                @staticmethod
                def model_dump():
                    return SAAS

    bind_or_verify(sf, LAB)
    with pytest.raises(CacheTargetMismatch):
        _guard_cache_target(_CM(), sf)


# ── startup advisory ─────────────────────────────────────────────────────────

def test_startup_reports_a_mismatch_without_raising(sf):
    bind_or_verify(sf, LAB)
    assert verify_at_startup(sf, SAAS) == "mismatch"


def test_startup_separates_a_populated_unbound_cache_from_a_fresh_one(sf):
    assert verify_at_startup(sf, LAB) == "empty"
    _seed_event(sf)
    # Populated with no binding is the upgrade case, and the one worth warning
    # about: the next ingest will adopt whatever is configured.
    assert verify_at_startup(sf, LAB) == "adopting"


def test_startup_does_not_bind(sf):
    """Adopting is the ingest path's decision; startup only reports it.

    If this ever binds, the warning it prints becomes a lie — it would be
    describing a decision it had already taken.
    """
    _seed_event(sf)
    verify_at_startup(sf, LAB)
    with sf() as s:
        assert s.execute(select(func.count()).select_from(CacheBinding)).scalar_one() == 0


# ── the flush clears the binding ─────────────────────────────────────────────

def test_flush_clears_the_binding_so_the_next_target_can_be_adopted(tmp_path, sf):
    """Every caller flushes BEFORE writing the new connection.

    So the binding must not survive: it would still name the PCE being left
    behind, and the next ingest would refuse to write into a cache that is
    legitimately empty.
    """
    from src.pce_cache.flush import flush_pce_derived_state

    db = str(tmp_path / "cache.sqlite")
    engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    local = sessionmaker(engine)
    bind_or_verify(local, LAB)

    flush_pce_derived_state(db, str(tmp_path / "state.json"))

    with local() as s:
        assert s.execute(select(func.count()).select_from(CacheBinding)).scalar_one() == 0
    # And the freshly emptied cache accepts the new PCE.
    assert bind_or_verify(local, SAAS) == ("https://ap-scp45.illum.io", "1")


# ── the six findings from Codex's adversarial review of 0449c36b ─────────────
#
# Each of these covers a path the first version got wrong. They are grouped
# here rather than scattered so the next person can see what the review found.

def test_same_pce_rebinds_and_keeps_the_rows(tmp_path):
    """P1-a: the supported 'same-pce' answer must not stop monitoring.

    One PCE reachable at a new address, operator keeps the data. Without a
    rebind the binding still names the old address and every ingest afterwards
    raises — a documented option would silently take monitoring down.
    """
    from src.pce_cache.provenance import rebind

    db = tmp_path / "cache.sqlite"
    engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    local = sessionmaker(engine)
    bind_or_verify(local, LAB)
    _seed_event(local)

    moved = {"url": "https://pce-new.lab.local:8443", "org_id": "1"}
    rebind(str(db), moved)

    # binding followed the address ...
    assert bind_or_verify(local, moved) == ("https://pce-new.lab.local:8443", "1")
    # ... and the cached rows are still there, which is the whole point.
    with local() as s:
        assert s.execute(select(func.count()).select_from(PceEvent)).scalar_one() == 1


def test_rebind_on_a_missing_database_is_not_an_error(tmp_path):
    """Nothing has been cached yet, so there is no binding to move."""
    from src.pce_cache.provenance import rebind
    assert rebind(str(tmp_path / "absent.sqlite"), LAB) == (
        "https://pce.lab.local:8443", "1")


def test_backfill_refuses_a_cache_bound_to_another_pce(sf):
    """P1-b: backfill wrote into the same DB without ever consulting the binding.

    Three supported entry points build a BackfillRunner — the CLI, the HTTP
    endpoint and the legacy menu — so the check lives in its constructor, before
    any write can have started.
    """
    from src.pce_cache.backfill import BackfillRunner

    class _Api:
        api_cfg = SAAS

    bind_or_verify(sf, LAB)
    with pytest.raises(CacheTargetMismatch):
        BackfillRunner(_Api(), sf)


def test_backfill_is_allowed_on_its_own_pce(sf):
    """The other half: the guard must not block the ordinary case."""
    from src.pce_cache.backfill import BackfillRunner

    class _Api:
        api_cfg = LAB

    bind_or_verify(sf, LAB)
    BackfillRunner(_Api(), sf)


def test_two_racing_first_binds_agree(tmp_path):
    """P2-a: events and traffic fire on the same kick from different executors.

    Read-then-insert let both see None and both write id=1; the loser got an
    IntegrityError and its first ingest failed. Insert-on-conflict then re-read
    means whoever wins, both callers return the same answer.
    """
    db = tmp_path / "cache.sqlite"
    engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    local = sessionmaker(engine)

    results, errors = [], []

    def _bind():
        try:
            results.append(bind_or_verify(local, LAB))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_bind) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert errors == [], errors
    assert results == [("https://pce.lab.local:8443", "1")] * 2
    with local() as s:
        assert s.execute(select(func.count()).select_from(CacheBinding)).scalar_one() == 1


def test_startup_sees_a_cache_whose_raw_rows_have_aged_out(sf):
    """P2-c: 'empty' was decided from events + raw only.

    Raw is kept 7 days, aggregates 90. A cache whose raw had aged out but which
    still holds aggregates reported 'empty', skipped the warning, and let the
    next ingest bind a new PCE to the old one's derived data.
    """
    from datetime import datetime, timezone
    from src.pce_cache.models import PceTrafficFlowAgg

    with sf() as s:
        s.add(PceTrafficFlowAgg(bucket_day=datetime(2026, 1, 1, tzinfo=timezone.utc),
                                port=443, protocol="tcp", action="allowed"))
        s.commit()

    assert verify_at_startup(sf, LAB) == "adopting"


def test_the_headless_daemon_reports_provenance_too(monkeypatch):
    """P2-b: the check hung off run_daemon_with_gui, so `--monitor` never ran it.

    Asserted at the shared entry point both daemon shapes go through, because
    that is the property that was missing — not that some function exists.
    """
    from src.cli import _runtime

    called = []
    monkeypatch.setattr(_runtime, "_report_cache_provenance", lambda cm: called.append(cm))
    monkeypatch.setattr(_runtime, "_register_signals", lambda: None)
    monkeypatch.setattr(_runtime, "build_scheduler", lambda *a, **k: None, raising=False)
    _runtime._shutdown_event.set()  # exit the loop immediately

    try:
        _runtime.run_daemon_loop(object(), interval=1)
    except Exception:  # noqa: BLE001 - the stubbed scheduler may bail; the call is the point
        pass
    assert called, "run_daemon_loop must report cache provenance"


def test_the_mismatch_message_only_offers_remedies_that_work():
    """P2-d: the first version's two remedies both failed.

    `cache flush` without --confirm exits on a usage error, and 'Settings → save
    offers a flush' is false in the case that produces this error: after a direct
    config edit the stored value already is the new target, so pce_target_changed
    returns False and nothing is offered.
    """
    msg = str(CacheTargetMismatch(("https://a", "1"), ("https://b", "2")))
    assert "cache flush --confirm" in msg, "the bare command exits with a usage error"
    assert "same-pce" in msg, "the same-address case needs its own instruction"
    # The claim that a plain settings save offers a flush must not come back.
    assert "which offers it" not in msg


def test_the_startup_advisory_never_creates_a_database(tmp_path, monkeypatch):
    """It reports; it must not bring a cache into being.

    Opening an engine creates the file, so a fresh install would be left with an
    empty database by a function whose whole job is to look. Under a MagicMock
    whose db_path stringifies to a Mock repr it went further and wrote 172KB
    files named after the Mock into the repository root — which is how this was
    found, while reading what `git add -A` had staged.
    """
    from unittest.mock import MagicMock

    from src.cli import _runtime

    monkeypatch.chdir(tmp_path)
    cm = MagicMock()
    cm.models.pce_cache.enabled = True
    cm.models.pce_cache.db_path = str(tmp_path / "absent.sqlite")

    _runtime._report_cache_provenance(cm)

    assert list(tmp_path.iterdir()) == [], (
        f"the advisory created files: {[p.name for p in tmp_path.iterdir()]}"
    )


def test_the_startup_advisory_still_reports_on_a_real_cache(tmp_path, monkeypatch):
    """The other half — skipping a missing DB must not skip a present one."""
    from unittest.mock import MagicMock

    from src.cli import _runtime

    db = tmp_path / "cache.sqlite"
    engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    local = sessionmaker(engine)
    bind_or_verify(local, LAB)
    engine.dispose()

    seen = {}
    monkeypatch.setattr("src.pce_cache.provenance.verify_at_startup",
                        lambda sf, cfg: seen.setdefault("called", True) or "match")

    cm = MagicMock()
    cm.models.pce_cache.enabled = True
    cm.models.pce_cache.db_path = str(db)
    _runtime._report_cache_provenance(cm)

    assert seen.get("called"), "a cache that exists must still be reported on"
