-- P4.5 (spec §6.5.8): detections an operator marked known, per PCE (owner: illumio_ops.store.detection_annotations).
-- Like tamper_annotations, the operator's input: a PCE switch keeps them, and they are listed only while their PCE
-- is the configured one. fingerprint NULL: every detection of this detector about this subject.
CREATE TABLE detection_annotations (
    id          INTEGER PRIMARY KEY,
    pce_url     TEXT NOT NULL,
    org_id      TEXT NOT NULL,
    detector    TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    fingerprint TEXT,
    reason      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    created_by  TEXT NOT NULL
);
