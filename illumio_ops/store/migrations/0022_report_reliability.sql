-- 6.16.0 (spec 2026-11-27 report reliability).
-- How many times a report was started: one left running by a stopped service is started again once; the second
-- time it is failed instead (a report that takes the service down must not do so at every start).
ALTER TABLE reports ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
UPDATE reports SET attempts = 1 WHERE status = 'running';  -- left running by the service this upgrade stopped
-- Whether the check on the schedules' reports (alerts: report_failing) has looked at the report. Not a watermark
-- on the id: SQLite gives a deleted newest row's id to the next report. The reports over before this upgrade are
-- not looked at (no alert for an old failure); one still queued or running, or whose email was going out, is.
ALTER TABLE reports ADD COLUMN alert_checked INTEGER NOT NULL DEFAULT 0;
UPDATE reports SET alert_checked = 1 WHERE status IN ('done', 'failed') AND COALESCE(email_status, '') != 'sending';
-- The key numbers of every finished report, kept apart from the report and its files (owner:
-- illumio_ops.store.reports): the next period compares with them after the report itself was deleted or aged out.
-- match_json is what must be the same for two reports to be comparable (the filter and the custom report).
CREATE TABLE report_kpi_history (
    id            INTEGER PRIMARY KEY,
    report_type   TEXT NOT NULL,
    pce_target    TEXT NOT NULL,
    match_json    TEXT NOT NULL,
    period_start  TEXT NOT NULL,
    period_end    TEXT NOT NULL,
    kpis_json     TEXT NOT NULL,
    recorded_at   TEXT NOT NULL,
    -- 1: the report read its whole period; 0: it said some of the period was not collected, pulled or archived;
    -- NULL: not known (a report made before this was recorded)
    complete      INTEGER,
    UNIQUE (report_type, pce_target, match_json, period_start, period_end)
);
CREATE INDEX ix_report_kpi_history_end ON report_kpi_history (report_type, pce_target, period_end);
