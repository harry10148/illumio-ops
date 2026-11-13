-- 6.10.0: whether each host of a day's snapshot was managed (had a VEN), as the inventory said that day. The security
-- risk report reads from it what share of the managed hosts was enforced on the last day of the previous period.
-- NULL: the row was written before this column. Such a day cannot be compared; it is never read as "not managed".
ALTER TABLE workload_snapshot_daily ADD COLUMN managed INTEGER;
