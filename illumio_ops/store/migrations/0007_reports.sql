-- P5a (spec §6.5 報表): every generated or queued report (owner: illumio_ops.store.reports). Manual and scheduled
-- reports are rows of one table and run through one path; the files live under reports/<id>/.
CREATE TABLE reports (
    id            INTEGER PRIMARY KEY,
    report_type   TEXT NOT NULL,
    params_json   TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('queued', 'running', 'done', 'failed')),
    trigger       TEXT NOT NULL CHECK (trigger IN ('manual', 'schedule')),
    schedule_id   TEXT,
    pce_label     TEXT NOT NULL,
    period_start  TEXT NOT NULL,
    period_end    TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    started_at    TEXT,
    finished_at   TEXT,
    error_key     TEXT,
    error_detail  TEXT,
    files_json    TEXT NOT NULL DEFAULT '[]',
    kpis_json     TEXT NOT NULL DEFAULT '[]',
    email_status  TEXT,
    email_detail  TEXT
);
CREATE INDEX ix_reports_status ON reports (status, id);
CREATE INDEX ix_reports_created ON reports (created_at);
