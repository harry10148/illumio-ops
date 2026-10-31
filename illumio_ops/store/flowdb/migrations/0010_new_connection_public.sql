-- Whether either end of a logged new connection is a public address (P7 follow-up, user 2026-10-31: a SIEM
-- destination may take east-west connections only). NULL: logged before this column, read as internal.
ALTER TABLE new_connection_log ADD COLUMN public INTEGER;
