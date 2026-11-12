-- 6.8.0: the addresses of each workload's interfaces as the PCE lists them (a JSON list), so a host can be found by
-- its IP on the VEN overview. NULL: the row predates the column — it is filled at the next inventory read.
ALTER TABLE workloads ADD COLUMN addresses_json TEXT;
