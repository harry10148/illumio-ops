"""Read-only database access, the PCE client, and the two output files. Nothing here prints."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

from illumio_ops.crosscheck.model import STATUSES, Finding
from illumio_ops.pce.client import PceClient, client_from_settings
from illumio_ops.pce.rate_limit import RateLimiter
from illumio_ops.settings.schema import Settings

AREA_ORDER = ("events", "alerts", "reports")


def open_ro(path: Path) -> sqlite3.Connection:
    """The database at `path`, opened read-only (`mode=ro`): a write raises sqlite3.OperationalError, a missing
    file is an error rather than a new empty database, and no migration ever runs (store.db.connect may migrate)."""
    conn = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def pce(settings: Settings) -> PceClient:
    """A read client on the configured key, with a budget of its own. The service runs meanwhile and spends the
    configured rate itself, so this takes half of it; PceNotConfigured when the connection is not filled in."""
    limiter = RateLimiter(max(settings.collection.rate_limit_per_minute // 2, 1))
    return client_from_settings(settings.pce, rate_limiter=limiter)


def _areas(findings: Sequence[Finding]) -> list[str]:
    seen = {f.area for f in findings}
    return [a for a in AREA_ORDER if a in seen] + sorted(seen - set(AREA_ORDER))


def _sample_lines(sample: Any) -> list[str]:
    if sample is None:
        return []
    items = sample if isinstance(sample, list) else [sample]
    # Every sample item is written in full: a check bounds how many it gives, this never cuts them.
    return [f"  - `{json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)}`" for item in items]


def _counts(findings: Sequence[Finding]) -> dict[str, int]:
    return {s: sum(1 for f in findings if f.status == s) for s in STATUSES}


def render(findings: Sequence[Finding], meta: Mapping[str, Any]) -> str:
    counts = _counts(findings)
    lines = [
        "# Cross-check against the PCE",
        "",
        f"- Period (UTC): {meta.get('period_start', '?')} to {meta.get('period_end', '?')}",
        f"- PCE: {meta.get('pce_url', '?')} (org {meta.get('org_id', '?')})",
        f"- illumio-ops version: {meta.get('version', '?')}",
    ]
    for key, label in (("command", "Command"), ("generated_at", "Generated at (UTC)")):
        if key in meta:
            lines.append(f"- {label}: {meta[key]}")
    lines += ["", "Totals: " + ", ".join(f"{s} {counts[s]}" for s in STATUSES),
              "", "`unchecked` means the item could not be compared; it is not a pass.", ""]
    limits = list(meta.get("limitations", []))
    if limits:
        lines += ["## Limitations", ""] + [f"- {x}" for x in limits] + [""]
    for area in _areas(findings):
        mine = [f for f in findings if f.area == area]
        lines += [f"## {area}", ""]
        for status in ("inconsistent", "unchecked"):
            group = [f for f in mine if f.status == status]
            if not group:
                continue
            lines += [f"### {status} ({len(group)})", ""]
            for f in group:
                lines.append(f"- **{f.item}**: {f.detail}")
                lines += _sample_lines(f.sample)
            lines.append("")
        agreed = [f for f in mine if f.status == "consistent"]
        lines += [f"### consistent: {len(agreed)}", ""]
        if agreed:
            lines += [f"- {f.item}: {f.detail}" if f.detail else f"- {f.item}" for f in agreed] + [""]
    return "\n".join(lines).rstrip("\n") + "\n"


def write(out: Path, findings: Sequence[Finding], meta: Mapping[str, Any]) -> None:
    """findings.json (for programs) and report.md (for people) in `out`, which must exist."""
    data = {"meta": dict(meta), "counts": _counts(findings), "findings": [asdict(f) for f in findings]}
    (out / "findings.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n",
                                       encoding="utf-8")
    (out / "report.md").write_text(render(findings, meta), encoding="utf-8")
