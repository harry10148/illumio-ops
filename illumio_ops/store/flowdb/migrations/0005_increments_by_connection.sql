-- P4: growth is recorded per connection, not per (src, dst, port, proto) (owner: store.flowdb.flows).
-- Each row carries how much of its connection's count has been recorded as growth already; a connection's
-- growth is its total past the largest of these, so a re-pairing that merges or splits connections never
-- counts the same connections twice. NULL: a row written before this; it counts as recorded in full.
ALTER TABLE flows ADD COLUMN counted_connections INTEGER;
ALTER TABLE flows ADD COLUMN counted_bytes INTEGER;
-- An increment names the record it was measured on by record_key, which pairing never rewrites (conn_key it
-- does); its dimensions (decision, process, user) are that connection's. The 0003 rows are dropped: they are
-- at most 26 hours of tuple-level growth.
DROP TABLE flow_increments;
CREATE TABLE flow_increments (
    id          INTEGER PRIMARY KEY,
    record_key  TEXT NOT NULL,      -- the connection's primary row when measured
    observed_at TEXT NOT NULL,      -- when the write that saw the growth ran
    connections INTEGER NOT NULL,   -- growth of the connection count (never negative)
    bytes       INTEGER,            -- growth of bytes in + out; NULL: no byte data
    seconds     REAL NOT NULL,      -- the flow time the growth spans
    late        INTEGER NOT NULL CHECK (late IN (0, 1))
);
CREATE INDEX ix_increments_observed ON flow_increments (observed_at);
