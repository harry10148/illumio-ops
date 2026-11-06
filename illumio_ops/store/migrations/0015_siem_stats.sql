-- What each SIEM destination sent and failed, in 10-minute buckets (owner: illumio_ops.store.siem): the SIEM page's
-- last hour, 24 hours and 7 days (5.x counted its dispatch rows; v6 forwards by cursor and kept only a running total).
-- bucket: the bucket's start, UTC ISO. sent: lines the destination took (with the cursor's move, or by a DLQ resend).
-- failed: send attempts that raised — once per run a destination fails at its head record, and each record it
-- refused or that could not be formatted. Buckets older than 8 days are deleted by the retention job.
CREATE TABLE siem_stats (
    destination_id TEXT NOT NULL,
    bucket         TEXT NOT NULL,
    sent           INTEGER NOT NULL DEFAULT 0,
    failed         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (destination_id, bucket)
) WITHOUT ROWID;
