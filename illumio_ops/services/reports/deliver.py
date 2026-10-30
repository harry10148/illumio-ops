"""Emailing a finished report through the one SMTP path (services.alerts.channels.send_mail). A send failure is
recorded on the report; the report itself stays done."""
from __future__ import annotations

from datetime import tzinfo
from pathlib import Path

from illumio_ops.domain.report import ReportDocument
from illumio_ops.domain.values import ReportFormat
from illumio_ops.services.alerts.channels import scrub, send_mail
from illumio_ops.services.context import AppContext
from illumio_ops.services.reports.registry import ReportParams
from illumio_ops.services.reports.render_email import render_email
from illumio_ops.services.reports.render_html import tr
from illumio_ops.store import reports as store

MAX_ATTACHMENTS_BYTES = 20 * 1024 * 1024
DETAIL_MAX = 300
MIME = {ReportFormat.HTML.value: "text/html", ReportFormat.XLSX.value:
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ReportFormat.JSON.value: "application/json", ReportFormat.CSV.value: "text/csv"}
TIMEOUT_SECONDS = 60.0


def gui_link(base: str, report_id: int) -> str | None:
    return f"{base.rstrip('/')}/reports?id={report_id}" if base else None


def deliver(ctx: AppContext, report_id: int, doc: ReportDocument, params: ReportParams, files: list[Path],
            *, tz: tzinfo | None) -> str:
    settings = ctx.settings.current()
    smtp = settings.alerts.channels.smtp
    if not smtp.enabled:
        status, detail = "skipped_no_smtp", None
    else:
        attachments = [(p.name, MIME[p.suffix[1:]], p.read_bytes()) for p in files]
        note = None
        if sum(len(a[2]) for a in attachments) > MAX_ATTACHMENTS_BYTES:
            attachments = [a for a in attachments if a[1] == MIME[ReportFormat.HTML.value]]
            note = tr(doc.lang, "rpt_mail_xlsx_too_large" if attachments else "rpt_mail_files_too_large",
                      mb=MAX_ATTACHMENTS_BYTES // (1024 * 1024))
        rendered = render_email(doc, tz=tz, note=note)
        ok, error = send_mail(smtp, subject=rendered.subject, text=rendered.text, html=rendered.html,
                              attachments=attachments, recipients=list(params.recipients) or None,
                              timeout=TIMEOUT_SECONDS)
        status = "sent" if ok else "failed"
        detail = None if ok else scrub(error or "failed", settings.alerts.channels)[:DETAIL_MAX]
    with ctx.db() as conn:
        store.set_email(conn, report_id, status=status, detail=detail)
    return status
