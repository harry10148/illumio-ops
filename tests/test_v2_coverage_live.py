"""The feature-coverage gate, against the real app: 102/102 or red.

tests/design_v2/test_final_gate.py::test_coverage_gate_green runs
design/v2/tools/gate_coverage.py, which proves the FROZEN MOCKUP renders every
anchor in design/v2/coverage.yaml. That gate cannot say anything about the
shipped product. This one runs tools/gate_coverage_live.py, which boots the
real Flask app, logs in through the real POST /api/login and sweeps the real
DOM — so "the feature is in the mockup" and "the feature is in the product"
become two separate, separately-failing questions.

Also guards the correspondence the gate rests on: src/static/js/v2/core/
store-map.mjs's GET_MAP is a line-by-line transcription of the GET entries in
design/v2/tools/endpoints.yaml (that file's own header says so). If an entry
is added on one side only, an area silently loads the wrong path — or nothing
— and the anchors it should have rendered go missing with no other signal.

Runtime: the gate visits 19 routes against a real backend and waits for each
to go quiet, so this is a slow test (minutes, not seconds) by construction —
it is doing the thing it claims to do rather than approximating it.
"""
from __future__ import annotations

import re

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)
pytest.importorskip("yaml", exc_type=ImportError)

import yaml  # noqa: E402

from tools import gate_coverage_live as gate  # noqa: E402

# Registers _v2_playwright/_v2_browser (session-scoped). Required, not an
# optimisation: sync_playwright() opens a background asyncio loop and a second
# independent one in the same process raises "Please use the Async API
# instead" — the same constraint tests/design_v2/test_filterbar_semantics.py
# documents. The gate is handed that browser rather than opening its own.
pytest_plugins = ["tests.v2_e2e_utils"]

ROOT = gate.ROOT
ENDPOINTS_YAML = ROOT / "design" / "v2" / "tools" / "endpoints.yaml"
STORE_MAP = ROOT / "src" / "static" / "js" / "v2" / "core" / "store-map.mjs"


# ── the gate ────────────────────────────────────────────────────────────────

def test_live_coverage_is_complete(_v2_browser):
    """Every anchor in design/v2/coverage.yaml is reachable in the real app.

    `run()` owns its own app, server, temp config, browser context and page,
    and releases all of them on every path (see tools/gate_coverage_live.py's
    "Teardown" section) — nothing here leaks into the rest of the suite. The
    BROWSER is the one exception: it is the suite's session-scoped one, passed
    in and deliberately not closed by the gate.
    """
    result = gate.run(browser=_v2_browser)

    assert result["missing"] == [], (
        "%d/%d coverage anchors reachable; missing: %s"
        % (result["covered"], result["total"], result["missing"])
    )
    assert result["extra"] == [], (
        "the app renders data-cov values that coverage.yaml does not list: %s"
        % result["extra"]
    )
    assert result["covered"] == result["total"] == 102, result


def test_every_route_contributed_something():
    """Guard the guard.

    The gate matches a flat set-union across routes, so a route that failed
    to mount at all could contribute nothing and still leave the total at
    102 if every one of its anchors happened to appear elsewhere. That would
    be a broken page reported as green. Each visited route must carry at
    least the shell's own anchors plus something of its own.
    """
    exp = gate.expected()
    routes = gate.routes_from(exp)
    assert len(routes) == 19, routes
    # Every hash route is inside the SPA shell, so it always sees the chrome:
    # XC-02 (palette), XC-13 (user menu), XC-14 (nav) and LG-03 (sign-out).
    # login.html is the one page outside the shell.
    assert "login.html" in routes
    assert sum(1 for r in routes if r.startswith("#")) == 18


# ── the correspondence the gate rests on ────────────────────────────────────

def _get_map_ids() -> set[str]:
    """Every key of GET_MAP, in both syntaxes the file uses.

    `id: "/api/..."` for a literal path, and ES6 shorthand-method
    `id(params) {` for the entries whose path depends on a caller-supplied
    value. Matching only the first form silently under-counts by five.
    """
    body = STORE_MAP.read_text(encoding="utf-8")
    body = body[body.index("export const GET_MAP"):]
    return set(re.findall(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*)\s*[:(]", body, re.M))


def _yaml_get_ids() -> set[str]:
    entries = yaml.safe_load(ENDPOINTS_YAML.read_text(encoding="utf-8"))
    return {e["id"] for e in entries if str(e.get("method", "GET")).upper() == "GET"}


def test_get_map_is_an_exact_transcription_of_the_frozen_endpoint_list():
    ids = _get_map_ids()
    assert ids == _yaml_get_ids(), {
        "in endpoints.yaml but not GET_MAP": sorted(_yaml_get_ids() - ids),
        "in GET_MAP but not endpoints.yaml": sorted(ids - _yaml_get_ids()),
    }


def test_get_map_has_the_forty_entries_the_gate_expects():
    """A count, on top of the set comparison, so that adding an entry to BOTH
    files without deciding it belongs still has to be a deliberate edit here."""
    assert len(_get_map_ids()) == 40, sorted(_get_map_ids())


def test_post_entries_are_deliberately_absent_from_get_map():
    """endpoints.yaml's POST entries are called with api.post(path, body) at
    the call site, not routed through the id-keyed map (store-map.mjs's own
    header states this). A POST id appearing in GET_MAP would mean something
    is issuing it as a GET."""
    entries = yaml.safe_load(ENDPOINTS_YAML.read_text(encoding="utf-8"))
    post_ids = {e["id"] for e in entries if str(e.get("method", "")).upper() == "POST"}
    assert post_ids, "endpoints.yaml no longer has POST entries — has it been reshaped?"
    assert post_ids & _get_map_ids() == set()
