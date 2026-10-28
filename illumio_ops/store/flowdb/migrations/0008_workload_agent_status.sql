-- P5b-2: what the VEN status report needs from each workload's agent.status. Rows written before this
-- migration read NULL (unknown) until the next inventory run, never "offline" or "in sync".
ALTER TABLE workloads ADD COLUMN agent_status TEXT;
ALTER TABLE workloads ADD COLUMN last_heartbeat_at TEXT;
ALTER TABLE workloads ADD COLUMN policy_sync_state TEXT;
ALTER TABLE workloads ADD COLUMN policy_received_at TEXT;
ALTER TABLE workloads ADD COLUMN policy_applied_at TEXT;
ALTER TABLE workloads ADD COLUMN managed_since TEXT;
ALTER TABLE workloads ADD COLUMN fw_config_current INTEGER;
ALTER TABLE workloads ADD COLUMN agent_health_json TEXT;
