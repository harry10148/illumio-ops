-- P4 review: a lateral rule realerts when the detection's own severity rises past what the rule last saw of it.
-- Kept per (rule, detection fingerprint) whether or not an alert fired (owner: store.alerts); NULL: not seen yet.
ALTER TABLE alert_rule_state ADD COLUMN seen_severity TEXT;
