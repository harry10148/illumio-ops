"""spec §7.3：v3 主場景六步，對**真的部署**走一遍並逐步截圖。

為什麼要有這一支：in-process 的 e2e 套件（`tests/v2_e2e_utils.py`）把 PCE 指向
一個關閉的埠，所以它能驗 DOM 與路由，但驗不到「這台機器上真的有告警、點進去
真的有東西」。主場景恰恰是一條**跨頁而且依賴資料**的路徑——它斷在哪裡，只有
真機知道。

六步與落點（2026-09-07 對測試機實測確認，不是照設計稿）：

| 步 | 路由 | 錨點 |
|---|---|---|
| 1 | `#/home` | `HM-00` 未處理告警數＋`HM-06` 儀表 |
| 2 | `#/investigate/alerts` | `AT-01` 告警清單 |
| 3 | `#/investigate/alerts?id=<n>` | `AT-03` 告警頁四段 |
| 4 | 同上 | `AT-04` 規則判定欄 |
| 5 | `#/investigate/traffic?alert=<n>` | `AT-06` 條件來源說明＋`IV-01` |
| 6 | 回告警頁 | `AT-05` 行動列 |

v3 §3.1 的「步進＋上下文條」不在畫面上——v3.1 修訂砍掉了它
（`investigate.mjs`：“The strip, the stepper and the investigation flow they
belonged to are gone.”）。照舊稿寫的走查會對著不存在的 UI 斷言。

**告警 id 不寫死**：從告警清單的第一列取，走查因此也順帶驗證了清單那一列真的是
連結、真的指向那一件。寫死 id 會讓這支測試在資料輪替後靜默失效。

2026-09-08：第 1 步原本錨在首頁的「最近的告警」（`HM-01`）並從那裡取 id。那份
清單依使用者要求移除了，所以第 1 步改成驗首頁仍然回答得出「有沒有事要做」
（`HM-00` 的數字與 `HM-06` 的儀表），id 改由第 2 步的清單提供。這一支不在 CI 裡，
壞掉不會有訊號，所以錨點跟著搬是移除工作的一部分，不是之後再說的事。
"""
from __future__ import annotations

import json
import os
import pathlib
import re

import pytest

_BASE = os.environ.get("ILLUMIO_OPS_E2E_BASE_URL")

#: 事件事實那一列的標籤，從 app 自己讀的同一份 i18n 取，不要在測試裡另打一份中文
#: 字串——那會在改文案時變成第二個要維護的地方，而且對不上時給的是難解的失敗。
_EVENT_ACTOR_LABEL = json.loads(
    (pathlib.Path(__file__).parent.parent / "src" / "i18n_zh_TW.json")
    .read_text(encoding="utf-8"))["gui_al_ev_actor"]
_SHOTS = pathlib.Path(
    os.environ.get("ILLUMIO_OPS_E2E_SHOT_DIR", "tmp/phase3d-verification/shots"))


def _step(page, n: int, name: str) -> None:
    _SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(_SHOTS / f"step{n}-{name}.png"), full_page=True)


def _anchor(page, cov: str) -> None:
    assert page.locator(f'[data-cov="{cov}"]').count() >= 1, (
        f"{cov} 不在畫面上；主場景這一步的落點變了，或這一頁根本沒渲染出來")


@pytest.mark.skipif(not _BASE, reason="Set ILLUMIO_OPS_E2E_BASE_URL to enable live Playwright run")
def test_the_main_scenario_walks_end_to_end():
    from playwright.sync_api import sync_playwright

    base = _BASE.rstrip("/")
    user = os.environ.get("ILLUMIO_OPS_E2E_USER", "illumio")
    password = os.environ.get("ILLUMIO_OPS_E2E_PASSWORD", "illumio")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(ignore_https_errors=True,
                                    viewport={"width": 1280, "height": 900})
            page.goto(base + "/login", wait_until="domcontentloaded")
            page.fill('[data-cov="LG-01"] input[data-field="username"]', user)
            page.fill('[data-cov="LG-01"] input[data-field="password"]', password)
            page.click('[data-cov="LG-01"] button.btn.primary')
            # 等 URL 離開 /login，不要等 body[data-booted]：login.mjs 在登入頁自己
            # 就會設 data-booted，那個條件在按下去的瞬間已經成立，分不出「已登入」
            # 與「還在表單上」。
            page.wait_for_url(lambda url: "/login" not in url, timeout=20000)

            # ── 步驟 1：首頁看到「還沒處理的告警」 ─────────────────────────
            page.goto(base + "/#/home")
            page.wait_for_selector('body[data-booted="true"]', timeout=20000)
            page.wait_for_selector('[data-cov="HM-00"]', timeout=20000)
            _anchor(page, "HM-00")
            _anchor(page, "HM-06")
            # 首頁的職責是回答「現在有沒有事要做」。標題那個數字若是 —，代表
            # /api/alerts 掛了，不是「沒有告警」——那種情況要當場停，不要讓走查
            # 帶著壞掉的前提往下走。
            headline = page.locator('[data-cov="HM-00"]').inner_text()
            assert "—" not in headline, (
                f"首頁未處理告警數是 —，代表 /api/alerts 沒回應：{headline!r}")
            _step(page, 1, "home")

            # ── 步驟 2：告警清單 ─────────────────────────────────────────
            page.goto(base + "/#/investigate/alerts")
            page.wait_for_selector('[data-cov="AT-01"]', timeout=20000)
            _anchor(page, "AT-01")
            # 走查要走進「某一件」告警，id 從清單第一列取——寫死會在資料輪替後
            # 靜默失效。
            row = page.locator('[data-cov="AT-01"] a[href*="alerts?id="]')
            assert row.count() >= 1, (
                "告警清單一則都沒有——這台機器上沒有告警資料，主場景走不下去。"
                "不是版面問題，先確認 logs/alerts.sqlite 有內容。")
            href = row.first.get_attribute("href") or ""
            _step(page, 2, "alert-list")

            # ── 步驟 3：告警頁 ───────────────────────────────────────────
            m = re.search(r"id=(\d+)", href)
            assert m, f"清單那一列的連結沒有帶 id：{href!r}"
            alert_id = m.group(1)
            page.goto(base + "/#/investigate/alerts?id=" + alert_id)
            page.wait_for_selector('[data-cov="AT-03"]', timeout=20000)
            _anchor(page, "AT-03")
            _anchor(page, "AT-02")   # 狀態切換 new/ack/done
            _step(page, 3, "alert-detail")

            # ── 步驟 4：這一頁要說「是什麼在跟什麼講話」 ─────────────────
            #
            # 兩種形狀，看告警型別而定，**不是**兩選一的寬鬆斷言：
            #   · traffic／bandwidth 告警 → `AT-04` 流量表，右欄逐列回填 PCE 判定
            #   · event／system 告警    → 事件事實（操作者／動作／資源）
            # 舊版無條件斷言 AT-04，那正好是這次修掉的缺陷所要求的畫面——
            # 事件被當成流量渲染。所以這裡斷言的是**這一步的目的**，並且要求
            # 兩種形狀至少有一種真的在畫面上（都沒有就是紅）。
            body = page.locator('[data-cov="AT-03"]')
            page.wait_for_selector('[data-cov="AT-03"]', timeout=30000)
            has_flows = page.locator('[data-cov="AT-04"]').count() >= 1
            if has_flows:
                shape = "rule-verdict"
            else:
                shape = "event-facts"
                text = body.text_content() or ""
                assert _EVENT_ACTOR_LABEL in text, (
                    "這則告警沒有流量表，也沒有事件事實——"
                    f"「誰在跟誰講話」整段不見了。畫面內容：{text[:200]!r}")
            _step(page, 4, shape)

            # ── 步驟 5：帶著這則告警去流量搜尋 ───────────────────────────
            page.goto(base + "/#/investigate/traffic?alert=" + alert_id)
            page.wait_for_selector('[data-cov="AT-06"]', timeout=30000)
            _anchor(page, "AT-06")   # 條件來自哪一則告警，附回告警的連結
            # 等，不是直接斷言：查詢面板是這一頁自己再跑一次載入才出現的，
            # AT-06 先到並不代表 IV-01 已經到。直接斷言會抓到一個時序假紅。
            page.wait_for_selector('[data-cov="IV-01"]', timeout=30000)
            _anchor(page, "IV-01")   # 查詢與 KPI
            back = page.locator('[data-cov="AT-06"] a[href*="alerts?id="]')
            assert back.count() >= 1, "條件來源那一行沒有回告警的連結，第 6 步就退不回去"
            _step(page, 5, "traffic-from-alert")

            # ── 步驟 6：回告警頁，行動列 ─────────────────────────────────
            page.goto(base + "/#/investigate/alerts?id=" + alert_id)
            page.wait_for_selector('[data-cov="AT-05"]', timeout=20000)
            _anchor(page, "AT-05")
            _step(page, 6, "actions")
        finally:
            browser.close()
