# Session Handoff — illumio-ops UX / Dashboard / Reports / Pipeline

> Date: 2026-05-31 · Repo: /home/harry/rd/illumio-ops · Respond in Traditional Chinese.

## TL;DR — where we are
- Everything committed to **`origin/main` @ `8ab2cd3`**; working tree clean (only `tmp/` untracked).
- **Status: PLANNING COMPLETE** for 3 big changes; **user is REVIEWING** the specs/plans. **No implementation started.**
- Test machine **`illumio-ops-test` (172.16.15.106) @ `221e7e8`, service active** — behind origin by 1 cosmetic relabel + docs (functionally current).

## Shipped & DEPLOYED this session (live on test machine @ 221e7e8)
1. VEN report column-slimming (drop Role/App, relative-time heartbeat, IP truncate).
2. Traffic trend → decision-type stacked + "flagged-only" toggle.
3. LINE/Telegram/Webhook channel-card fix (read FLAT `alerts.line_channel_access_token` + `<key>__set`, not nested).
4. Cache ingestion-lag surfacing (`/api/cache/lag` + UI row + error state) + gui-only scheduler-absent warning.
5. `event_poll_status` recorded on the cache event path (dashboard "Event Poll" card was stuck UNKNOWN).

## Committed but NOT deployed (cosmetic)
- `76629f9` relabel dashboard "Traffic" story card → "Rules & Alerts" (its stats are rule/alert metrics). Test machine still shows old label. Deploy anytime / with dashboard work.

## Planning artifacts — READ THESE TO RESUME (all on origin/main)
- Assessment: `docs/ux-review-2026-05-30/assessment.md`
- Specs: `docs/superpowers/specs/2026-05-31-{dashboard-redesign,report-engine-upgrade,pipeline-observability}-design.md`
- Plans (TDD, bite-sized): `docs/superpowers/plans/2026-05-31-{dashboard-redesign,report-engine-upgrade,pipeline-observability}.md`
  - dashboard = 10 tasks, report-engine = 6, pipeline = 7.

## Key decisions (DO NOT re-litigate)
- **Dashboard**: balanced layout; 4 verdict tiles (VEN / blocked-now / pipeline / alerts); new `GET /api/dashboard/overview` (per-section verdict + graceful degradation + `as_of`); VEN via periodic `run_ven_summary` job → `state["ven_summary"]` (independent of pce_cache); retire `dashboard_v2.js` (it wins today; v1 hero/maturity is dead); keep lower detail zone; `degraded` deferred; new route NOT `@login_required` (matches sibling dashboard routes); auto-refresh reuses existing 30s utils.js interval.
- **Reports**: VEN trend delta via existing `trend_store` (already wired for Traffic/Audit/Policy); shared `concern_card.py` (Audit adopts first); donut→bar for skewed distributions (VEN/policy-decision/audit-severity/deny); distinct NetworkInventory cover (new `rpt_cover_type_inventory`, no maturity grade); print `page-break-inside:avoid` on cards/tables/KPIs.
- **Pipeline**: windowed (1h) rates computed on-the-fly from existing timestamps (no rollup table; add 2 indexes on `siem_dispatch`); shared `pipeline_verdict` (`src/pce_cache/health.py`) + thin `/api/cache/health`; DLQ single-item full payload rebuilt from `source_table/source_id` via `dispatcher._build_payload` (no schema change); DLQ replay-by-id with per-item result. **OUT of scope: backfill async/progress; SIEM append-only per-attempt history table.**
- **Governance track** (RBAC / config-audit-log / MFA / secure defaults): **SKIPPED by user**; not planned. Re-open with its own spec→plan if wanted. (The assessment flags it as P1 security; user deferred.)

## Cross-plan dependency
- `pipeline_verdict` is created in the pipeline plan (Task 2) and shared with the dashboard plan's `_overview_pipeline`. Whichever plan lands second imports the shared fn from `src/pce_cache/health.py` instead of inlining thresholds.

## Environment / workflow (verified this session)
- **Test machine**: `ssh illumio-ops-test` → 172.16.15.106 (batch.lab.local), root + passwordless sudo. App `/root/illumio-ops` = git clone tracking `origin/main`. WSGI = cheroot. GUI `https://172.16.15.106:5001`, creds `illumio` / `1qaz@WSX`. systemd unit `illumio-ops.service`, `ExecStart … illumio-ops.py --monitor-gui --interval 10` (scheduler runs; monitor cycle every 30s; cache ingest every 5m).
- **Deploy flow**: branch → commit → `git checkout main && git merge --ff-only <branch> && git push` → `ssh illumio-ops-test 'cd /root/illumio-ops && git pull && sudo systemctl restart illumio-ops.service'`. Confirm `systemctl is-active` + `curl -k https://127.0.0.1:5001/` (302).
- **Live UI verify**: `ssh -fN -L 15001:127.0.0.1:5001 illumio-ops-test` then Python Playwright (`venv/bin/python`, chromium) → login `illumio`/`1qaz@WSX` (fill #username/#password, press Enter) → drive SPA via `switchTab(...)`/`integrationsSwitch(...)`. Kill tunnel after.
- **Tests**: `venv/bin/python -m pytest -q -p no:cacheprovider` (full ~5m45s; baseline **1469 passed / 5 skipped**). JS: `node --check <file>`. i18n parity must stay equal (**3129 keys** each); glossary terms (PCE / VEN / Workload / Blocked / Potentially Blocked / SIEM / DLQ) stay **English** in zh_TW. JS verified via Playwright harnesses loading the real file with globals stubbed (pattern used repeatedly).
- **No hardcoded CJK in Python/JS/HTML source** (i18n audit Category C). Dashboard-scope zh_TW keys not in `dashboard_approved.json` are unconstrained by the Han-ratio gate.

## Open housekeeping
- `tmp/uxaudit/` = 26 screenshots + 5 report HTML + capture scripts (scratch, untracked). Delete when review done.
- Relabel `76629f9` undeployed (cosmetic).

## NEXT STEP
User is reviewing the 3 specs + 3 plans. When they return: act on review feedback, OR pick a plan to execute (dashboard = highest user value; report-engine = most independent / no cross-dep), choosing **subagent-driven** (`superpowers:subagent-driven-development`, recommended) or **inline** (`superpowers:executing-plans`). Optionally fold governance back in (new spec→plan). Nothing is half-built — clean resume point.
