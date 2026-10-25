-- P3: lateral-movement analysis (P3 plan Task 2).

-- F10: each record keeps its own byte counts; a connection's bytes (on its primary row) are recomputed
-- from them whenever its records change, so a record that moves to another connection takes its bytes
-- along instead of leaving them counted twice (owner: store.flowdb.flows). Rows of a single-record
-- connection hold their own counts already; rows of a multi-record connection written before this
-- migration stay NULL (own count unknown) and keep their stored bytes.
ALTER TABLE flows ADD COLUMN own_bytes_in INTEGER;
ALTER TABLE flows ADD COLUMN own_bytes_out INTEGER;
UPDATE flows SET own_bytes_in = bytes_in, own_bytes_out = bytes_out
 WHERE conn_key IN (SELECT conn_key FROM flows GROUP BY conn_key HAVING COUNT(*) = 1);

-- The reported decision of each baseline connection's newest observation: the exposure graph is built
-- from the baseline (kept baseline_days in every collection mode) and splits "now" from "all enforced"
-- by it. Filled once from the primary rows still stored; NULL where they are gone.
ALTER TABLE connection_baseline ADD COLUMN last_decision TEXT;
WITH newest AS (
    SELECT src_key, dst_key, COALESCE(port, -1) AS port, proto, policy_decision,
           ROW_NUMBER() OVER (PARTITION BY src_key, dst_key, COALESCE(port, -1), proto
                              ORDER BY last_detected DESC, id DESC) AS rn
      FROM flows WHERE is_primary = 1
)
UPDATE connection_baseline SET last_decision = newest.policy_decision
  FROM newest
 WHERE newest.rn = 1 AND newest.src_key = connection_baseline.src_key
   AND newest.dst_key = connection_baseline.dst_key AND newest.port = connection_baseline.port
   AND newest.proto = connection_baseline.proto;
-- Management-port reads (exposure graph, ransomware overlay). port and the key never change after a
-- row is written, so only new connections add an index entry; last_seen updates do not touch it.
CREATE INDEX ix_baseline_port ON connection_baseline (port);

-- Lateral-movement detections (owner: store.flowdb.analysis). A repeat of a detector's fingerprint
-- within the detector's dedup window updates the row; after a quiet period it is a new row.
CREATE TABLE detections (
    id              INTEGER PRIMARY KEY,
    detector        TEXT NOT NULL,
    fingerprint     TEXT NOT NULL,
    subject_key     TEXT NOT NULL,
    severity        TEXT NOT NULL,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL,
    occurrences     INTEGER NOT NULL,
    late            INTEGER NOT NULL CHECK (late IN (0, 1)),
    critical_asset  INTEGER NOT NULL CHECK (critical_asset IN (0, 1)),
    summary_json    TEXT NOT NULL,
    segment_json    TEXT NOT NULL,
    confidence_json TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX ix_detections_fp ON detections (detector, fingerprint, last_seen);
CREATE INDEX ix_detections_last ON detections (last_seen);
CREATE INDEX ix_detections_subject ON detections (subject_key, last_seen);

-- Each analysis job's progress and outcome, and the latest stored results (owner: store.flowdb.analysis).
CREATE TABLE analysis_runs (
    kind            TEXT PRIMARY KEY,
    watermark       TEXT,
    last_started_at TEXT,
    last_ok_at      TEXT,
    last_error      TEXT,
    status_json     TEXT
);
CREATE TABLE analysis_results (
    kind        TEXT PRIMARY KEY,
    computed_at TEXT NOT NULL,
    params_json TEXT NOT NULL,
    result_json TEXT NOT NULL
);
-- Lateral exposure metrics per day, for trends and period-over-period (spec §6.4).
CREATE TABLE lateral_snapshot_daily (
    day          TEXT PRIMARY KEY,
    metrics_json TEXT NOT NULL
);
-- The focus list's items and when each first appeared ("new this week", "for N weeks").
CREATE TABLE focus_items (
    fingerprint TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    active      INTEGER NOT NULL CHECK (active IN (0, 1)),
    score       REAL NOT NULL,
    item_json   TEXT NOT NULL
);
