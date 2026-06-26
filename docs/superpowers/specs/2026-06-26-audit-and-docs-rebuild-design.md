---
title: Full Code Audit & Documentation Rebuild — Design / Plan
date: 2026-06-26
branch: review/audit-and-docs-rebuild
status: approved
---

# Full Code Audit & Documentation Rebuild

## 1. Goal
Two linked deliverables:
1. **Comprehensive code review** of the whole project (static + dynamic), fixing
   low-risk issues inline, producing a prioritized findings report.
2. **Documentation rebuild** ("teardown & redo", may reference existing) centered on
   three core docs:
   - Complete **README** (project capabilities + architecture)
   - **Operations manual** (操作手冊)
   - **Event-rules explanation** (事件規則說明) — internal rule judgment & analysis methods

## 2. Approved decisions
- **Review method:** static + full dynamic driving (Playwright over ~88 GUI routes + CLI).
- **Issue handling:** fix low-risk/clear issues inline (tests + diff); report larger/risky ones.
- **Scale:** multi-agent parallel review with adversarial verification.
- **Docs language:** README bilingual; operations-manual & event-rules zh_TW first (EN later).
- **Old docs:** keep & refresh essential reference (CLI, glossary, REST API, TLS); move
  historical/process docs to `docs/_archive/`.
- **Dynamic env:** test machine `root@172.16.15.106` (`batch.lab.local`), GUI `:5001`,
  systemd service `illumio-ops`, currently `main@d61036e`.

## 3. Project facts (verified 2026-06-26)
- **~47.5K LOC** `src/` across 11 subsystems. Largest: `report/` (18.8K), `gui/` (5.4K,
  88 routes), `cli/` (5.1K), `api/` (2.2K), `events/` (2.0K), `siem/` (1.8K),
  `pce_cache/` (1.6K). Root `src/*.py` 9.2K (`reporter.py` 1946, `analyzer.py` 1342,
  `api_client.py` 945, `main.py` 902, `config.py` 738). Tests: 359 files / 32K LOC.
- **24 security rules:** B (ransomware/coverage), L (lateral movement/exfil),
  R (Draft policy alignment — `src/report/rules/r01..r05`). Rule engine: `analyzer.py`
  + `rule_id.py`. Event pipeline: `src/events/` (catalog/matcher/normalizer/poller/
  throttle/shadow/stats/runbooks).
- **i18n:** `src/i18n_en.json` + `src/i18n_zh_TW.json` (~2767 keys); `AGENTS.md` enforces
  guardrails + `scripts/audit_i18n_usage.py`.
- **Runtime data present locally:** `data/pce_cache.sqlite` (27.6 MB),
  `ransomware_posture_cache.json`; `config/{config,alerts}.json` (gitignored, REAL secrets).

## 4. Phases
### Phase 0 — Safety prep (DONE)
Branch created; `config/` + `data/` backed up to scratchpad; test-machine reachability
confirmed; this plan committed.

### Phase 1 — Static multi-agent review
Fan out 15 read-only reviewers (Workflow `illumio-audit-static`): report×3, gui×2, cli,
events, analyzer+ruleengine, api, siem, pce_cache, alerts+reporter, scheduler+config+i18n,
entry+packaging, cross-cutting (security + code↔doc drift). → structured findings →
adversarial verify (refute high/critical) → filter + synthesize.
**Output:** `reports/audit/2026-06-26-static-findings.{md,json}`.

### Phase 2 — Dynamic driving (test machine)
Deploy branch to test machine; apply **side-effect-safe** config (back up its config,
disable real alert sends, guard PCE writes). Enumerate 88 routes; Playwright-drive read
routes fully + mutating/outbound routes carefully; capture 500/traceback/broken-render/
console errors; screenshot key pages. CLI smoke. → runtime findings appended.

### Phase 3 — Fix & report
Fix `safe-inline` findings on branch with tests; re-run affected tests; record diffs.
Larger/risky → report only. Final prioritized report (fixed vs deferred).

### Phase 4 — Documentation rebuild
Build 3 core docs on verified facts. Refresh kept reference; move historical/process docs
to `docs/_archive/`. Rewrite INDEX; run `scripts/docs_check.py`.

## 5. Safety boundaries
- All changes on branch; never on `main` directly. `config/` + `data/` backed up.
- Dynamic testing: **no real alert delivery** (SMTP/LINE/Telegram dry-run/disabled);
  **no real PCE writes** (quarantine/policy apply verified pre-send or expected-fail).
- Reports & docs **never emit secret values**.
- Test machine restored to `main` after Phase 2.

## 6. Target doc structure
```
README.md / README_zh.md            core 1 — rewritten, bilingual
docs/operations-manual_zh.md        core 2 — zh first (EN later)
docs/event-rules_zh.md              core 3 — zh first (EN later)
docs/reference/{cli,glossary,rest-api,tls}  kept, refreshed
docs/INDEX.md / INDEX_zh.md         rewritten hub
docs/_archive/                      plans, specs, handoffs, ux-review, QA, audits (history)
```
