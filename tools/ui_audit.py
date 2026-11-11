"""The shared presentation rules against a real installation, read-only: sign in, open every page, count what breaks
each rule, and optionally keep a full-page screenshot of each.

    V6_SMOKE_PASSWORD=... python tools/ui_audit.py https://host:5001 [--width 1440] [--out DIR]

The password comes from the environment only (default: the first-start default) and is never printed. Nothing is
clicked but the sign-in button. Exit status 1 when any rule is broken."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from tests.e2e import ui_rules

HEIGHT = 900      # overlap and distance are measured in an ordinary window, never the stretched one
TALLEST = 9000
QUIET_MS = 20000  # how long a page is given to finish its requests


def _name(path: str) -> str:
    return path.strip("/").replace("/", "_").replace("?", "_").replace("=", "-") or "home"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("url")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    base = args.url.rstrip("/")
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
    broken = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(ignore_https_errors=True, viewport={"width": args.width, "height": HEIGHT})
        page = ctx.new_page()
        page.goto(base + "/")
        page.fill("input[autocomplete=username]", "illumio")
        page.fill("input[autocomplete=current-password]", os.environ.get("V6_SMOKE_PASSWORD", "illumio"))
        page.click("button[type=submit]")
        page.wait_for_selector(".shell")
        for path in ui_rules.PATHS:
            page.set_viewport_size({"width": args.width, "height": HEIGHT})
            page.goto(base + path)
            page.wait_for_selector("main .page, main section, main h1")
            waiting = ""
            try:
                page.wait_for_load_state("networkidle", timeout=QUIET_MS)
            except PlaywrightTimeout:  # basic mode asks the PCE live, and a SaaS PCE can take a minute to answer
                waiting = "  (measured while still loading)"
            found = ui_rules.violations(page)
            broken += sum(len(v) for v in found.values())
            counts = ", ".join(f"{rule} {len(found[rule])}" for rule in ui_rules.RULES if rule in found) or "clean"
            print(f"{path:32} {counts}{waiting}")
            for rule, items in found.items():
                for item in items:
                    print(f"    [{rule}] {item}")
            if args.out:
                tall = page.evaluate("() => Math.max(...[...document.querySelectorAll('*')].map((e) => e.scrollHeight))")
                page.set_viewport_size({"width": args.width, "height": min(tall + 20, TALLEST)})
                page.wait_for_timeout(300)
                page.screenshot(path=str(args.out / f"{_name(path)}.png"), full_page=True)
        browser.close()
    print(f"{broken} broken" if broken else "every rule holds on every page")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
