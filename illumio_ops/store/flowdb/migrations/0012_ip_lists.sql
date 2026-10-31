-- The PCE's active IP lists and the networks each covers, exclusions taken out (user 2026-10-31: an alert rule can
-- leave out an IP list). Replaced whole by each inventory run (owner: store.flowdb.ip_lists).
CREATE TABLE ip_lists (
    href        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    fetched_at  TEXT NOT NULL
);
CREATE TABLE ip_list_nets (
    href        TEXT NOT NULL,
    net         TEXT NOT NULL
);
CREATE INDEX ix_ip_list_nets ON ip_list_nets (href);
