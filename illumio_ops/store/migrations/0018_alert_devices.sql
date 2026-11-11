-- The hosts an alert is about (purpose-led UI spec §8): one row per host and role, so "the alerts about this host" is
-- a lookup and not a search through every alert's parameters. A key is a workload href or ip:<address>; names are
-- resolved when read. devices_more: how many more hosts there were than the alert lists (domain.alert_devices).
-- Alerts stored before this are given their hosts at the next start (illumio_ops.store.alerts.backfill_devices).
-- Owner: illumio_ops.store.alerts.
CREATE TABLE alert_devices (
    alert_id INTEGER NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    key      TEXT NOT NULL,
    role     TEXT NOT NULL CHECK (role IN ('source', 'destination', 'subject')),
    PRIMARY KEY (alert_id, key, role)
);
CREATE INDEX ix_alert_devices_key ON alert_devices (key);
ALTER TABLE alerts ADD COLUMN devices_more INTEGER NOT NULL DEFAULT 0;
