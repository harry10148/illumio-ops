"""操作者手冊寫的路由，必須是這個產品真的有的路由。

`scripts/check_doc_links.py` 驗的是「連結指向的檔案存在」，它看不到散文裡的
`#/alerting/rules` 這種字串——那不是連結，是說明文字。所以 v2 六區改成 v3 五區
之後，`docs/guide/gui-tour.md` 有 11 處還在教人去已經不存在的地方（含
`#/investigate/inbox`，v3.1 已經把它轉址掉了），而所有既有閘門都是綠的。

**路由表從 `shell.mjs` 的 `NAV` 解析，不在這裡再打一份。** NAV 同時是左側選單、
麵包屑與 `labelForRoute()` 的來源；在測試裡複製一份路由清單，等於製造第二個會
落後的事實來源，而那正是這條守門要防的事。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SHELL = REPO_ROOT / "src" / "static" / "js" / "v2" / "shell.mjs"
TOUR = REPO_ROOT / "docs" / "guide" / "gui-tour.md"

#: 散文裡出現、但不是「一條路由」的字串，逐條寫明為什麼放行。
#: 空的才是預期狀態——有東西就代表有人想寫一個不存在的路由又不想改。
_ALLOWED_NON_ROUTES: dict[str, str] = {}

#: 手冊刻意會提到已退役的路由（router 真的會轉址的舊書籤）。那一段用註解標出，
#: 掃描前整段拿掉——差別在於「這是現在該去的地方」還是「這是以前的地方」，
#: 而那個差別在文件裡是有標記的，不必靠猜。
_LEGACY_BLOCK = re.compile(
    r"<!--\s*legacy-routes:.*?<!--\s*/legacy-routes\s*-->", re.S)


def nav_routes() -> set[str]:
    """`shell.mjs` 的 NAV 宣告裡所有的 `#/…` 字面量。"""
    src = SHELL.read_text(encoding="utf-8")
    start = src.index("export const NAV")
    end = src.index("\n];", start)
    routes = set(re.findall(r'"(#/[^"]*)"', src[start:end]))
    assert len(routes) >= 15, f"NAV 只解析出 {len(routes)} 條路由，解析壞了"
    return routes


def test_every_route_the_tour_names_is_a_route_the_app_has():
    routes = nav_routes()
    text = _LEGACY_BLOCK.sub("", TOUR.read_text(encoding="utf-8"))
    used = sorted(set(re.findall(r"#/[A-Za-z0-9/_\-]+", text)))

    def ok(candidate: str) -> bool:
        if candidate in routes or candidate in _ALLOWED_NON_ROUTES:
            return True
        # 區域前綴：散文常寫「系統區（`#/system/`）」指整個區，不是某一頁。
        # 只有在它真的是某條路由的前綴時才放行——`#/alerting/` 不是任何路由的
        # 前綴，所以照樣會被抓到。
        return any(r.startswith(candidate) for r in routes)

    strays = [c for c in used if not ok(c)]
    assert not strays, (
        "手冊寫了這個產品沒有的路由——操作者照著找會找不到，而且 check_doc_links "
        "看不到散文裡的路由字串：\n  " + "\n  ".join(strays))


def test_the_tour_covers_every_area_the_nav_offers():
    """反向：NAV 有的區，手冊要提到。

    只驗「手冊寫的路由存在」是單向的——整個區漏掉不寫，那條照樣綠。
    """
    text = TOUR.read_text(encoding="utf-8")
    src = SHELL.read_text(encoding="utf-8")
    start = src.index("export const NAV")
    end = src.index("\n];", start)
    areas = re.findall(r'id:\s*"([a-z]+)",\s*key:', src[start:end])
    assert len(areas) == 5, f"NAV 的區域數是 {len(areas)}，不是五區？{areas}"
    missing = [a for a in areas if f"#/{a}" not in text]
    assert not missing, f"手冊沒有提到這些區的任何路由：{missing}"
