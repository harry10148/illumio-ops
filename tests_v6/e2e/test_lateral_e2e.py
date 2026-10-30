"""Lateral movement page in a browser (P6c): the stored exposure shown with names (never an href), the paths and
cut points of a critical asset, a cut simulated, and what the page says when something is missing."""
import json
from datetime import UTC, datetime, timedelta

from playwright.sync_api import expect

from illumio_ops.store.flowdb import analysis, workloads
from illumio_ops.store.flowdb.labels import label_set_id
from tests_v6.e2e.conftest import sign_in

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
