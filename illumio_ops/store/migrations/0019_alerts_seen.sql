-- When the alerts page was last opened (purpose-led UI spec §6.1): alerts fired after it are "new". One row for the
-- installation — it has one sign-in account, so one person opening the page is everyone having seen it. It starts
-- at the moment of this migration: an upgrade does not call the whole history new.
-- Owner: illumio_ops.store.alerts.
CREATE TABLE alerts_seen (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    seen_at TEXT NOT NULL
);
INSERT INTO alerts_seen (id, seen_at) VALUES (1, strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00');
