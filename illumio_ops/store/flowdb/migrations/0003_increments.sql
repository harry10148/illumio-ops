-- P4: how much each (src, dst, port, proto) grew in one collection write (owner: store.flowdb.flows). The PCE's
-- counts are daily totals (spec §6.6 F12), so a threshold rule adds these up instead of the totals. Rows older
-- than the longest rule window plus margin are deleted as new ones are written.
CREATE TABLE flow_increments (
    id          INTEGER PRIMARY KEY,
    conn_key    TEXT NOT NULL,      -- the tuple's newest primary row, for its dimensions
    observed_at TEXT NOT NULL,      -- when the write that saw the growth ran
    connections INTEGER NOT NULL,   -- growth of the connection count (never negative)
    bytes       INTEGER,            -- growth of bytes in + out; NULL: no byte data
    seconds     REAL NOT NULL,      -- the flow time the growth spans
    late        INTEGER NOT NULL CHECK (late IN (0, 1))
);
CREATE INDEX ix_increments_observed ON flow_increments (observed_at);
