"""The report types this build can generate, what each needs, and the one parameter shape (spec §6.3: a built-in
report stores its type and parameters, so later improvements apply to schedules automatically)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from illumio_ops.domain.filter import FlowCondition
from illumio_ops.domain.report import ReportDocument
from illumio_ops.domain.values import Language, ReportFormat, ReportType
from illumio_ops.services.context import AppContext
from illumio_ops.settings.schema import Settings

Group = Literal["lateral", "inventory", "analysis", "assessment", "policy", "operations"]


class ReportParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    report_type: ReportType
    lookback_days: int = Field(default=7, ge=1, le=90)
    lang: Language | None = None  # None: the display language
    formats: tuple[ReportFormat, ...] = (ReportFormat.HTML, ReportFormat.XLSX)
    filter: FlowCondition | None = None  # flow reports only: e.g. one app (labels), as the workbench filters
    email: bool = False
    recipients: tuple[str, ...] = Field(default=(), max_length=50)  # empty: the SMTP channel's recipients

    @field_validator("recipients")
    @classmethod
    def _addresses(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        out = tuple(a.strip() for a in v)
        if any("@" not in a or any(c in a for c in "\r\n,; ") for a in out):
            raise ValueError("every recipient must be one email address")
        return out

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
    max_lookback: Callable[[Settings], int] | None = None  # the most days back the report's data reaches
    requires_app: bool = False  # the filter must name an app label (one application's report)
    accepts_filter: bool = False  # the report reads ReportParams.filter (flow reports); others refuse one
    retention: Callable[[Settings], int] | None = None  # days its data is kept: the period may not start earlier
    # On demand (spec §6.4): how far before the period the pull starts (a baseline the report compares with),
    # and a step run on the pulled store before the build (an analysis the report reads instead of computing).
    ondemand_lead: Callable[[Settings], timedelta] | None = None
    ondemand_prepare: Callable[[AppContext, datetime], None] | None = None


REGISTRY: dict[ReportType, ReportSpec] = {}


# A period the install does not keep is pulled from the PCE (spec §6.4); the PCE keeps traffic only so long
# (how long varies by PCE), and the report says where its answer starts. The lookback offered is the request's own
# limit (90 days); the floor is two days more, so a period starting at a local midnight, across a DST change,
# is never refused for an hour.
ONDEMAND_LOOKBACK = 90
POLICY_USAGE_MAX_DAYS = 30


def flow_retention(settings: Settings) -> int:
    """The flow reports read the flows table, kept flow_days back from now, or pull an older period on demand."""
    return max(settings.collection.retention.flow_days, ONDEMAND_LOOKBACK + 2)


def flow_days(settings: Settings) -> int:
    """The lookback the flow reports offer: a period starts at a calendar midnight, so it reaches back at most
    flow_days - 1 whole days of the kept traffic, and at least ONDEMAND_LOOKBACK days pulled on demand."""
    return max(settings.collection.retention.flow_days - 1, ONDEMAND_LOOKBACK)


def baseline_lead(settings: Settings) -> timedelta:
    return timedelta(days=settings.collection.retention.baseline_days)


def _prepare_exposure(ctx: AppContext, now: datetime) -> None:
    from illumio_ops.services.analysis.exposure import run_exposure
    run_exposure(ctx, now=now)


def _builtin() -> dict[ReportType, ReportSpec]:
    from illumio_ops.services.reports.app_summary import build_app_summary
    from illumio_ops.services.reports.audit import build_audit
    from illumio_ops.services.reports.lateral_posture import build_lateral_posture
    from illumio_ops.services.reports.network_inventory import build_network_inventory
    from illumio_ops.services.reports.new_connections import build_new_connections
    from illumio_ops.services.reports.policy_usage import build_policy_usage
    from illumio_ops.services.reports.ransomware_report import build_ransomware
    from illumio_ops.services.reports.readiness import build_readiness
    from illumio_ops.services.reports.security_risk import build_security_risk
    from illumio_ops.services.reports.traffic import build_traffic
    from illumio_ops.services.reports.unmanaged import build_unmanaged
    from illumio_ops.services.reports.ven_status import build_ven_status
    return {
        ReportType.LATERAL_POSTURE: ReportSpec(ReportType.LATERAL_POSTURE, "lateral", True, build_lateral_posture,
                                               ondemand_lead=baseline_lead, ondemand_prepare=_prepare_exposure),
        ReportType.NEW_CONNECTIONS: ReportSpec(ReportType.NEW_CONNECTIONS, "analysis", True, build_new_connections,
                                               ondemand_lead=baseline_lead),
        ReportType.UNMANAGED_ENDPOINTS: ReportSpec(ReportType.UNMANAGED_ENDPOINTS, "inventory", True, build_unmanaged),
        ReportType.TRAFFIC: ReportSpec(ReportType.TRAFFIC, "analysis", True, build_traffic,
                                       max_lookback=flow_days, accepts_filter=True,
                                       retention=flow_retention),
        ReportType.SECURITY_RISK: ReportSpec(ReportType.SECURITY_RISK, "assessment", True, build_security_risk,
                                             max_lookback=flow_days, accepts_filter=True,
                                       retention=flow_retention),
        ReportType.NETWORK_INVENTORY: ReportSpec(ReportType.NETWORK_INVENTORY, "inventory", True,
                                                 build_network_inventory, max_lookback=flow_days, accepts_filter=True,
                                       retention=flow_retention),
        ReportType.APP_SUMMARY: ReportSpec(ReportType.APP_SUMMARY, "analysis", True, build_app_summary,
                                           max_lookback=flow_days, requires_app=True,
                                           accepts_filter=True, retention=flow_retention),
        ReportType.VEN_STATUS: ReportSpec(ReportType.VEN_STATUS, "operations", False, build_ven_status),
        ReportType.AUDIT: ReportSpec(ReportType.AUDIT, "operations", False, build_audit),
        ReportType.RANSOMWARE: ReportSpec(ReportType.RANSOMWARE, "assessment", False, build_ransomware),
        # Reads the PCE's draft recompute, not the install's traffic: the same in every collection mode; a day per
        # recompute, so a month at most.
        ReportType.POLICY_USAGE: ReportSpec(ReportType.POLICY_USAGE, "policy", False, build_policy_usage,
                                            max_lookback=lambda settings: POLICY_USAGE_MAX_DAYS),
        ReportType.READINESS: ReportSpec(ReportType.READINESS, "assessment", True, build_readiness,
                                         max_lookback=flow_days, accepts_filter=True, retention=flow_retention),
    }


def specs() -> dict[ReportType, ReportSpec]:
    """Every type this build generates (filled on first use: the builders import this module)."""
    if not REGISTRY:
        REGISTRY.update(_builtin())
    return REGISTRY


def names_app(cond: FlowCondition | None) -> bool:
    """The filter narrows to an application: an app label on either side."""
    if cond is None:
        return False
    return any(lc.key == "app" for side in (cond.src, cond.dst) if side is not None for lc in side.labels)


def app_filter_ok(cond: FlowCondition | None) -> bool:
    """One application's report needs a filter it can honour whole: an app named on one side only, nothing
    else on the other side and no exclusions or individual hosts (the report builds both directions from
    that side). Ports, decisions and the user/process conditions stay as they are."""
    if cond is None:
        return False
    named = [s for s in (cond.src, cond.dst) if s is not None and any(lc.key == "app" for lc in s.labels)]
    if len(named) != 1 or named[0].hrefs or named[0].ips:
        return False
    other = cond.dst if named[0] is cond.src else cond.src
    return all(e is None or e.is_empty() for e in (other, cond.src_exclude, cond.dst_exclude))
