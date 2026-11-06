"""Reports: the catalog, generating one, the list, one report, deleting one or several (spec §6.5 報表, §6.5.5), and
a report's file — downloaded, or an HTML report opened in the browser (not under /api: a file, not an envelope; the
login check is done here)."""
from __future__ import annotations

from datetime import UTC, datetime

from flask import Blueprint, Response, request, send_from_directory
from flask_login import current_user
from pydantic import BaseModel, Field, ValidationError
from werkzeug.exceptions import NotFound

from illumio_ops.services.reports import retention, views
from illumio_ops.services.reports.generate import REFUSAL_FIELDS, reach, refusal
from illumio_ops.services.reports.registry import ReportParams
from illumio_ops.services.reports.views import Catalog, ReportItem, ReportPage
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, Empty, api_route, operation
from illumio_ops.web.errors import api_error


class ListQuery(BaseModel):
    page: int = Field(default=1, ge=1, le=10_000)


BULK_MAX = 500


class BulkDelete(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=BULK_MAX)


class BulkDeleted(BaseModel):
    removed: list[int]
    running: list[int]  # being made: kept, deleted once done
    missing: list[int]


# An HTML report opened in the browser runs its own inline style and table script, which the console's policy
# forbids. It gets its own: a sandbox without allow-same-origin gives the page an opaque origin, so its script can
# reach neither the console's session cookie nor its API, and it may load nothing from anywhere.
INLINE_REPORT_CSP: dict[str, str | list[str]] = {
    "default-src": "'none'",
    "style-src": "'unsafe-inline'",
    "script-src": "'unsafe-inline'",
    "img-src": "data:",
    "base-uri": "'none'",
    "form-action": "'none'",
    "sandbox": "allow-scripts allow-modals allow-popups allow-popups-to-escape-sandbox",
}


OP_CATALOG = operation("reports.catalog", "GET", "/api/reports/catalog", None, Catalog)
OP_LIST = operation("reports.list", "GET", "/api/reports", None, ReportPage)
OP_GET = operation("reports.get", "GET", "/api/reports/<int:report_id>", None, ReportItem)
OP_GENERATE = operation("reports.generate", "POST", "/api/reports", ReportParams, ReportItem)
OP_DELETE = operation("reports.delete", "DELETE", "/api/reports/<int:report_id>", None, Empty)
OP_BULK_DELETE = operation("reports.bulk_delete", "POST", "/api/reports/bulk-delete", BulkDelete, BulkDeleted)

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
    ctx = get_ctx()
    now = datetime.now(UTC)
    reason = refusal(ctx.settings.current(), body, now=now, reached=reach(ctx, now))
    if reason:
        raise ApiFailure(400, "invalid_input", reason, field=f"report.{REFUSAL_FIELDS[reason]}")
    return views.generate_now(ctx, body)


@api_route(bp, OP_DELETE)
def delete_report(report_id: int) -> Empty:
    outcome = retention.remove_report(get_ctx(), report_id)
    if outcome == "missing":
        raise ApiFailure(404, "not_found", "err_not_found")
    if outcome == "running":
        raise ApiFailure(409, "report_running", "gui_reports_err_running")
    return Empty()


@api_route(bp, OP_BULK_DELETE)
def bulk_delete(body: BulkDelete) -> BulkDeleted:
    ctx = get_ctx()
    out: dict[str, list[int]] = {"removed": [], "running": [], "missing": []}
    for rid in dict.fromkeys(body.ids):
        out[retention.remove_report(ctx, rid)].append(rid)
    return BulkDeleted(**out)


def _report_file(report_id: int, name: str, *, inline: bool) -> Response | tuple[Response, int]:
    ctx = get_ctx()
    if not current_user.is_authenticated:
        return api_error(401, "auth_required", "err_auth_required")
    if ctx.settings.current().web.must_change_password:
        return api_error(423, "password_change_required", "err_password_change_required")
    path = views.report_file(ctx, report_id, name)
    if path is None or (inline and path.suffix.lower() != ".html"):
        raise NotFound()
    resp = send_from_directory(path.parent, path.name, as_attachment=not inline, max_age=0,
                               mimetype="text/html" if inline else None)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@bp.get("/reports/files/<int:report_id>/<name>")
def download(report_id: int, name: str) -> Response | tuple[Response, int]:
    return _report_file(report_id, name, inline=False)


@bp.get("/reports/view/<int:report_id>/<name>")
def open_inline(report_id: int, name: str) -> Response | tuple[Response, int]:
    """An HTML report shown in the browser (5.x /reports/<file>), under INLINE_REPORT_CSP."""
    return _report_file(report_id, name, inline=True)


# flask-talisman reads a view's own options from this attribute (what its @talisman(...) decorator sets).
open_inline.talisman_view_options = {"content_security_policy": INLINE_REPORT_CSP}  # type: ignore[attr-defined]
