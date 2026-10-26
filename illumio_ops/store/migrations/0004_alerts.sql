-- P4: alert records, their delivery per channel, operator notes, each rule's cooldown and throttle, where each
-- evaluation got to, and each channel's recent failures (owner: illumio_ops.store.alerts). Application state:
-- a PCE switch keeps them; alerts are listed only while their PCE is the configured one (spec §6.4).
CREATE TABLE alerts (
    id                 INTEGER PRIMARY KEY,
    pce_url            TEXT NOT NULL,
    org_id             TEXT NOT NULL,
    rule_id            TEXT NOT NULL,
    rule_type          TEXT NOT NULL,
    rule_name          TEXT NOT NULL,      -- "" for a pack rule shown by its translated pack_key
    pack_key           TEXT,
    severity           TEXT NOT NULL,
    subject_key        TEXT NOT NULL,
    fired_at           TEXT NOT NULL,
    first_seen         TEXT NOT NULL,
    last_seen          TEXT NOT NULL,
    late               INTEGER NOT NULL CHECK (late IN (0, 1)),
    notify             INTEGER NOT NULL CHECK (notify IN (0, 1)),
    grouped_annotation INTEGER,
    message_key        TEXT NOT NULL,
    params_json        TEXT NOT NULL,
    facts_json         TEXT NOT NULL,
    evidence_json      TEXT,
    confidence_json    TEXT NOT NULL
);
CREATE INDEX ix_alerts_pce_fired ON alerts (pce_url, org_id, fired_at);
CREATE INDEX ix_alerts_rule_subject ON alerts (rule_id, subject_key, fired_at);
CREATE TABLE alert_deliveries (
    id              INTEGER PRIMARY KEY,
    alert_id        INTEGER NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    channel         TEXT NOT NULL,         -- a ChannelKind, or "-" for an alert that is not sent
    status          TEXT NOT NULL,
    attempts        INTEGER NOT NULL,
    next_attempt_at TEXT,
    sent_at         TEXT,
    last_error      TEXT
);
CREATE INDEX ix_deliveries_due ON alert_deliveries (status, next_attempt_at);
CREATE INDEX ix_deliveries_alert ON alert_deliveries (alert_id);
CREATE TABLE alert_notes (
    id         INTEGER PRIMARY KEY,
    alert_id   INTEGER NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    body       TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX ix_notes_alert ON alert_notes (alert_id);
CREATE TABLE alert_rule_state (
    rule_id             TEXT NOT NULL,
    subject_key         TEXT NOT NULL,
    last_fired_at       TEXT,
    recent_json         TEXT NOT NULL,
    suppressed_cooldown INTEGER NOT NULL DEFAULT 0,
    suppressed_throttle INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (rule_id, subject_key)
) WITHOUT ROWID;
-- A rule's latest evaluation outcome (ok, no_data, incomplete, collection_off), shown on the rules page.
CREATE TABLE alert_rule_status (
    rule_id      TEXT PRIMARY KEY,
    status       TEXT NOT NULL,
    evaluated_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE alert_eval_state (
    source    TEXT PRIMARY KEY,
    pce_url   TEXT NOT NULL,
    org_id    TEXT NOT NULL,
    watermark TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE channel_state (
    channel              TEXT PRIMARY KEY,
    consecutive_failures INTEGER NOT NULL,
    cooldown_until       TEXT,
    last_error           TEXT,
    last_ok_at           TEXT
) WITHOUT ROWID;
-- Consecutive failures of each job, for the job_failing check (owner: illumio_ops.jobs.health).
ALTER TABLE job_health ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0;
