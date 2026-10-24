"""Which module may write each table, across both databases (table names are unique between
them). tests_v6/gates/test_single_writer.py enforces it; a new table must be registered here
before any module can write it."""
from __future__ import annotations

TABLE_OWNERS: dict[str, str] = {
    # data/app.sqlite
    "job_health": "illumio_ops.jobs.health",
    "pce_probe": "illumio_ops.services.pce_health",
    # data/flows.sqlite
    "pce_binding": "illumio_ops.store.flowdb.binding",
    "ingest_state": "illumio_ops.store.flowdb.ingest_state",
    "ingest_gaps": "illumio_ops.store.flowdb.ingest_state",
    "label_sets": "illumio_ops.store.flowdb.labels",
    "label_set_members": "illumio_ops.store.flowdb.labels",
    "flows": "illumio_ops.store.flowdb.flows",
    "flow_rollup_daily": "illumio_ops.store.flowdb.flows",
    "connection_baseline": "illumio_ops.store.flowdb.flows",
    "user_baseline": "illumio_ops.store.flowdb.flows",
    "events": "illumio_ops.store.flowdb.events",
    "workloads": "illumio_ops.store.flowdb.workloads",
    "workload_snapshot_daily": "illumio_ops.store.flowdb.workloads",
    "ransomware_services": "illumio_ops.store.flowdb.ransomware",
    "ransomware_snapshot_daily": "illumio_ops.store.flowdb.ransomware",
    "org_risk_snapshot_daily": "illumio_ops.store.flowdb.ransomware",
    "pce_capabilities": "illumio_ops.store.flowdb.capabilities",
    "archive_log": "illumio_ops.store.flowdb.archive",
}
