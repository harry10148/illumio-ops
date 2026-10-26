-- Which PCE the stored probe result is about: a probe of the previous PCE that answers after a switch
-- is not written, and a stored result of another PCE is never shown as the current one (P2 final
-- review F15; owner: illumio_ops.services.pce_health).
ALTER TABLE pce_probe ADD COLUMN pce_url TEXT NOT NULL DEFAULT '';
ALTER TABLE pce_probe ADD COLUMN org_id TEXT NOT NULL DEFAULT '';
