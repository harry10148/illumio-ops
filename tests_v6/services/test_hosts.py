"""Host profile (P6b): what the store holds about one host — inventory, its slice of the exposure result, tamper
investigation, ransomware breakdown. Traffic and event numbers come from the workbench operations, not here."""
from datetime import timedelta

import pytest

from illumio_ops.domain.values import TamperPattern
from illumio_ops.services import hosts
from illumio_ops.services.analysis import ransomware as ransomware_service
from illumio_ops.store.flowdb import analysis
from tests_v6.services.analysis.test_tamper import HOST, _ctx
from tests_v6.services.collect.conftest import NOW


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(ransomware_service, "explain_service", lambda *a, **k: pytest.fail("rule search on page load"))
    return _ctx(tmp_path)


def test_managed_host_profile(ctx):
    with ctx.flows().connect() as conn:
        analysis.write_result(conn, "exposure", params={}, result={
            "hosts": [{"key": HOST, "reach_now": 7, "reach_enforced": 1, "pivot_now": True, "pivot_enforced": False}],
            "assets": [{"key": HOST, "sources_now": 4, "sources_enforced": 0, "paths": [], "cuts": []}]}, at=NOW)
        conn.commit()
    p = hosts.profile(ctx, HOST, now=NOW)
    assert p.managed and p.in_inventory and p.name == "dev"
    assert p.identity is not None and p.identity.enforcement_mode == "visibility_only"
    assert p.exposure is not None and p.exposure.reach_now == 7 and p.exposure.asset is not None
    assert p.tamper is not None and p.tamper.pattern.kind is TamperPattern.REGULAR_CYCLE
    assert p.ransomware is not None and p.ransomware.allow_rules == {}


def test_unmanaged_address(ctx):
    p = hosts.profile(ctx, "ip:10.0.0.9", now=NOW)
    assert not p.managed and p.address == "10.0.0.9" and p.name == "10.0.0.9"
    assert p.identity is None and p.tamper is None and p.ransomware is None


def test_href_not_in_inventory(ctx):
    p = hosts.profile(ctx, "/orgs/1/workloads/gone", now=NOW)
    assert p.managed and not p.in_inventory and p.identity is None and p.ransomware is None


@pytest.mark.parametrize("key", ["", "ip:not-an-ip", "/etc/passwd", "/orgs/1/vens/x", "ip:"])
def test_bad_key_refused(ctx, key):
    with pytest.raises(ValueError):
        hosts.profile(ctx, key, now=NOW)


def test_ransomware_allows_asks_rule_search(ctx, monkeypatch):
    asked = []
    monkeypatch.setattr(ransomware_service, "explain_service", lambda c, href, port, proto: asked.append(port))
    hosts.ransomware_allows(ctx, HOST)  # no service an allow rule can be behind in this store: nothing asked
    assert asked == []
    with pytest.raises(ValueError):
        hosts.ransomware_allows(ctx, "ip:10.0.0.9")


def test_tamper_note_explains_readings(ctx):
    note = hosts.add_tamper_note(ctx, HOST, pattern=TamperPattern.REGULAR_CYCLE, process=None, reason="NetBird",
                                 by="admin")
    p = hosts.profile(ctx, HOST, now=NOW)
    assert p.tamper is not None and p.tamper.explained.get(note) == 12
    hosts.remove_tamper_note(ctx, note)
    p = hosts.profile(ctx, HOST, now=NOW + timedelta(seconds=1))
    assert p.tamper is not None and p.tamper.explained == {}


def test_host_of_another_pce_refused(ctx):
    """Final review #1: the exposure slice and the tamper reading of a PCE whose clearing has not finished."""
    from illumio_ops.services.collect.guard import BindingMismatch, ensure_binding
    with ctx.flows().connect() as conn:
        ensure_binding(conn, ctx.settings.current().pce, NOW)
        conn.commit()
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update(url="https://pce-b.example:8443"))
    for key in (HOST, "ip:10.0.0.9"):
        with pytest.raises(BindingMismatch):
            hosts.profile(ctx, key, now=NOW)


def test_ransomware_details_state(ctx):
    """Final review #3: details never read (or failed) are not "no high-risk service"."""
    from illumio_ops.store.flowdb import ransomware as rstore
    p = hosts.profile(ctx, HOST, now=NOW)
    assert p.ransomware_details == "not_rated"  # the PCE gave this host no rating
    with ctx.flows().connect() as conn:
        conn.execute("UPDATE workloads SET risk_percent = 40, risk_updated_at = '2026-10-29T00:00:00Z'")
        conn.commit()
    assert hosts.profile(ctx, HOST, now=NOW).ransomware_details == "missing"
    with ctx.flows().connect() as conn:
        rstore.upsert_services(conn, HOST, [], source_updated_at="2026-10-28T00:00:00Z", at=NOW)
        conn.commit()
    assert hosts.profile(ctx, HOST, now=NOW).ransomware_details == "stale"
    with ctx.flows().connect() as conn:
        rstore.upsert_services(conn, HOST, [], source_updated_at="2026-10-29T00:00:00Z", at=NOW)
        conn.commit()
    assert hosts.profile(ctx, HOST, now=NOW).ransomware_details == "ok"
