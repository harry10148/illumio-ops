"""What the Settings › Lateral movement page shows beside the settings: the management ports in effect, the
labels to choose from, and how the analysis is doing."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

from illumio_ops.domain.values import DetectorKind, DetectorState
from illumio_ops.services.analysis.context import load_lateral_context
from illumio_ops.services.context import AppContext
from illumio_ops.store.flowdb import analysis

MAX_LABEL_VALUES = 500  # values listed per label key; more are said to exist


class AdminPortView(BaseModel):
    port: int
    proto: int | None
    name: str | None
    source: Literal["builtin", "pce", "added"]


class LabelChoice(BaseModel):
    key: str
    values: list[str]
    truncated: bool


class DetectorStatusView(BaseModel):
    detector: DetectorKind
    state: DetectorState
    reason_key: str | None
    params: dict[str, Any]


class StaleSelectorView(BaseModel):
    setting: Literal["critical_assets", "admin_groups"]
    key: str
    value: str


class LateralStatus(BaseModel):
    collected: bool
    baseline_days: float
    baseline_required: int
    baseline_backfilling: bool
    observation_days_used: int     # the graph looks back no further than the baseline keeps
    detect_last_ok_at: datetime | None
    detectors: list[DetectorStatusView]  # empty until the first detection run
    exposure_last_ok_at: datetime | None
    stale_selectors: list[StaleSelectorView]


class LateralOverview(BaseModel):
    effective_ports: list[AdminPortView]
    label_choices: list[LabelChoice]
    status: LateralStatus


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def lateral_overview(ctx: AppContext, *, now: datetime | None = None) -> LateralOverview:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    lc = load_lateral_context(ctx, now=at)
    with ctx.flows().connect() as conn:
        detect, exposure = analysis.get_run(conn, "detect"), analysis.get_run(conn, "exposure")
    statuses = json.loads(detect["status_json"]) if detect is not None and detect["status_json"] else {}
    by_key: dict[str, list[str]] = {}
    for k, v in sorted(lc.known_labels):
        by_key.setdefault(k, []).append(v)
    return LateralOverview(
        effective_ports=[AdminPortView(port=e.port, proto=e.proto, name=e.name, source=e.source)
                         for e in lc.admin_ports.entries],
        label_choices=[LabelChoice(key=k, values=vs[:MAX_LABEL_VALUES], truncated=len(vs) > MAX_LABEL_VALUES)
                       for k, vs in sorted(by_key.items())],
        status=LateralStatus(
            collected=lc.collected, baseline_days=round(lc.baseline_days, 1), baseline_required=lc.baseline_required,
            baseline_backfilling=lc.baseline_backfilling,
            observation_days_used=min(lc.settings.observation_days, lc.baseline_required),
            detect_last_ok_at=_when(detect["last_ok_at"]) if detect is not None else None,
            detectors=[DetectorStatusView(detector=DetectorKind(s["detector"]), state=DetectorState(s["state"]),
                                          reason_key=s.get("reason_key"), params=s.get("params") or {})
                       for s in statuses.values()],
            exposure_last_ok_at=_when(exposure["last_ok_at"]) if exposure is not None else None,
            stale_selectors=[StaleSelectorView(setting=s, key=k, value=v) for s, k, v in lc.stale]))
