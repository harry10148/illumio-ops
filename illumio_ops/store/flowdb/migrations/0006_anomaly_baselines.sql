-- P4.5: anomalies in allowed traffic (spec §6.5.8). Owner of every table here: store.flowdb.flows.

-- Peer-group reads ask "which destinations did these sources use on this port": (port, src_key) serves them, and
-- the exposure graph's reads by port use its prefix as they used ix_baseline_port.
DROP INDEX ix_baseline_port;
CREATE INDEX ix_baseline_port_src ON connection_baseline (port, src_key);

-- Which source hosts each account started connections from (C). account is account_key(initiator_user).
CREATE TABLE account_source_baseline (
    account    TEXT NOT NULL,
    src_key    TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    PRIMARY KEY (account, src_key)
) WITHOUT ROWID;
-- Which processes started connections on each host (D), as normalize_process names them.
CREATE TABLE process_baseline (
    src_key    TEXT NOT NULL,
    process    TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    PRIMARY KEY (src_key, process)
) WITHOUT ROWID;
-- Each source's live growth per hour (B, E③), summed from the increments of collection cycles that were not
-- blocked: 'all' ports and the built-in 'directory' ports. Late (daily re-read) and backfill growth is not
-- counted. Kept 8 days; not seeded (the increments it is made of are kept 26 hours).
CREATE TABLE source_activity_hourly (
    hour        TEXT NOT NULL,
    src_key     TEXT NOT NULL,
    port_class  TEXT NOT NULL CHECK (port_class IN ('all', 'directory')),
    connections INTEGER NOT NULL,
    bytes       INTEGER NOT NULL,
    bytes_known INTEGER NOT NULL,   -- increments that carried byte counts
    PRIMARY KEY (hour, src_key, port_class)
) WITHOUT ROWID;

-- The two baselines start from the daily rollups (kept longer than the baseline period), a day at a time.
INSERT INTO account_source_baseline (account, src_key, first_seen, last_seen)
SELECT CASE WHEN instr(initiator_user, '\') > 0 OR instr(initiator_user, '@') > 0 THEN lower(initiator_user)
            ELSE initiator_user END AS account,
       src_key, MIN(day) || 'T00:00:00.000+00:00', MAX(day) || 'T23:59:59.000+00:00'
  FROM flow_rollup_daily WHERE initiator_user <> '' GROUP BY 1, 2;
INSERT INTO process_baseline (src_key, process, first_seen, last_seen)
SELECT src_key, initiator_process, MIN(day) || 'T00:00:00.000+00:00', MAX(day) || 'T23:59:59.000+00:00'
  FROM flow_rollup_daily WHERE initiator_process <> '' GROUP BY 1, 2;
