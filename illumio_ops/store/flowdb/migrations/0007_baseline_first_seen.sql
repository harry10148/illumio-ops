-- P5a: the new-connections report reads the baseline by when each connection first appeared. Only a new
-- connection adds an index entry (first_seen moves only earlier, and only when a backfill finds older traffic).
CREATE INDEX ix_baseline_first ON connection_baseline (first_seen);
