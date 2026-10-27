"""Report delivery by email (P5a Task 6): attachments, the size fallback, and what is recorded."""
from datetime import UTC, datetime

import pytest

from illumio_ops.domain.values import ReportType
from illumio_ops.services.reports import deliver, generate
from illumio_ops.services.reports.registry import ReportParams
from illumio_ops.store import reports as store
from tests_v6.services.alerts.test_channels import _Smtp, smtp  # noqa: F401 - the local SMTP server fixture
from tests_v6.services.collect.conftest import configured_ctx
from tests_v6.services.reports.test_generate import FakeBuilder, _register

NOW = datetime(2026, 10, 27, 1, 30, tzinfo=UTC)


def _ctx(tmp_path, port, *, enabled=True, external=""):
    ctx = configured_ctx(tmp_path)

    def mutate(d):
        d["alerts"]["channels"]["smtp"].update(enabled=enabled, host="127.0.0.1", port=port, security="none",
                                               username="", password="", sender="ops@example.com",
                                               recipients=["sec@example.com"])
        d["reports"]["gui_external_url"] = external
    ctx.settings.update(ctx.settings.current().revision, mutate)
    return ctx


def _run(ctx, **params):
    rid = generate.enqueue(ctx, ReportParams(report_type=ReportType.LATERAL_POSTURE, **params), trigger="schedule",
                           schedule_id="s", now=NOW)
    generate.run_queued(ctx, now=NOW)
    with ctx.db() as conn:
        return store.get(conn, rid)


def _data():
    return "\n".join(line for kind, line in _Smtp.log if kind == "DATA")


def test_attachments_and_recipients(tmp_path, smtp, monkeypatch):  # noqa: F811
    ctx = _ctx(tmp_path, smtp)
    _register(monkeypatch, FakeBuilder())
    row = _run(ctx, email=True, recipients=("boss@example.com",))
    assert row.email_status == "sent"
    rcpt = [line for kind, line in _Smtp.log if kind == "CMD" and line.upper().startswith("RCPT")]
    assert [r.upper() for r in rcpt] == ["RCPT TO:<BOSS@EXAMPLE.COM>"]
    data = _data()
    assert "multipart/mixed" in data and ".html" in data and ".xlsx" in data


def test_channel_recipients_when_none_given(tmp_path, smtp, monkeypatch):  # noqa: F811
    ctx = _ctx(tmp_path, smtp)
    _register(monkeypatch, FakeBuilder())
    assert _run(ctx, email=True).email_status == "sent"
    assert any("sec@example.com" in line for kind, line in _Smtp.log if kind == "CMD")


def test_size_fallback_drops_xlsx(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, 25)
    _register(monkeypatch, FakeBuilder())
    sent = {}

    def fake_send(cfg, **kw):
        sent.update(kw)
        return True, None
    monkeypatch.setattr(deliver, "send_mail", fake_send)
    monkeypatch.setattr(deliver, "MAX_ATTACHMENTS_BYTES", 1)
    assert _run(ctx, email=True).email_status == "sent"
    assert [name.rsplit(".", 1)[1] for name, _, _ in sent["attachments"]] == ["html"]
    assert "too large" in sent["text"] and "too large" in sent["html"]


def test_smtp_disabled_records_skipped(tmp_path, smtp, monkeypatch):  # noqa: F811
    ctx = _ctx(tmp_path, smtp, enabled=False)
    _register(monkeypatch, FakeBuilder())
    row = _run(ctx, email=True)
    assert row.status.value == "done" and row.email_status == "skipped_no_smtp" and _Smtp.log == []


def test_no_email_unless_asked(tmp_path, smtp, monkeypatch):  # noqa: F811
    ctx = _ctx(tmp_path, smtp)
    _register(monkeypatch, FakeBuilder())
    assert _run(ctx).email_status is None and _Smtp.log == []


def test_send_failure_recorded_report_stays_done(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, 1)  # nothing listens on port 1
    _register(monkeypatch, FakeBuilder())
    row = _run(ctx, email=True)
    assert row.status.value == "done" and row.email_status == "failed" and row.email_detail


def test_gui_link_set_from_external_url(tmp_path, smtp, monkeypatch):  # noqa: F811
    ctx = _ctx(tmp_path, smtp, external="https://ops.example:5443/")
    b = FakeBuilder()
    _register(monkeypatch, b)
    row = _run(ctx, email=True)
    html = (ctx.paths.reports_dir / str(row.id) / next(f for f in row.files if f.endswith(".html"))).read_text()
    assert f"https://ops.example:5443/reports?id={row.id}" in html


@pytest.mark.parametrize("url", ["ftp://x", "https://x/?a=1", "https://x/#f", "javascript:alert(1)"])
def test_external_url_validated(tmp_path, url):
    from illumio_ops.settings.store import SettingsInvalid
    ctx = configured_ctx(tmp_path)
    with pytest.raises(SettingsInvalid):
        ctx.settings.update(ctx.settings.current().revision, lambda d: d["reports"].update(gui_external_url=url))


def test_sending_shown_between_done_and_sent(tmp_path, monkeypatch):
    """Lab: a finished report showed no email status while its email was still going out."""
    ctx = _ctx(tmp_path, 25)
    _register(monkeypatch, FakeBuilder())
    seen = []

    def watch(ctx_, report_id, *a, **kw):
        with ctx_.db() as conn:
            seen.append(store.get(conn, report_id).email_status)
        return "sent"
    monkeypatch.setattr(generate, "deliver", watch)
    _run(ctx, email=True)
    assert seen == ["sending"]
