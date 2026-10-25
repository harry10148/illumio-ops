-- Background job health: one row per scheduled job (owner: illumio_ops.jobs.health).
CREATE TABLE job_health (
    job_id           TEXT PRIMARY KEY,
    last_started_at  TEXT NOT NULL,
    last_finished_at TEXT,
    last_ok          INTEGER,
    last_error       TEXT,
    runs             INTEGER NOT NULL DEFAULT 0,
    failures         INTEGER NOT NULL DEFAULT 0
);

-- Latest PCE health probe; exactly one row (owner: illumio_ops.services.pce_health).
CREATE TABLE pce_probe (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    checked_at   TEXT NOT NULL,
    results_json TEXT NOT NULL
);
