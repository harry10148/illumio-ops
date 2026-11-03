-- Rule scheduling (UI redesign spec §4.5; owner: illumio_ops.store.rule_schedules). A schedule enables or disables an
-- active rule or rule set of one PCE (pce_url, org_id) by a weekly window or an expiry; one schedule per target.
-- plan_json: domain.rule_schedule Weekly | Expiry. live: the target's enabled state as last read from the PCE.
CREATE TABLE rule_schedules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pce_url         TEXT NOT NULL,
    org_id          TEXT NOT NULL,
    href            TEXT NOT NULL,
    is_ruleset      INTEGER NOT NULL CHECK (is_ruleset IN (0, 1)),
    name            TEXT NOT NULL,
    ruleset_name    TEXT NOT NULL,
    summary         TEXT NOT NULL,
    plan_json       TEXT NOT NULL,
    paused          INTEGER NOT NULL CHECK (paused IN (0, 1)),
    pce_status      TEXT NOT NULL CHECK (pce_status IN ('active', 'deleted', 'unknown')),
    live            TEXT NOT NULL DEFAULT 'unknown' CHECK (live IN ('enabled', 'disabled', 'unknown')),
    last_checked_at TEXT,
    created_by      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE (pce_url, org_id, href)
);
-- What each check did: a switch, a skip, a refusal; kept RUNS_KEEP days (the engine prunes).
CREATE TABLE rule_schedule_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pce_url     TEXT NOT NULL,
    org_id      TEXT NOT NULL,
    schedule_id INTEGER,
    href        TEXT NOT NULL,
    name        TEXT NOT NULL,
    at          TEXT NOT NULL,
    action      TEXT NOT NULL CHECK (action IN ('enable', 'disable', 'expire', 'skip_draft', 'not_found', 'error',
                                                'note', 'note_cleared')),
    result      TEXT NOT NULL CHECK (result IN ('ok', 'failed', 'skipped')),
    status      INTEGER,
    detail      TEXT
);
CREATE INDEX ix_rule_schedule_runs_at ON rule_schedule_runs (pce_url, org_id, at);
