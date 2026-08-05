"""放行前終局檢查：覆蓋 100%、lint 乾淨、tour 齊全。

這一族測試是 Phase 1 的最後一道閘：前面每個 task 各自的守門測試管自己的區，
這裡管的是「交付包本身」——覆蓋 gate 真的跑得過、mockup 沒有手寫資料、
而導覽頁確實把每一條路由、每一個功能錨點、每一張截圖都帶到了。
"""
import pathlib
import re
import subprocess
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOUR = ROOT / "design" / "v2" / "tour" / "tour.html"
SHOTS = ROOT / "design" / "v2" / "tour" / "shots"


def _coverage() -> dict:
    return yaml.safe_load((ROOT / "design/v2/coverage.yaml").read_text())


def _tour_text() -> str:
    assert TOUR.exists(), f"tour.html 不存在：{TOUR}（先跑 python3 design/v2/tools/tour.py）"
    return TOUR.read_text()


def test_coverage_gate_green():
    pytest.importorskip("playwright.sync_api", exc_type=ImportError)
    r = subprocess.run(
        [sys.executable, "design/v2/tools/gate_coverage.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_lint_clean():
    r = subprocess.run(
        [sys.executable, "design/v2/tools/lint_no_inline_data.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout


def test_tour_has_all_routes():
    cov = _coverage()
    tour = _tour_text()
    for route in {v["route"] for v in cov.values()}:
        assert route in tour, f"tour missing {route}"


def test_tour_references_every_coverage_id():
    """每個 cov ID 都要在導覽頁上被點名——不然使用者無從知道它被做在哪一頁。"""
    tour = _tour_text()
    missing = [cid for cid in _coverage() if cid not in tour]
    assert not missing, f"tour 沒有提到這些功能錨點：{missing}"


def test_tour_shots_exist_for_every_route():
    """每條路由至少亮/暗兩張；導覽頁引用到的每一張圖都得真的在磁碟上。"""
    routes = {v["route"] for v in _coverage().values()}
    shots = sorted(p.name for p in SHOTS.glob("*.png"))
    assert len(shots) >= len(routes) * 2, f"截圖只有 {len(shots)} 張，少於 {len(routes)} 條路由 × 2"

    referenced = set(re.findall(r'(?:src|href)="(shots/[^"]+)"', _tour_text()))
    assert referenced, "tour.html 沒有引用任何截圖"
    absent = sorted(r for r in referenced if not (TOUR.parent / r).exists())
    assert not absent, f"tour.html 引用了不存在的截圖：{absent}"

    # 亮/暗/審視態三態齊全（檔名由 tour.py 的 Variant.shot 決定）
    for state in ("light", "dark", "audit"):
        n = len([s for s in shots if s.endswith(f"--{state}.png")])
        assert n >= len(routes), f"{state} 只有 {n} 張，少於 {len(routes)} 條路由"


def test_tour_is_self_contained():
    """交付物要能離線開：不得引用任何外部主機的資源。"""
    tour = _tour_text()
    external = re.findall(r'(?:src|href)="(https?://[^"]+)"', tour)
    assert not external, f"tour.html 引用了外部資源：{external}"


def test_tour_links_the_companion_deliverables():
    """重排報表、CLI 流程稿、覆蓋清單都要從導覽頁走得到，而且檔案真的在。"""
    tour = _tour_text()
    for rel in (
        "../reports/reskinned/traffic.html",
        "../reports/reskinned/traffic.pdf",
        "../reports/reskinned/audit.html",
        "../reports/reskinned/audit.pdf",
        "../cli-flows.md",
        "../coverage.yaml",
    ):
        assert f'href="{rel}"' in tour, f"tour.html 少了連結：{rel}"
        assert (TOUR.parent / rel).exists(), f"連結指向不存在的檔案：{rel}"


def test_tour_documents_how_to_run_the_mockup():
    tour = _tour_text()
    assert "http.server 8378" in tour and "design/v2/mockup" in tour


AREAS = ROOT / "design" / "v2" / "mockup" / "js" / "areas"

# 這些 section-head key 標的都是「畫面收什麼／後端收到什麼」的對照面板：本
# mockup 為了讓審閱者驗證映射而加的裝置，Phase 2 不會做進產品。一律要帶
# 驗證面板標記（js/components/verifypane.mjs）。
_PREVIEW_PANE_KEYS = {
    "v2_al_payload", "v2_rp_payload", "v2_sy_payload", "v2_iv_payload",
    "v2_lg_request", "v2_au_note_preview",
}
# 對照組：產品本來就有的資料面（事件原始 JSON、DLQ 明細、模組日誌）。這些會
# 隨產品出貨，標上「實作不出現」反而是假話——刻意不標。
_PRODUCT_DATA_PANE_KEYS = {
    "gui_ev_parsed_event", "gui_ev_raw_event", "gui_dlq_dt_reason",
    "gui_dlq_dt_payload", "v2_sy_log_msg", "v2_sy_log_raw",
}


def _panes_by_key(keys):
    """回傳 {key: [該 key 出現處往後 4 行的原始碼]}，用來檢查有沒有接上
    verifyPane()。掃原始碼而非 DOM，是因為這條不變量要在改動當下就擋住，
    不是等到有人跑瀏覽器才發現。"""
    found = {}
    for path in sorted(AREAS.glob("*.mjs")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            for key in re.findall(r't\("([a-z0-9_]+)"\)', line):
                if key in keys:
                    found.setdefault(key, []).append((path.name, i + 1,
                                                      "\n".join(lines[i:i + 4])))
    return found


def test_request_preview_panes_are_badged_as_verification_panes():
    found = _panes_by_key(_PREVIEW_PANE_KEYS)
    assert set(found) == _PREVIEW_PANE_KEYS, \
        f"預覽面板 key 對不上原始碼：{_PREVIEW_PANE_KEYS - set(found)}"
    for key, sites in found.items():
        for name, line, window in sites:
            assert "verifyPane(" in window, f"{name}:{line} {key} 沒有驗證面板標記"


def test_product_data_panes_are_not_badged_as_samples():
    found = _panes_by_key(_PRODUCT_DATA_PANE_KEYS)
    assert set(found) == _PRODUCT_DATA_PANE_KEYS, \
        f"資料面 key 對不上原始碼：{_PRODUCT_DATA_PANE_KEYS - set(found)}"
    for key, sites in found.items():
        for name, line, window in sites:
            assert "verifyPane(" not in window, \
                f"{name}:{line} {key} 是產品真有的資料面，不可標成「實作不出現」"


def test_verification_badge_key_is_bilingual():
    import json
    keys = json.loads((ROOT / "design/v2/mockup/i18n-supplement.json")
                      .read_text(encoding="utf-8"))["keys"]
    entry = keys["v2_verify_pane"]
    assert entry["zh"] and entry["en"]


def test_health_rail_is_scoped_to_the_overview_route():
    """spec §1.1（Gate 2 修訂）：健康列只在 #/overview 出現。app.mjs 用「掛上／
    卸下」而非隱藏——hidden 會被任何 display 規則蓋掉（本 repo 踩過），而只是
    看不見的元素仍會被覆蓋 gate 的 [data-cov] 掃到。"""
    app = (ROOT / "design/v2/mockup/js/app.mjs").read_text(encoding="utf-8")
    assert 'HEALTH_ROUTE = "#/overview"' in app
    assert "syncRail(" in app and "removeChild(railNode)" in app
    assert not re.search(r"\.hidden\s*=", app), \
        "健康列不可改用 hidden 收起（會被 display 規則蓋掉）"
    cov = _coverage()
    assert cov["XC-01"]["route"] == "#/overview"
