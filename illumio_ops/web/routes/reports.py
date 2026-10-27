"""Reports: the catalog, generating one, the list, one report, deleting one (spec §6.5 報表, §6.5.5), and
downloading a report's file (not under /api: a file, not an envelope; the login check is done here)."""
from __future__ import annotations

from flask import Blueprint, Response, request, send_from_directory
from flask_login import current_user
from pydantic import BaseModel, Field, ValidationError
from werkzeug.exceptions import NotFound

from illumio_ops.services.reports import retention, views
from illumio_ops.services.reports.registry import ReportParams
from illumio_ops.services.reports.views import Catalog, ReportItem, ReportPage
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, Empty, api_route, operation
from illumio_ops.web.errors import api_error


class ListQuery(BaseModel):
    page: int = Field(default=1, ge=1, le=10_000)


OP_CATALOG = operation("reports.catalog", "GET", "/api/reports/catalog", None, Catalog)
OP_LIST = operation("reports.list", "GET", "/api/reports", None, ReportPage)
OP_GET = operation("reports.get", "GET", "/api/reports/<int:report_id>", None, ReportItem)
OP_GENERATE = operation("reports.generate", "POST", "/api/reports", ReportParams, ReportItem)
OP_DELETE = operation("reports.delete", "DELETE", "/api/reports/<int:report_id>", None, Empty)

bp = Blueprint("reports", __name__)


@api_route(bp, OP_CATALOG)
def catalog() -> Catalog:
    return views.catalog(get_ctx())


@api_route(bp, OP_LIST)
def list_reports() -> ReportPage:
    try:
        q = ListQuery.model_validate(request.args.to_dict())
    except ValidationError:
        raise ApiFailure(400, "invalid_input", "err_invalid_input", field="page") from None
    return views.list_reports(get_ctx(), page=q.page)


@api_route(bp, OP_GET)
def get_report(report_id: int) -> ReportItem:
    found = views.get_report(get_ctx(), report_id)
    if found is None:
        raise ApiFailure(404, "not_found", "err_not_found")
    return found


@api_route(bp, OP_GENERATE)
def generate(body: ReportParams) -> ReportItem:
    return views.generate_now(get_ctx(), body)


@api_route(bp, OP_DELETE)
def delete_report(report_id: int) -> Empty:
    outcome = retention.remove_report(get_ctx(), report_id)
    if outcome == "missing":
        raise ApiFailure(404, "not_found", "err_not_found")
    if outcome == "running":
        raise ApiFailure(409, "report_running", "gui_reports_err_running")
    return Empty()


@bp.get("/reports/files/<int:report_id>/<name>")
def download(report_id: int, name: str) -> Response | tuple[Response, int]:
    ctx = get_ctx()
    if not current_user.is_authenticated:
        return api_error(401, "auth_required", "err_auth_required")
    if ctx.settings.current().web.must_change_password:
        return api_error(423, "password_change_required", "err_password_change_required")
    path = views.report_file(ctx, report_id, name)
    if path is None:
        raise NotFound()
    resp = send_from_directory(path.parent, path.name, as_attachment=True, max_age=0)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp
