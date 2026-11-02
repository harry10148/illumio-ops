-- Anomalies, second batch (spec §6.5.8 第二批). Owner: store.flowdb.flows.
-- Each destination's live growth per hour (I, data staging), summed from the same increments as
-- source_activity_hourly: cycles that were not blocked; late and backfill growth is not counted. Not seeded.
CREATE TABLE destination_activity_hourly (
    hour        TEXT NOT NULL,
    dst_key     TEXT NOT NULL,
    connections INTEGER NOT NULL,
    bytes       INTEGER NOT NULL,
    bytes_known INTEGER NOT NULL,   -- increments that carried byte counts
    PRIMARY KEY (hour, dst_key)
) WITHOUT ROWID;
