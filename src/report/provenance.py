"""Where a report's numbers came from — one place every generator asks.

Covers showed only "Generated" because ReportGenerator.export never passed the
PCE, org or window to the exporter, and the audit / policy-usage / VEN
generators read a ``_pce_url`` attribute nothing ever set. The tool version,
the query filters and the timezone of the window were shown nowhere.
"""
from __future__ import annotations

import datetime
from typing import Any

from src.report.tz_utils import fmt_ts_local, parse_tz

_PD_LABEL = {"allowed": "allowed", "blocked": "blocked",
             "potentially_blocked": "potentially_blocked", "unknown": "unknown"}
_DEFAULT_PDS = {"allowed", "blocked", "potentially_blocked", "unknown"}


def tool_version() -> str:
    try:
        from src import __version__
        return str(__version__)
    except Exception:  # pragma: no cover - packaging edge
        return ""


def pce_identity(cm) -> tuple[str, str]:
    """(PCE URL, org label) from the active config; empty when unknown."""
    config = getattr(cm, "config", None)
    api = config.get("api") if isinstance(config, dict) else None
    if not isinstance(api, dict):
        return "", ""
    url = str(api.get("url", "") or "")
    org = str(api.get("org_id", "") or "")
    return url, (f"org {org}" if org else "")


def report_tz(cm):
    config = getattr(cm, "config", None)
    settings = config.get("settings") if isinstance(config, dict) else None
    tz_str = settings.get("timezone", "local") if isinstance(settings, dict) else "local"
    return parse_tz(tz_str if isinstance(tz_str, str) else "local")


def window_labels(start: str | None, end: str | None, tz) -> tuple[str, str]:
    """Query window bounds rendered in the report timezone (with offset)."""
    return fmt_ts_local(start, tz) if start else "", fmt_ts_local(end, tz) if end else ""


def filters_summary(filters: dict | None, policy_decisions: list | None = None) -> str:
    """Human-readable one-liner of the query filters; '' when unfiltered."""
    parts: list[str] = []
    pds = [p for p in (policy_decisions or []) if p]
    if pds and set(pds) != _DEFAULT_PDS:
        parts.append("policy_decision=" + ",".join(_PD_LABEL.get(p, str(p)) for p in pds))
    for key, value in sorted((filters or {}).items()):
        if key in ("policy_decisions", "requires_draft_pd") or value in (None, "", [], {}):
            continue
        if isinstance(value, (list, tuple, set)):
            value = ",".join(str(v) for v in value)
        elif isinstance(value, dict):
            value = ",".join(f"{k}:{v}" for k, v in value.items())
        parts.append(f"{key}={value}")
    return "; ".join(parts)


def build_provenance(cm, *, source: str, start: str | None = None, end: str | None = None,
                     filters: dict | None = None, policy_decisions: list | None = None) -> dict[str, Any]:
    tz = report_tz(cm)
    url, org = pce_identity(cm)
    w_start, w_end = window_labels(start, end, tz)
    now = datetime.datetime.now(tz)
    return {
        "source": source or "",
        "pce_url": url if source != "csv" else "",
        "org": org if source != "csv" else "",
        "window_start": w_start,
        "window_end": w_end,
        "filters": filters_summary(filters, policy_decisions),
        "tool_version": tool_version(),
        "generated_at": fmt_ts_local(now.isoformat(), tz),
    }
