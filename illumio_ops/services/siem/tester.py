"""Send one test line to a destination as it is on the page, saved or not (P7): it touches no cursor and no DLQ."""
from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from illumio_ops.i18n import translate
from illumio_ops.services.context import AppContext
from illumio_ops.services.siem.dispatch import SYSLOG_HOST, TransportFactory
from illumio_ops.settings.schema import SiemDestination
from illumio_ops.siem.formatters.factory import formatter_for
from illumio_ops.siem.records import SiemRecord
from illumio_ops.siem.transports.factory import transport_for


class SiemTestResult(BaseModel):
    ok: bool
    error: str | None
    line: str          # what was sent, for the operator to look for in the SIEM


def send_test(ctx: AppContext, dest: SiemDestination, *, now: datetime | None = None,
                     transport_factory: TransportFactory = transport_for) -> SiemTestResult:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    lang = ctx.settings.current().display.language
    rec = SiemRecord(kind="test", record_id=int(at.timestamp()), time=at, signature="test",
                     name=translate(lang, "siem_test_name"), summary=translate(lang, "siem_test_summary"))
    line = formatter_for(dest.format, host=SYSLOG_HOST).format_record(rec)
    transport = None
    try:
        transport = transport_factory(dest)
        transport.send_record(line, at.timestamp())
        transport.finish_batch()
    except Exception as exc:  # noqa: BLE001 — the operator reads the reason on the page
        return SiemTestResult(ok=False, error=str(exc) or type(exc).__name__, line=line)
    finally:
        if transport is not None:
            try:
                transport.close()
            except Exception:  # noqa: BLE001, S110 — the line is already through or the error already said
                pass
    return SiemTestResult(ok=True, error=None, line=line)
