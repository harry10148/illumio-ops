-- P6e (spec §6.5.5): custom reports, made of sections saved from the workbench (owner:
-- illumio_ops.store.custom_reports). sections_json: [{title, segment}] where a segment is an analysis segment without
-- its period (the report's period is given when it is made). The operator's input, kept across a PCE switch like the
-- schedules that use them.
CREATE TABLE custom_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,  -- never reused: a queued request names its report by id
    name          TEXT NOT NULL,
    sections_json TEXT NOT NULL,
    created_by    TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
