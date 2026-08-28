from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import DeadLetter, SiemDispatch


@pytest.fixture
def sf(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _seed_dlq(sf, count=3, dest="dest1", days_old=0):
    ts = datetime.now(timezone.utc) - timedelta(days=days_old)
    with sf.begin() as s:
        for i in range(count):
            s.add(DeadLetter(
                source_table="pce_events", source_id=i,
                destination=dest, retries=10,
                last_error="fail", payload_preview="...",
                quarantined_at=ts,
            ))


def test_dlq_list_entries(sf):
    from src.siem.dlq import DeadLetterQueue
    _seed_dlq(sf, count=3)
    dlq = DeadLetterQueue(sf)
    entries = dlq.list_entries("dest1")
    assert len(entries) == 3


def test_dlq_replay_creates_dispatch_rows(sf):
    from src.siem.dlq import DeadLetterQueue
    _seed_dlq(sf, count=2)
    dlq = DeadLetterQueue(sf)
    count = dlq.replay("dest1", limit=10)
    assert count == 2
    with sf() as s:
        rows = s.execute(select(SiemDispatch)).scalars().all()
    assert len(rows) == 2
    assert all(r.status == "pending" for r in rows)


def test_dlq_replay_deletes_entries_and_is_not_double_forwarded(sf):
    """Regression: replay() must remove the DeadLetter rows it requeues so the
    queue reflects reality and a second replay can't re-enqueue the same records."""
    from src.siem.dlq import DeadLetterQueue
    _seed_dlq(sf, count=2)
    dlq = DeadLetterQueue(sf)

    assert dlq.replay("dest1", limit=10) == 2
    with sf() as s:
        assert s.execute(select(DeadLetter)).scalars().all() == []  # entries gone

    # Second replay is a no-op — no duplicate dispatch rows.
    assert dlq.replay("dest1", limit=10) == 0
    with sf() as s:
        dispatch_rows = s.execute(select(SiemDispatch)).scalars().all()
    assert len(dispatch_rows) == 2


def test_dlq_replay_ids_deletes_and_is_idempotent(sf):
    """Regression: replay_ids() deletes the replayed entry, so a repeat call
    reports 'not found' instead of enqueuing a duplicate dispatch row."""
    from src.siem.dlq import DeadLetterQueue
    _seed_dlq(sf, count=2)
    with sf() as s:
        ids = [e.id for e in s.execute(select(DeadLetter)).scalars().all()]

    dlq = DeadLetterQueue(sf)
    res1 = dlq.replay_ids(ids)
    assert all(r["ok"] for r in res1)
    with sf() as s:
        assert s.execute(select(DeadLetter)).scalars().all() == []

    res2 = dlq.replay_ids(ids)
    assert all((not r["ok"] and r["error"] == "not found") for r in res2)
    with sf() as s:
        dispatch_rows = s.execute(select(SiemDispatch)).scalars().all()
    assert len(dispatch_rows) == 2  # second replay added nothing


def test_dlq_purge_removes_old_entries(sf):
    from src.siem.dlq import DeadLetterQueue
    _seed_dlq(sf, count=3, days_old=60)
    _seed_dlq(sf, count=1, days_old=0)
    dlq = DeadLetterQueue(sf)
    removed = dlq.purge("dest1", older_than_days=30)
    assert removed == 3
    with sf() as s:
        remaining = s.execute(select(DeadLetter)).scalars().all()
    assert len(remaining) == 1


# ── Task 12 (#8): the GUI's "All destinations" filter carries "" ─────────────
#
# list_entries("") used to filter on `destination == ""`, which matches no
# real row — so the DLQ page's DEFAULT view showed nothing at all, and the
# purge issued from it silently removed 0 entries. dlq_export
# (src/siem/web.py) already reads a blank dest as "every destination"; these
# pin list_entries to the same reading, and pin replay() to NOT inherit it.


def test_dlq_list_entries_blank_destination_lists_every_destination(sf):
    from src.siem.dlq import DeadLetterQueue
    _seed_dlq(sf, count=2, dest="dest1")
    _seed_dlq(sf, count=3, dest="dest2")
    dlq = DeadLetterQueue(sf)

    entries = dlq.list_entries("")
    assert len(entries) == 5
    assert {e.destination for e in entries} == {"dest1", "dest2"}
    # A named destination still narrows, exactly as before.
    assert len(dlq.list_entries("dest1")) == 2


def test_dlq_replay_blank_destination_stays_a_no_op(sf):
    """replay() reads its rows through list_entries(), so widening list_entries
    must not turn a blank dest into "requeue the entire DLQ". Both callers
    (POST /api/siem/dlq/replay's dest branch, `siem replay --dest`) are
    destination-scoped; a blank one is a caller mistake, not a mass replay."""
    from src.siem.dlq import DeadLetterQueue
    _seed_dlq(sf, count=2, dest="dest1")
    _seed_dlq(sf, count=3, dest="dest2")
    dlq = DeadLetterQueue(sf)

    assert dlq.replay("", limit=100) == 0
    with sf() as s:
        assert s.execute(select(SiemDispatch)).scalars().all() == []
        assert len(s.execute(select(DeadLetter)).scalars().all()) == 5


def test_dlq_purge_ids_removes_only_the_given_ids(sf):
    """purge_ids() is the symmetric twin of replay_ids(): the operator ticks
    rows and exactly those rows go, whatever their destination or age."""
    from src.siem.dlq import DeadLetterQueue
    _seed_dlq(sf, count=2, dest="dest1")
    _seed_dlq(sf, count=2, dest="dest2")
    with sf() as s:
        rows = s.execute(select(DeadLetter).order_by(DeadLetter.id)).scalars().all()
        picked = [rows[0].id, rows[2].id]
        survivors = {rows[1].id, rows[3].id}

    results = DeadLetterQueue(sf).purge_ids(picked)
    assert results == [{"id": picked[0], "ok": True}, {"id": picked[1], "ok": True}]
    with sf() as s:
        left = s.execute(select(DeadLetter)).scalars().all()
    assert {e.id for e in left} == survivors


def test_dlq_purge_ids_reports_an_id_that_is_already_gone(sf):
    """Same per-item shape as replay_ids: a row someone else already purged
    comes back {ok: False, error: "not found"} instead of vanishing into a
    count that would tell the operator nothing."""
    from src.siem.dlq import DeadLetterQueue
    _seed_dlq(sf, count=1, dest="dest1")
    with sf() as s:
        only_id = s.execute(select(DeadLetter)).scalars().one().id

    dlq = DeadLetterQueue(sf)
    assert dlq.purge_ids([only_id]) == [{"id": only_id, "ok": True}]
    assert dlq.purge_ids([only_id]) == [
        {"id": only_id, "ok": False, "error": "not found"}
    ]


# ── the same two fixes at the HTTP boundary ─────────────────────────────────


@pytest.fixture
def dlq_client(tmp_path):
    """Flask test client whose pce_cache DB is a pre-seeded temp file.

    Same shape as tests/test_siem_dlq_export.py's fixture — the DLQ routes
    reach their rows through _get_sf(), which reads
    CM.models.pce_cache.db_path, so the config has to point at the seeded DB.
    """
    import json
    import os
    import tempfile

    from sqlalchemy import create_engine
    from src.config import ConfigManager
    from src.pce_cache.schema import init_schema

    db_path = str(tmp_path / "cache.sqlite")
    engine = create_engine(f"sqlite:///{db_path}")
    init_schema(engine)
    seeded = sessionmaker(engine)
    _seed_dlq(seeded, count=2, dest="demo")
    _seed_dlq(seeded, count=1, dest="other")

    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, "w") as f:
            json.dump({
                "web_gui": {"username": "admin", "password": "pw",
                            "secret_key": "s", "allowed_ips": ["127.0.0.1"]},
                "pce_cache": {"enabled": True, "db_path": db_path},
            }, f)
        cm = ConfigManager(config_file=path)
        from src.gui import _create_app
        app = _create_app(cm, persistent_mode=True)
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        with app.test_client() as c:
            c.post("/api/login", json={"username": "admin", "password": "pw"},
                   environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
            yield c, seeded
    finally:
        os.unlink(path)


def test_list_dlq_endpoint_blank_dest_returns_every_destination(dlq_client):
    """GET /api/siem/dlq with no dest is what the GUI's default "All" filter
    sends (system.mjs builds `dest=` + encodeURIComponent("")). It used to
    answer an empty list."""
    client, _ = dlq_client
    body = client.get("/api/siem/dlq?dest=",
                      environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert len(body["entries"]) == 3
    assert {e["destination"] for e in body["entries"]} == {"demo", "other"}


def test_purge_dlq_endpoint_ids_branch_removes_only_those_ids(dlq_client):
    """POST /api/siem/dlq/purge {ids: [...]} purges exactly those rows —
    the branch the "Purge Selected" button now uses. The dest branch is
    untouched and still answers a plain count."""
    client, seeded = dlq_client
    with seeded() as s:
        rows = s.execute(select(DeadLetter).order_by(DeadLetter.id)).scalars().all()
    picked = [rows[0].id]
    survivors = {r.id for r in rows[1:]}

    body = client.post("/api/siem/dlq/purge", json={"ids": picked},
                       environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert body == {"status": "ok", "removed": [{"id": picked[0], "ok": True}]}
    with seeded() as s:
        left = s.execute(select(DeadLetter)).scalars().all()
    assert {e.id for e in left} == survivors

    # dest branch unchanged: still a count, still destination-scoped.
    body = client.post("/api/siem/dlq/purge",
                       json={"dest": "other", "older_than_days": 0},
                       environ_overrides={"REMOTE_ADDR": "127.0.0.1"}).get_json()
    assert body == {"status": "ok", "removed": 1}
