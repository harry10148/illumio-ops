-- P4: event ids are never reused. Alert evaluation keeps the last evaluated id as its cursor; with a plain
-- INTEGER PRIMARY KEY, retention deleting the highest row gave its id to the next event, which the cursor had
-- already passed. AUTOINCREMENT needs the table rebuilt (owner: store.flowdb.events): a full copy at startup,
-- needing free disk at least the events table's size (spec §5: about 7.5 GB at 1,000 workloads).
CREATE TABLE events_new (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    href                  TEXT NOT NULL UNIQUE,
    event_type            TEXT NOT NULL,
    severity              TEXT,
    status                TEXT,
    timestamp             TEXT NOT NULL,
    created_by_kind       TEXT,
    created_by_name       TEXT,
    created_by_href       TEXT,
    workload_href         TEXT,
    tamper_classification TEXT,
    raw_json              TEXT NOT NULL,
    origin                TEXT NOT NULL CHECK (origin IN ('ingest', 'backfill')),
    ingested_at           TEXT NOT NULL
);
INSERT INTO events_new SELECT * FROM events;
DROP TABLE events;
ALTER TABLE events_new RENAME TO events;
CREATE INDEX ix_events_ts ON events (timestamp);
CREATE INDEX ix_events_type_ts ON events (event_type, timestamp);
CREATE INDEX ix_events_wl_ts ON events (workload_href, timestamp);
