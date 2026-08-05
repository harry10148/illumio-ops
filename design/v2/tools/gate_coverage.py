"""功能覆蓋 gate：起本機 http.server 服務 mockup，Playwright 走每條路由，
收集 DOM 中 data-cov，與 coverage.yaml 對帳。"""
import pathlib
import subprocess
import sys
import time
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def expected():
    return yaml.safe_load((ROOT / "coverage.yaml").read_text())


def report(found: set):
    exp = expected()
    return sorted(set(exp) - found), sorted(found - set(exp))


def collect_dom_cov(base_url: str, routes: list[str]) -> set:
    from playwright.sync_api import sync_playwright
    found = set()
    with sync_playwright() as p:
        pg = p.chromium.launch().new_page()
        for r in routes:
            url = f"{base_url}/{r}" if r.endswith(".html") else f"{base_url}/index.html{r}"
            pg.goto(url)
            pg.wait_for_timeout(600)
            # drawer/modal 內的錨也要：mockup 約定 window.__openAllForAudit() 依序開啟所有 drawer/modal
            pg.evaluate("window.__openAllForAudit ? window.__openAllForAudit() : null")
            pg.wait_for_timeout(400)
            found |= set(pg.eval_on_selector_all("[data-cov]", "els => els.map(e => e.dataset.cov)"))
        pg.context.browser.close()
    return found


def main():
    routes = sorted({v["route"] for v in expected().values()})
    srv = subprocess.Popen(
        [sys.executable, "-m", "http.server", "8377", "-d", str(ROOT / "mockup")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.8)
    try:
        missing, extra = report(collect_dom_cov("http://127.0.0.1:8377", routes))
    finally:
        srv.terminate()
    print(f"covered={len(expected()) - len(missing)}/{len(expected())} extra={extra}")
    if missing:
        print("MISSING:", *missing, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
