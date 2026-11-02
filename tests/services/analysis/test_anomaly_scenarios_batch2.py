"""The second batch end to end (spec §6.5.8 第二批): the store as a run sees it, and run_detection storing exactly the
detection each scenario plants."""
import json
from datetime import timedelta

from illumio_ops.services.analysis.detect import run_detection
from illumio_ops.store.flowdb.db import db_time
from tests.services.analysis.test_anomaly_scenarios import (
    DAY,
    W,
    by_kind,
    flow,
    kinds,
    setup,
)
from tests.services.collect.conftest import NOW

HOUR = NOW.replace(minute=0)


def more(r, *, conns=1, bytes_in=None):
    return type(r)(**{**r.__dict__, "num_connections": conns, "bytes_in": bytes_in,
                      "bytes_out": 0 if bytes_in else None})


def seed(ctx, table, rows):
    with ctx.flows().connect() as conn:
        if table == "src":
            conn.executemany("INSERT INTO source_activity_hourly VALUES (?, ?, 'all', ?, 0, 0)",
                             [(db_time(h), k, n) for h, k, n in rows])
        else:
            conn.executemany("INSERT INTO destination_activity_hourly VALUES (?, ?, ?, ?, ?)",
                             [(db_time(h), k, n, b, 1 if b else 0) for h, k, n, b in rows])
        conn.commit()


def test_scenario_direction_reversal(tmp_path):
    ctx = setup(tmp_path, inventory={"app": {}, "db": {}},
                history=[flow("app", "db", port=5432, minutes_ago=20 * DAY)],
                live=[flow("db", "app", port=8080, minutes_ago=5)])
    run_detection(ctx, now=NOW)
    assert kinds(ctx) == {"direction_reversal"}
    [d] = by_kind(ctx, "direction_reversal")
    assert d["subject_key"] == W + "db" and json.loads(d["summary_json"])["port"] == 8080


def test_scenario_new_pair_port(tmp_path):
    ctx = setup(tmp_path, inventory={"a": {}, "b": {}},
                history=[flow("a", "b", port=8443, minutes_ago=20 * DAY)],
                live=[flow("a", "b", port=4444, minutes_ago=5)])
    run_detection(ctx, now=NOW)
    assert kinds(ctx) == {"new_pair_port"}
    [d] = by_kind(ctx, "new_pair_port")
    assert d["severity"] == "medium" and json.loads(d["summary_json"])["new_listener"] is True


def test_scenario_quiet_host_wakes(tmp_path):
    ctx = setup(tmp_path, inventory={"quiet": {}, "b": {}, "other": {}},
                history=[flow("quiet", "b", port=8080, minutes_ago=20 * DAY)],
                live=[more(flow("quiet", "b", port=8080, minutes_ago=5), conns=150)])
    seed(ctx, "src", [(HOUR - timedelta(days=10), W + "quiet", 4), (HOUR - timedelta(days=14), W + "other", 1)])
    run_detection(ctx, now=NOW)
    assert kinds(ctx) == {"quiet_host_wakes"}
    [d] = by_kind(ctx, "quiet_host_wakes")
    assert d["subject_key"] == W + "quiet" and json.loads(d["summary_json"])["connections"] == 150


def test_scenario_off_hours(tmp_path):
    ctx = setup(tmp_path, inventory={"night": {}, "b": {}},
                history=[flow("night", "b", port=8080, minutes_ago=20 * DAY)],
                live=[more(flow("night", "b", port=8080, minutes_ago=5), conns=120)])
    seed(ctx, "src", [(HOUR.replace(hour=h) - timedelta(days=d), W + "night", 50)
                      for d in range(1, 8) for h in range(1, 10)])
    run_detection(ctx, now=NOW)
    assert kinds(ctx) == {"off_hours"}
    [d] = by_kind(ctx, "off_hours")
    assert d["severity"] == "low" and json.loads(d["summary_json"])["usual_hours"] == "01–09"


def test_scenario_data_staging(tmp_path):
    sources = [f"s{i}" for i in range(6)]
    ctx = setup(tmp_path, inventory={"sink": {}, **{s: {} for s in sources}},
                history=[flow(s, "sink", port=445, minutes_ago=20 * DAY) for s in sources],
                live=[more(flow(s, "sink", port=8443, minutes_ago=5), bytes_in=400 * 2**20) for s in sources])
    seed(ctx, "dst", [(HOUR - timedelta(days=10), W + "sink", 3, 50 * 2**20)])
    run_detection(ctx, now=NOW)
    assert "data_staging" in kinds(ctx)
    [d] = by_kind(ctx, "data_staging")
    s = json.loads(d["summary_json"])
    assert d["subject_key"] == W + "sink" and s["sources"] == 6 and s["mb"] == 2400
