"""Shared harness for the Phase 2B report-shell migration.

``conservation`` is the guard every migration task (T3/T4/T5) uses to prove
that moving an exporter onto the v2 shell rearranged the markup without losing
any narrative text. ``fixtures`` builds one minimal document per HTML report
type so that guard has something real to run against.

This is test-support code, not product code: nothing under ``src/`` imports it.
"""
