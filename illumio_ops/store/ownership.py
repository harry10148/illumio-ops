"""Which module may write each table. tests_v6/gates/test_single_writer.py enforces it;
a new table must be registered here before any module can write it."""
from __future__ import annotations

TABLE_OWNERS: dict[str, str] = {
    "job_health": "illumio_ops.jobs.health",
    "pce_probe": "illumio_ops.services.pce_health",
}
