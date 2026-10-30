-- P6d (spec §6.5.1 防堵): every quarantine label put on or taken off, and every attempt the PCE refused (owner:
-- illumio_ops.store.quarantine_actions). original_labels_json: the workload's labels as read right before the write,
-- so a removal can be checked against what was there. Kept per PCE, like the annotations.
CREATE TABLE quarantine_actions (
    id                   INTEGER PRIMARY KEY,
    pce_url              TEXT NOT NULL,
    org_id               TEXT NOT NULL,
    at                   TEXT NOT NULL,
    by_user              TEXT NOT NULL,
    action               TEXT NOT NULL,      -- apply | remove
    workload_href        TEXT NOT NULL,
    hostname             TEXT,
    level                TEXT,               -- the level put on (apply); NULL for a removal
    previous_level       TEXT,
    original_labels_json TEXT NOT NULL,
    result               TEXT NOT NULL,      -- ok | failed | skipped | not_quarantined
    detail               TEXT
);
CREATE INDEX ix_quarantine_actions_workload ON quarantine_actions (pce_url, org_id, workload_href, id);
