"""A context with SIEM on and one destination, events to send, and a transport that records or fails."""
import errno
from datetime import UTC, datetime, timedelta

import pytest
import requests

from illumio_ops.domain.events import normalize_event
from illumio_ops.domain.values import DataOrigin
from illumio_ops.siem.transports.base import Transport
from illumio_ops.store.flowdb.events import upsert_events
from tests_v6.web.conftest import make_ctx

NOW = datetime(2026, 10, 31, 8, 0, tzinfo=UTC)
DEST = "d" * 32


def destination(**kw):
    base = {"id": DEST, "name": "graylog", "enabled": True, "transport": "tcp", "format": "json", "host": "siem.test",
            "port": 5514, "framing": "lf", "verify_tls": True, "hec_token": "", "batch_size": 100, "max_retries": 3,
            "sources": ["audit"], "new_connection_decisions": [], "new_connection_internal_only": True, "mask_pii": False}
    base.update(kw)
    return base


def configure(ctx, *dests, **siem):
    def mutate(d):
        d["pce"].update({"url": "https://pce.test:8443", "org_id": "1"})
        d["siem"].update({"enabled": True, "destinations": list(dests or (destination(),)), **siem})
    ctx.settings.update(ctx.settings.current().revision, mutate)


def event(i, *, at=NOW, etype="user.sign_in"):
    return {"href": f"/orgs/1/events/e{i}", "event_type": etype, "status": "success", "severity": "info",
            "timestamp": (at + timedelta(seconds=i)).isoformat().replace("+00:00", "Z"), "pce_fqdn": "pce.test",
            "created_by": {"user": {"href": "/users/1", "username": "admin@lab.local"}}}


def add_events(ctx, ids, *, origin=DataOrigin.INGEST):
    with ctx.flows().connect() as conn:
        upsert_events(conn, [normalize_event(event(i)) for i in ids], origin=origin, now=NOW)
        conn.commit()


class FakeTransport(Transport):
    """Records each line; `fail` maps the n-th send (0-based) or a predicate on the line to an exception."""

    def __init__(self, fail=None, *, unconfirmed=False):
        self.lines = []
        self.attempts = 0
        self.fail = fail or (lambda n, line: None)
        self.unconfirmed = unconfirmed
        self.closed = False

    def send(self, payload):
        exc = self.fail(self.attempts, payload)
        self.attempts += 1
        if exc is not None:
            raise exc
        self.lines.append(payload)

    def finish_batch(self):
        if self.unconfirmed:
            raise ConnectionResetError("peer reset")

    def close(self):
        self.closed = True


def http_error(code):
    resp = requests.Response()
    resp.status_code = code
    return requests.HTTPError(f"{code} Client Error", response=resp)


REFUSED = ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused")


@pytest.fixture
def ctx(tmp_path):
    c = make_ctx(tmp_path)
    configure(c)
    return c
