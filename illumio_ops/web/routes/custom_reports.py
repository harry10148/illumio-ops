"""Custom reports (spec §6.5.5, P6e): sections saved from the workbench, listed, renamed, removed; a report still made
by a schedule is not deleted."""
from __future__ import annotations

from datetime import UTC, datetime

from flask import Blueprint
from flask_login import current_user
from pydantic import BaseModel, Field

from illumio_ops.services import custom_reports
from illumio_ops.services.custom_reports import TITLE_MAX, CustomReport
from illumio_ops.services.workbench import WorkbenchRequest
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, Empty, api_route, operation


class CustomReportList(BaseModel):
    reports: list[CustomReport]


class CustomSectionAdd(BaseModel):
    report_id: int | None = None  # None: a new custom report named `name`
    name: str | None = Field(default=None, max_length=TITLE_MAX)
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    request: WorkbenchRequest


class CustomRename(BaseModel):
    name: str = Field(min_length=1, max_length=TITLE_MAX)


OP_LIST = operation("custom_reports.list", "GET", "/api/custom-reports", None, CustomReportList)
OP_ADD = operation("custom_reports.add_section", "POST", "/api/custom-reports/sections", CustomSectionAdd, CustomReport)
OP_REMOVE = operation("custom_reports.remove_section", "POST",
                      "/api/custom-reports/<int:report_id>/sections/<int:index>/remove", Empty, CustomReport)
OP_RENAME = operation("custom_reports.rename", "POST", "/api/custom-reports/<int:report_id>/rename", CustomRename,
                      CustomReport)
OP_DELETE = operation("custom_reports.delete", "DELETE", "/api/custom-reports/<int:report_id>", None, Empty)

bp = Blueprint("custom_reports", __name__)


def _mapped(exc: Exception) -> ApiFailure:
    if isinstance(exc, custom_reports.InUse):
        return ApiFailure(409, "in_use", "cust_err_in_use", params={"schedules": ", ".join(exc.schedules)})
    if isinstance(exc, LookupError):
        return ApiFailure(404, "not_found", "cust_err_not_found")
    return ApiFailure(400, "invalid_input", "cust_err_invalid", params={"why": str(exc)[:200]})


@api_route(bp, OP_LIST)
def list_reports() -> CustomReportList:
    return CustomReportList(reports=custom_reports.list_reports(get_ctx()))


@api_route(bp, OP_ADD)
def add_section(body: CustomSectionAdd) -> CustomReport:
    try:
        return custom_reports.add_section(get_ctx(), report_id=body.report_id, name=body.name, title=body.title,
                                          request=body.request, by=str(current_user.get_id()), now=datetime.now(UTC))
    except (LookupError, ValueError) as exc:
        raise _mapped(exc) from None


@api_route(bp, OP_REMOVE)
def remove_section(body: Empty, report_id: int, index: int) -> CustomReport:
    try:
        return custom_reports.remove_section(get_ctx(), report_id, index, now=datetime.now(UTC))
    except (LookupError, ValueError) as exc:
        raise _mapped(exc) from None


@api_route(bp, OP_RENAME)
def rename(body: CustomRename, report_id: int) -> CustomReport:
    try:
        return custom_reports.rename(get_ctx(), report_id, body.name, now=datetime.now(UTC))
    except (LookupError, ValueError) as exc:
        raise _mapped(exc) from None


@api_route(bp, OP_DELETE)
def delete(report_id: int) -> Empty:
    try:
        custom_reports.delete(get_ctx(), report_id)
    except (custom_reports.InUse, LookupError) as exc:
        raise _mapped(exc) from None
    return Empty()
