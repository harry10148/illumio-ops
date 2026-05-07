"""a6 HTTPS layout-break verification smoke script.

Spawns headless Chromium against a running illumio-ops GUI on HTTPS and
captures: console messages, page errors, network failures, response status,
loaded fonts, computed body font, layout dimensions, cookies, and any
mixed-content / blocked / refused warnings.

Used to verify the a6 hand-off (assessment §3.1.0) — the four hypotheses for
"HTTPS-enabled layout breaks":
  1. Mixed-content blocking
  2. external resources via http://
  3. CSP font-src 'self' over-strict
  4. Cookie SameSite=Strict / Secure

Track A vendoring + Track A finalize moved login.html to local woff2, which
removes hypotheses 1-3 structurally. This script is the reproducer that
confirms the fix end-to-end and can be re-run if external resources are ever
re-introduced.

Prerequisites:
  - playwright installed (pip install playwright; playwright install chromium)
  - illumio-ops GUI running on URL below (default https://127.0.0.1:5443)
    Launch with: python illumio-ops.py gui --port 5443 --host 127.0.0.1

Usage:
  URL=https://127.0.0.1:5443/login python scripts/a6_https_smoke.py

Output: JSON findings printed to stdout; full-page screenshot saved next to
this script as a6_login.png.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = os.environ.get("URL", "https://127.0.0.1:5443/login")
SCREENSHOT_PATH = Path(__file__).resolve().parent / "a6_login.png"

findings: dict = {
    "url": URL,
    "console_messages": [],
    "page_errors": [],
    "network_failures": [],
    "responses_non_2xx": [],
    "request_count": 0,
    "cookies_after_load": [],
    "mixed_content_warnings": [],
}


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=["--ignore-certificate-errors"]
        )
        context = browser.new_context(
            ignore_https_errors=True, viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()

        page.on("console", lambda msg: findings["console_messages"].append(
            {"type": msg.type, "text": msg.text, "location": msg.location}
        ))
        page.on("pageerror", lambda exc: findings["page_errors"].append(str(exc)))
        page.on("requestfailed", lambda req: findings["network_failures"].append(
            {"url": req.url, "failure": req.failure}
        ))
        page.on("response", lambda resp: (
            findings["responses_non_2xx"].append({"url": resp.url, "status": resp.status})
            if resp.status >= 400 else None
        ))
        page.on(
            "request",
            lambda _req: findings.update(request_count=findings["request_count"] + 1),
        )

        try:
            resp = page.goto(URL, wait_until="networkidle", timeout=15000)
            findings["main_status"] = resp.status if resp else None
        except Exception as exc:
            findings["main_navigation_error"] = repr(exc)

        try:
            findings["layout"] = page.evaluate("""() => {
                const card = document.querySelector('.login-card, .login-container, form, body');
                if (!card) return null;
                const rect = card.getBoundingClientRect();
                return {
                    selector: card.tagName + (card.className ? '.' + card.className : ''),
                    width: rect.width,
                    height: rect.height,
                    x: rect.x,
                    y: rect.y,
                    body_scrollHeight: document.body.scrollHeight,
                    body_scrollWidth: document.body.scrollWidth,
                    viewport_width: window.innerWidth,
                    viewport_height: window.innerHeight,
                };
            }""")
            findings["computed_font"] = page.evaluate("""() => {
                return window.getComputedStyle(document.body).fontFamily;
            }""")
            findings["fonts_loaded"] = page.evaluate("""() => {
                return Array.from(document.fonts).map(f => ({
                    family: f.family, weight: f.weight, status: f.status
                }));
            }""")
        except Exception as exc:
            findings["layout_eval_error"] = repr(exc)

        try:
            findings["cookies_after_load"] = context.cookies()
        except Exception as exc:
            findings["cookies_error"] = repr(exc)

        try:
            page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
            findings["screenshot"] = str(SCREENSHOT_PATH)
        except Exception as exc:
            findings["screenshot_error"] = repr(exc)

        for m in findings["console_messages"]:
            t = m["text"].lower()
            if any(k in t for k in ("mixed", "insecure", "blocked:csp", "refused to")):
                findings["mixed_content_warnings"].append(m)

        browser.close()

    print(json.dumps(findings, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
