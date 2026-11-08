-- 6.4.3: each VEN's compatibility as the PCE's compatibility report gives it (GET /vens/<id>/compatibility_report);
-- workload agent_health carries no compatibility entries on a real PCE (lab 26.2.20). Kept across inventory runs and
-- read again once a day (owner: store.flowdb.ven_compat). A NULL qualify_status: the PCE has no report for the VEN.
CREATE TABLE ven_compat (
    ven_href        TEXT PRIMARY KEY,
    qualify_status  TEXT,
    issues_json     TEXT NOT NULL,
    report_at       TEXT,
    fetched_at      TEXT NOT NULL
);
