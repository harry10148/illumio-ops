-- The PCE's active services (their ports) and label groups (their member labels, sub-groups expanded), for the flow
-- conditions that name them (5.x parity 2026-11-06). Replaced whole by each inventory run (owner:
-- store.flowdb.policy_objects). A NULL port or proto in pce_service_ports means any.
CREATE TABLE pce_services (
    href        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    fetched_at  TEXT NOT NULL
);
CREATE TABLE pce_service_ports (
    href        TEXT NOT NULL,
    port        INTEGER,
    to_port     INTEGER,
    proto       INTEGER
);
CREATE INDEX ix_pce_service_ports ON pce_service_ports (href);
CREATE TABLE label_groups (
    href        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    key         TEXT NOT NULL,
    fetched_at  TEXT NOT NULL
);
CREATE TABLE label_group_members (
    href        TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL
);
CREATE INDEX ix_label_group_members ON label_group_members (href);
