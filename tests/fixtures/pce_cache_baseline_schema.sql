-- FROZEN baseline: pce_cache schema as shipped on 2026-07-12.
-- Do NOT regenerate when adding model columns — this file simulates an
-- already-deployed old DB so test_schema_drift_guard.py can prove that
-- init_schema upgrades it. Regenerating would defeat the guard.
CREATE TABLE dead_letter (
	id INTEGER NOT NULL, 
	source_table VARCHAR(32) NOT NULL, 
	source_id BIGINT NOT NULL, 
	destination VARCHAR(64) NOT NULL, 
	retries INTEGER NOT NULL, 
	last_error TEXT NOT NULL, 
	payload_preview VARCHAR(512) NOT NULL, 
	quarantined_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE ingestion_cursors (
	consumer VARCHAR(64) NOT NULL, 
	source_table VARCHAR(32) NOT NULL, 
	last_ingested_at DATETIME, 
	last_row_id BIGINT, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (consumer, source_table)
);
CREATE TABLE ingestion_watermarks (
	source VARCHAR(32) NOT NULL, 
	last_timestamp DATETIME, 
	last_href VARCHAR(255), 
	last_sync_at DATETIME, 
	last_status VARCHAR(32), 
	last_error TEXT, 
	PRIMARY KEY (source)
);
CREATE TABLE pce_events (
	id INTEGER NOT NULL, 
	pce_href VARCHAR(255) NOT NULL, 
	pce_event_id VARCHAR(64) NOT NULL, 
	timestamp DATETIME NOT NULL, 
	event_type VARCHAR(128) NOT NULL, 
	severity VARCHAR(32) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	pce_fqdn VARCHAR(255) NOT NULL, 
	raw_json TEXT NOT NULL, 
	ingested_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE pce_traffic_flows_agg (
	id INTEGER NOT NULL, 
	bucket_day DATETIME NOT NULL, 
	src_workload VARCHAR(255), 
	dst_workload VARCHAR(255), 
	port INTEGER NOT NULL, 
	protocol VARCHAR(8) NOT NULL, 
	action VARCHAR(32) NOT NULL, 
	flow_count INTEGER NOT NULL, 
	bytes_total BIGINT NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE pce_traffic_flows_raw (
	id INTEGER NOT NULL, 
	flow_hash VARCHAR(64) NOT NULL, 
	first_detected DATETIME NOT NULL, 
	last_detected DATETIME NOT NULL, 
	src_ip VARCHAR(45) NOT NULL, 
	src_workload VARCHAR(255), 
	dst_ip VARCHAR(45) NOT NULL, 
	dst_workload VARCHAR(255), 
	port INTEGER NOT NULL, 
	protocol VARCHAR(8) NOT NULL, 
	action VARCHAR(32) NOT NULL, 
	flow_count INTEGER NOT NULL, 
	bytes_in BIGINT NOT NULL, 
	bytes_out BIGINT NOT NULL, 
	raw_json TEXT NOT NULL, 
	ingested_at DATETIME NOT NULL, 
	report_json TEXT, 
	PRIMARY KEY (id)
);
CREATE TABLE siem_dispatch (
	id INTEGER NOT NULL, 
	source_table VARCHAR(32) NOT NULL, 
	source_id BIGINT NOT NULL, 
	destination VARCHAR(64) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	retries INTEGER NOT NULL, 
	next_attempt_at DATETIME, 
	last_error TEXT, 
	queued_at DATETIME NOT NULL, 
	sent_at DATETIME, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_agg_unique ON pce_traffic_flows_agg (bucket_day, src_workload, dst_workload, port, protocol, action);
CREATE INDEX ix_dead_letter_destination ON dead_letter (destination);
CREATE INDEX ix_dead_letter_quarantined_at ON dead_letter (quarantined_at);
CREATE INDEX ix_dispatch_pending ON siem_dispatch (status, next_attempt_at);
CREATE INDEX ix_dispatch_queued_at ON siem_dispatch (queued_at);
CREATE INDEX ix_dispatch_sent_at ON siem_dispatch (sent_at);
CREATE INDEX ix_dispatch_source ON siem_dispatch (source_table, source_id);
CREATE INDEX ix_events_ts_type ON pce_events (timestamp, event_type);
CREATE INDEX ix_pce_events_event_type ON pce_events (event_type);
CREATE INDEX ix_pce_events_ingested_at ON pce_events (ingested_at);
CREATE INDEX ix_pce_events_pce_event_id ON pce_events (pce_event_id);
CREATE UNIQUE INDEX ix_pce_events_pce_href ON pce_events (pce_href);
CREATE INDEX ix_pce_events_severity ON pce_events (severity);
CREATE INDEX ix_pce_events_timestamp ON pce_events (timestamp);
CREATE INDEX ix_pce_traffic_flows_agg_action ON pce_traffic_flows_agg (action);
CREATE INDEX ix_pce_traffic_flows_agg_bucket_day ON pce_traffic_flows_agg (bucket_day);
CREATE INDEX ix_pce_traffic_flows_agg_dst_workload ON pce_traffic_flows_agg (dst_workload);
CREATE INDEX ix_pce_traffic_flows_agg_src_workload ON pce_traffic_flows_agg (src_workload);
CREATE INDEX ix_pce_traffic_flows_raw_dst_workload ON pce_traffic_flows_raw (dst_workload);
CREATE UNIQUE INDEX ix_pce_traffic_flows_raw_flow_hash ON pce_traffic_flows_raw (flow_hash);
CREATE INDEX ix_pce_traffic_flows_raw_ingested_at ON pce_traffic_flows_raw (ingested_at);
CREATE INDEX ix_pce_traffic_flows_raw_last_detected ON pce_traffic_flows_raw (last_detected);
CREATE INDEX ix_pce_traffic_flows_raw_src_workload ON pce_traffic_flows_raw (src_workload);
CREATE INDEX ix_raw_last_action ON pce_traffic_flows_raw (last_detected, action);
CREATE INDEX ix_raw_report_json_null ON pce_traffic_flows_raw (last_detected) WHERE report_json IS NULL;
CREATE INDEX ix_siem_dispatch_destination ON siem_dispatch (destination);
CREATE INDEX ix_siem_dispatch_next_attempt_at ON siem_dispatch (next_attempt_at);
CREATE INDEX ix_siem_dispatch_source_table ON siem_dispatch (source_table);
CREATE INDEX ix_siem_dispatch_status ON siem_dispatch (status);
