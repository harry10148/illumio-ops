"""Task 4 — #/investigate/fleet：車隊頁與推進抽屜。

Spec: docs/superpowers/specs/2026-09-09-ven-fleet-manager-design.md
Plan: docs/superpowers/plans/2026-09-09-ven-fleet-manager.md Task 4

後端一律用 `page.route` stub，所以這些測試守的是**畫面對同一份資料說了什麼**，
不是後端算得對不對（那是 Task 1–3 的測試在守）。

兩件事這一頁刻意不做，各有一支守門：
  - 沒有快照時不渲染 0。「還沒分析過」與「外面什麼都沒有」當成數字長得一樣，
    對值班的人意思相反。
  - 套用之後不說「已套用」。PCE 收下了，VEN 下次回報才生效。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

pytest_plugins = ["tests.v2_e2e_utils"]

ROUTE = "#/investigate/fleet"


def _labels(page):
    keys = [
        "gui_fleet_title", "gui_fleet_no_snapshot",
        "gui_fleet_target_unset", "gui_fleet_partial",
        "gui_fleet_index_truncated",
        "gui_nav_fleet",
    ]
    return page.evaluate(
        "async (ks) => { const { t } = await import('/static/js/v2/core/i18n.mjs'); "
        "const o = {}; ks.forEach(k => { o[k] = t(k); }); return o; }", keys)


def _index(n_sel=3, n_idle=1):
    rows = [{"href": "/orgs/1/workloads/s%d" % i, "hostname": "sel-%d" % i,
             "mode": "selective", "online": True, "version": "26.2.20-2063",
             "compat": "unknown", "hslh": 0.1, "app": "web", "env": "prod",
             "os": "ubuntu"} for i in range(n_sel)]
    rows += [{"href": "/orgs/1/workloads/i%d" % i, "hostname": "idle-%d" % i,
              "mode": "idle", "online": False, "version": "23.4.11-8",
              "compat": "warn", "hslh": 99.0, "app": "", "env": "",
              "os": "rhel"} for i in range(n_idle)]
    return rows


def _fleet(**over):
    f = {
        "total": 4, "managed_online": 3, "managed_offline": 1,
        "versions": {"distribution": {"26.2.20-2063": {"count": 3, "os_breakdown": {"ubuntu": 3}},
                                      "23.4.11-8": {"count": 1, "os_breakdown": {"rhel": 1}}},
                     "ordered": ["26.2.20-2063", "23.4.11-8"], "target": None,
                     "on_target": 0, "needs_upgrade": None, "unparsable": [],
                     "oldest": "23.4.11-8", "newest": "26.2.20-2063"},
        "compat": {"pass": 0, "warn": 1, "fail": 0, "unknown": 0},
        "pipeline": {b: {"count": 0, "sample": []} for b in
                     ("idle_compat_pass", "idle_compat_warn", "idle_compat_fail",
                      "idle_compat_unknown", "visibility_ready", "visibility_not_ready",
                      "selective", "full")},
        "heartbeat": {"fresh": 3, "stale_24h": 0, "stale_48h": 1, "no_heartbeat": 0},
        "coverage_gaps": {"by_app": {"web": {"selective": 3}}, "by_env": {},
                          "unlabeled": {"count": 1, "sample": []}},
        "agent_health": {"errors": {"count": 0, "sample": []},
                         "warnings": {"count": 0, "sample": []}},
        "health_score": {"score": 62, "partial": True,
                         "components": {"online": {"present": True, "value": 0.75},
                                        "enforcement": {"present": True, "value": 0.75},
                                        "version": {"present": False, "value": None},
                                        "heartbeat": {"present": True, "value": 0.75},
                                        "compat": {"present": True, "value": 0.0}}},
        "index_truncated": False, "updated_at": "2026-09-14T00:00:00Z",
    }
    f["pipeline"]["selective"]["count"] = 3
    f["pipeline"]["idle_compat_warn"]["count"] = 1
    f.update(over)
    return f


def _stub(page, *, available=True, fleet=None, rows=None):
    body = {"ok": True, "available": available,
            "fleet": {} if not available else (fleet if fleet is not None else _fleet()),
            "next_run_at": "2026-09-14T00:05:00Z"}

    def _json(route, payload):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    page.route("**/api/fleet", lambda r: _json(r, body))
    page.route("**/api/fleet/list*", lambda r: _json(r, {
        "ok": True, "bucket": "selective",
        "total": len(rows if rows is not None else _index()),
        "rows": rows if rows is not None else _index(),
        "index_truncated": bool((fleet or {}).get("index_truncated"))}))


def _goto(page, base_url):
    page.goto(base_url + "/" + ROUTE)
    page.wait_for_selector('[data-route="%s"]' % ROUTE, timeout=20000)


# ── 冷載入 ───────────────────────────────────────────────────────────────────

def test_the_page_mounts_with_all_four_anchors_and_a_nav_entry(v2_page):
    page, base_url = v2_page
    _stub(page)
    _goto(page, base_url)
    for cov in ("IV-16", "IV-17", "IV-18", "IV-19"):
        assert page.locator('[data-cov="%s"]' % cov).count(), "缺 anchor %s" % cov
    labels = _labels(page)
    nav = page.locator('a[href="%s"]' % ROUTE)
    assert nav.count(), "左導覽沒有這一頁"
    assert labels["gui_nav_fleet"] in nav.first.inner_text()


def test_no_snapshot_renders_no_numbers_at_all(v2_page):
    """「還沒分析過」不是「0 台」。

    這一頁沒有快照時只能說「還不知道」——渲染任何計數都是在回答一個沒有
    答案的問題。斷言方式是掃整塊有沒有出現數字，而不是找某一個 0：後者
    只要改個版面就失效。
    """
    page, base_url = v2_page
    _stub(page, available=False)
    _goto(page, base_url)
    labels = _labels(page)
    box = page.locator('.board .empty')
    box.wait_for(state="visible")
    text = box.inner_text()
    assert labels["gui_fleet_no_snapshot"] in text
    import re
    # next_run_at 的時間戳本身有數字，所以只看說明那兩段
    head = text.split("2026")[0]
    assert not re.search(r"\d", head), "沒有快照卻渲染了數字：%r" % head


def test_a_partial_score_names_the_parts_it_left_out(v2_page):
    """只說「部分資料」等於說「這個數字有條件」但不說是什麼條件。"""
    page, base_url = v2_page
    _stub(page)
    _goto(page, base_url)
    labels = _labels(page)
    card = page.locator('[data-cov="IV-16"]')
    card.wait_for(state="visible")
    text = card.inner_text()
    assert labels["gui_fleet_partial"] in text
    version_word = page.evaluate(
        "async () => { const { t } = await import('/static/js/v2/core/i18n.mjs'); "
        "return t('gui_fleet_c_version'); }")
    # 斷言「那個詞出現在說明句裡」，不是「出現在整張卡裡」——版本卡就在隔壁，
    # 後者只要卡片列的任何地方提到版本就綠（注入實測：拿掉缺項名單仍全綠）。
    prefix = page.evaluate(
        "async () => { const { tf } = await import('/static/js/v2/core/i18n.mjs'); "
        "return tf('gui_fleet_partial_missing', { names: '\u0000' }).split('\u0000')[0]; }")
    assert prefix and prefix in text, "缺項說明整句不見了"
    after = text.split(prefix, 1)[1]
    assert version_word in after.split("\n")[0], (
        "說了「部分資料」卻沒點名缺的分量：%r" % after.split("\n")[0])


def test_an_unset_target_links_to_where_it_is_set(v2_page):
    page, base_url = v2_page
    _stub(page)
    _goto(page, base_url)
    labels = _labels(page)
    card = page.locator('[data-cov="IV-16"]')
    card.wait_for(state="visible")
    assert labels["gui_fleet_target_unset"] in card.inner_text()
    assert card.locator('a[href="#/system/pce"]').count(), "沒有指向設定它的地方"


def test_a_truncated_index_says_so_instead_of_looking_empty(v2_page):
    """index 被 cap 掉時清單是空的，但那不是「這個桶沒有東西」。"""
    page, base_url = v2_page
    f = _fleet(index_truncated=True)
    _stub(page, fleet=f, rows=[])
    _goto(page, base_url)
    labels = _labels(page)
    host = page.locator('[data-cov="IV-17"]')
    host.wait_for(state="visible")
    assert labels["gui_fleet_index_truncated"] in host.inner_text()


# ── 推進抽屜 ─────────────────────────────────────────────────────────────────


# ── 唯讀 ─────────────────────────────────────────────────────────────────────

def test_the_page_offers_no_way_to_change_enforcement(v2_page):
    """VEN 盤點只看不改：頁面上沒有推進按鈕，也不送任何非 GET 的請求。"""
    page, base_url = v2_page
    _stub(page)
    writes = []
    page.on("request", lambda req: writes.append(req.url)
            if req.method != "GET" and "/api/fleet" in req.url else None)
    _goto(page, base_url)
    page.wait_for_selector('[data-cov="IV-17"]', timeout=10000)
    assert page.locator('[data-field="open_progress"]').count() == 0
    assert page.locator('[data-cov="IV-20"]').count() == 0
    assert writes == []
