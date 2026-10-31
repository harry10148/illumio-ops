-- P7 SIEM forwarding reads detections after the last id it sent: a plain INTEGER PRIMARY KEY gave the id of a deleted
-- newest detection to the next one, which a cursor had already passed. AUTOINCREMENT needs the table rebuilt (owner:
-- store.flowdb.analysis; no foreign key points at it; same columns, same order — the on-demand copy is SELECT *).
CREATE TABLE detections_new (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    detector        TEXT NOT NULL,
    fingerprint     TEXT NOT NULL,
    subject_key     TEXT NOT NULL,
    severity        TEXT NOT NULL,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL,
    occurrences     INTEGER NOT NULL,
    late            INTEGER NOT NULL CHECK (late IN (0, 1)),
    critical_asset  INTEGER NOT NULL CHECK (critical_asset IN (0, 1)),
    summary_json    TEXT NOT NULL,
    segment_json    TEXT NOT NULL,
    confidence_json TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
INSERT INTO detections_new SELECT * FROM detections;
DROP TABLE detections;
ALTER TABLE detections_new RENAME TO detections;
CREATE INDEX ix_detections_fp ON detections (detector, fingerprint, last_seen);
CREATE INDEX ix_detections_last ON detections (last_seen);
CREATE INDEX ix_detections_subject ON detections (subject_key, last_seen);

-- Each connection (source → destination × port/protocol) the first time it appears in the baseline period, written
-- by live collection once the baseline period is full (owner: store.flowdb.flows). The SIEM's "new connection"
-- source: no connection or byte counts (spec §6.5). Ends and labels as the flow showed them then.
CREATE TABLE new_connection_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    src_key       TEXT NOT NULL,
    dst_key       TEXT NOT NULL,
    port          INTEGER NOT NULL,
    proto         INTEGER NOT NULL,
    decision      TEXT,
    first_seen    TEXT NOT NULL,
    src_ip        TEXT,
    dst_ip        TEXT,
    src_hostname  TEXT,
    dst_hostname  TEXT,
    src_label_set INTEGER,
    dst_label_set INTEGER,
    recorded_at   TEXT NOT NULL
);
CREATE INDEX ix_new_connection_log_recorded ON new_connection_log (recorded_at);
