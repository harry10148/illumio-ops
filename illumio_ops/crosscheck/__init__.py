"""Cross-check this system's events, event-rule alerts and report numbers against the PCE's raw data.

Run as `python -m illumio_ops.crosscheck {events|alerts|reports|all} --out DIR`.
Independence: nothing here may import the code it checks; tests/crosscheck/test_boundary.py holds the whitelist.
"""
