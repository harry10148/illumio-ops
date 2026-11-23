-- New schedules are draft-only by default. Existing schedules keep their former provision-on-change behaviour.
-- Owner: illumio_ops.store.rule_schedules.
ALTER TABLE rule_schedules ADD COLUMN provision INTEGER NOT NULL DEFAULT 1 CHECK (provision IN (0, 1));
ALTER TABLE rule_schedules ADD COLUMN last_want INTEGER CHECK (last_want IN (0, 1) OR last_want IS NULL);
ALTER TABLE rule_schedules ADD COLUMN draft_live TEXT NOT NULL DEFAULT 'unknown'
    CHECK (draft_live IN ('enabled', 'disabled', 'unknown'));

DROP INDEX ix_rule_schedule_runs_at;
ALTER TABLE rule_schedule_runs RENAME TO rule_schedule_runs_old;
CREATE TABLE rule_schedule_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pce_url     TEXT NOT NULL,
    org_id      TEXT NOT NULL,
    schedule_id INTEGER,
    href        TEXT NOT NULL,
    name        TEXT NOT NULL,
    at          TEXT NOT NULL,
    action      TEXT NOT NULL CHECK (action IN ('enable', 'disable', 'expire', 'draft_enable', 'draft_disable',
                                                'draft_expire', 'skip_draft', 'not_found', 'error', 'note',
                                                'note_cleared')),
    result      TEXT NOT NULL CHECK (result IN ('ok', 'failed', 'skipped')),
    status      INTEGER,
    detail      TEXT
);
INSERT INTO rule_schedule_runs SELECT * FROM rule_schedule_runs_old;
DROP TABLE rule_schedule_runs_old;
CREATE INDEX ix_rule_schedule_runs_at ON rule_schedule_runs (pce_url, org_id, at);
