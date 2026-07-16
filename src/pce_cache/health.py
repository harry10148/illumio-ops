"""Shared pipeline-health verdict (cache lag + SIEM 1h + DLQ). Used by the
dashboard overview and the integrations overview so thresholds never drift."""


def pipeline_verdict(*, lag_levels, siem_success_1h, denom, dlq,
                     dlq_cap=10000, siem_idle=False):
    """Overall pipeline verdict. siem_idle = SIEM enabled but not moving (no
    enabled destination, or a source has data yet 24h enqueue count is zero) —
    denom=0 "no traffic" and "broken and not sending" must be distinguishable,
    the latter is at least warn (2026-07-16 false-green fix)."""
    lag_err = any(l == "error" for l in (lag_levels or []))
    lag_warn = any(l == "warning" for l in (lag_levels or []))
    if lag_err or (denom and siem_success_1h < 95) or dlq >= int(dlq_cap * 0.8):
        return "error"
    if lag_warn or (denom and siem_success_1h < 99) or dlq > 0 or siem_idle:
        return "warn"
    return "ok"
