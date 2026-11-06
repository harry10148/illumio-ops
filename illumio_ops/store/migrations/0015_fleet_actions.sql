-- VEN fleet writes (owner: illumio_ops.store.fleet_actions): every enforcement-mode change and every traffic update
-- rate increase, one row per host and attempt — a refused one too, with the PCE's answer. batch_id groups the hosts
-- of one confirmation. Kept per PCE, like the quarantine actions.
CREATE TABLE fleet_actions (
    id            INTEGER PRIMARY KEY,
    pce_url       TEXT NOT NULL,
    org_id        TEXT NOT NULL,
    batch_id      TEXT NOT NULL,
    at            TEXT NOT NULL,
    by_user       TEXT NOT NULL,
    action        TEXT NOT NULL,      -- enforcement | traffic_rate
    workload_href TEXT NOT NULL,
    hostname      TEXT,
    previous_mode TEXT,               -- enforcement: the mode the PCE held right before the write
    target_mode   TEXT,               -- enforcement: the mode written
    result        TEXT NOT NULL,      -- pending | ok | failed | skipped | unknown | refused
    detail        TEXT
);
CREATE INDEX ix_fleet_actions_pce ON fleet_actions (pce_url, org_id, id);
