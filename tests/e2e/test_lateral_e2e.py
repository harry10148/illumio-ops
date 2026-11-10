"""Lateral movement page in a browser (P6c): the stored exposure shown with names (never an href), the paths and
cut points of a critical asset, a cut simulated, and what the page says when something is missing."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from playwright.sync_api import expect

from illumio_ops.store.flowdb import analysis, workloads
from illumio_ops.store.flowdb.labels import label_set_id
from tests.e2e.conftest import sign_in

W = "/orgs/1/workloads/"
HOSTS = [f"h{i:02d}" for i in range(25)]


def _wl(name, label_set=None):
    return workloads.WorkloadRow(
        href=W + name, hostname=f"{name}.lab", name=None, managed=1, enforcement_mode="selective",
        visibility_level=None, os_id=None, ven_version=None, ven_href=None, label_set=label_set, online=1,
        risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at="x")


def _result(now, *, groups=True):
    r = {"computed_at": now.isoformat(), "observation_from": (now - timedelta(days=30)).isoformat(),
         "observation_to": now.isoformat(), "hops": 3, "nodes": 27, "edges_now": 40, "edges_enforced": 6,
         "unknown_edges": 2,
         "hosts": [{"key": W + h, "reach_now": 30 - i, "reach_enforced": 1, "pivot_now": h == "h01",
                    "pivot_enforced": False} for i, h in enumerate(HOSTS)],
         "assets": [{"key": W + "fin", "sources_now": 9, "sources_enforced": 1,
                     "paths": [[W + "h00", W + "h01", W + "fin"], [W + "h02", W + "fin"]],
                     "cuts": [{"kind": "edge", "src": W + "h01", "dst": W + "fin", "ports": [[3389, 6]], "before": 9,
                               "after": 2},
                              {"kind": "node", "src": W + "h01", "dst": None, "ports": [], "before": 9, "after": 3}]},
                    {"key": W + "hr", "sources_now": 2, "sources_enforced": 0, "paths": [[W + "h03", W + "hr"]],
                     "cuts": []}],
         "cross_env": [{"src": W + "h04", "dst": W + "fin", "src_env": "Dev", "dst_env": "Prod", "ports": [[22, 6]],
                        "state": "allowed"}], "cross_env_total": 1,
         "footholds": [{"host": W + "h05", "name": "SMB", "port": 445, "proto": 6, "severity": "critical"}],
         "limits_hit": []}
    if groups:
        r["groups"] = {"app": {"groups": ["Web", "DB"], "edges": [["Web", "DB", 3, "allowed"]]},
                       "env": {"groups": ["Dev", "Prod"], "edges": [["Dev", "Prod", 1, "allowed"]]}}
    return r


def _seed(live_app, *, critical=True, groups=True, mode="full"):
    ctx = live_app.ctx
    now = datetime.now(UTC)

    def mutate(d):
        d["collection"].update(mode=mode)
        if critical:
            d["lateral"].update({"critical_assets": [{"key": "app", "value": "Finance"}]})
    ctx.settings.update(ctx.settings.current().revision, mutate)
    with ctx.flows().connect() as conn:
        fin = label_set_id(conn, (("app", "Finance"),))
        workloads.replace_inventory(conn, [_wl(h) for h in HOSTS] + [_wl("fin", fin), _wl("hr", fin)])
        analysis.write_result(conn, "exposure", params={}, result=_result(now, groups=groups), at=now)
        analysis.set_run(conn, "exposure", status={"state": "ok"}, ok_at=now)
        conn.commit()


def _open(context, live_app, path="/lateral"):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}{path}")
    page.wait_for_selector("[data-section=status]")
    return page


def test_exposure_sections(context, live_app):
    _seed(live_app)
    page = _open(context, live_app)
    expect(page.locator("[data-role=lat-computed]")).to_have_count(1)
    expect(page.locator("[data-role=edges-now]")).to_have_text("40")
    expect(page.locator("[data-role=edges-enforced]")).to_have_text("6")
    expect(page.locator("[data-role=path-diagram]")).to_have_count(1)
    expect(page.locator("[data-role=cuts] li")).to_have_count(2)
    assert "h01.lab" in page.locator("[data-role=cuts]").inner_text()
    expect(page.locator("[data-role=reach] tbody tr")).to_have_count(20)
    page.locator("[data-role=lat-more]").click()
    expect(page.locator("[data-role=reach] tbody tr")).to_have_count(25)
    expect(page.locator("[data-role=matrix] tbody tr")).to_have_count(2)
    expect(page.locator("[data-section=footholds] li")).to_have_count(1)
    assert "/orgs/" not in page.locator("[data-role=lateral]").inner_text()


def test_critical_not_set_guides(context, live_app):
    _seed(live_app, critical=False)
    page = _open(context, live_app)
    expect(page.locator("[data-role=critical-not-set]")).to_have_count(1)
    # lab acceptance 2026-10-30: "critical assets reachable 0" read as none reachable; nothing is set
    expect(page.locator("[data-role=assets-now]")).to_have_text("Not set")
    expect(page.locator("[data-role=assets-enforced]")).to_have_text("Not set")
    page.locator("[data-role=sim-cross]").first.click()  # nothing set is not "no host matches"
    expect(page.locator("[data-role=sim-no-assets]")).to_have_text("No critical assets are set: the change in reach is not shown.")
    expect(page.locator("[data-role=reach] tbody tr")).to_have_count(20)  # the ranking covers every host


def test_lightweight_detections_need_mode(context, live_app):
    _seed(live_app, mode="lightweight")
    page = _open(context, live_app)
    expect(page.locator("[data-role=detections-need-mode]")).to_have_count(1)
    expect(page.locator("[data-role=lat-compute]")).to_have_count(1)
    expect(page.locator("[data-section=reach]")).to_have_count(0)  # the stored full-mode result is not shown


def test_old_result_without_groups(context, live_app):
    _seed(live_app, groups=False)
    page = _open(context, live_app)
    expect(page.locator("[data-role=groups-later]")).to_have_count(1)
    expect(page.locator("[data-role=reach] tbody tr")).to_have_count(20)


def test_simulate_from_cut(context, live_app):
    _seed(live_app)
    page = _open(context, live_app)
    page.locator("[data-role=sim-cut]").first.click()
    panel = page.locator("[data-role=simulation]")
    expect(panel.locator("[data-role=sim-counts]")).to_have_count(1)
    assert "h01.lab" in panel.locator("[data-role=sim-rule]").inner_text()
    expect(panel.locator("[data-role=sim-csv]")).to_have_count(1)
    expect(panel.locator("[data-role=sim-reach] tbody tr")).to_have_count(2)
    page.locator("[data-role=sim-cut]").nth(1).click()  # the host cut: only its inbound traffic is counted
    expect(panel.locator("[data-role=sim-node]")).to_have_count(1)


def test_focus_asset_link_preselects(context, live_app):
    _seed(live_app)
    page = _open(context, live_app, f"/lateral?asset={W}hr")
    expect(page.locator("[data-role=asset]")).to_have_attribute("data-asset", W + "hr")
    page.goto(f"{live_app.url}/lateral?host={W}h22")
    expect(page.locator("[data-role=reach] tbody tr")).to_have_count(25)  # the host's row is past the first 20
    expect(page.locator("tr.lat-focus")).to_have_count(1)


def test_result_json_names_never_hrefs(live_app):
    """The stored result keeps hrefs; the page's own data names them (what the browser shows is checked above)."""
    _seed(live_app)
    from illumio_ops.services import lateral_view
    v = lateral_view.view(live_app.ctx)
    assert all(not n.startswith("/orgs/") for n in v.names.values())
    assert json.loads(v.model_dump_json())["state"] == "ok"


def test_csv_cells_never_formulas(context, live_app):
    """Security review: a hostname from the PCE starting with = (or + - @) is written as text, not a formula a
    spreadsheet would run."""
    from illumio_ops.domain.flows import normalize_flow
    from illumio_ops.domain.values import DataOrigin
    from illumio_ops.store.flowdb.flows import upsert_flows
    from tests.services.collect.conftest import raw_flow
    _seed(live_app)
    now = datetime.now(UTC)
    raw = raw_flow(1, now - timedelta(days=1, minutes=5), now - timedelta(days=1), port=3389)
    raw["src"]["workload"].update(href=W + "h01", hostname='=HYPERLINK("http://x","y")')
    raw["dst"]["workload"].update(href=W + "fin", hostname="-fin")
    with live_app.ctx.flows().connect() as conn:
        upsert_flows(conn, [normalize_flow(raw)], origin=DataOrigin.INGEST, now=now)
        conn.commit()
    page = _open(context, live_app)
    page.locator("[data-role=sim-cut]").first.click()
    csv_button = page.locator("[data-role=sim-csv]")
    expect(csv_button).to_be_enabled()
    with page.expect_download() as dl:
        csv_button.click()
    text = Path(dl.value.path()).read_text(encoding="utf-8-sig")
    row = text.splitlines()[1]
    assert row.startswith("\"'=HYPERLINK(") and ",'-fin," in row


# ── final review (2026-10-30) ─────────────────────────────────────────────────

def test_states_said_not_shown_as_nothing(context, live_app):
    """#4–#6: a failed hourly run, detections never evaluated, and ransomware details not read are said; the
    detections and footholds sections do not say "none"."""
    _seed(live_app)
    with live_app.ctx.flows().connect() as conn:
        analysis.set_run(conn, "exposure", error="Boom")
        conn.execute("UPDATE workloads SET risk_percent = 40, risk_updated_at = 'x'")
        conn.commit()
    page = _open(context, live_app)
    expect(page.locator("[data-role=lat-run-failed]")).to_have_count(1)
    expect(page.locator("[data-role=detect-not-run]")).to_have_count(1)
    expect(page.locator("[data-role=rw-unread]")).to_have_count(1)
    assert "No detection in the last 7 days" not in page.locator("[data-section=detections]").inner_text()


def test_short_observation_computes_the_offered_period(context, live_app):
    """#7: with a 1-day observation period the only choice is 1 day, and that is what is asked for."""
    _seed(live_app, mode="lightweight")
    live_app.ctx.settings.update(live_app.ctx.settings.current().revision,
                                 lambda d: d["lateral"].update(observation_days=1))
    page = _open(context, live_app)
    with page.expect_request("**/api/lateral/compute") as req:
        page.click("[data-role=lat-compute]")
    assert json.loads(req.value.post_data)["days"] == 1


def test_pivots_quarantined_as_a_batch(context, live_app):
    """P6d: pivot hosts picked and quarantined together; with no PCE set up the dialog says so."""
    _seed(live_app)
    page = _open(context, live_app)
    button = page.locator("[data-role=pivots-quarantine]")
    expect(button).to_be_disabled()
    page.locator("[data-role=pivots] input[type=checkbox]").first.check()
    button.click()
    dialog = page.locator("[data-role=quarantine]")
    expect(dialog.locator(".form-error")).to_have_text("The PCE connection is not set up yet.")


# ── the detection page (UI redesign spec §4.2) ──────────────────────────────

def test_detect_sections_present(context, live_app):
    _seed(live_app)
    page = _open(context, live_app, "/detect")
    expect(page.locator("h1")).to_have_text("Detection")
    strip = page.locator("[data-role=kpi-strip]")
    expect(strip.locator("[data-kpi=reachable] .kpi-value")).to_have_count(1)
    expect(strip.locator("[data-kpi=hubs] .kpi-value")).to_have_count(1)
    expect(page.locator("[data-section=detections]")).to_have_count(1)
    expect(page.locator("[data-role=focus]")).to_contain_text("Needs attention")


def test_old_lateral_url_redirects(context, live_app):
    _seed(live_app)
    page = _open(context, live_app, "/lateral?section=cross_env")
    page.wait_for_url(f"{live_app.url}/detect?section=cross_env")


def test_basic_mode_explains_not_empty(context, live_app):
    _seed(live_app, mode="lightweight")
    page = _open(context, live_app, "/detect")
    expect(page.locator("[data-role=detections-need-mode] [data-role=needs-advanced]")).to_have_count(1)
    strip = page.locator("[data-role=kpi-strip]")
    expect(strip.locator("[data-kpi=new_week] [data-reason]")).to_have_text("Needs advanced mode")
    expect(strip.locator(".kpi-value")).to_have_count(0)  # nothing computed until the traffic is read


def test_detect_no_overflow_760(narrow_context, live_app):
    from tests.e2e.conftest import no_horizontal_overflow
    _seed(live_app)
    page = narrow_context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/detect")
    page.locator("[data-section=detections]").wait_for()
    assert no_horizontal_overflow(page)


def _admin_flows(live_app):
    from illumio_ops.domain.values import DataOrigin
    from illumio_ops.store.flowdb.flows import upsert_flows
    from tests.services.reports.test_findings import flow
    now = datetime.now(UTC)
    long_name = "CORP\\" + "svc-a-very-long-service-account-name-" * 3
    rows = [flow(src="adm", dst="db1", port=3389, user="CORP\\alice"), flow(src="adm", dst="db2", port=3389, user="CORP\\alice"),
            flow(src="adm", dst="db1", port=22, user=long_name), flow(src="bak", dst="db1", port=445, user="root"),
            flow(src="bak", dst="db2", port=445)]
    for r in rows:  # inside the period the page reads
        object.__setattr__(r, "first_detected", now - timedelta(hours=2))
        object.__setattr__(r, "last_detected", now - timedelta(hours=1))
    with live_app.ctx.flows().connect() as conn:
        upsert_flows(conn, rows, origin=DataOrigin.INGEST, now=now)
        conn.commit()


def test_initiator_rankings_and_their_coverage(context, live_app):
    """6.5.0 B3: who initiates management-port connections, and how much of that traffic names a user at all."""
    _seed(live_app)
    _admin_flows(live_app)
    page = _open(context, live_app, "/detect")
    card = page.locator("[data-section=initiators]")
    card.locator("[data-role=init-users] tbody tr").first.wait_for()
    assert card.locator("[data-role=init-users] tbody tr").first.inner_text().split() == ["corp\\alice", "2"]
    assert "root" in card.locator("[data-role=init-system]").inner_text()
    assert "No management-port flow record names a process." in card.locator("[data-role=init-processes]").inner_text()
    cov = card.locator("[data-role=initiators-coverage]").inner_text()
    assert "flow records in the last" in cov and "5;" in cov and "4 (80.0%)" in cov and "0 (0.0%)" in cov


def test_initiators_basic_mode_says_what_it_needs(context, live_app):
    _seed(live_app, mode="lightweight")
    page = _open(context, live_app, "/detect")
    expect(page.locator("[data-role=initiators-need-mode] [data-role=needs-advanced]")).to_have_count(1)


def test_initiators_no_overflow_760_with_a_long_account_name(narrow_context, live_app):
    from tests.e2e.conftest import no_horizontal_overflow
    _seed(live_app)
    _admin_flows(live_app)
    page = narrow_context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/detect")
    page.locator("[data-role=init-users] tbody tr").first.wait_for()
    assert no_horizontal_overflow(page)
    cell = page.locator("[data-role=init-users] td.wrap-any", has_text="svc-a-very-long").first
    assert cell.evaluate("e => e.scrollWidth <= e.clientWidth + 1")  # wrapped, not cut
