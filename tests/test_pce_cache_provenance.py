"""The cache must refuse to hold two PCEs' data at once.

Written after 2026-08-30, when the appliance was re-pointed by editing
config/config.json directly: none of `pce_target_changed`'s three call sites ran,
no flush happened, and 11 events from a second PCE landed beside 11,535 from the
first. The edit-time guard cannot see an edit that bypasses it, so this one sits
on the ingest path instead.
"""
from __future__ import annotations

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
