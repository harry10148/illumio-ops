"""FilterBar parity gate (UI redesign v2, failure point #3).

The previous redesign attempt died on an AND/OR filter divergence: the new bar
serialized a merged-column query differently from the shipping one, so the same
saved query returned different flows. This test makes that class of divergence a
test failure instead of a field report.

Method: load the SHIPPING file (src/static/js/filter-bar.js), the MOCKUP file
(design/v2/mockup/js/components/filter-bar.mjs) and the ported V2 PRODUCT file
(src/static/js/v2/components/filter-bar.mjs) into the same headless browser,
one per blank page, and drive all three through the identical call sequence
over the queries actually stored on the appliance
(design/v2/snapshots/dashboard_queries.json, which carries one AND query —
src_labels + dst_labels — and one OR query — any_label). Outputs must be
equal, key for key, across all three.

THREE-WAY, not two-way, and why: Phase 2A Task 3 ported the mockup file into
the production tree (verbatim except a single i18n key rename outside the
serialization core — see that file's header). This test now guards the port
itself, not just the original mockup, by parameterizing `_sources()` over all
three paths below. Task 11 deletes the legacy `filter-bar.js` once the v2 GUI
replaces it in production, at which point this drops back to a two-way
comparison (mockup vs v2) — that cleanup is Task 11's job, not this one's.

Paths compared (PROD/MOCK/V2 constants below, `_sources()` iterates the list):

Departures from the task brief's sketch, and why:
  * `_objfbDeserialize(state, dict)` takes the state as its FIRST argument and
    mutates it (filter-bar.js:155); it does not return a state, so the sketch's
    `_objfbSerialize(_objfbDeserialize({...}))` could never have run. The tests
    build the state explicitly.
  * `mode` is not a filter key — it is inferred from the pills during
    deserialization (filter-bar.js:205-217) and changed by _objfbToggleMode
    (:1055-1081). Parametrising over the mode therefore means "force the bar into
    this mode through its own toggle, then serialize", which is what
    test_serialize_matches_production_in_both_modes does. Re-implementing the
    toggle inside the test would have tested the test.
  * The snapshot is a flat list of query_def dicts (dashboard.py:539-546 stores
    them flattened), not {"queries": [...]} with a `filters` member.

The mockup module is loaded with "export " stripped so a classic script sees the
same global function names as production — which is why that module is written
with zero imports (see its header).
"""
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROD = ROOT / "src" / "static" / "js" / "filter-bar.js"
MOCK = ROOT / "design" / "v2" / "mockup" / "js" / "components" / "filter-bar.mjs"
V2 = ROOT / "src" / "static" / "js" / "v2" / "components" / "filter-bar.mjs"
# Ordered (name, path) pairs — the "parameterized paths" the three-way
# comparison iterates. PROD is the reference every other name is compared
# against; the .mjs sources have "export " stripped so a classic <script> tag
# sees the same global function names as PROD (both mockup and v2 files are
# written import-free for exactly this reason — see their own headers).
SOURCE_PATHS = [("prod", PROD), ("mock", MOCK), ("v2", V2)]
CASES_FILE = ROOT / "design" / "v2" / "snapshots" / "dashboard_queries.json"

# filter-bar.js:104 calls window.debounce at construction; the mockup resolves
# candidates synchronously and never needs it. Stubbing it is the only thing the
# production file needs that a blank page does not already provide.
STUB = "window.debounce = function (fn) { return fn; };"

# Deserialize into a bare state, then serialize. This is the pure core: no DOM,
# no instance, no view.
CORE_JS = """
([cases]) => cases.map(function (dict) {
  var state = { pills: [], mode: 'and', cats: [] };
  _objfbDeserialize(state, dict);
  return { mode: state.mode, pills: state.pills, out: _objfbSerialize(state) };
})
"""

# Drive the public API the way the product does: build a bar from the stored
# query (filter-bar.js:108 opts.initial), force the requested mode through the
# bar's own toggle, read the filters back.
API_JS = """
([cases, mode]) => cases.map(function (dict) {
  var host = document.createElement('div');
  document.body.appendChild(host);
  var api = createFilterBar(host, { initial: dict });
  var id = host.dataset.objfbId;
  var st = window._objfbGetInstance(id);
  if (st.mode !== mode) window._objfbToggleMode(id);
  var out = api.getFilters();
  var again = null;
  try {
    api.setFilters(out);            // round trip: re-import what we just emitted
    again = api.getFilters();
  } catch (e) {
    again = { _error: String(e) };
  }
  api.destroy();
  host.remove();
  return { mode: window._objfbGetInstance(id) ? null : st.mode, out: out, round: again };
})
"""


def _cases():
    data = json.loads(CASES_FILE.read_text())
    queries = data if isinstance(data, list) else data.get("queries", [])
    assert queries, f"{CASES_FILE} carries no stored query to compare"
    return queries


def _sources():
    return {
        name: (path.read_text() if name == "prod" else path.read_text().replace("export ", ""))
        for name, path in SOURCE_PATHS
    }


@pytest.fixture(scope="module")
def page():
    playwright = pytest.importorskip("playwright.sync_api", exc_type=ImportError)
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.errors = errors
        yield pg
        browser.close()


def _run(page, expression, argument):
    out = {}
    for name, source in _sources().items():
        page.goto("about:blank")
        page.add_script_tag(content=STUB)
        page.add_script_tag(content=source)
        out[name] = page.evaluate(expression, argument)
    assert page.errors == [], page.errors
    return out


def test_snapshot_carries_one_and_query_and_one_or_query():
    """The comparison is only worth running on real AND and OR queries.

    Hand-written cases are banned for this gate: the point is that the two
    implementations agree on what the appliance actually stores.
    """
    cases = _cases()
    has_and = any(c.get("src_labels") or c.get("dst_labels") for c in cases)
    has_or = any(c.get("any_label") or c.get("any_ip") or c.get("any_iplist") or c.get("any_workload")
                 for c in cases)
    assert has_and, "dashboard_queries.json has no per-side (AND) query"
    assert has_or, "dashboard_queries.json has no merged-column (OR) query"


def test_deserialize_then_serialize_matches_production(page):
    """The serialization core: same pills, same inferred mode, same dict —
    for BOTH the mockup and the ported v2 product file, against PROD."""
    results = _run(page, CORE_JS, [_cases()])
    assert results["mock"] == results["prod"]
    assert results["v2"] == results["prod"]


@pytest.mark.parametrize("mode", ["and", "or"])
def test_serialize_matches_production_in_both_modes(page, mode):
    """Whole-bar parity, including the mode toggle and a re-import round trip.

    In AND mode a label pill serializes to {src,dst}_labels; in OR mode every
    pill collapses onto the single-value any_* keys (filter-bar.js:130-142), and
    several pills of one category keep only the last. That lossy collapse is the
    behaviour the product ships, so the mockup — and the ported v2 file — have
    to lose exactly as much.
    """
    results = _run(page, API_JS, [_cases(), mode])
    assert results["mock"] == results["prod"]
    assert results["v2"] == results["prod"]


@pytest.mark.parametrize("mode", ["and", "or"])
def test_modes_actually_differ(page, mode):
    """Guard the guard: if both modes produced the same dict, the parity tests
    above would pass without ever exercising the AND/OR split."""
    results = _run(page, API_JS, [_cases(), mode])
    keys = sorted({k for row in results["prod"] for k in row["out"]})
    if mode == "or":
        assert any(k.startswith("any_") for k in keys), keys
        assert not any(k.startswith("src_") or k.startswith("dst_") for k in keys), keys
    else:
        assert any(k.startswith("src_") or k.startswith("dst_") for k in keys), keys
        assert not any(k.startswith("any_") for k in keys), keys
