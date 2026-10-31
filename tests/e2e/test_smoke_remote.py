"""Smoke test against a real installation (the test box). Skipped unless V6_SMOKE_URL is set.

Environment (inject secrets from the vault into this process only; never print them):
  V6_SMOKE_URL        https://host:port of the v6 installation
  V6_SMOKE_PASSWORD   admin password (default: the first-start default)
  V6_PCE_URL, V6_PCE_ORG, V6_PCE_KEY, V6_PCE_SECRET   the PCE to connect to
  V6_PCE_DEPLOYMENT   on_prem (default) or saas
  V6_PCE_VERIFY       system | off (default) | /path/to/ca.pem on the installation host
"""
import os

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

URL = os.environ.get("V6_SMOKE_URL", "")
pytestmark = [pytest.mark.requires_pce, pytest.mark.skipif(not URL, reason="V6_SMOKE_URL not set")]


def test_sign_in_connect_probe_and_see_it_everywhere():
    env = os.environ
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(ignore_https_errors=True, locale="en-US", viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.goto(URL + "/")
        page.fill("input[autocomplete=username]", "illumio")
        page.fill("input[autocomplete=current-password]", env.get("V6_SMOKE_PASSWORD", "illumio"))
        page.click("button[type=submit]")
        page.wait_for_selector(".shell")

        page.goto(URL + "/system/pce")
        page.wait_for_selector("input[name=url]")
        page.fill("input[name=url]", env["V6_PCE_URL"])
        page.fill("input[name=org_id]", env["V6_PCE_ORG"])
        page.fill("input[name=api_key]", env["V6_PCE_KEY"])
        page.fill("input[name=api_secret]", env["V6_PCE_SECRET"])
        page.select_option("select[name=deployment_type]", env.get("V6_PCE_DEPLOYMENT", "on_prem"))
        verify = env.get("V6_PCE_VERIFY", "off")
        page.select_option("select[name=tls]", verify if verify in ("system", "off") else "bundle")
        if verify not in ("system", "off"):
            page.fill("input[name=ca_path]", verify)
        page.get_by_role("button", name="Save").click()
        page.wait_for_selector("text=Saved.")
        # The page already shows the previous check; wait for THIS probe's answer and for the
        # rendered check time to change, or we would read stale rows (a false green seen once).
        before = page.inner_text(".probe-results") if page.locator(".probe-results").count() else ""
        with page.expect_response(lambda r: r.url.endswith("/api/system/pce/probe")) as resp:
            page.get_by_role("button", name="Test connection").click()
        assert resp.value.status in (200, 502), resp.value.status
        sync_api.expect(page.locator(".probe-results")).not_to_have_text(before or "\u0000", timeout=10000)
        tones = [r.get_attribute("data-tone") for r in page.locator(".probe-row").all()]
        texts = [r.inner_text() for r in page.locator(".probe-row").all()]
        assert tones and all(t == "ok" for t in tones), texts

        page.goto(URL + "/")
        page.wait_for_selector(".probe-results")
        assert "Last checked" in page.inner_text(".probe-results")

        page.goto(URL + "/system/jobs")
        page.wait_for_selector("tr[data-job=pce_probe]")
        assert "PCE health check" in page.inner_text("tr[data-job=pce_probe]")
        browser.close()
