-- The flow database: everything collected from one PCE (spec §6.4, P2 plan Task 2).
-- Each table's single writing module is named in its comment and in store/ownership.py.
-- Primary-key columns are NOT NULL everywhere: SQLite treats NULLs in a non-INTEGER
-- primary key as distinct, which would silently duplicate rollup and baseline rows.

-- Which PCE this database belongs to; exactly one row (owner: store.flowdb.binding).
CREATE TABLE pce_binding (
    id        INTEGER PRIMARY KEY CHECK (id = 1),
    pce_url   TEXT NOT NULL,
    org_id    TEXT NOT NULL,
    bound_at  TEXT NOT NULL
);

-- Collection progress per source, and windows that failed or were truncated
-- (owner: store.flowdb.ingest_state).
CREATE TABLE ingest_state (
    source               TEXT PRIMARY KEY,
    watermark            TEXT,
    last_started_at      TEXT,
    last_finished_at     TEXT,
    last_ok_at           TEXT,
    last_error           TEXT,
    last_rows            INTEGER,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    progress_json        TEXT
);
CREATE TABLE ingest_gaps (
    id           INTEGER PRIMARY KEY,
    source       TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end   TEXT NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('failed', 'truncated')),
    detail       TEXT,
    recorded_at  TEXT NOT NULL,
    resolved_at  TEXT
);
CREATE INDEX ix_gaps_open ON ingest_gaps (source, resolved_at);

-- Distinct label combinations, shared by flows and workloads (owner: store.flowdb.labels).
CREATE TABLE label_sets (
    id        INTEGER PRIMARY KEY,
    signature TEXT NOT NULL UNIQUE
);
CREATE TABLE label_set_members (
    set_id INTEGER NOT NULL REFERENCES label_sets(id),
    key    TEXT NOT NULL,
    value  TEXT NOT NULL,
    PRIMARY KEY (set_id, key)
);
CREATE INDEX ix_label_members_kv ON label_set_members (key, value);

-- One row per flow record the PCE returned; rows of the same connection share conn_key and
-- exactly one of them has is_primary = 1 (owner: store.flowdb.flows).
CREATE TABLE flows (
    id                INTEGER PRIMARY KEY,
    record_key        TEXT NOT NULL UNIQUE,
    conn_key          TEXT NOT NULL,
    is_primary        INTEGER NOT NULL CHECK (is_primary IN (0, 1)),
    direction         TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    src_ip            TEXT NOT NULL,
    dst_ip            TEXT NOT NULL,
    src_key           TEXT NOT NULL,
    dst_key           TEXT NOT NULL,
    src_href          TEXT,
    dst_href          TEXT,
    src_hostname      TEXT,
    dst_hostname      TEXT,
    src_managed       INTEGER NOT NULL,
    dst_managed       INTEGER NOT NULL,
    src_mode          TEXT,
    dst_mode          TEXT,
    src_label_set     INTEGER REFERENCES label_sets(id),
    dst_label_set     INTEGER REFERENCES label_sets(id),
    port              INTEGER,
    proto             INTEGER NOT NULL,
    initiator_process TEXT,
    initiator_user    TEXT,
    service_process   TEXT,
    service_user      TEXT,
    windows_service   TEXT,
    policy_decision   TEXT NOT NULL,
    first_detected    TEXT NOT NULL,
    last_detected     TEXT NOT NULL,
    num_connections   INTEGER NOT NULL,
    bytes_in          INTEGER,
    bytes_out         INTEGER,
    state             TEXT,
    transmission      TEXT,
    network_href      TEXT,
    origin            TEXT NOT NULL CHECK (origin IN ('ingest', 'backfill')),
    ingested_at       TEXT NOT NULL
);
CREATE INDEX ix_flows_last ON flows (last_detected);
CREATE INDEX ix_flows_conn ON flows (conn_key);
CREATE INDEX ix_flows_primary_last ON flows (is_primary, last_detected);
CREATE INDEX ix_flows_src ON flows (src_key);
CREATE INDEX ix_flows_dst ON flows (dst_key);
CREATE INDEX ix_flows_port ON flows (port, proto);
CREATE INDEX ix_flows_iuser ON flows (initiator_user);
CREATE INDEX ix_flows_iproc ON flows (initiator_process);
CREATE INDEX ix_flows_tuple ON flows (src_ip, dst_ip, port, proto);

CREATE TABLE flow_rollup_daily (
    day                 TEXT NOT NULL,
    src_key             TEXT NOT NULL,
    dst_key             TEXT NOT NULL,
    port                INTEGER NOT NULL,   -- -1 when the flow has no port
    proto               INTEGER NOT NULL,
    policy_decision     TEXT NOT NULL,
    initiator_user      TEXT NOT NULL,      -- '' when unknown
    initiator_process   TEXT NOT NULL,      -- '' when unknown
    connections         INTEGER NOT NULL,
    flow_records        INTEGER NOT NULL,
    bytes_in            INTEGER NOT NULL,
    bytes_out           INTEGER NOT NULL,
    bytes_known_records INTEGER NOT NULL,
    PRIMARY KEY (day, src_key, dst_key, port, proto, policy_decision, initiator_user, initiator_process)
);

CREATE TABLE connection_baseline (
    src_key    TEXT NOT NULL,
    dst_key    TEXT NOT NULL,
    port       INTEGER NOT NULL,
    proto      INTEGER NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    PRIMARY KEY (src_key, dst_key, port, proto)
);
CREATE TABLE user_baseline (
    initiator_user TEXT NOT NULL,
    dst_key        TEXT NOT NULL,
    port           INTEGER NOT NULL,
    proto          INTEGER NOT NULL,
    first_seen     TEXT NOT NULL,
    last_seen      TEXT NOT NULL,
    PRIMARY KEY (initiator_user, dst_key, port, proto)
);

-- PCE audit events (owner: store.flowdb.events).
CREATE TABLE events (
    id                    INTEGER PRIMARY KEY,
    href                  TEXT NOT NULL UNIQUE,
    event_type            TEXT NOT NULL,
    severity              TEXT,
    status                TEXT,
    timestamp             TEXT NOT NULL,
    created_by_kind       TEXT,
    created_by_name       TEXT,
    created_by_href       TEXT,
    workload_href         TEXT,
    tamper_classification TEXT,
    raw_json              TEXT NOT NULL,
    origin                TEXT NOT NULL CHECK (origin IN ('ingest', 'backfill')),
    ingested_at           TEXT NOT NULL
);
CREATE INDEX ix_events_ts ON events (timestamp);
CREATE INDEX ix_events_type_ts ON events (event_type, timestamp);
CREATE INDEX ix_events_wl_ts ON events (workload_href, timestamp);

-- Managed workload inventory and its daily snapshot (owner: store.flowdb.workloads).
CREATE TABLE workloads (
    href             TEXT PRIMARY KEY,
    hostname         TEXT,
    name             TEXT,
    managed          INTEGER NOT NULL,
    enforcement_mode TEXT,
    visibility_level TEXT,
    os_id            TEXT,
    ven_version      TEXT,
    ven_href         TEXT,               -- joins agent events (created_by.ven) to the host
    label_set        INTEGER REFERENCES label_sets(id),
    online           INTEGER,
    risk_exposure    TEXT,
    risk_percent     REAL,
    risk_updated_at  TEXT,
    fetched_at       TEXT NOT NULL
);
CREATE INDEX ix_workloads_ven ON workloads (ven_href);
CREATE TABLE workload_snapshot_daily (
    day              TEXT NOT NULL,
    href             TEXT NOT NULL,
    enforcement_mode TEXT,
    visibility_level TEXT,
    risk_exposure    TEXT,
    risk_percent     REAL,
    PRIMARY KEY (day, href)
);

-- Ransomware protection as the PCE judges it (owner: store.flowdb.ransomware).
CREATE TABLE ransomware_services (
    workload_href     TEXT NOT NULL,
    name              TEXT NOT NULL,
    port              INTEGER NOT NULL,
    proto             INTEGER NOT NULL,
    severity          TEXT,
    category          TEXT,
    protection_state  TEXT,
    port_status       TEXT,
    active_policy     TEXT,
    draft_policy      TEXT,
    recommendation    TEXT,
    source_updated_at TEXT,
    fetched_at        TEXT NOT NULL,
    PRIMARY KEY (workload_href, name, port, proto)
);
CREATE TABLE ransomware_snapshot_daily (
    day              TEXT NOT NULL,
    workload_href    TEXT NOT NULL,
    name             TEXT NOT NULL,
    port             INTEGER NOT NULL,
    proto            INTEGER NOT NULL,
    severity         TEXT,
    protection_state TEXT,
    port_status      TEXT,
    PRIMARY KEY (day, workload_href, name, port, proto)
);
CREATE TABLE org_risk_snapshot_daily (
    day          TEXT PRIMARY KEY,
    summary_json TEXT NOT NULL
);

-- What this PCE / VEN version offers (owner: store.flowdb.capabilities).
CREATE TABLE pce_capabilities (
    name       TEXT PRIMARY KEY,
    state      TEXT NOT NULL CHECK (state IN ('supported', 'unsupported', 'unknown')),
    detail     TEXT,
    checked_at TEXT NOT NULL
);

-- Days written to data/archive (owner: store.flowdb.archive).
CREATE TABLE archive_log (
    kind       TEXT NOT NULL,
    day        TEXT NOT NULL,
    rows       INTEGER NOT NULL,
    path       TEXT NOT NULL,
    written_at TEXT NOT NULL,
    PRIMARY KEY (kind, day)
);
