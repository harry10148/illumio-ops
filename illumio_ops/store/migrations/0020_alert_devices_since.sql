-- Since when alerts record the hosts they are about (0018): the moment this is applied. Alerts older than this were
-- given their hosts where they could be read back (backfill_devices); those that could not (a count rule's, a
-- traffic rule's) are missing from "the alerts about this host", and a page that counts them says since when.
-- Owner: illumio_ops.store.alerts.
CREATE TABLE alert_devices_since (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    at TEXT NOT NULL
);
INSERT INTO alert_devices_since (id, at) VALUES (1, strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00');
