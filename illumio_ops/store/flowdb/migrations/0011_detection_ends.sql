-- Every source and target host of a detection, [[role, key, address], ...] (user 2026-10-31: an alert rule can leave
-- detections out by label, Workload, address or public address). NULL: stored before this column, ends unknown.
ALTER TABLE detections ADD COLUMN ends_json TEXT;
