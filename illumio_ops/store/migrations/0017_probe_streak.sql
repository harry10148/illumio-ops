-- How many probes in a row have failed, ending with the stored one (0 when it passed): the PCE health alert waits
-- for a second one, as a PCE that reports itself unhealthy for a minute or two is not news (lab 2026-11-08; owner:
-- illumio_ops.services.pce_health).
ALTER TABLE pce_probe ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0;
