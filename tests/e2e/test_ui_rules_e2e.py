"""Every page against the shared presentation rules (purpose-led UI spec §5, §11): with data, without, in basic mode,
and in English at the narrow width. PENDING names the rules the pages still break and the task that mends each — a
rule listed there must still be broken (a mended rule left on the list fails), every other rule must hold."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from illumio_ops.domain.events import normalize_event
from illumio_ops.domain.values import DataOrigin, DeliveryStatus
from illumio_ops.store.flowdb import analysis, workloads
from illumio_ops.store.flowdb import labels as label_store
from illumio_ops.store.flowdb.db import db_time
from illumio_ops.store.flowdb.events import upsert_events
from illumio_ops.store.flowdb.flows import upsert_flows
from tests.e2e import test_alerts_e2e as alerts_e2e
from tests.e2e import test_fleet_e2e as fleet_e2e
from tests.e2e import test_lateral_e2e as lateral_e2e
from tests.e2e import ui_rules
from tests.e2e.conftest import NARROW, sign_in
from tests.services.analysis.test_tamper import _tamper
from tests.services.reports.test_findings import flow

PATHS = ui_rules.PATHS

PENDING: dict[str, str] = {
    "styled_checkbox": "Task 3", "cards_apart": "Task 4", "no_overlap": "Task 4", "header_one_line": "Task 4"}

WIDE = {"width": 1440, "height": 900}


def seed_everything(live_app, fake_pce) -> list[str]:
    """One installation with something on every page: an inventory, traffic, an exposure result, tampering events,
    alerts sent and recorded only. Returns the extra pages worth walking (an alert, a host)."""
    ctx = live_app.ctx
    now = datetime.now(UTC)

    def mutate(d):
        d["collection"].update(mode="full")
        d["lateral"].update({"critical_assets": [{"key": "app", "value": "Finance"}]})
        d["pce"].update(url=fake_pce.url, org_id="1", api_key="k", api_secret="s", write_api_key="wk", write_api_secret="ws")
    ctx.settings.update(ctx.settings.current().revision, mutate)
    with ctx.flows().connect() as conn:
        fin = label_store.label_set_id(conn, (("app", "Finance"),))
        prod = label_store.label_set_id(conn, (("app", "DB"), ("env", "Prod")))
        dev = label_store.label_set_id(conn, (("app", "Web"), ("env", "Dev")))
        workloads.replace_inventory(conn, [
            fleet_e2e._wl(fleet_e2e.DB, "db", "visibility_only", prod, now),
            fleet_e2e._wl(fleet_e2e.WEB, "web", "selective", dev, now),
            # values as long as real ones: what makes a narrow column wrap its heading
            *[replace(fleet_e2e._wl(f"/orgs/1/workloads/real{i}", f"Harrys-MacBook-Air-{i}.lab.example.internal", "visibility_only",
                                    prod, now), os_id="ubuntu-x86_64-noble", ven_version="26.2.20-2063") for i in range(3)],
            *[lateral_e2e._wl(h) for h in lateral_e2e.HOSTS], lateral_e2e._wl("fin", fin), lateral_e2e._wl("hr", fin)])
        upsert_flows(conn, [flow(src="adm", dst="db", decision="potentially_blocked", conns=4, port=3389),
                            flow(src="bak", dst="db", decision="allowed", conns=2, port=445)],
                     origin=DataOrigin.INGEST, now=now)
        conn.execute("UPDATE flows SET first_detected = ?, last_detected = ?",
                     (db_time(now - timedelta(hours=2)), db_time(now - timedelta(hours=1))))
        analysis.write_result(conn, "exposure", params={}, result=lateral_e2e._result(now), at=now)
        analysis.set_run(conn, "exposure", status={"state": "ok"}, ok_at=now)
        start = now - timedelta(hours=3)
        upsert_events(conn, [normalize_event(_tamper(i, start + timedelta(minutes=10 * i))) for i in range(3)],
                      origin=DataOrigin.INGEST, now=now)
        conn.commit()
    first = alerts_e2e.seed(ctx)
    alerts_e2e.seed(ctx, hold=DeliveryStatus.NOT_NOTIFIED)
    return [f"/alerts/{first}", f"/hosts?key={fleet_e2e.DB}"]


def set_language(live_app, language: str) -> None:
    s = live_app.ctx.settings
    s.update(s.current().revision, lambda d: d["display"].update(language=language))


def walk(page, base_url: str, paths=PATHS) -> dict[str, list[str]]:
    """Every page's violations, each named with its path."""
    found: dict[str, list[str]] = {}
    for path in paths:
        page.goto(base_url + path)
        page.wait_for_selector("main .page, main section, main h1")
        page.wait_for_load_state("networkidle")
        for rule, items in ui_rules.violations(page).items():
            found.setdefault(rule, []).extend(f"{path}  {item}" for item in items)
    return found


def _report(found: dict[str, list[str]], rules) -> str:
    return "\n".join(f"[{r}] {line}" for r in rules for line in found.get(r, []))


def _holds(found: dict[str, list[str]]) -> None:
    broken = [r for r in found if r not in PENDING]
    assert not broken, _report(found, broken)


def test_rules_hold_with_data(live_app, fake_pce, browser):
    extra = seed_everything(live_app, fake_pce)
    set_language(live_app, "zh_TW")
    ctx = browser.new_context(locale="zh-TW", viewport=WIDE)
    page = ctx.new_page()
    sign_in(page, live_app.url)
    found = walk(page, live_app.url, (*PATHS, *extra))
    ctx.close()
    _holds(found)
    mended = [r for r in PENDING if r not in found]
    assert not mended, f"mended, take them off PENDING: {mended}"


def test_rules_hold_without_data(live_app, browser):
    ctx = browser.new_context(locale="en-US", viewport=WIDE)
    page = ctx.new_page()
    sign_in(page, live_app.url)
    found = walk(page, live_app.url)
    ctx.close()
    _holds(found)


def test_rules_hold_in_basic_mode(live_app, fake_pce, browser):
    extra = seed_everything(live_app, fake_pce)
    s = live_app.ctx.settings
    s.update(s.current().revision, lambda d: d["collection"].update(mode="lightweight"))
    ctx = browser.new_context(locale="en-US", viewport=WIDE)
    page = ctx.new_page()
    sign_in(page, live_app.url)
    found = walk(page, live_app.url, (*PATHS, *extra))
    ctx.close()
    _holds(found)


def test_rules_hold_in_english_and_at_760(live_app, fake_pce, browser):
    extra = seed_everything(live_app, fake_pce)
    set_language(live_app, "en")
    ctx = browser.new_context(locale="en-US", viewport={"width": NARROW, "height": 900})
    page = ctx.new_page()
    sign_in(page, live_app.url)
    found = walk(page, live_app.url, (*PATHS, *extra))
    ctx.close()
    _holds(found)
