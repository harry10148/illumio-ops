-- P7 SIEM forwarding. Each destination reads each source after the last id it sent (siem_cursor), so a source's ids
-- must never be reused: alerts kept a plain INTEGER PRIMARY KEY, and retention deleting the newest alert gave its id
-- to the next one, which a cursor had already passed. Rebuilding alerts for AUTOINCREMENT would cascade-delete its
-- deliveries and notes (foreign keys are on inside a migration), so the highest id ever used is kept beside it
-- (owner: illumio_ops.store.alerts, which assigns ids above it) and a delete trigger keeps it.
CREATE TABLE alert_id_floor (id INTEGER NOT NULL);
INSERT INTO alert_id_floor (id) SELECT COALESCE(MAX(id), 0) FROM alerts;
CREATE TRIGGER alerts_keep_id_floor AFTER DELETE ON alerts
BEGIN
    UPDATE alert_id_floor SET id = MAX(id, old.id);
END;

-- Where each destination got to in each source (owner: illumio_ops.store.siem). Sources: audit, alerts, detections,
-- new_connections. pce_url/org_id: the PCE whose ids last_id counts — a switch recreates the flow store and its ids
-- start again at 1, so a cursor of another PCE starts over from the newest id. floor_time: reserved for the 5.x
-- cutover (P8: skip what 5.x already sent). head_*: the record at the cursor that keeps failing, and how often it
-- did (after max_retries it goes to the DLQ and the cursor moves on). dropped: records retention deleted before
-- this destination sent them.
CREATE TABLE siem_cursor (
    destination_id TEXT NOT NULL,
    source         TEXT NOT NULL,
    pce_url        TEXT NOT NULL,
    org_id         TEXT NOT NULL,
    last_id        INTEGER NOT NULL,
    floor_time     TEXT,
    head_id        INTEGER,
    head_attempts  INTEGER NOT NULL DEFAULT 0,
    sent           INTEGER NOT NULL DEFAULT 0,
    dropped        INTEGER NOT NULL DEFAULT 0,
    last_sent_at   TEXT,
    last_error     TEXT,
    last_error_at  TEXT,
    PRIMARY KEY (destination_id, source)
) WITHOUT ROWID;

-- Records a destination would not take (owner: illumio_ops.store.siem): the formatted line itself, so a resend does
-- not need the source row (retention may have deleted it).
CREATE TABLE siem_dlq (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    destination_id TEXT NOT NULL,
    source         TEXT NOT NULL,
    record_id      INTEGER NOT NULL,
    external_id    TEXT NOT NULL,
    event_time     TEXT,
    payload        TEXT NOT NULL,
    error          TEXT NOT NULL,
    attempts       INTEGER NOT NULL,
    quarantined_at TEXT NOT NULL
);
CREATE INDEX ix_siem_dlq_dest ON siem_dlq (destination_id, id);
