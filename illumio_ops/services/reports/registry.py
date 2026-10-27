"""The report types this build can generate, what each needs, and the one parameter shape (spec §6.3: a built-in
report stores its type and parameters, so later improvements apply to schedules automatically)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from illumio_ops.domain.report import ReportDocument
from illumio_ops.domain.values import Language, ReportFormat, ReportType
from illumio_ops.services.context import AppContext

Group = Literal["lateral", "inventory", "analysis", "assessment", "operations"]


class ReportParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    report_type: ReportType
    lookback_days: int = Field(default=7, ge=1, le=90)
    lang: Language | None = None  # None: the display language
    formats: tuple[ReportFormat, ...] = (ReportFormat.HTML, ReportFormat.XLSX)

    @field_validator("formats")
    @classmethod
    def _formats(cls, v: tuple[ReportFormat, ...]) -> tuple[ReportFormat, ...]:
        if not v or len(set(v)) != len(v):
            raise ValueError("at least one format, each once")
        return v


@dataclass(frozen=True)
class BuildInput:
    ctx: AppContext
    params: ReportParams
    start: datetime
    end: datetime  # exclusive
    lang: Language
    tz: tzinfo | None
    now: datetime
    pce_label: str


@dataclass(frozen=True)
class ReportSpec:
    report_type: ReportType
    group: Group
    needs_traffic: bool
    build: Callable[[BuildInput], ReportDocument]


REGISTRY: dict[ReportType, ReportSpec] = {}


def _builtin() -> dict[ReportType, ReportSpec]:
    from illumio_ops.services.reports.lateral_posture import build_lateral_posture
    from illumio_ops.services.reports.new_connections import build_new_connections
    from illumio_ops.services.reports.unmanaged import build_unmanaged
    return {
        ReportType.LATERAL_POSTURE: ReportSpec(ReportType.LATERAL_POSTURE, "lateral", True, build_lateral_posture),
        ReportType.NEW_CONNECTIONS: ReportSpec(ReportType.NEW_CONNECTIONS, "analysis", True, build_new_connections),
        ReportType.UNMANAGED_ENDPOINTS: ReportSpec(ReportType.UNMANAGED_ENDPOINTS, "inventory", True, build_unmanaged),
    }


def specs() -> dict[ReportType, ReportSpec]:
    """Every type this build generates (filled on first use: the builders import this module)."""
    if not REGISTRY:
        REGISTRY.update(_builtin())
    return REGISTRY
