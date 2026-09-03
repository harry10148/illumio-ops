"""Throwaway screenshot harness for the density redesign.

Not named test_*.py on purpose: default collection skips it, and it only runs
when named explicitly. It reuses the e2e fixtures so the page renders against a
real Flask app rather than a mock, which is the whole point — density is a
judgement about the real thing.

    ./.venv/bin/python3 ./.venv/bin/pytest tests/shot_jobs.py -s -q

Delete once the redesign has its own visual-check step.
"""
import os
import pathlib

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

# Registers v2_page and its fixture chain (same two lines, same order, as every
# tests/test_v2_*_e2e.py — see tests/v2_e2e_utils.py's docstring).
pytest_plugins = ["tests.v2_e2e_utils"]

OUT = pathlib.Path(os.environ.get(
    "SHOT_DIR",
    "/tmp/claude-1000/-home-harry-rd-illumio-ops/"
    "048b4a55-5589-4c71-adde-d2205a4c2b54/scratchpad/redesign"))

ROUTES = [
    ("overview", "#/home"),
    ("traffic", "#/investigate/traffic"),
    ("alrules", "#/policy/alert-rules"),
    ("aureports", "#/reports/schedules"),
    ("reports", "#/reports"),
    ("siem", "#/system/siem"),
    ("jobs", "#/system/jobs"),      # status page
    ("ops", "#/policy/ops"),          # action page
    ("cache", "#/system/cache"),        # settings page
]


def test_shot(v2_page):
    page, base_url = v2_page
    OUT.mkdir(parents=True, exist_ok=True)
    for name, route in ROUTES:
        page.goto(base_url + "/" + route)
        page.wait_for_selector('[data-route="%s"]' % route)
        # Wait for content, not for a stopwatch. The overview loads fourteen
        # datasets against an unreachable PCE and had not painted a single
        # panel within a fixed 1.5s, which photographed as an empty board and
        # read as a rendering bug — the third time this script has produced
        # misleading evidence by not checking what it was looking at.
        try:
            page.wait_for_selector("section.panel, section.wip, .errcard", timeout=45000)
        except Exception as exc:
            print("WARN %s: nothing rendered (%s)" % (name, exc.__class__.__name__))
        page.wait_for_timeout(1500)
        for theme, suffix in (("dark", ""), ("light", "-light")):
            page.evaluate("t => document.documentElement.dataset.theme = t", theme)
            page.wait_for_timeout(200)
            path = OUT / ("%s%s.png" % (name, suffix))
            page.screenshot(path=str(path), full_page=False)
            print("wrote", path)
