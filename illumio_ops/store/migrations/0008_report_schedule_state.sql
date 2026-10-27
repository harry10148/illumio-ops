-- P5a: when each report schedule last came due (owner: illumio_ops.store.reports). The schedules themselves are
-- settings; whether their reports succeeded is read from the reports table.
CREATE TABLE report_schedule_state (
    schedule_id TEXT PRIMARY KEY,
    last_due    TEXT NOT NULL
) WITHOUT ROWID;
CREATE INDEX ix_reports_schedule ON reports (schedule_id, id);
