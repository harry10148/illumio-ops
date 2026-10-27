-- P5a review: the PCE a report was queued for (normalized URL and org), so one run after a PCE switch fails
-- instead of reading the new PCE under the old one's name. '' for rows written before this column.
ALTER TABLE reports ADD COLUMN pce_target TEXT NOT NULL DEFAULT '';
