#!/usr/bin/env python3
"""Feature-coverage gate against the REAL app.

design/v2/tools/gate_coverage.py answers "does the frozen mockup render every
anchor in design/v2/coverage.yaml" by serving design/v2/mockup over
http.server. This is its production counterpart: it boots the real Flask app,
logs in through the real POST /api/login, drives a real Chromium over every
route the coverage map names, and collects the same `[data-cov]` attributes
from the DOM the shipped frontend actually renders.

    python tools/gate_coverage_live.py                 # temp app, ephemeral port
    python tools/gate_coverage_live.py --base-url URL  # an already-running one
    python tools/gate_coverage_live.py --json          # machine-readable report

Exit code is 0 only when every anchor was seen. Anchors are matched as a flat
set-union across all visited routes, exactly like the mockup gate: the map's
`route` field records where an anchor is EXPECTED to live and is used to build
the visit list, not to bind the anchor to that one page.

Route translation, the only real difference from the mockup gate:

    "#/overview"   ->  <base>/#/overview      the SPA shell, one hash route
    "login.html"   ->  <base>/login           the real login page

Drawer/modal/popover anchors are invisible to a DOM sweep until something
opens them, so each route is swept twice: once as it lands, and again after
`window.__openAllForAudit()` (src/static/js/v2/core/audit.mjs) has run every
opener the mounted area and the shell registered.

## Teardown

Everything this tool starts — a temp config directory, a werkzeug server on a
background thread, a Playwright driver, a browser, a context and a page — is
registered on a single contextlib.ExitStack, so a failure anywhere (including
an exception inside the sweep, or Ctrl-C) unwinds all of it in reverse order.
Nothing here touches process-global state: no logging configuration, no
environment mutation, no signal handlers, no chdir. That is deliberate and is
what lets tests/test_v2_coverage_live.py call run() in-process without
leaking a server or a browser into the rest of the suite.
"""
from __future__ import annotations

import argparse
import contextlib
import http.server
import json
import pathlib
import sys
import tempfile
import threading

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
COVERAGE_YAML = ROOT / "design" / "v2" / "coverage.yaml"

USERNAME = "coverage-gate"
PASSWORD = "coverage-gate-password"

# The mockup gate could sweep after a fixed 600ms because its data came from
# static JSON on a local http.server. This one cannot, and the two obvious
# alternatives were both measured and rejected:
#
#   flat 1200ms wait          -> 59/102. Most boards had not painted yet.
#   "count stopped growing"   -> 59/102, IDENTICALLY. A board waiting on a
#                                slow fetch has a stable anchor count for
#                                seconds before it paints, so "stable" fired
#                                during the wait, not after it.
#
# What actually distinguishes "still loading" from "finished" here is the
# network. Every area load goes through core/api.mjs's fetch, and a
# PCE-backed endpoint against an unreachable PCE takes ~8-10s to fail:
# ApiClient retries a refused connection three times with backoff_factor=1.0
# (1s + 2s + 4s) before the 502 comes back.
#
# Playwright's own `wait_for_load_state("networkidle")` does NOT work for
# this, and was measured doing nothing: it tracks a per-navigation flag that
# is already set by the time goto() returns (the document and its module
# graph have loaded; the AREA's fetches start after), and the API is
# documented to "resolve immediately" once the state has been reached. It
# scored the same 59/102 as the flat wait.
#
# So the in-flight request count is tracked here instead, from Playwright's
# request/requestfinished/requestfailed events, and a route is "quiet" only
# after the count has been zero across consecutive polls.
QUIET_POLLS = 4           # consecutive polls with zero requests in flight
MAX_QUIET_MS = 90_000     # ceiling on the quiet wait; not a sleep
POLL_MS = 300             # between polls
STABLE_POLLS = 3          # consecutive unchanged anchor counts after quiet
MAX_SETTLE_MS = 15_000    # ceiling on the confirmation phase
AUDIT_SETTLE_MS = 700     # after __openAllForAudit(), which opens synchronously


def expected() -> dict:
    return yaml.safe_load(COVERAGE_YAML.read_text(encoding="utf-8"))


def report(found: set) -> tuple[list, list]:
    exp = expected()
    return sorted(set(exp) - found), sorted(found - set(exp))


def routes_from(exp: dict) -> list[str]:
    """Every distinct route in the coverage map, hashes first, login last.

    Login is visited last on purpose: it is the one page that is not the SPA,
    and landing on it mid-sweep would otherwise leave the browser off the
    shell for whatever came next.
    """
    all_routes = sorted({v["route"] for v in exp.values()})
    hashes = [r for r in all_routes if r.startswith("#")]
    others = [r for r in all_routes if not r.startswith("#")]
    return hashes + others


def url_for(base_url: str, route: str) -> str:
    if route.startswith("#"):
        return f"{base_url}/{route}"
    if route == "login.html":
        return f"{base_url}/login"
    raise ValueError(f"coverage.yaml route not understood: {route!r}")


# ── the temp app ────────────────────────────────────────────────────────────

# The one ruleset the stand-in PCE serves. Shape copied from
# tests/test_v2_automation_e2e.py's _fake_ruleset() — the same minimal object
# that file feeds through a monkeypatch for the same anchor.
_STUB_RULESET_ID = "900099"
_STUB_RULESET_HREF = "/orgs/1/sec_policy/draft/rule_sets/" + _STUB_RULESET_ID
STUB_RULESET = {
    "href": _STUB_RULESET_HREF,
    "name": "coverage-gate-ruleset",
    "enabled": True,
    "update_type": None,
    "sec_rules": [{
        "href": _STUB_RULESET_HREF + "/sec_rules/1",
        "enabled": True,
        "description": "coverage-gate-rule",
        "update_type": None,
        "destinations": [], "consumers": [], "providers": [], "ingress_services": [],
    }],
    "rules": [],
    "deny_rules": [],
}

# The report schedule the gate seeds into its throwaway config. AU-12 is the
# per-row action cell of the schedules table: it has no audit opener because
# there is nothing to open — it renders when a row exists, and a row is
# config data, so the gate supplies one rather than faking anything.
STUB_REPORT_SCHEDULE = {
    "id": 900099,
    "name": "coverage-gate-schedule",
    "enabled": True,
    "report_type": "traffic",
    "schedule_type": "weekly",
    "day_of_week": "monday",
    "hour": 8,
    "minute": 0,
    "timezone": "local",
    "lookback_days": 7,
    "max_reports": 30,
    "format": ["html"],
    "email_report": False,
    "email_recipients": [],
    "cron_expr": "",
}


class _StubPceHandler(http.server.BaseHTTPRequestHandler):
    """The narrowest possible stand-in for a PCE.

    Why it exists at all: two coverage anchors are DATA-dependent, not
    interaction-dependent. AU-03/AU-04 (the ruleset browser and the per-rule
    search panel inside it) cannot render without at least one ruleset, and a
    ruleset only ever comes from the PCE — there is no local source for one.
    The mockup gate has the same need and meets it with captured snapshots;
    this is the live equivalent.

    What it deliberately is NOT: a PCE simulator. It answers exactly two
    reads — the draft rule_sets collection and one ruleset by href — and 404s
    everything else, so every other area still exercises its real
    "PCE unavailable" path (which is what makes XC-10's error card real).
    404 rather than a refused connection is also much faster: urllib3's
    retry budget does not apply to it, where a refused connection costs
    ~7s of backoff per call.
    """

    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler's API
        path = self.path.split("?", 1)[0]
        if path.endswith("/sec_policy/draft/rule_sets"):
            return self._json([STUB_RULESET])
        if path.endswith(_STUB_RULESET_HREF) or path.endswith("/rule_sets/" + _STUB_RULESET_ID):
            return self._json(STUB_RULESET)
        return self._json({"message": "not served by the coverage gate stub"}, 404)

    def _json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):  # silence per-request logging
        return


@contextlib.contextmanager
def stub_pce():
    """Serve the stand-in PCE on an ephemeral port. Yields its base URL."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _StubPceHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d/api/v2" % server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class _LiveServer:
    """A real werkzeug HTTP server for `app`, on a background thread."""

    def __init__(self, app):
        from werkzeug.serving import make_server
        self._server = make_server("127.0.0.1", 0, app, threaded=True)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return "http://127.0.0.1:%d" % self._server.server_address[1]

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)


@contextlib.contextmanager
def temp_app_server():
    """Build a throwaway app on a throwaway config and serve it. Yields base_url."""
    from src.config import ConfigManager, hash_password
    from src.gui import build_app

    with contextlib.ExitStack() as stack:
        tmp = stack.enter_context(tempfile.TemporaryDirectory(prefix="gate-coverage-live-"))
        pce_url = stack.enter_context(stub_pce())

        config_file = str(pathlib.Path(tmp) / "config.json")
        cm = ConfigManager(config_file=config_file)
        cm.load()
        cm.config["api"] = dict(cm.config.get("api", {}))
        cm.config["api"].update({"url": pce_url, "key": "gate", "secret": "gate", "org_id": "1"})
        cm.config["report_schedules"] = [dict(STUB_REPORT_SCHEDULE)]
        cm.config["web_gui"] = {
            "username": USERNAME,
            "password": hash_password(PASSWORD),
            "allowed_ips": ["127.0.0.1"],
            "secret_key": "x" * 64,
        }
        cm.save()

        app = build_app(cm, persistent_mode=True, use_https=False)
        app.config.update({"TESTING": True})
        app.testing = True  # disables Talisman's forced-HTTPS redirect

        server = _LiveServer(app)
        server.start()
        stack.callback(server.stop)
        yield server.base_url


# ── the sweep ───────────────────────────────────────────────────────────────

def collect_dom_cov(base_url: str, route_list: list[str], username: str,
                    password: str, verbose: bool = False,
                    browser=None) -> tuple[set, dict]:
    """Visit every route, sweep [data-cov] twice, return (found, per_route).

    `browser` lets a caller hand in an ALREADY-OPEN Playwright browser. This
    is not an optimisation: `sync_playwright()` opens a background asyncio
    loop, and a second, independent one in the same process raises "Please use
    the Async API instead". tests/test_v2_coverage_live.py runs alongside
    tests/v2_e2e_utils.py's session-scoped browser, so it passes that one in;
    the CLI passes nothing and opens (and closes) its own.

    Whatever this function opens, it closes — and only that. A browser passed
    in belongs to its owner and is left alone.
    """
    found: set[str] = set()
    per_route: dict[str, list[str]] = {}

    with contextlib.ExitStack() as stack:
        if browser is None:
            from playwright.sync_api import sync_playwright
            pw = stack.enter_context(sync_playwright())
            browser = pw.chromium.launch()
            stack.callback(browser.close)
        context = browser.new_context(ignore_https_errors=True)
        stack.callback(context.close)

        # The real login endpoint, from the browser context, so the session
        # cookie it sets is carried by every page.goto() below. Same approach
        # as tests/v2_e2e_utils.v2_login — no auth bypass.
        resp = context.request.post(
            base_url + "/api/login",
            data=json.dumps({"username": username, "password": password}),
            headers={"Content-Type": "application/json"},
        )
        if not resp.ok or resp.json().get("ok") is not True:
            raise SystemExit(f"gate_coverage_live: login failed: {resp.status} {resp.text()}")

        page = context.new_page()
        stack.callback(page.close)
        page.set_default_timeout(30_000)
        inflight = _InFlight(page)

        for route in route_list:
            inflight.reset()
            page.goto(url_for(base_url, route))
            page.wait_for_selector('body[data-booted="true"]')
            seen = _settled_sweep(page, inflight)
            # Anchors that only exist inside a drawer / modal / popover. The
            # openers can themselves fetch (a drawer that loads its own
            # detail), so wait for quiet again rather than a fixed pause.
            page.evaluate("window.__openAllForAudit ? window.__openAllForAudit() : null")
            page.wait_for_timeout(AUDIT_SETTLE_MS)
            seen |= _settled_sweep(page, inflight)

            per_route[route] = sorted(seen)
            found |= seen
            if verbose:
                print(f"  {route:28} {len(seen):3d} anchors", file=sys.stderr)

    return found, per_route


def _sweep(page) -> set:
    return set(page.eval_on_selector_all(
        "[data-cov]", "els => els.map(e => e.dataset.cov)"
    ))


class _InFlight:
    """Counts requests in flight on a page, from Playwright's own events.

    Registered once per page; reset() before each navigation. See the module
    constants for why Playwright's networkidle load state cannot be used.
    """

    def __init__(self, page):
        self.n = 0
        page.on("request", self._start)
        page.on("requestfinished", self._end)
        page.on("requestfailed", self._end)

    def _start(self, _request):
        self.n += 1

    def _end(self, _request):
        self.n -= 1

    def reset(self) -> None:
        self.n = 0


def _wait_until_quiet(page, inflight: "_InFlight | None") -> None:
    """Block until nothing has been in flight for QUIET_POLLS polls."""
    if inflight is None:
        return
    quiet = 0
    waited = 0
    while waited <= MAX_QUIET_MS:
        # wait_for_timeout also pumps the event loop, so the counters above
        # are up to date by the time it returns.
        page.wait_for_timeout(POLL_MS)
        waited += POLL_MS
        quiet = quiet + 1 if inflight.n <= 0 else 0
        if quiet >= QUIET_POLLS:
            return


def _settled_sweep(page, inflight=None) -> set:
    """Sweep once the page has gone quiet, then confirm the DOM has settled.

    Returns the UNION of every poll, not just the last one: an area that
    replaces a skeleton with real content can briefly drop an anchor, and the
    question this gate asks ("is this feature reachable in the product") is
    answered by having seen it at all.

    Hitting MAX_QUIET_MS is not fatal — an area that polls on a timer may
    never go quiet. The confirmation loop below still bounds the wait, and a
    genuinely unreachable anchor is then reported as missing, which is the
    outcome an operator can act on.
    """
    _wait_until_quiet(page, inflight)

    seen: set[str] = set()
    stable = 0
    waited = 0
    while waited <= MAX_SETTLE_MS:
        before = len(seen)
        seen |= _sweep(page)
        stable = stable + 1 if len(seen) == before else 0
        if stable >= STABLE_POLLS:
            break
        page.wait_for_timeout(POLL_MS)
        waited += POLL_MS
    return seen


# ── entry point ─────────────────────────────────────────────────────────────

def run(base_url: str | None = None, username: str = USERNAME,
        password: str = PASSWORD, verbose: bool = False, browser=None) -> dict:
    """Run the gate. Returns a report dict; raises nothing on a miss.

    `base_url` None means "boot a throwaway app and serve it here".
    `browser` None means "open one"; see collect_dom_cov for why a caller
    inside a test session must pass its own.
    """
    exp = expected()
    route_list = routes_from(exp)

    with contextlib.ExitStack() as stack:
        if base_url is None:
            base_url = stack.enter_context(temp_app_server())
        found, per_route = collect_dom_cov(
            base_url, route_list, username, password, verbose, browser
        )

    missing, extra = report(found)
    return {
        "total": len(exp),
        "covered": len(exp) - len(missing),
        "missing": missing,
        "extra": extra,
        "routes": per_route,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default=None,
                        help="run against an already-running app instead of booting one")
    parser.add_argument("--username", default=USERNAME)
    parser.add_argument("--password", default=PASSWORD)
    parser.add_argument("--json", action="store_true", help="emit the full report as JSON")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="print a per-route anchor count to stderr")
    args = parser.parse_args(argv)

    result = run(args.base_url, args.username, args.password, args.verbose)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("covered=%d/%d extra=%s" % (result["covered"], result["total"], result["extra"]))
        if result["missing"]:
            print("MISSING:", *result["missing"], sep="\n  ")
    return 1 if result["missing"] else 0


if __name__ == "__main__":
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
