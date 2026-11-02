-- Anomalies, second batch, review fixes (2026-11-02). Owner: store.flowdb.flows.
-- The hours a live collection cycle ran in. A late re-read fills a collection gap without filling the hourly
-- activity, so an hour no live cycle ran in is unknown activity, not silence (H quiet host, J off-hours).
CREATE TABLE live_activity_hours (
    hour TEXT PRIMARY KEY
) WITHOUT ROWID;
-- G: "had anyone used this port on this host" per candidate, without walking every row of a busy port.
CREATE INDEX ix_baseline_dst_port ON connection_baseline (dst_key, port, proto);
