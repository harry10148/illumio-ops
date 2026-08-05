"""截圖導覽產生器（Task 15）。

起本機 http.server 服務 design/v2/mockup，用 Playwright 走 coverage.yaml 的每一條
路由（外加 login.html 的兩個 demo 變體）× 亮/暗主題，逐畫面全頁截圖；再對每條路由
呼叫 window.__openAllForAudit() 拍一張「審視態」（所有抽屜／彈窗同時開啟）。

最後把截圖、coverage.yaml 反查出來的功能錨點清單、以及每條路由的一句功能說明，
組成 design/v2/tour/tour.html —— 一份自足（相對路徑引用）的交付導覽。

用法：
    python3 design/v2/tools/tour.py            # 截圖 + 產生 tour.html
    python3 design/v2/tools/tour.py --html-only  # 只重產 tour.html（沿用既有截圖）
"""
from __future__ import annotations

import datetime
import html
import pathlib
import subprocess
import sys
import time

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
MOCKUP = ROOT / "mockup"
TOUR = ROOT / "tour"
SHOTS = TOUR / "shots"
PORT = 8379  # 8378 是文件裡給人用的互動埠，這裡另開一個避免打架
VIEWPORT = {"width": 1440, "height": 900}

# ── 六區 + 登入的分組（順序即 tour 的閱讀順序，與 shell.mjs 的 AREAS 一致）──────
AREAS = [
    ("overview", "總覽", "開機第一眼：這台機器現在好不好、接下來該做什麼。"),
    ("investigate", "調查", "查流量、查 workload、查事件——所有「發生了什麼」的問題都在這一區。"),
    ("alerting", "告警", "規則怎麼寫、怎麼測、怎麼送出去。"),
    ("automation", "自動化", "排程器與背景工作：不用人在場也會跑的東西。"),
    ("reports", "報表", "11 型報表的產生、參數、進度與產出管理。"),
    ("system", "系統", "連線、快取、轉送、憑證、外觀——設定都收在這裡。"),
    ("login", "登入", "進門與出門。"),
]

# 每條路由一句功能說明（zh-TW）。key = 路由變體 slug。
BLURBS = {
    "overview": "系統狀態、posture score、待辦動作與近期事件收在同一頁；健康列只出現在本頁（頂欄下方），離開總覽就收起來。",
    "investigate-traffic": "流量分析器：選視窗與來源（即時快取／Archive），用 FilterBar 收斂條件，看 KPI 與明細分頁。",
    "investigate-workloads": "workload 搜尋與隔離：單台套用、批次套用、解除隔離；破壞性動作一律先出影響摘要再確認。",
    "investigate-events": "事件檢視器：三層事件分類目錄、逐批載入詳情，並可與影子規則的判定結果對照。",
    "alerting-rules": "告警規則清單與四型編輯抽屜（事件／系統健康／流量／頻寬），改完可用沙盤測試先跑一次。",
    "alerting-ops": "告警運維台：單次執行、debug 模式、測試送出、水位重置、最佳實務套用，輸出直接落在主控台。",
    "automation-rules": "規則排程器：狀態列與時間軸交代下一次何時跑，ruleset／rule 兩層都能各自排程並與 PCE 對帳。",
    "automation-reports": "報表排程：清單增修刪、啟停、立即執行，以及每一筆的執行歷史。",
    "automation-jobs": "背景工作的健康與歷史（唯讀），可只列出異常的那幾筆。",
    "reports": "11 型報表卡、產生抽屜的型專屬參數、統一進度元件，以及產出清單的下載、瀏覽與刪除。",
    "system-pce": "PCE profile 的新增、切換與連線測試；設定列會追蹤未儲存的變更，離開前擋你一下。",
    "system-cache": "快取設定與狀態、lag 列、retention 立即執行、流量過濾器（含 IP 驗證）與取樣設定。",
    "system-siem": "SIEM forwarder 與目的地設定、測試送出，以及 DLQ 的搜尋、回放、匯出與清除。",
    "system-tls": "TLS 憑證狀態、續期、CSR 產生與憑證匯入。",
    "system-security": "認證與 session 的安全設定，以及 GUI 停止。",
    "system-display": "顯示偏好：主題、密度、時區、語言——每一項切換都立刻反映在整個介面上。",
    "system-channels": "五種告警管道的連線設定；憑證欄位一律遮罩後顯示。",
    "system-logs": "模組日誌檢視器：挑模組、篩層級、看尾端輸出。",
    "login": "登入表單本身：帳號、密碼、錯誤訊息。",
    "login-first-login": "首次登入強制改密碼的分支，含密碼規則檢核。",
    "login-signed-out": "登出後回到登入頁的狀態，會說明你是被登出的還是自己離開的。",
}

# 六區之外的分組標題（cov 前綴 → 中文名），用於摘要表
PREFIX_NAMES = {
    "OV": "總覽",
    "IV": "調查",
    "AL": "告警",
    "AU": "自動化",
    "RP": "報表",
    "SY": "系統",
    "LG": "登入",
    "XC": "跨區元件",
}

STATES = [("light", "亮"), ("dark", "暗"), ("audit", "審視態")]

# 導覽的閱讀順序 = 產品自己的導覽順序（shell.mjs AREAS ＋ 各區 SUB_ROUTES）。
ROUTE_ORDER = [
    "#/overview",
    "#/investigate/traffic",
    "#/investigate/workloads",
    "#/investigate/events",
    "#/alerting/rules",
    "#/alerting/ops",
    "#/automation/rules",
    "#/automation/reports",
    "#/automation/jobs",
    "#/reports",
    "#/system/pce",
    "#/system/cache",
    "#/system/siem",
    "#/system/tls",
    "#/system/security",
    "#/system/display",
    "#/system/channels",
    "#/system/logs",
    "login.html",
]


# ── 路由與變體 ────────────────────────────────────────────────────────────────
class Variant:
    """一個要截圖的畫面：路由 + 可選的 demo 查詢字串。"""

    def __init__(self, route: str, query: str = "", slug: str = "", area: str = ""):
        self.route = route          # coverage.yaml 裡的路由字串（測試用它比對）
        self.query = query          # login.html 的 ?demo=... 變體
        self.slug = slug            # 檔名與 DOM id
        self.area = area            # 所屬區

    def url(self, base: str, nonce: int = 0) -> str:
        """Hash 路由之間的 goto 是同文件導覽（不重新載入），畫面會停在上一頁的掛載
        結果上。帶一個唯一的 query 參數強制每張截圖都從乾淨的開機狀態出發。"""
        if self.route.endswith(".html"):
            sep = "&" if self.query else "?"
            return f"{base}/{self.route}{self.query}{sep}shot={nonce}"
        return f"{base}/index.html?shot={nonce}{self.route}"

    def shot(self, state: str) -> str:
        return f"{self.slug}--{state}.png"


def slug_of(route: str) -> str:
    return route.replace("#/", "").replace("/", "-").replace(".html", "") or "index"


def area_of(route: str) -> str:
    if route.endswith(".html"):
        return "login"
    return route.replace("#/", "").split("/")[0]


def coverage() -> dict:
    return yaml.safe_load((ROOT / "coverage.yaml").read_text())


def variants() -> list[Variant]:
    """coverage.yaml 的每一條路由，外加 login.html 的兩個 demo 變體。

    順序刻意寫死成產品自己的導覽順序（shell.mjs 的 AREAS ＋ 各區 SUB_ROUTES），
    不是字典序——導覽要照使用者實際走的路讀。與 coverage.yaml 對帳，新增路由沒
    排進來就直接報錯，不會默默漏一頁。
    """
    listed = {v["route"] for v in coverage().values()}
    if set(ROUTE_ORDER) != listed:
        raise SystemExit(
            f"ROUTE_ORDER 與 coverage.yaml 不一致：少了 {sorted(listed - set(ROUTE_ORDER))}，"
            f"多了 {sorted(set(ROUTE_ORDER) - listed)}"
        )
    out = []
    for r in ROUTE_ORDER:
        out.append(Variant(r, "", slug_of(r), area_of(r)))
        if r == "login.html":
            out.append(Variant(r, "?demo=first-login", "login-first-login", "login"))
            out.append(Variant(r, "?demo=signed-out", "login-signed-out", "login"))
    return out


def by_route() -> dict[str, list[tuple[str, str]]]:
    """路由 → [(cov id, 功能名)]，即 coverage.yaml 的反查索引。"""
    idx: dict[str, list[tuple[str, str]]] = {}
    for cid, row in coverage().items():
        idx.setdefault(row["route"], []).append((cid, row["item"]))
    for rows in idx.values():
        rows.sort()
    return idx


# ── 截圖 ──────────────────────────────────────────────────────────────────────
def _settle(pg, variant: Variant):
    """等到畫面真的長出來——不是等固定秒數。"""
    if variant.route.endswith(".html"):
        pg.wait_for_selector("#login-root form, #login-root .loginbox, #login-root *", timeout=15000)
    else:
        pg.wait_for_selector('body[data-booted="true"]', timeout=30000)
    pg.wait_for_timeout(700)
    # 全頁截圖對 position:fixed 的處理是「只畫在第一個視窗高度上」，所以設定頁的
    # 儲存列會橫切在頁面中央，看起來像破圖。它本來就有一個 .savedock 佔位在流內，
    # 截圖時改用流內定位，畫出來的位置與實際捲到底時看到的一致。
    pg.add_style_tag(content=".savebar { position: static !important; }")


def capture(base: str, vs: list[Variant]) -> dict[str, dict]:
    """走完所有變體 × 亮/暗，外加暗色的審視態。回傳每個變體的畫面標題資訊。"""
    from playwright.sync_api import sync_playwright

    meta: dict[str, dict] = {}
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in ("light", "dark"):
            ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
            ctx.add_init_script(
                "try { localStorage.setItem('ov2.theme', %r);"
                " localStorage.setItem('ov2.density', 'cozy'); } catch (e) {}" % theme
            )
            pg = ctx.new_page()
            for n, v in enumerate(vs):
                pg.goto(v.url(base, n))
                _settle(pg, v)
                pg.screenshot(path=str(SHOTS / v.shot(theme)), full_page=True)
                if theme == "dark":
                    meta[v.slug] = pg.evaluate(
                        """() => {
                          const h1 = document.querySelector('.area-head h1');
                          const cur = document.querySelector('.subnav a[aria-current="page"]');
                          return {
                            area: h1 ? h1.textContent.trim() : '',
                            tab: cur ? cur.textContent.trim() : '',
                            title: document.title,
                          };
                        }"""
                    )
                    res = pg.evaluate("window.__openAllForAudit ? window.__openAllForAudit() : null")
                    meta[v.slug]["opened"] = (res or {}).get("opened", 0)
                    pg.wait_for_timeout(600)
                    # 指令面板與使用者選單是全域面，openAll 會在每一頁都打開它們，蓋住該頁
                    # 自己的抽屜。coverage.yaml 把 XC-02/XC-13 掛在 #/overview，所以只有
                    # 總覽的審視態留著它們，其餘各頁把版面讓回給本頁的抽屜。
                    if v.route != "#/overview":
                        pg.evaluate(
                            """() => {
                              const p = document.querySelector('.palette-wrap');
                              if (p) p.hidden = true;
                              const m = document.querySelector('.usermenu-pop');
                              if (m && m.parentNode) m.parentNode.removeChild(m);
                            }"""
                        )
                    pg.evaluate("window.scrollTo(0, 0)")
                    pg.screenshot(path=str(SHOTS / v.shot("audit")), full_page=True)
            ctx.close()
        browser.close()
    return meta


def serve():
    return subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT), "-d", str(MOCKUP)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ── tour.html ────────────────────────────────────────────────────────────────
def e(s) -> str:
    return html.escape(str(s), quote=True)


CSS = """
/* design/v2/tour — Direction B「Ops dark console」的紙本分身。
   token 值逐字抄自 design/v2/mockup/assets/tokens.css，維持同一套視覺 DNA。 */
:root {
  --font-ui: "Noto Sans", "Noto Sans CJK TC", "PingFang TC", "Microsoft JhengHei", sans-serif;
  --font-mono: "Noto Sans Mono", "DejaVu Sans Mono", "SFMono-Regular", Consolas, monospace;
  --radius-s: 2px; --radius-m: 3px; --radius-l: 6px;

  --surface-0: #0B0E13; --surface-1: #151A21; --surface-2: #1B212A;
  --text-1: #E6EAF0; --text-2: #9AA4B2; --text-3: #6E7A8A;
  --line: #232A34; --line-soft: #1D242D; --track: #1E252F;
  --accent: #3987e5; --accent-fg: #6da7ec; --accent-on: #FFFFFF;
  --chrome: #0E1218; --chrome-edge: #000000;
  --chrome-text-1: #FFFFFF; --chrome-text-2: #8C97A8; --chrome-text-3: #6B7788;
  --chrome-line: rgba(255,255,255,.09); --chrome-hover: rgba(255,255,255,.05);
  --shadow-1: 0 1px 2px rgba(0,0,0,.45); --shadow-2: 0 14px 40px rgba(0,0,0,.58);
  --ok: #0ca30c; --ok-fg: #3ec93e; --ok-bg: #0F2A14;
  --warn: #fab219; --warn-fg: #fab219; --warn-bg: #2E2410;
  --info: #3987e5; --info-fg: #6da7ec; --info-bg: #132437;
  --neutral: #8b929e; --neutral-fg: #9AA4B2; --neutral-bg: #1E242D;
}
:root[data-doc="light"] {
  --surface-0: #EEF1F5; --surface-1: #FFFFFF; --surface-2: #F5F7FA;
  --text-1: #12161C; --text-2: #414B59; --text-3: #6E7A8A;
  --line: #DDE2E9; --line-soft: #E7EBF0; --track: #E9EDF2;
  --accent: #2a78d6; --accent-fg: #1c5cab;
  --shadow-1: 0 1px 2px rgba(18,22,28,.10); --shadow-2: 0 14px 40px rgba(18,22,28,.22);
  --ok-fg: #0a7d0a; --ok-bg: #E4F3E4;
  --warn-fg: #8a5d00; --warn-bg: #FBF0D8;
  --info-fg: #1c5cab; --info-bg: #E3EEFB;
  --neutral-fg: #5c6472; --neutral-bg: #EDF0F4;
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--surface-0); color: var(--text-1);
  font: 13px/1.5 var(--font-ui); -webkit-font-smoothing: antialiased;
}
a { color: var(--accent-fg); text-decoration: none; }
a:hover { text-decoration: underline; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
code, .mono, kbd { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
h1, h2, h3, h4 { margin: 0; font-weight: 600; letter-spacing: -.01em; }
p { margin: 0; }

.eyebrow {
  font-size: 9.5px; letter-spacing: .12em; text-transform: uppercase;
  color: var(--text-3); font-weight: 600;
}

/* ── 頂欄：和產品同一片儀器邊框，換主題也不變色 ───────────────────────── */
.chrome {
  position: sticky; top: 0; z-index: 40;
  background: var(--chrome); border-bottom: 1px solid var(--chrome-edge);
  box-shadow: var(--shadow-1);
}
.chrome-in {
  max-width: 1360px; margin: 0 auto; padding: 0 20px;
  height: 46px; display: flex; align-items: center; gap: 18px;
}
.brand { display: flex; align-items: baseline; gap: 6px; color: var(--chrome-text-1); }
.brand b { font-size: 14px; letter-spacing: -.02em; }
.brand i {
  width: 1px; height: 12px; background: var(--chrome-line);
  display: inline-block; transform: translateY(1px);
}
.brand span { color: var(--chrome-text-2); font-size: 12px; }
.chrome nav { display: flex; gap: 2px; margin-left: auto; flex-wrap: wrap; }
.chrome nav a {
  color: var(--chrome-text-2); padding: 5px 9px; border-radius: var(--radius-m);
  font-size: 12px;
}
.chrome nav a:hover { background: var(--chrome-hover); color: var(--chrome-text-1); text-decoration: none; }
.doctoggle {
  background: transparent; color: var(--chrome-text-2); cursor: pointer;
  border: 1px solid var(--chrome-line); border-radius: var(--radius-m);
  padding: 4px 9px; font: inherit; font-size: 11px;
}
.doctoggle:hover { color: var(--chrome-text-1); background: var(--chrome-hover); }

.wrap { max-width: 1360px; margin: 0 auto; padding: 0 20px 80px; }

/* ── 開場 ───────────────────────────────────────────────────────────────── */
.masthead { padding: 44px 0 28px; border-bottom: 1px solid var(--line); }
.masthead h1 { font-size: 30px; margin: 10px 0 12px; }
.masthead .lead { color: var(--text-2); max-width: 62ch; font-size: 14px; line-height: 1.6; }
.facts { display: flex; flex-wrap: wrap; gap: 0; margin-top: 22px; border: 1px solid var(--line); border-radius: var(--radius-m); overflow: hidden; }
.facts div { padding: 9px 14px; border-right: 1px solid var(--line); background: var(--surface-1); }
.facts div:last-child { border-right: 0; }
.facts dt { font-size: 9.5px; letter-spacing: .12em; text-transform: uppercase; color: var(--text-3); margin: 0 0 3px; }
.facts dd { margin: 0; font-family: var(--font-mono); font-size: 15px; color: var(--text-1); }

/* ── 摘要區 ─────────────────────────────────────────────────────────────── */
.grid2 { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); gap: 20px; margin-top: 26px; }
.panel { border: 1px solid var(--line); border-radius: var(--radius-m); background: var(--surface-1); }
.panel > h3 {
  font-size: 9.5px; letter-spacing: .12em; text-transform: uppercase; color: var(--text-3);
  padding: 9px 14px; border-bottom: 1px solid var(--line); background: var(--surface-2);
}
.panel .body { padding: 14px; display: grid; gap: 10px; }
.panel .body p { color: var(--text-2); line-height: 1.65; }

table.cov { width: 100%; border-collapse: collapse; font-size: 12px; }
table.cov th, table.cov td { padding: 6px 14px; text-align: left; border-bottom: 1px solid var(--line-soft); }
table.cov th { font-size: 9.5px; letter-spacing: .1em; text-transform: uppercase; color: var(--text-3); font-weight: 600; }
table.cov td.n { font-family: var(--font-mono); font-variant-numeric: tabular-nums; text-align: right; }
table.cov tr:last-child td { border-bottom: 0; }
table.cov tfoot td { border-top: 1px solid var(--line); font-weight: 600; color: var(--text-1); }
.bar { display: block; height: 3px; background: var(--track); border-radius: 2px; overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--ok); }

.runbox { font-family: var(--font-mono); font-size: 12px; }
.runbox pre {
  margin: 0; padding: 10px 12px; background: var(--surface-2);
  border: 1px solid var(--line); border-radius: var(--radius-m);
  color: var(--text-1); overflow-x: auto;
}
.linklist { display: grid; gap: 1px; background: var(--line-soft); border: 1px solid var(--line-soft); border-radius: var(--radius-m); overflow: hidden; }
.linklist a { display: flex; gap: 10px; align-items: baseline; padding: 8px 12px; background: var(--surface-1); }
.linklist a:hover { background: var(--surface-2); text-decoration: none; }
.linklist a b { font-weight: 600; color: var(--text-1); font-size: 12px; }
.linklist a small { color: var(--text-3); font-family: var(--font-mono); font-size: 10.5px; margin-left: auto; }

/* ── 區段 ───────────────────────────────────────────────────────────────── */
/* 頂欄是 sticky 的，錨點跳轉要留出它的高度，否則標題會躲到欄後面。 */
.area, .route, .limits { scroll-margin-top: 62px; }
.area { padding-top: 46px; }
.area-head { display: flex; align-items: baseline; gap: 12px; border-bottom: 1px solid var(--line); padding-bottom: 10px; }
.area-head h2 { font-size: 19px; }
.area-head .slug { font-family: var(--font-mono); font-size: 11px; color: var(--text-3); }
.area-head p { color: var(--text-2); margin-left: auto; text-align: right; font-size: 12px; }

.route { margin-top: 22px; border: 1px solid var(--line); border-radius: var(--radius-m); background: var(--surface-1); overflow: hidden; }
.route > header { padding: 12px 16px; border-bottom: 1px solid var(--line); background: var(--surface-2); display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.route > header h3 { font-size: 14px; }
.route > header code { font-size: 11px; color: var(--text-3); }
.route > header .seg { margin-left: auto; }
.route .blurb { padding: 12px 16px 0; color: var(--text-2); line-height: 1.65; max-width: 78ch; }

/* 分段控制：亮 / 暗 / 審視態 */
.seg { display: inline-flex; border: 1px solid var(--line); border-radius: var(--radius-m); overflow: hidden; background: var(--surface-1); }
.seg button {
  font: inherit; font-size: 11px; padding: 4px 11px; cursor: pointer;
  background: transparent; color: var(--text-2); border: 0; border-right: 1px solid var(--line);
  display: inline-flex; align-items: center; gap: 6px;
}
.seg button:last-child { border-right: 0; }
.seg button:hover { background: var(--surface-2); color: var(--text-1); }
.seg button[aria-pressed="true"] { background: var(--accent); color: var(--accent-on); }
.seg button .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; opacity: .55; }
.seg button[aria-pressed="true"] .dot { opacity: 1; }

/* 螢幕框：全頁截圖可在框內自行捲動，不裁切也不撐爆版面 */
.screen { margin: 12px 16px 0; border: 1px solid var(--line); border-radius: var(--radius-m); background: var(--surface-0); overflow: hidden; }
.screen .bezel {
  display: flex; align-items: center; gap: 8px; padding: 5px 10px;
  background: var(--chrome); border-bottom: 1px solid var(--chrome-edge); color: var(--chrome-text-3);
  font-family: var(--font-mono); font-size: 10.5px;
}
.screen .bezel .led { width: 6px; height: 6px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 6px var(--ok); }
.screen .bezel .state { color: var(--chrome-text-1); }
.screen .bezel a { margin-left: auto; color: var(--chrome-text-2); font-size: 10.5px; }
.screen .view { max-height: 78vh; overflow: auto; background: var(--surface-0); }
.screen .view img { display: block; width: 100%; height: auto; }

.thumbs { display: flex; gap: 10px; padding: 12px 16px 0; }
.thumbs button {
  padding: 0; border: 1px solid var(--line); border-radius: var(--radius-s); cursor: pointer;
  background: var(--surface-0); overflow: hidden; width: 132px; text-align: left;
}
.thumbs button:hover { border-color: var(--text-3); }
.thumbs button[aria-pressed="true"] { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.thumbs button span {
  display: block; padding: 3px 6px; font-size: 9.5px; letter-spacing: .08em; text-transform: uppercase;
  color: var(--text-3); border-top: 1px solid var(--line); background: var(--surface-1);
}
.thumbs button[aria-pressed="true"] span { color: var(--text-1); }
.thumbs button .crop { height: 62px; overflow: hidden; }
.thumbs button img { display: block; width: 100%; height: auto; }

/* 功能錨點 */
.covs { padding: 14px 16px 16px; display: grid; gap: 10px; }
.covs .grouphead { font-size: 9.5px; letter-spacing: .12em; text-transform: uppercase; color: var(--text-3); font-weight: 600; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  display: inline-flex; align-items: baseline; gap: 7px; max-width: 100%;
  border: 1px solid var(--line); border-radius: var(--radius-m); padding: 3px 9px;
  background: var(--surface-2); font-size: 11.5px; color: var(--text-2);
}
.chip b { font-family: var(--font-mono); font-size: 11px; color: var(--accent-fg); font-weight: 600; }
.chip.xc b { color: var(--neutral-fg); }

/* 已知侷限 */
.limits { margin-top: 52px; border: 1px solid var(--line); border-left: 2px solid var(--warn); border-radius: var(--radius-m); background: var(--surface-1); }
.limits > h2 { font-size: 15px; padding: 14px 18px 0; }
.limits ul { margin: 10px 0 0; padding: 0 18px 18px 34px; display: grid; gap: 9px; color: var(--text-2); line-height: 1.65; }
.limits li strong { color: var(--text-1); font-weight: 600; }
.limits code { font-size: 11.5px; color: var(--text-1); background: var(--surface-2); padding: 1px 4px; border-radius: var(--radius-s); }

footer.doc { margin-top: 44px; padding-top: 16px; border-top: 1px solid var(--line); color: var(--text-3); font-size: 11.5px; display: flex; gap: 14px; flex-wrap: wrap; }

@media (max-width: 900px) {
  .grid2 { grid-template-columns: 1fr; }
  .area-head { flex-wrap: wrap; }
  .area-head p { margin-left: 0; text-align: left; width: 100%; }
  .thumbs { flex-wrap: wrap; }
  .chrome nav { display: none; }
}
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
"""

JS = """
// 每個路由段自己記住現在看的是哪一態；頂欄的全域切換一次改全部。
(function () {
  // HTML 屬性名一律小寫，所以 dataset 的鍵是 shotLight / labelLight（data-shot-light）。
  function shotOf(sec, state) {
    return { light: sec.dataset.shotLight, dark: sec.dataset.shotDark, audit: sec.dataset.shotAudit }[state];
  }
  function labelOf(sec, state) {
    return { light: sec.dataset.labelLight, dark: sec.dataset.labelDark, audit: sec.dataset.labelAudit }[state];
  }

  function apply(sec, state) {
    var img = sec.querySelector(".view img");
    var label = sec.querySelector(".bezel .state");
    var full = sec.querySelector(".bezel a");
    var src = shotOf(sec, state);
    if (!src) return;
    img.src = src;
    label.textContent = labelOf(sec, state);
    full.href = src;
    sec.querySelectorAll("[data-state]").forEach(function (b) {
      b.setAttribute("aria-pressed", b.dataset.state === state ? "true" : "false");
    });
    sec.querySelector(".view").scrollTop = 0;
  }

  document.querySelectorAll(".route").forEach(function (sec) {
    sec.querySelectorAll("[data-state]").forEach(function (b) {
      b.addEventListener("click", function () { apply(sec, b.dataset.state); });
    });
  });

  document.querySelectorAll("[data-all-state]").forEach(function (b) {
    b.addEventListener("click", function () {
      document.querySelectorAll("[data-all-state]").forEach(function (o) {
        o.setAttribute("aria-pressed", o === b ? "true" : "false");
      });
      document.querySelectorAll(".route").forEach(function (sec) { apply(sec, b.dataset.allState); });
    });
  });

  var root = document.documentElement;
  var toggle = document.getElementById("doctheme");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var next = root.dataset.doc === "light" ? "dark" : "light";
      root.dataset.doc = next;
      toggle.textContent = next === "light" ? "本頁：亮" : "本頁：暗";
    });
  }
})();
"""


def seg_html(slug: str, default: str = "dark") -> str:
    btns = "".join(
        f'<button type="button" data-state="{s}" aria-pressed="{"true" if s == default else "false"}">'
        f'<i class="dot"></i>{e(label)}</button>'
        for s, label in STATES
    )
    return f'<div class="seg" role="group" aria-label="{e(slug)} 畫面狀態">{btns}</div>'


def thumbs_html(v: Variant, default: str = "dark") -> str:
    cells = []
    for s, label in STATES:
        cells.append(
            f'<button type="button" data-state="{s}" aria-pressed="{"true" if s == default else "false"}">'
            f'<span class="crop"><img loading="lazy" src="shots/{v.shot(s)}" alt="{e(v.slug)} {e(label)} 縮圖"></span>'
            f"<span>{e(label)}</span></button>"
        )
    return '<div class="thumbs">' + "".join(cells) + "</div>"


def route_html(v: Variant, meta: dict, cov_rows: list[tuple[str, str]]) -> str:
    m = meta.get(v.slug, {})
    title = m.get("tab") or m.get("area") or BLURBS.get(v.slug, v.slug)
    if v.query:
        title = f'{title} · {v.query.replace("?demo=", "")}'
    label = {
        "light": "亮色主題 · 1440 寬全頁",
        "dark": "暗色主題 · 1440 寬全頁",
        "audit": f"審視態 · __openAllForAudit() 開啟 {m.get('opened', 0)} 個面",
    }
    own = [row for row in cov_rows if not row[0].startswith("XC")]
    xc = [row for row in cov_rows if row[0].startswith("XC")]

    def chips(rows, cls=""):
        return "".join(
            f'<span class="chip {cls}"><b>{e(cid)}</b>{e(item)}</span>' for cid, item in rows
        )

    blocks = []
    if own:
        blocks.append(
            f'<div><div class="grouphead">本頁功能錨點 · {len(own)}</div>'
            f'<div class="chips">{chips(own)}</div></div>'
        )
    if xc:
        blocks.append(
            f'<div><div class="grouphead">在此頁驗收的跨區元件 · {len(xc)}</div>'
            f'<div class="chips">{chips(xc, "xc")}</div></div>'
        )

    data_attrs = " ".join(
        f'data-shot-{s}="shots/{v.shot(s)}" data-label-{s}="{e(label[s])}"' for s, _ in STATES
    )
    route_txt = v.route + v.query
    return f"""<article class="route" id="r-{e(v.slug)}" {data_attrs}>
  <header>
    <h3>{e(title)}</h3>
    <code>{e(route_txt)}</code>
    {seg_html(v.slug)}
  </header>
  <p class="blurb">{e(BLURBS.get(v.slug, ""))}</p>
  <div class="screen">
    <div class="bezel"><i class="led"></i><span class="state">{e(label["dark"])}</span>
      <a href="shots/{v.shot("dark")}" target="_blank" rel="noopener">原尺寸開啟 ↗</a></div>
    <div class="view"><img loading="lazy" src="shots/{v.shot("dark")}" alt="{e(title)} 畫面截圖"></div>
  </div>
  {thumbs_html(v)}
  <div class="covs">{"".join(blocks)}</div>
</article>"""


def summary_table(cov: dict) -> str:
    counts: dict[str, int] = {}
    for cid in cov:
        counts[cid.split("-")[0]] = counts.get(cid.split("-")[0], 0) + 1
    rows = []
    for pfx, name in PREFIX_NAMES.items():
        n = counts.get(pfx, 0)
        rows.append(
            f"<tr><td><b>{e(pfx)}</b> {e(name)}</td><td class='n'>{n}</td><td class='n'>{n}</td>"
            f"<td style='width:120px'><span class='bar'><i style='width:100%'></i></span></td></tr>"
        )
    total = sum(counts.values())
    return f"""<table class="cov">
  <thead><tr><th>功能群</th><th class="n">清單</th><th class="n">DOM 實作</th><th>覆蓋</th></tr></thead>
  <tbody>{"".join(rows)}</tbody>
  <tfoot><tr><td>合計</td><td class="n">{total}</td><td class="n">{total}</td>
  <td><span class="bar"><i style="width:100%"></i></span></td></tr></tfoot>
</table>"""


def build_html(vs: list[Variant], meta: dict) -> str:
    cov = coverage()
    idx = by_route()
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    nav = "".join(
        f'<a href="#a-{aid}">{e(name)}</a>' for aid, name, _ in AREAS
    )

    areas_html = []
    for aid, name, tagline in AREAS:
        mine = [v for v in vs if v.area == aid]
        if not mine:
            continue
        routes = "".join(route_html(v, meta, idx.get(v.route, [])) for v in mine)
        areas_html.append(
            f"""<section class="area" id="a-{e(aid)}">
  <div class="area-head"><h2>{e(name)}</h2><span class="slug">{e(aid)}</span><p>{e(tagline)}</p></div>
  {routes}
</section>"""
        )

    shots_n = len(vs) * len(STATES)
    all_seg = "".join(
        f'<button type="button" data-all-state="{s}" aria-pressed="{"true" if s == "dark" else "false"}">'
        f'<i class="dot"></i>{e(label)}</button>'
        for s, label in STATES
    )

    return f"""<!doctype html>
<html lang="zh-Hant" data-doc="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>illumio-ops · UI 重新設計 v2 Phase 1 · 樣本導覽</title>
<style>{CSS}</style>
</head>
<body>
<div class="chrome"><div class="chrome-in">
  <span class="brand"><b>illumio</b><i></i><span>ops · 樣本導覽</span></span>
  <nav>{nav}<a href="#limits">已知侷限</a></nav>
  <button class="doctoggle" id="doctheme" type="button">本頁：暗</button>
</div></div>

<div class="wrap">
<header class="masthead">
  <div class="eyebrow">UI/UX 全面重新設計 v2 · Phase 1 · 使用者閘門 2</div>
  <h1>互動樣本導覽</h1>
  <p class="lead">這是 Phase 1 的全部產出：一份跑得動的靜態樣本，把現行 GUI 的 {len(cov)} 項功能
  重新編排進六個區。以下逐頁附亮色、暗色，以及一張「審視態」——同時開啟該頁所有抽屜與彈窗，
  讓藏在互動後面的東西也能一次看完。看完請決定是否放行進 Phase 2（逐區改 src/）。</p>
  <dl class="facts">
    <div><dt>功能覆蓋</dt><dd>{len(cov)} / {len(cov)}</dd></div>
    <div><dt>畫面</dt><dd>{len(vs)}</dd></div>
    <div><dt>截圖</dt><dd>{shots_n}</dd></div>
    <div><dt>視窗寬度</dt><dd>1440</dd></div>
    <div><dt>產出時間</dt><dd>{e(stamp)}</dd></div>
  </dl>
</header>

<div class="grid2">
  <div class="panel">
    <h3>功能覆蓋對帳</h3>
    {summary_table(cov)}
  </div>
  <div class="panel">
    <h3>如何開互動樣本</h3>
    <div class="body runbox">
      <pre>python3 -m http.server 8378 -d design/v2/mockup</pre>
      <p style="font-family: var(--font-ui)">然後開 <code>http://127.0.0.1:8378/index.html</code>（主畫面）
      或 <code>http://127.0.0.1:8378/login.html</code>（登入頁；加 <code>?demo=first-login</code>、
      <code>?demo=signed-out</code> 可切換分支）。頂欄右上的使用者選單可切主題與密度，
      <kbd>⌘K</kbd> 開指令面板。</p>
    </div>
  </div>
</div>

<div class="grid2">
  <div class="panel">
    <h3>一併交付的東西</h3>
    <div class="body">
      <div class="linklist">
        <a href="../reports/reskinned/traffic.html"><b>流量報表（重排後）</b><small>HTML</small></a>
        <a href="../reports/reskinned/traffic.pdf"><b>流量報表（重排後）</b><small>PDF</small></a>
        <a href="../reports/reskinned/audit.html"><b>稽核報表（重排後）</b><small>HTML</small></a>
        <a href="../reports/reskinned/audit.pdf"><b>稽核報表（重排後）</b><small>PDF</small></a>
        <a href="../cli-flows.md"><b>CLI 選單流程稿</b><small>Markdown</small></a>
        <a href="../coverage.yaml"><b>功能覆蓋清單</b><small>YAML</small></a>
      </div>
      <p>兩份報表是用真機資料重跑的，不是示意稿；原始版本保留在
      <code>design/v2/reports/original/</code> 可逐頁對照。</p>
    </div>
  </div>
  <div class="panel">
    <h3>怎麼看這份導覽</h3>
    <div class="body">
      <p>每個路由一張主畫面，下面三張縮圖就是這一頁的三種狀態，點縮圖換主畫面。
      主畫面是完整長截圖，可以在框內直接往下捲；要看原始像素就按「原尺寸開啟」。</p>
      <p>下面這排會一次把所有路由切到同一態，方便整份掃過去比對：</p>
      <div class="seg" role="group" aria-label="全部畫面狀態">{all_seg}</div>
    </div>
  </div>
</div>

{"".join(areas_html)}

<section class="limits" id="limits">
  <h2>已知侷限</h2>
  <ul>
    <li><strong>這是快照驅動的靜態樣本，不是可用系統。</strong>畫面上的每一個數字都來自
      <code>design/v2/snapshots/</code> 裡真機錄下的 API 回應，所以看起來是真的——但它不會重新查詢。</li>
    <li><strong>寫入類操作不會真的執行。</strong>儲存、刪除、隔離、送出測試、重置水位這些動作，
      抽屜與確認框照常開，影響摘要照常算，但按下去只會顯示一句誠實說明：這是樣本，不會動到任何東西。</li>
    <li><strong>審視態是為了驗收，不是真實畫面。</strong>它呼叫 <code>window.__openAllForAudit()</code>
      把該路由所有抽屜、彈窗、popover 一次打開，好讓藏在互動後的功能錨點被看見；
      實際使用時這些面不會同時出現，堆疊與遮擋屬正常現象。指令面板與使用者選單是全域面，
      只留在總覽的審視態裡（XC-02／XC-13 也掛在總覽），其餘各頁把版面讓回給該頁自己的抽屜。
      另外，抽屜是固定定位的，長截圖裡它只覆蓋第一個視窗高度，下方頁面照常延伸——這是全頁截圖的性質，不是破圖。
      同理，設定頁那條固定在畫面底部的儲存列，截圖時改用它在流內的佔位位置畫（<code>.savedock</code> 本來就在那裡預留了高度），
      否則它會橫切在長截圖中央。</li>
    <li><strong>守門測試就是這份樣本的驗收依據。</strong>三個「翻車點」各有一族測試盯著：
      告警規則欄位（<code>test_alert_rule_fields.py</code>）、FilterBar 語意
      （<code>test_filterbar_semantics.py</code>）、規則排程模型
      （<code>test_rule_scheduler_model.py</code>）——這三處是設計最容易失真的地方。</li>
    <li><strong>覆蓋與資料來源另有兩道機械閘。</strong><code>gate_coverage.py</code> 實際開瀏覽器走完每條路由，
      比對 DOM 裡的 <code>data-cov</code> 錨點與清單，少一個就不給過；
      <code>lint_no_inline_data.py</code> 禁止在 mockup 裡手寫假資料，逼所有畫面都吃快照。</li>
    <li><strong>還沒做的：</strong>行動裝置寬度、完整鍵盤操作流程、真實 API 的錯誤與延遲時序、
      以及英文介面的實際排版。這些留到 Phase 2 逐區改 <code>src/</code> 時處理。</li>
    <li><strong>快照與截圖中的通知收件人與寄件設定（email／LINE／SMTP 帳號與主機）已遮罩為
      <code>***MASKED***</code>。</strong>這是抓取端（<code>design/v2/tools/masking.py</code>）的個資（PII）
      遮罩，跟機密欄位遮罩走同一條 pipeline 但屬不同類別——收件人與寄件位址本身不是憑證，
      只是不該外流的真實聯絡方式。系統／告警管道頁的 SMTP 欄位因此顯示為遮罩值，不是空值。</li>
    <li><strong>標了「驗證面板」的區塊不會出現在實作裡。</strong>抽屜與設定頁底部那些印出
      request body／送出參數的面板，是為了讓審閱者對照「畫面收了什麼、後端會收到什麼」而加的
      驗證裝置；它們是樣本，Phase 2 改 <code>src/</code> 時不會做進產品介面。</li>
    <li><strong>健康列只在總覽出現。</strong>五盞燈原本常駐頂欄下方，Gate 2 依使用者裁決改成
      總覽專屬（spec §1.1）；其餘各區的頂欄只有導覽列。健康資料仍然餵給總覽的卡片。</li>
  </ul>
</section>

<footer class="doc">
  <span>illumio-ops · design/v2</span>
  <span>產出：<code>python3 design/v2/tools/tour.py</code></span>
  <span>{e(stamp)}</span>
</footer>
</div>
<script>{JS}</script>
</body>
</html>
"""


def main():
    html_only = "--html-only" in sys.argv
    vs = variants()
    meta_path = TOUR / "meta.yaml"
    TOUR.mkdir(parents=True, exist_ok=True)

    if html_only:
        meta = yaml.safe_load(meta_path.read_text()) if meta_path.exists() else {}
    else:
        srv = serve()
        time.sleep(0.8)
        try:
            meta = capture(f"http://127.0.0.1:{PORT}", vs)
        finally:
            srv.terminate()
        meta_path.write_text(yaml.safe_dump(meta, allow_unicode=True, sort_keys=True))

    (TOUR / "tour.html").write_text(build_html(vs, meta))
    print(f"routes={len(vs)} shots={len(vs) * len(STATES)} -> {TOUR / 'tour.html'}")


if __name__ == "__main__":
    main()
