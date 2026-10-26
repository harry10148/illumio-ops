-- An operator's known causes for tampering, per PCE (owner: illumio_ops.store.annotations). Application state,
-- so a PCE switch keeps them; they are listed only while their PCE is the configured one.
CREATE TABLE tamper_annotations (
    id         INTEGER PRIMARY KEY,
    pce_url    TEXT NOT NULL,
    org_id     TEXT NOT NULL,
    host_href  TEXT,
    pattern    TEXT,
    process    TEXT,
    reason     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL
);
