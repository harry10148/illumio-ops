#!/usr/bin/env python3
"""One-off: save the Wave A+B upgrade completion snapshot to Mem0 cloud.

Reads MEM0_API_KEY from the environment. Does NOT hardcode the key.
Safe to delete after running — this is not a recurring workflow.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    if not os.environ.get("MEM0_API_KEY"):
        print("ERROR: MEM0_API_KEY env var not set", file=sys.stderr)
        return 1

    from mem0 import MemoryClient

    client = MemoryClient()  # picks up MEM0_API_KEY from env
    user_id = "harry10148"

    # Each memory is a self-contained fact; Mem0 will dedupe + index
    entries = [
        (
            "illumio_ops upgrade roadmap Wave A complete 2026-04-18. "
            "Phase 0/1/2/3 merged to main. Tags: v3.4.0-deps, v3.4.1-cli "
            "(rich/questionary/click/humanize), v3.4.2-http "
            "(requests/orjson/cachetools), v3.4.3-settings (pydantic v2). "
            "Resolves Status.md Q5 (label cache TTL) and D2 (config validation)."
        ),
        (
            "illumio_ops upgrade roadmap Wave B complete 2026-04-18. "
            "Phase 4/5/6 merged to main. Tags: v3.5.0-websec "
            "(flask-wtf/limiter/talisman/login + argon2id), v3.5.1-reports "
            "(openpyxl/weasyprint/matplotlib/plotly/pygments/humanize), "
            "v3.5.2-scheduler (APScheduler BackgroundScheduler + RLock). "
            "Resolves Status.md S1/S4/S5 (argon2+CSRF+rate-limit), A3 "
            "(daemon blocking), T1 (TTLCache thread-safety)."
        ),
        (
            "illumio_ops main branch after Wave A+B: 252 tests passing, 3 skipped "
            "(2 PDF on Windows no-GTK3, 1 pre-existing). i18n audit 0 findings "
            "maintained throughout. 7 version tags on origin."
        ),
        (
            "illumio_ops upgrade execution method: Subagent-Driven Development "
            "via superpowers skill. Each phase in own worktree (../illumio_ops-phaseN) "
            "sharing .venv-phase0. Parallel implementers + sequential spec+quality "
            "review per phase + fix subagent for CHANGES_REQUESTED. Merged sequentially "
            "(smallest to largest) to minimize rebase conflicts on Status.md/Task.md."
        ),
        (
            "illumio_ops deployment target: offline RHEL RPM (no Docker). "
            "pandas is mandatory (41 files, 338 DataFrame ops). Python startup "
            "(python illumio_ops.py) is dev-only post-roadmap. Production goes "
            "through future RPM bundle (Phase 8 — separate plan, not started). "
            "All packages pinned in requirements.txt + requirements-dev.txt."
        ),
        (
            "illumio_ops remaining roadmap work after Wave A+B: Phase 7 (Logging "
            "full replacement stdlib→loguru, 77 files, codemod needed for "
            "%s→{} format) and Phase 9 (architecture refactor: api_client 2542 LOC "
            "god-class split into TrafficQueryBuilder+AsyncJobManager+LabelResolver; "
            "run_analysis 196-line decomposition; A1/A2/A4/A5+Q1/Q2/Q3). "
            "Both plans NOT yet written."
        ),
        (
            "illumio_ops CLI after Wave A+B: `illumio-ops` subcommands = "
            "version|config|monitor|gui|report|status. Legacy argparse flags "
            "(--monitor, --gui, --report) still work via argv[1] dispatcher. "
            "CLI --format accepts html/csv/pdf/xlsx/all. src/cli/ click package "
            "integrates Phase 3's config_group + Phase 1's subcommands."
        ),
        (
            "illumio_ops ApiClient (src/api_client.py) after Phase 2+6: uses "
            "requests.Session with urllib3.Retry (429/502/503/504 backoff). "
            "5 TTLCaches (label/service_ports/label_href/label_group_href/iplist_href) "
            "with ttl=900, all protected by self._cache_lock (threading.RLock). "
            "orjson.loads on hot parse paths. verify_ssl preserves CA bundle path "
            "strings. _request() return contract (status_code: int, body: bytes) "
            "unchanged; 50+ calling methods untouched."
        ),
        (
            "illumio_ops Web GUI (src/gui.py) after Phase 4: build_app(cm) factory "
            "for testability. flask-login current_user.is_authenticated (before_request). "
            "flask-wtf CSRFProtect with X-CSRFToken/X-CSRF-Token dual header. "
            "flask-limiter 5/minute on /api/login memory storage; 429 returns JSON. "
            "flask-talisman CSP/HSTS/XFO/Permissions-Policy restricting "
            "camera/microphone/geolocation. argon2id hashing via "
            "hash_password_argon2 + verify_and_upgrade_password; PBKDF2 silent upgrade."
        ),
        (
            "illumio_ops Reports (src/report/) after Phase 5: dual-engine "
            "chart_renderer.py (plotly HTML offline-inline + matplotlib PNG "
            "with Noto Sans CJK TC fallback); xlsx_exporter multi-sheet+embedded PNG; "
            "pdf_exporter weasyprint+CJK CSS (lazy import); pygments code_highlighter. "
            "chart_spec added to mod02/05/07/10/15 (pie/bar/heatmap/line/network). "
            "CLI + GUI + /api/reports/generate format allowlist (security)."
        ),
    ]

    for text in entries:
        msg = [{"role": "user", "content": text}]
        try:
            result = client.add(
                messages=msg,
                user_id=user_id,
                metadata={"project": "illumio_ops", "category": "upgrade_roadmap_wave_a_b"},
            )
            print(f"OK: {text[:80]}...")
        except Exception as exc:
            print(f"FAIL ({text[:60]}...): {exc}", file=sys.stderr)

    # Verify by searching
    print("\n--- verification ---")
    results = client.search("illumio_ops Wave A complete", user_id=user_id, limit=3)
    hits = results.get("results", []) if isinstance(results, dict) else results
    for r in hits[:3]:
        print(f"  hit: {r.get('memory', str(r))[:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
