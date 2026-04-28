# Documentation Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the project documentation to v3.20.0 quality with full EN/ZH parity, cross-document navigation, and coverage of every CLI subcommand, report module, security rule, SIEM transport, and the offline bundle workflow that was lost in commit `ed20df0`.

**Architecture:** Six-phase rebuild — restore baselines from `git show ed20df0~1`, refresh to v3.20.0 by reading current source, supplement with NotebookLM-extracted Illumio platform background, install a uniform Documentation Map header in every file, mirror EN content into Traditional Chinese, and gate completion on a 9-point acceptance checklist.

**Tech Stack:** Markdown, bash, Python 3 (small verification scripts), `notebooklm` CLI v0.3.4, `git` (for baseline recovery).

**Spec:** `docs/superpowers/specs/2026-04-28-documentation-rebuild-design.md`

---

## File Structure

**Created (10 user-facing docs + Status/Task + 2 verification scripts + 1 gitignore entry):**
- `README.md` (rewrite)
- `README_zh.md` (rewrite)
- `docs/User_Manual.md`
- `docs/User_Manual_zh.md`
- `docs/Architecture.md`
- `docs/Architecture_zh.md`
- `docs/Security_Rules_Reference.md`
- `docs/Security_Rules_Reference_zh.md`
- `Status.md` (restore + refresh)
- `Task.md` (restore + refresh)
- `scripts/check_doc_coverage.sh`
- `scripts/check_doc_links.py`
- `.gitignore` (append `docs/_notebooklm_excerpts/`)

**Deleted (after merge into the new structure):**
- `docs/API_Cookbook_zh.md` (content folded into `docs/Architecture_zh.md`)
- `docs/Project_Architecture_zh.md` (content folded into `docs/Architecture_zh.md`)
- `docs/SIEM_Integration.md` (content folded into `docs/User_Manual.md` §5)
- `docs/Security_Rules_Reference_zh.md` (rewritten in place — same path is reused)
- `docs/User_Manual_zh.md` (rewritten in place — same path is reused)

**Reference baselines (read-only, recovered from git):**
- `git show ed20df0~1:docs/User_Manual.md`
- `git show ed20df0~1:docs/User_Manual_zh.md`
- `git show ed20df0~1:docs/Project_Architecture.md`
- `git show ed20df0~1:docs/Project_Architecture_zh.md`
- `git show ed20df0~1:docs/API_Cookbook.md`
- `git show ed20df0~1:docs/API_Cookbook_zh.md`
- `git show ed20df0~1:docs/SIEM_Forwarder.md`
- `git show ed20df0~1:docs/SIEM_Integration.md`
- `git show ed20df0~1:docs/Security_Rules_Reference.md`
- `git show ed20df0~1:docs/Security_Rules_Reference_zh.md`
- `git show ed20df0~1:docs/PCE_Cache.md`
- `git show ed20df0~1:docs/report_module_inventory_zh.md`
- `git show ed20df0~1:README.md`
- `git show ed20df0~1:README_zh.md`
- `git show 6518f10:Status.md`
- `git show 6518f10:Task.md`

---

## Phase A — Skeleton Restore

Recover the pre-`ed20df0` baselines so each new document starts from the most recent fully-formed ancestor.

### Task 1: Working tree pre-flight

**Files:** none modified (verification only)

- [ ] **Step 1: Verify baseline commits are reachable**

Run:
```bash
git cat-file -e ed20df0~1 && echo OK_BASELINE
git cat-file -e 6518f10  && echo OK_STATUS
```
Expected: both lines print `OK_BASELINE` / `OK_STATUS`. If either errors, abort the rebuild and ask the user — recovery is impossible without the ancestor commit.

- [ ] **Step 2: Stash any unrelated working-tree changes that touch docs**

Run:
```bash
git status --porcelain -- 'docs/*' README.md README_zh.md Status.md Task.md
```
If anything unexpected is listed, ask the user before proceeding. Do not destroy unstaged work.

### Task 2: Restore README.md and README_zh.md baselines

**Files:**
- Create: `README.md`
- Create: `README_zh.md`

- [ ] **Step 1: Restore both READMEs from the pre-consolidation commit**

Run:
```bash
git show ed20df0~1:README.md    > README.md
git show ed20df0~1:README_zh.md > README_zh.md
```

- [ ] **Step 2: Verify line counts match the historical baseline**

Run:
```bash
wc -l README.md README_zh.md
```
Expected: README.md ≈ 169, README_zh.md ≈ 128 (within ±5).

- [ ] **Step 3: Commit**

```bash
git add README.md README_zh.md
git commit -m "docs: restore README EN/ZH baselines from ed20df0~1"
```

### Task 3: Restore docs/User_Manual.md baseline (merged with SIEM_Forwarder + report_module_inventory)

**Files:**
- Create: `docs/User_Manual.md`

- [ ] **Step 1: Restore the historical EN User_Manual**

Run:
```bash
git show ed20df0~1:docs/User_Manual.md > docs/User_Manual.md
```

- [ ] **Step 2: Append the historical SIEM_Forwarder content as section 5**

Run:
```bash
{
  echo
  echo '---'
  echo
  echo '# 5. SIEM Integration'
  echo
  git show ed20df0~1:docs/SIEM_Forwarder.md
} >> docs/User_Manual.md
```

- [ ] **Step 3: Append the historical Reports inventory as a sub-section of section 4**

Run:
```bash
{
  echo
  echo '---'
  echo
  echo '# Appendix A — Report Module Inventory'
  echo
  echo '> Translated from `docs/report_module_inventory_zh.md` (ed20df0~1) — refresh in Phase B.'
  echo
  git show ed20df0~1:docs/report_module_inventory_zh.md
} >> docs/User_Manual.md
```

- [ ] **Step 4: Verify the merged file has the expected sections**

Run:
```bash
grep -c '^# 5\. SIEM Integration\|^# Appendix A' docs/User_Manual.md
```
Expected: `2`.

- [ ] **Step 5: Commit**

```bash
git add docs/User_Manual.md
git commit -m "docs: restore docs/User_Manual.md baseline (merge SIEM_Forwarder + reports inventory)"
```

### Task 4: Restore docs/User_Manual_zh.md baseline (merged with SIEM_Integration + report_module_inventory_zh)

**Files:**
- Create: `docs/User_Manual_zh.md`

- [ ] **Step 1: Restore the historical ZH User_Manual**

Run:
```bash
git show ed20df0~1:docs/User_Manual_zh.md > docs/User_Manual_zh.md
```

- [ ] **Step 2: Append SIEM_Integration as ZH section 5**

Run:
```bash
{
  echo
  echo '---'
  echo
  echo '# 5. SIEM 整合'
  echo
  git show ed20df0~1:docs/SIEM_Integration.md
} >> docs/User_Manual_zh.md
```

- [ ] **Step 3: Append the historical ZH report inventory as Appendix A**

Run:
```bash
{
  echo
  echo '---'
  echo
  echo '# 附錄 A — 報表模組清單'
  echo
  git show ed20df0~1:docs/report_module_inventory_zh.md
} >> docs/User_Manual_zh.md
```

- [ ] **Step 4: Verify the merged ZH file**

Run:
```bash
grep -c '^# 5\. SIEM 整合\|^# 附錄 A' docs/User_Manual_zh.md
```
Expected: `2`.

- [ ] **Step 5: Commit**

```bash
git add docs/User_Manual_zh.md
git commit -m "docs: restore docs/User_Manual_zh.md baseline (merge SIEM_Integration + 報表模組清單)"
```

### Task 5: Restore docs/Architecture.md baseline (merged with API_Cookbook + PCE_Cache)

**Files:**
- Create: `docs/Architecture.md`

- [ ] **Step 1: Start from historical Project_Architecture EN**

Run:
```bash
git show ed20df0~1:docs/Project_Architecture.md > docs/Architecture.md
```

- [ ] **Step 2: Append PCE_Cache content as section 5**

Run:
```bash
{
  echo
  echo '---'
  echo
  echo '# 5. PCE Cache'
  echo
  git show ed20df0~1:docs/PCE_Cache.md
} >> docs/Architecture.md
```

- [ ] **Step 3: Append API_Cookbook as section 6**

Run:
```bash
{
  echo
  echo '---'
  echo
  echo '# 6. PCE REST API Integration Cookbook'
  echo
  git show ed20df0~1:docs/API_Cookbook.md
} >> docs/Architecture.md
```

- [ ] **Step 4: Verify both appended sections exist**

Run:
```bash
grep -c '^# 5\. PCE Cache\|^# 6\. PCE REST API' docs/Architecture.md
```
Expected: `2`.

- [ ] **Step 5: Commit**

```bash
git add docs/Architecture.md
git commit -m "docs: restore docs/Architecture.md baseline (merge PCE_Cache + API_Cookbook)"
```

### Task 6: Restore docs/Architecture_zh.md baseline

**Files:**
- Create: `docs/Architecture_zh.md`

- [ ] **Step 1: Start from historical Project_Architecture_zh**

Run:
```bash
git show ed20df0~1:docs/Project_Architecture_zh.md > docs/Architecture_zh.md
```

- [ ] **Step 2: Append PCE_Cache (EN — will be translated in Phase E) as section 5 placeholder**

Run:
```bash
{
  echo
  echo '---'
  echo
  echo '# 5. PCE Cache（待翻譯）'
  echo
  git show ed20df0~1:docs/PCE_Cache.md
} >> docs/Architecture_zh.md
```

- [ ] **Step 3: Append API_Cookbook_zh as section 6**

Run:
```bash
{
  echo
  echo '---'
  echo
  echo '# 6. PCE REST API 整合手冊'
  echo
  git show ed20df0~1:docs/API_Cookbook_zh.md
} >> docs/Architecture_zh.md
```

- [ ] **Step 4: Commit**

```bash
git add docs/Architecture_zh.md
git commit -m "docs: restore docs/Architecture_zh.md baseline (merge PCE_Cache + API_Cookbook_zh)"
```

### Task 7: Restore docs/Security_Rules_Reference.md baseline

**Files:**
- Create: `docs/Security_Rules_Reference.md`

- [ ] **Step 1: Restore from baseline**

Run:
```bash
git show ed20df0~1:docs/Security_Rules_Reference.md > docs/Security_Rules_Reference.md
```

- [ ] **Step 2: Verify**

Run: `wc -l docs/Security_Rules_Reference.md`
Expected: ≈ 711 lines.

- [ ] **Step 3: Commit**

```bash
git add docs/Security_Rules_Reference.md
git commit -m "docs: restore docs/Security_Rules_Reference.md baseline from ed20df0~1"
```

### Task 8: Restore docs/Security_Rules_Reference_zh.md baseline

**Files:**
- Create: `docs/Security_Rules_Reference_zh.md` (overwrite the truncated current file)

- [ ] **Step 1: Restore from baseline**

Run:
```bash
git show ed20df0~1:docs/Security_Rules_Reference_zh.md > docs/Security_Rules_Reference_zh.md
```

- [ ] **Step 2: Verify**

Run: `wc -l docs/Security_Rules_Reference_zh.md`
Expected: ≈ 742 lines (was 836 in current file but truncated semantically — baseline is the reference).

- [ ] **Step 3: Commit**

```bash
git add docs/Security_Rules_Reference_zh.md
git commit -m "docs: restore docs/Security_Rules_Reference_zh.md baseline from ed20df0~1"
```

### Task 9: Restore Status.md and Task.md

**Files:**
- Create: `Status.md`
- Create: `Task.md`

- [ ] **Step 1: Restore both from commit 6518f10**

Run:
```bash
git show 6518f10:Status.md > Status.md
git show 6518f10:Task.md   > Task.md
```

- [ ] **Step 2: Append a rebuild notice to both**

Append to `Status.md`:
```markdown

---

## 2026-04-28 — Documentation rebuild in progress

The documentation set is being rebuilt under `docs/superpowers/plans/2026-04-28-documentation-rebuild.md`. Status will be updated when Phase F acceptance passes.
```

Append to `Task.md`:
```markdown

---

## Active task — Documentation rebuild

Plan: `docs/superpowers/plans/2026-04-28-documentation-rebuild.md`
Spec: `docs/superpowers/specs/2026-04-28-documentation-rebuild-design.md`
```

- [ ] **Step 3: Commit**

```bash
git add Status.md Task.md
git commit -m "docs: restore Status.md and Task.md from 6518f10 + note rebuild WIP"
```

### Task 10: Phase A acceptance check

**Files:** none modified

- [ ] **Step 1: Confirm all 10 planned files exist with non-trivial size**

Run:
```bash
for f in README.md README_zh.md Status.md Task.md \
         docs/User_Manual.md docs/User_Manual_zh.md \
         docs/Architecture.md docs/Architecture_zh.md \
         docs/Security_Rules_Reference.md docs/Security_Rules_Reference_zh.md; do
  lines=$(wc -l < "$f" 2>/dev/null || echo MISSING)
  printf '%6s  %s\n' "$lines" "$f"
done
```
Expected: every line shows ≥ 100 except README files which may be ≥ 100; no `MISSING`.

---

## Phase B — Refresh to v3.20.0

Update the restored baselines so they match the codebase at the rebuild start. New material lives mostly in `docs/User_Manual.md` (offline bundle, R3 modules, Policy Usage modules, draft_pd, web_gui defaults), `docs/Architecture.md` (current `src/` layout, JSON snapshot store), and `docs/Security_Rules_Reference.md` (R01–R05 + `compute_draft` auto-enable).

### Task 11: Create the doc coverage check script

**Files:**
- Create: `scripts/check_doc_coverage.sh`

- [ ] **Step 1: Write the script**

Create `scripts/check_doc_coverage.sh`:
```bash
#!/usr/bin/env bash
# Verify docs/User_Manual.md mentions every report module, subcommand, and bundle script.
# Exits non-zero with a list of missing terms.
set -euo pipefail

DOC=docs/User_Manual.md
[ -f "$DOC" ] || { echo "FATAL: $DOC not found"; exit 2; }

missing=()

# Report analysis modules (file basename without .py)
while IFS= read -r path; do
  mod=$(basename "$path" .py)
  grep -q -- "$mod" "$DOC" || missing+=("module:$mod")
done < <(find src/report/analysis -maxdepth 1 -name 'mod*.py' -not -name '__init__.py')

# Policy Usage modules
while IFS= read -r path; do
  mod=$(basename "$path" .py)
  grep -q -- "$mod" "$DOC" || missing+=("pu_module:$mod")
done < <(find src/report/analysis/policy_usage -maxdepth 1 -name 'pu_*.py')

# CLI subcommands (excluding -h/--help meta entries)
for sub in cache monitor gui report rule siem workload config status version; do
  grep -qE "(\`|\b)${sub}(\`|\b)" "$DOC" || missing+=("subcommand:$sub")
done

# Offline bundle scripts
for s in build_offline_bundle.sh install.sh uninstall.sh; do
  grep -q -- "$s" "$DOC" || missing+=("script:$s")
done

if [ ${#missing[@]} -ne 0 ]; then
  printf 'MISSING in %s:\n' "$DOC"
  printf '  %s\n' "${missing[@]}"
  exit 1
fi

echo "OK — all required terms present in $DOC"
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x scripts/check_doc_coverage.sh`

- [ ] **Step 3: Run it now to capture the current baseline gap**

Run: `scripts/check_doc_coverage.sh || true`
Expected: prints a `MISSING` list — many entries since the baseline pre-dates v3.20.0. Save this list mentally as the work backlog for Tasks 12–17.

- [ ] **Step 4: Commit**

```bash
git add scripts/check_doc_coverage.sh
git commit -m "chore: add scripts/check_doc_coverage.sh for documentation coverage gates"
```

### Task 12: Refresh User_Manual §1 — Installation (Offline Bundle)

**Files:**
- Modify: `docs/User_Manual.md` (replace or insert section 1)

**Source material to read first:** `scripts/build_offline_bundle.sh`, `scripts/install.sh`, `scripts/uninstall.sh`, `docs/superpowers/plans/2026-04-20-phase-16-offline-bundle.md`.

- [ ] **Step 1: Read source files**

Run:
```bash
cat scripts/build_offline_bundle.sh scripts/install.sh scripts/uninstall.sh
```
Take notes on: bundle layout, `--install-root` flag, `IS_UPGRADE` detection (config preservation), `--purge` semantics, the systemd unit name `illumio-ops.service`, and the `--monitor-gui` daemon flag.

- [ ] **Step 2: Replace section 1 in User_Manual.md**

The new section 1 must cover, with at least one fenced code block per sub-section:

- 1.1 Building the bundle (`scripts/build_offline_bundle.sh` invocation, the `bundle/python/` and `bundle/config/` layout it produces, the resulting `.tar.gz`).
- 1.2 Installing on the target host (`sudo ./install.sh`, default `INSTALL_ROOT=/opt/illumio_ops`, `--install-root /opt/custom` override, the `rsync -a "$SRC/python/" "$INSTALL_ROOT/python/"` step).
- 1.3 Upgrade behaviour (`IS_UPGRADE=true` when `$INSTALL_ROOT/config/config.json` exists, the entire `config/` tree is preserved on upgrade — quote the comment "Preserve all of config/ on upgrade").
- 1.4 Uninstall (`sudo /opt/illumio_ops/uninstall.sh` default behaviour preserves config; `--purge` removes everything; `--install-root` override).
- 1.5 systemd integration (the generated `/etc/systemd/system/illumio-ops.service`, the service `ExecStart=` line, `--monitor-gui` flag, `systemctl enable --now illumio-ops`).

End the section with a "Smoke test" that runs `illumio-ops version` and `curl -sf http://127.0.0.1:5000/healthz`.

- [ ] **Step 3: Verify the section was inserted**

Run:
```bash
grep -nE "^## 1\.[1-5]" docs/User_Manual.md | head -10
grep -c "build_offline_bundle.sh\|install.sh\|uninstall.sh\|--install-root\|--monitor-gui" docs/User_Manual.md
```
Expected: 5 sub-section lines printed; the count grep ≥ 6.

- [ ] **Step 4: Commit**

```bash
git add docs/User_Manual.md
git commit -m "docs(user-manual): refresh §1 Installation with offline bundle workflow"
```

### Task 13: Refresh User_Manual §2 — Configuration

**Files:**
- Modify: `docs/User_Manual.md` (replace or insert section 2)

**Source material:** `config/config.json.example`, `src/settings.py`, `config/report_config.yaml`, `config/rule_schedules.json`.

- [ ] **Step 1: Read sources**

Run:
```bash
cat config/config.json.example
sed -n '1,80p' src/settings.py
cat config/report_config.yaml
```

- [ ] **Step 2: Write section 2 covering the following keys**

Section 2 must contain a key reference table with columns *Key*, *Type*, *Default*, *Description*, including these keys:

- `pce_profiles[]`, `active_pce_id`, `api.url`, `api.org_id`, `api.key`, `api.secret`, `api.verify_ssl`
- `alerts.active`, `alerts.line_*`, `alerts.webhook_url`
- `email.sender`, `email.recipients`, `smtp.host`, `smtp.port`, `smtp.user`, `smtp.password`, `smtp.enable_auth`, `smtp.enable_tls`
- `settings.enable_health_check`, `settings.language`, `settings.theme`, `settings.dashboard_queries[]`
- `web_gui.username` (default `illumio`), `web_gui.password` (default `illumio`), `web_gui.bind_host`, `web_gui.port`
- `report.snapshot_retention_days`, `report.threat_intel_csv_path`, `report.draft_actions_enabled`
- TLS file conventions under `config/tls/`

Include callouts:
- "**Default credentials are `illumio:illumio` — change them on first login.**"
- "Scheduling is configured in `config/rule_schedules.json` (one cron expression per rule)."
- "Report behaviour is tuned via `config/report_config.yaml`."

- [ ] **Step 3: Verify**

Run:
```bash
grep -c "web_gui\|snapshot_retention_days\|threat_intel_csv_path\|draft_actions_enabled\|rule_schedules.json" docs/User_Manual.md
```
Expected: ≥ 5.

- [ ] **Step 4: Commit**

```bash
git add docs/User_Manual.md
git commit -m "docs(user-manual): refresh §2 Configuration with v3.20.0 keys"
```

### Task 14: Refresh User_Manual §3 — Operations (CLI subcommands)

**Files:**
- Modify: `docs/User_Manual.md` (replace or insert section 3)

**Source material:** `illumio_ops.py`, `src/cli/*.py`.

- [ ] **Step 1: Capture each subcommand's help output**

Run, for each subcommand in the set `cache monitor gui report rule siem workload config status version`:
```bash
for sub in cache monitor gui report rule siem workload config status version; do
  echo "===== illumio-ops $sub --help ====="
  python3 illumio_ops.py "$sub" --help 2>&1 || true
done
```
Capture the output; you will quote the synopsis lines (USAGE / DESCRIPTION) into the doc.

- [ ] **Step 2: Write section 3 with one sub-section per subcommand**

For each of the 10 subcommands write a sub-section `## 3.X <subcommand>` containing:
- One-sentence description.
- Synopsis: a fenced bash block showing `illumio-ops <sub> [OPTIONS]`.
- A short table of the most-used options (taken from the `--help` output).
- One concrete example invocation with its expected effect.

Also include `## 3.11 GUI walkthrough` (Dashboard / Quarantine / Integrations / Reports pages — references `src/templates/index.html` and the static JS files), and `## 3.12 Daemon mode` (covers `--monitor` and `--monitor-gui`, the systemd unit, log paths under `logs/`).

- [ ] **Step 3: Verify**

Run:
```bash
for sub in cache monitor gui report rule siem workload config status version; do
  grep -qE "^## 3\.[0-9]+ ${sub}\b" docs/User_Manual.md || echo "MISSING subsection: $sub"
done
```
Expected: no `MISSING` lines.

- [ ] **Step 4: Commit**

```bash
git add docs/User_Manual.md
git commit -m "docs(user-manual): refresh §3 Operations with all 10 subcommands + GUI/daemon"
```

### Task 15: Refresh User_Manual §4 — Reports

**Files:**
- Modify: `docs/User_Manual.md` (replace or insert section 4)

**Source material:** every file under `src/report/analysis/` and `src/report/analysis/policy_usage/`, plus `src/report/report_generator.py`, `src/report/policy_usage_generator.py`, `src/report/audit_generator.py`, `src/report/ven_status_generator.py`.

- [ ] **Step 1: Enumerate modules**

Run:
```bash
ls src/report/analysis/mod*.py src/report/analysis/policy_usage/pu_*.py | sed 's|.*/||;s|\.py$||'
```
You should see: `mod01_traffic_overview … mod15_lateral_movement`, `mod_change_impact mod_draft_actions mod_draft_summary mod_enforcement_rollout mod_exfiltration_intel mod_ringfence`, `pu_mod00_executive … pu_mod05_draft_pd`.

- [ ] **Step 2: Write the four report-type overviews**

`## 4.1 Report types` table with rows: *Traffic*, *Audit*, *Policy Usage*, *VEN Status*. Each row links to the generator module and lists supported output formats (HTML, JSON, CSV, Markdown).

- [ ] **Step 3: Write the standard module catalogue**

`## 4.2 Standard modules (mod01–mod15)` — one bullet per module with: filename, one-sentence purpose (read the module's docstring or the first 30 lines of the file), the cross-tabs/columns it produces.

- [ ] **Step 4: Write the R3 intelligence module catalogue**

`## 4.3 R3 intelligence modules` — one bullet per: `mod_change_impact`, `mod_draft_actions`, `mod_draft_summary`, `mod_enforcement_rollout`, `mod_exfiltration_intel`, `mod_ringfence`. For each: input data, output rows/columns, related config (e.g. `snapshot_retention_days` for `mod_change_impact`, `threat_intel_csv_path` for `mod_exfiltration_intel`, `draft_actions_enabled` for `mod_draft_actions`).

- [ ] **Step 5: Write the Policy Usage module catalogue**

`## 4.4 Policy Usage modules` — one bullet each for `pu_mod00_executive` … `pu_mod05_draft_pd`.

- [ ] **Step 6: Write the draft_pd behaviour section**

`## 4.5 Draft Policy Decision behaviour` — explain `compute_draft` auto-enable when ruleset uses `draft_pd`, the draft pill in the HTML report header (`feat(report): add draft-enabled pill in HTML report header when compute_draft=True`), the `draft_breakdown` cross-tab from mod02, and the `draft_enforcement_gap` from mod13.

- [ ] **Step 7: Write the output formats section**

`## 4.6 Output formats` — HTML/JSON/CSV/Markdown invocation examples via `illumio-ops report --format ...`.

- [ ] **Step 8: Verify**

Run: `scripts/check_doc_coverage.sh`
Expected: passes for every `module:` and `pu_module:` line, OR remaining failures are only in non-Reports terms (subcommand:, script:) which are covered by Tasks 12 and 14.

- [ ] **Step 9: Commit**

```bash
git add docs/User_Manual.md
git commit -m "docs(user-manual): refresh §4 Reports with R3 + Policy Usage + draft_pd"
```

### Task 16: Refresh User_Manual §5 — SIEM Integration

**Files:**
- Modify: `docs/User_Manual.md` (replace or insert section 5)

**Source material:** `src/siem/`, `src/cli/siem.py`.

- [ ] **Step 1: Read sources**

Run:
```bash
ls src/siem/
cat src/cli/siem.py
```

- [ ] **Step 2: Write section 5 with five sub-sections**

- `## 5.1 Transports` — UDP, TCP, TLS, HEC. One paragraph each + the `siem.transport` config key value.
- `## 5.2 Formats` — CEF and JSON. Show one full sample message of each.
- `## 5.3 Forwarder configuration` — table of `siem.*` config keys (transport, host, port, tls_cert, hec_token, hec_endpoint, format).
- `## 5.4 Field mapping reference` — table mapping internal event fields to CEF extension keys and JSON property names.
- `## 5.5 Operator commands` — `illumio-ops siem test`, `illumio-ops siem flush`, `illumio-ops siem status` (mirror the `--help` output of each).

- [ ] **Step 3: Verify**

Run:
```bash
grep -c "CEF\|HEC\|TLS\|UDP\|TCP" docs/User_Manual.md
```
Expected: ≥ 10.

- [ ] **Step 4: Commit**

```bash
git add docs/User_Manual.md
git commit -m "docs(user-manual): refresh §5 SIEM Integration (transports, formats, mapping)"
```

### Task 17: Refresh Architecture §2–§3 — System Overview and Module Map

**Files:**
- Modify: `docs/Architecture.md` (replace sections 2 and 3)

**Source material:** `illumio_ops.py`, `src/main.py`, `src/api_client.py`, `src/api/`, `src/analyzer.py`, `src/report/`, `src/events/`, `src/siem/`, `src/scheduler/`, `src/gui/`, `src/i18n.py`, `src/pce_cache/`.

- [ ] **Step 1: Inventory the current src/ layout**

Run:
```bash
find src -maxdepth 2 -type d -not -path '*/\.*' | sort
```
This list IS the table of contents of section 3.

- [ ] **Step 2: Write section 2 — System Overview**

Include an ASCII topology diagram showing PCE ⇄ illumio_ops with sub-blocks for Cache (SQLite WAL), SIEM forwarder, Web GUI (Flask), Reports, Daemon (APScheduler). Reference the entry path `illumio_ops.py → src/main.py → click subcommands`. Explain the three runtime modes: CLI one-shot, Daemon (`--monitor` / `--monitor-gui`), Web GUI standalone.

- [ ] **Step 3: Write section 3 — Module Map**

One sub-section per `src/` directory listed in step 1. Each must have:
- The directory path.
- The dominant entry-point file.
- A 2-3 sentence description of responsibility.
- Cross-references to the sections in `docs/User_Manual.md` that operators interact with.

- [ ] **Step 4: Verify**

Run:
```bash
grep -c "src/api_client.py\|src/analyzer.py\|src/report\|src/events\|src/siem\|src/scheduler\|src/gui\|src/i18n.py\|src/pce_cache" docs/Architecture.md
```
Expected: ≥ 8.

- [ ] **Step 5: Commit**

```bash
git add docs/Architecture.md
git commit -m "docs(architecture): refresh §2 System Overview and §3 Module Map for v3.20.0"
```

### Task 18: Refresh Architecture §4 — Data Flow + JSON snapshot store

**Files:**
- Modify: `docs/Architecture.md` (replace section 4)

**Source material:** `src/report/analysis/mod_change_impact.py`, `src/report/report_generator.py`, the snapshot-store implementation referenced by commit `320683e feat(report): JSON snapshot store with retention for Change Impact`.

- [ ] **Step 1: Locate the snapshot store**

Run:
```bash
grep -RIn "snapshot" src/report/ | grep -v test_ | head -20
```

- [ ] **Step 2: Write section 4 covering**

- 4.1 Traffic ingestion path (`src/api/` → `src/analyzer.py` → events → reports / SIEM).
- 4.2 Event pipeline (`src/events/`) and how events become alerts and SIEM messages.
- 4.3 Report generation pipeline (analysis → exporters → HTML/JSON/CSV/Markdown).
- 4.4 JSON snapshot store: location on disk, file naming convention, retention controlled by `report.snapshot_retention_days`, how `mod_change_impact` reads the previous snapshot for Δ calculation, the guard added in commit `354ac0d` (previous_snapshot_at None handling).

- [ ] **Step 3: Verify**

Run:
```bash
grep -c "snapshot_retention_days\|mod_change_impact\|JSON snapshot" docs/Architecture.md
```
Expected: ≥ 3.

- [ ] **Step 4: Commit**

```bash
git add docs/Architecture.md
git commit -m "docs(architecture): refresh §4 Data Flow + JSON snapshot store"
```

### Task 19: Refresh Architecture §5 — PCE Cache (folded in)

**Files:**
- Modify: `docs/Architecture.md` (rewrite section 5 in place)

**Source material:** `src/pce_cache/`, `src/cli/cache.py`.

- [ ] **Step 1: Read sources**

Run:
```bash
ls src/pce_cache/
cat src/cli/cache.py
```

- [ ] **Step 2: Rewrite section 5 to cover**

- 5.1 Why a cache: PCE API latency, pagination cost, batch operation efficiency.
- 5.2 SQLite WAL design: schema overview, WAL mode rationale (concurrent readers + single writer), file location.
- 5.3 Refresh policy: TTLs per object type, manual refresh trigger.
- 5.4 Operator commands: `illumio-ops cache status`, `illumio-ops cache refresh`, `illumio-ops cache clear` (mirror `--help`).
- 5.5 Troubleshooting: corrupted DB recovery, file permission issues.

- [ ] **Step 3: Verify**

Run:
```bash
grep -nE "^## 5\.[1-5]" docs/Architecture.md
```
Expected: 5 sub-section lines.

- [ ] **Step 4: Commit**

```bash
git add docs/Architecture.md
git commit -m "docs(architecture): refresh §5 PCE Cache (SQLite WAL + operator commands)"
```

### Task 20: Refresh Security_Rules_Reference for R01–R05

**Files:**
- Modify: `docs/Security_Rules_Reference.md`

**Source material:** files added in commits `fd1244a feat(rules): add R01-R05 draft_policy_decision security rules`, `cfb688d feat(analyzer): honor query_spec.requires_draft_pd for rules engine`, `945f814 feat(rules): auto-enable compute_draft when ruleset contains draft_pd rules`, `18cd180 test(rules): tighten R05 severity assertion`.

- [ ] **Step 1: Locate the rule definitions**

Run:
```bash
grep -RIn "R0[1-5]" src/ tests/ | grep -v __pycache__ | head -30
```

- [ ] **Step 2: Write the rule catalogue**

Add or replace a top-level "Rule catalogue" section. For each of R01, R02, R03, R04, R05 produce a sub-section with the schema:

- ID and short name
- Trigger condition (the analyzer expression in plain English)
- `requires_draft_pd`: yes/no
- Severity classification
- Sample finding row (1–3 line example)
- Recommended remediation (link to the relevant `docs/User_Manual.md` Reports section)

- [ ] **Step 3: Document compute_draft auto-enable**

Add a "Configuration → compute_draft auto-enable" section explaining: when a ruleset contains any rule with `requires_draft_pd=True`, the analyzer auto-sets `compute_draft=True` even if the operator did not opt in. Reference the test file `tests/test_phase34_attack_summaries.py` and the analyzer change in `cfb688d`.

- [ ] **Step 4: Verify**

Run:
```bash
grep -c "^### R0[1-5]\|^## R0[1-5]" docs/Security_Rules_Reference.md
grep -c "compute_draft\|requires_draft_pd" docs/Security_Rules_Reference.md
```
Expected: first count = 5; second count ≥ 4.

- [ ] **Step 5: Commit**

```bash
git add docs/Security_Rules_Reference.md
git commit -m "docs(security-rules): document R01-R05 + compute_draft auto-enable"
```

### Task 21: Phase B acceptance — coverage script must pass

**Files:** none modified

- [ ] **Step 1: Run the coverage check**

Run: `scripts/check_doc_coverage.sh`
Expected: `OK — all required terms present in docs/User_Manual.md`. If not, return to the appropriate task and fix the gaps reported.

---

## Phase C — NotebookLM Extraction

Use the existing `Illumio` notebook (id `8c325126-bc83-4c86-8c6e-8759a242928e`) and its two key sources to extract Illumio platform background and REST API patterns. Save raw outputs to a gitignored directory; commit only the synthesized prose.

### Task 22: Gitignore the excerpts directory

**Files:**
- Modify: `.gitignore`
- Create: `docs/_notebooklm_excerpts/` (directory only)

- [ ] **Step 1: Append the gitignore entry**

Append this line to `.gitignore`:
```
docs/_notebooklm_excerpts/
```

- [ ] **Step 2: Create the directory**

Run: `mkdir -p docs/_notebooklm_excerpts`

- [ ] **Step 3: Verify gitignore takes effect**

Run:
```bash
touch docs/_notebooklm_excerpts/.placeholder
git status --porcelain docs/_notebooklm_excerpts/
```
Expected: empty output (directory is gitignored).

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore docs/_notebooklm_excerpts/ for raw NotebookLM material"
```

### Task 23: Resolve the two NotebookLM source IDs

**Files:** none modified (state capture only)

- [ ] **Step 1: Find full source IDs**

Run:
```bash
notebooklm source list -n 8c325126 --json 2>/dev/null \
  | python3 -c "import json,sys; d=json.load(sys.stdin); [print(s['id'], s['title']) for s in d['sources'] if 'Admin_25' in s['title'] or 'REST_APIs_25' in s['title']]"
```
Expected: two lines — one Admin_25_4.pdf id, one REST_APIs_25_4.pdf id. Record them as `ADMIN_ID` and `REST_ID` for the next task.

If the source IDs are not present in the notebook, fall back to listing all sources and grep for `Admin_25` and `REST_APIs_25` to find the correct titles, then re-run.

### Task 24: Run the 7 NotebookLM ask queries

**Files:**
- Create: `docs/_notebooklm_excerpts/01_pce_ven.md` … `07_traffic_explorer.md` (7 files, gitignored)

- [ ] **Step 1: Set the source IDs as shell variables**

Run (replacing placeholders with the real IDs from Task 23):
```bash
ADMIN_ID=<from Task 23>
REST_ID=<from Task 23>
NB=8c325126
```

- [ ] **Step 2: Run the 7 ask queries**

Each query saves its raw JSON answer (including citations) to its own excerpt file:
```bash
mkdir -p docs/_notebooklm_excerpts

declare -a queries=(
  "01_pce_ven|Explain the PCE (Policy Compute Engine) and the supported VEN (Virtual Enforcement Node) deployment modes. List the platforms VENs run on and how they communicate with the PCE."
  "02_labels|Explain the four label dimensions Role, Application, Environment, Location. How are labels applied to workloads and how do they drive policy?"
  "03_workload_types|List and explain the workload types: Managed (with VEN), Unmanaged, and Container Workloads. Include how each is represented in the PCE."
  "04_policy_lifecycle|Describe the policy lifecycle: how policy is authored as Draft, what Pending means, and how it becomes Active. Include provisioning."
  "05_enforcement_modes|Explain the four enforcement modes: Idle, Visibility Only, Selective, Full. What traffic is observed vs blocked in each mode?"
  "06_api_auth_pagination|Describe the REST API authentication using API key + secret, the HTTP header format, and pagination semantics (Link header, max_results parameter)."
  "07_async_traffic_explorer|Describe the async job pattern used by long-running PCE API calls (job submission, status polling, result retrieval). Then describe Traffic Explorer query semantics: what fields are queryable and how flow_link works."
)

for q in "${queries[@]}"; do
  name="${q%%|*}"
  question="${q#*|}"
  out="docs/_notebooklm_excerpts/${name}.md"
  echo "==> $name"
  notebooklm ask "$question" -s "$ADMIN_ID" -s "$REST_ID" -n "$NB" --json --retry 2 \
    > "$out" 2> "${out}.err" || echo "WARN: $name failed; see ${out}.err"
done
```

- [ ] **Step 3: Verify each excerpt has substantive content**

Run:
```bash
for f in docs/_notebooklm_excerpts/0*.md; do
  size=$(wc -c < "$f")
  echo "$size  $f"
done
```
Expected: every file > 500 bytes (raw JSON with `answer` field). For any file < 500 bytes, re-run that single query.

- [ ] **Step 4: Confirm nothing is staged**

Run: `git status --porcelain docs/_notebooklm_excerpts/`
Expected: empty output (still gitignored).

### Task 25: Distill Architecture §1 — Illumio Platform Background

**Files:**
- Modify: `docs/Architecture.md` (insert section 1 at the very top, after the H1 title and before the existing section 2)

- [ ] **Step 1: Read excerpts 01–05**

Run:
```bash
cat docs/_notebooklm_excerpts/0{1,2,3,4,5}_*.md | python3 -c "
import json, sys
for line in sys.stdin.read().split('}\n{'):
    line = line.strip()
    if not line: continue
    try:
        d = json.loads(line if line.startswith('{') else '{'+line if not line.endswith('}') else line)
        print(d.get('answer','')); print('---')
    except Exception:
        print(line); print('---')
"
```
(If the JSON parser approach fails, just `cat` the files and read the `answer` strings manually — the files are intermediate.)

- [ ] **Step 2: Insert section 1 with the following sub-sections**

The new `# 1. Illumio Platform Background` must contain:
- `## 1.1 PCE and VEN` — distilled from excerpt 01. 2–3 paragraphs. Define PCE as the central policy authority and VEN as the on-host enforcement agent. Mention supported VEN platforms. End with a citation: *Source: Illumio Admin Guide 25.4.*
- `## 1.2 Label dimensions` — distilled from excerpt 02. Table of the four dimensions (Role, App, Env, Loc) with example values and how they appear in `illumio_ops` reports.
- `## 1.3 Workload types` — distilled from excerpt 03. Bullet list of Managed / Unmanaged / Container with discriminating attributes.
- `## 1.4 Policy lifecycle` — distilled from excerpt 04. Sequence Draft → Pending → Active with what each state means and which `illumio_ops` features key off draft.
- `## 1.5 Enforcement modes` — distilled from excerpt 05. Table of Idle / Visibility Only / Selective / Full with the observed-vs-blocked behaviour and a cross-reference to `docs/Security_Rules_Reference.md` for rules that depend on enforcement mode.

End the section with a `> **References:** Illumio Admin Guide 25.4 (`Admin_25_4.pdf`).` blockquote.

- [ ] **Step 3: Verify**

Run:
```bash
grep -nE "^## 1\.[1-5] " docs/Architecture.md
grep -c "Illumio Admin Guide 25.4" docs/Architecture.md
```
Expected: 5 sub-section lines; reference grep ≥ 1.

- [ ] **Step 4: Commit**

```bash
git add docs/Architecture.md
git commit -m "docs(architecture): add §1 Illumio Platform Background (NotebookLM-sourced)"
```

### Task 26: Distill Architecture §6 — PCE REST API Cookbook

**Files:**
- Modify: `docs/Architecture.md` (replace existing section 6 with refreshed content)

- [ ] **Step 1: Read excerpts 06 and 07**

Run: `cat docs/_notebooklm_excerpts/06_api_auth_pagination.md docs/_notebooklm_excerpts/07_async_traffic_explorer.md`

- [ ] **Step 2: Cross-check against `src/api_client.py`**

Run:
```bash
sed -n '1,200p' src/api_client.py
```
Note any auth header format / pagination handling already implemented; the cookbook should describe what the code actually does, not a hypothetical pattern.

- [ ] **Step 3: Rewrite section 6**

Replace `# 6. PCE REST API Integration Cookbook` with:
- `## 6.1 Authentication` — API key + secret, HTTP Basic header format, where `illumio_ops` reads them from `config/config.json` (`api.key`, `api.secret`).
- `## 6.2 Pagination` — `Link` header, `max_results` parameter, how `src/api_client.py` chains pages.
- `## 6.3 Async job pattern` — submit job → poll status → fetch result. Include a code block showing the polling loop in `src/api_client.py`.
- `## 6.4 Common endpoints used by illumio_ops` — table: `/workloads`, `/traffic_flows/async_queries`, `/rule_sets`, `/services`, `/ip_lists` etc. with the `src/api/` method that calls each.
- `## 6.5 Error handling and retry strategy` — HTTP error classes, retry-after handling.
- `## 6.6 Rate limiting` — what the PCE returns on overload and how `illumio_ops` backs off.

End with `> **References:** Illumio REST API Guide 25.4 (`REST_APIs_25_4.pdf`).`

- [ ] **Step 4: Verify**

Run:
```bash
grep -nE "^## 6\.[1-6] " docs/Architecture.md
```
Expected: 6 sub-section lines.

- [ ] **Step 5: Commit**

```bash
git add docs/Architecture.md
git commit -m "docs(architecture): rewrite §6 PCE REST API Cookbook against src/api_client.py + REST guide 25.4"
```

### Task 27: Add NotebookLM callouts to User_Manual §4 and Security_Rules_Reference §3

**Files:**
- Modify: `docs/User_Manual.md`
- Modify: `docs/Security_Rules_Reference.md`

- [ ] **Step 1: In `docs/User_Manual.md` §4 (Reports)**

Add a `> **Background**` blockquote after the section 4 H1, briefly defining label dimensions and enforcement modes (1 short paragraph each), with a link `→ docs/Architecture.md §1`.

- [ ] **Step 2: In `docs/Security_Rules_Reference.md` (Configuration → compute_draft)**

Add a `> **Background**` blockquote linking to `docs/Architecture.md §1.4 Policy lifecycle` to ground the reader before the `compute_draft` discussion.

- [ ] **Step 3: Verify**

Run:
```bash
grep -c "Architecture.md §1" docs/User_Manual.md docs/Security_Rules_Reference.md
```
Expected: at least 1 in each file.

- [ ] **Step 4: Commit**

```bash
git add docs/User_Manual.md docs/Security_Rules_Reference.md
git commit -m "docs: add NotebookLM background callouts linking to Architecture §1"
```

---

## Phase D — Documentation Map and Cross-Linking

Install a uniform Documentation Map header in every file and add See-also footers. Build a small Python link checker.

### Task 28: Build the link checker

**Files:**
- Create: `scripts/check_doc_links.py`

- [ ] **Step 1: Write the script**

Create `scripts/check_doc_links.py`:
```python
#!/usr/bin/env python3
"""Walk every Markdown file at repo root and under docs/ and report broken local links.

Exits 0 on success, 1 on any broken link.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINK_RE = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<href>[^)]+)\)")

INCLUDE_DIRS = ["docs"]
INCLUDE_FILES = ["README.md", "README_zh.md", "Status.md", "Task.md"]
EXCLUDE_PARTS = {"_notebooklm_excerpts", "superpowers"}


def iter_markdown() -> list[Path]:
    files: list[Path] = []
    for name in INCLUDE_FILES:
        p = ROOT / name
        if p.is_file():
            files.append(p)
    for d in INCLUDE_DIRS:
        for p in (ROOT / d).rglob("*.md"):
            if EXCLUDE_PARTS & set(p.parts):
                continue
            files.append(p)
    return files


def is_local(href: str) -> bool:
    return not (
        href.startswith(("http://", "https://", "mailto:", "#"))
        or href.startswith("data:")
    )


def check(file: Path) -> list[str]:
    text = file.read_text(encoding="utf-8")
    errors: list[str] = []
    for m in LINK_RE.finditer(text):
        href = m.group("href").split("#", 1)[0].strip()
        if not href or not is_local(href):
            continue
        target = (file.parent / href).resolve()
        if not target.exists():
            errors.append(f"{file.relative_to(ROOT)}: broken link → {href}")
    return errors


def main() -> int:
    errors: list[str] = []
    for f in iter_markdown():
        errors.extend(check(f))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        print(f"\n{len(errors)} broken link(s)", file=sys.stderr)
        return 1
    print("OK — all local links resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Make it executable and run a baseline**

Run:
```bash
chmod +x scripts/check_doc_links.py
python3 scripts/check_doc_links.py || true
```
Expected: prints any pre-existing broken links. They should all be fixed by the end of Phase D.

- [ ] **Step 3: Commit**

```bash
git add scripts/check_doc_links.py
git commit -m "chore: add scripts/check_doc_links.py local-markdown link checker"
```

### Task 29: Insert the Documentation Map block into every file

**Files:**
- Modify: `README.md`, `README_zh.md`, `docs/User_Manual.md`, `docs/User_Manual_zh.md`, `docs/Architecture.md`, `docs/Architecture_zh.md`, `docs/Security_Rules_Reference.md`, `docs/Security_Rules_Reference_zh.md`

- [ ] **Step 1: Define the canonical block (relative paths from inside `docs/`)**

For files **inside** `docs/`, the block is:
```markdown
<!-- BEGIN:doc-map -->
| Document | EN | 中文 |
|---|---|---|
| README | [README.md](../README.md) | [README_zh.md](../README_zh.md) |
| User Manual | [User_Manual.md](./User_Manual.md) | [User_Manual_zh.md](./User_Manual_zh.md) |
| Architecture | [Architecture.md](./Architecture.md) | [Architecture_zh.md](./Architecture_zh.md) |
| Security Rules | [Security_Rules_Reference.md](./Security_Rules_Reference.md) | [Security_Rules_Reference_zh.md](./Security_Rules_Reference_zh.md) |
<!-- END:doc-map -->
```

For files **at repo root** (READMEs), the same table but using `docs/` prefixes for the doc files and `README.md` / `README_zh.md` for the README cells.

- [ ] **Step 2: Insert the block immediately after the first H1 of each file**

For each of the 8 doc files, open the file, locate the first `^# ` line, and insert the appropriate block as the next paragraph.

- [ ] **Step 3: Verify all 8 files have the marker**

Run:
```bash
grep -L "BEGIN:doc-map" README.md README_zh.md docs/User_Manual.md docs/User_Manual_zh.md docs/Architecture.md docs/Architecture_zh.md docs/Security_Rules_Reference.md docs/Security_Rules_Reference_zh.md
```
Expected: empty output (every file matched).

- [ ] **Step 4: Commit**

```bash
git add README.md README_zh.md docs/*.md
git commit -m "docs: insert Documentation Map header in every doc file"
```

### Task 30: Add See-also footer to each file

**Files:** same 8 files

- [ ] **Step 1: For each file append a See-also section**

For `docs/User_Manual.md`, append:
```markdown

## See also

- [Architecture](./Architecture.md) — System overview, module map, PCE Cache, REST API Cookbook
- [Security Rules Reference](./Security_Rules_Reference.md) — R01–R05 rules and `compute_draft` behaviour
- [README](../README.md) — Project entry and Quickstart
```

For `docs/Architecture.md`, append:
```markdown

## See also

- [User Manual](./User_Manual.md) — CLI / GUI / Daemon / Reports / SIEM
- [Security Rules Reference](./Security_Rules_Reference.md) — Rule catalogue
- [README](../README.md) — Project entry and Quickstart
```

For `docs/Security_Rules_Reference.md`, append:
```markdown

## See also

- [User Manual](./User_Manual.md) §4 Reports — How rule findings appear in reports
- [Architecture](./Architecture.md) §1.4 — Policy lifecycle background
- [README](../README.md) — Project entry and Quickstart
```

For each ZH counterpart, mirror the EN footer with translated labels but identical link targets.

For `README.md` and `README_zh.md`, append a "Documentation" section listing all four doc pairs with one-line descriptions.

- [ ] **Step 2: Verify**

Run:
```bash
grep -c "^## See also\|^## 延伸閱讀" README.md README_zh.md docs/*.md
```
Expected: each of the 8 files reports `1`.

- [ ] **Step 3: Commit**

```bash
git add README.md README_zh.md docs/*.md
git commit -m "docs: add See-also footer to every doc file"
```

### Task 31: Phase D acceptance — link checker must pass

**Files:** none modified

- [ ] **Step 1: Run the link checker**

Run: `python3 scripts/check_doc_links.py`
Expected: `OK — all local links resolve`. If broken, fix the offending links and re-run.

---

## Phase E — ZH Translation Pass

Translate each EN doc into Traditional Chinese, preserving heading structure and code blocks byte-for-byte. Status.md and Task.md are excluded.

### Task 32: Translate docs/User_Manual.md → docs/User_Manual_zh.md

**Files:**
- Modify: `docs/User_Manual_zh.md` (full rewrite, mirroring EN structure)

- [ ] **Step 1: Pull the heading skeleton from EN**

Run:
```bash
grep -nE '^#{1,6} ' docs/User_Manual.md > /tmp/um_en_headings.txt
wc -l /tmp/um_en_headings.txt
```

- [ ] **Step 2: For each heading, write the ZH equivalent**

Translate H1–H4 headings to Traditional Chinese using these conventions:
- "Installation" → "安裝"
- "Configuration" → "設定"
- "Operations" → "操作"
- "Reports" → "報表"
- "SIEM Integration" → "SIEM 整合"
- "Background" → "背景"
- "See also" → "延伸閱讀"

Subcommand names, file paths, config keys, CLI flags, and module names remain in English. Code blocks are byte-identical.

- [ ] **Step 3: For each paragraph, write the ZH equivalent**

Mirror each EN paragraph in Traditional Chinese, preserving inline code (backticks unchanged), tables (header keys in EN, value cells translated where they describe behaviour).

- [ ] **Step 4: Heading-structure parity check**

Run:
```bash
diff <(grep -E '^#{1,6} ' docs/User_Manual.md    | sed -E 's/^(#+) .*/\1/') \
     <(grep -E '^#{1,6} ' docs/User_Manual_zh.md | sed -E 's/^(#+) .*/\1/')
```
Expected: empty output (heading depths match in order).

- [ ] **Step 5: Line-count parity check**

Run:
```bash
en=$(wc -l < docs/User_Manual.md)
zh=$(wc -l < docs/User_Manual_zh.md)
python3 -c "import sys; en=$en; zh=$zh; ratio=zh/en; assert 0.85<=ratio<=1.15, f'ZH/EN ratio {ratio:.2f} out of band'; print(f'OK ratio={ratio:.2f}')"
```
Expected: `OK ratio=…` within 0.85–1.15.

- [ ] **Step 6: Commit**

```bash
git add docs/User_Manual_zh.md
git commit -m "docs(user-manual): full ZH retranslation aligned to EN section structure"
```

### Task 33: Translate docs/Architecture.md → docs/Architecture_zh.md

**Files:**
- Modify: `docs/Architecture_zh.md` (full rewrite mirroring EN)

- [ ] **Step 1: Translate**

Apply the same procedure as Task 32. Term conventions:
- "Illumio Platform Background" → "Illumio 平台背景"
- "System Overview" → "系統概觀"
- "Module Map" → "模組地圖"
- "Data Flow" → "資料流"
- "PCE Cache" → "PCE 快取"
- "PCE REST API Integration Cookbook" → "PCE REST API 整合手冊"
- "References" → "參考資料"

- [ ] **Step 2: Heading-structure parity check**

Run:
```bash
diff <(grep -E '^#{1,6} ' docs/Architecture.md    | sed -E 's/^(#+) .*/\1/') \
     <(grep -E '^#{1,6} ' docs/Architecture_zh.md | sed -E 's/^(#+) .*/\1/')
```
Expected: empty output.

- [ ] **Step 3: Line-count parity check**

Run:
```bash
en=$(wc -l < docs/Architecture.md)
zh=$(wc -l < docs/Architecture_zh.md)
python3 -c "import sys; en=$en; zh=$zh; ratio=zh/en; assert 0.85<=ratio<=1.15, f'ZH/EN ratio {ratio:.2f} out of band'; print(f'OK ratio={ratio:.2f}')"
```

- [ ] **Step 4: Commit**

```bash
git add docs/Architecture_zh.md
git commit -m "docs(architecture): full ZH retranslation aligned to EN section structure"
```

### Task 34: Translate docs/Security_Rules_Reference.md → docs/Security_Rules_Reference_zh.md

**Files:**
- Modify: `docs/Security_Rules_Reference_zh.md` (full rewrite mirroring EN)

- [ ] **Step 1: Translate**

Same procedure. Term conventions:
- "Rule catalogue" → "規則目錄"
- "Severity model" → "嚴重度模型"
- "Trigger condition" → "觸發條件"
- "Recommended remediation" → "建議補救"
- "compute_draft auto-enable" → "compute_draft 自動啟用"

Rule IDs (R01–R05), config key names, and the analyzer expression literals are NOT translated.

- [ ] **Step 2: Heading-structure parity check**

Run:
```bash
diff <(grep -E '^#{1,6} ' docs/Security_Rules_Reference.md    | sed -E 's/^(#+) .*/\1/') \
     <(grep -E '^#{1,6} ' docs/Security_Rules_Reference_zh.md | sed -E 's/^(#+) .*/\1/')
```
Expected: empty output.

- [ ] **Step 3: Line-count parity check**

Run:
```bash
en=$(wc -l < docs/Security_Rules_Reference.md)
zh=$(wc -l < docs/Security_Rules_Reference_zh.md)
python3 -c "en=$en; zh=$zh; ratio=zh/en; assert 0.85<=ratio<=1.15, f'ZH/EN ratio {ratio:.2f} out of band'; print(f'OK ratio={ratio:.2f}')"
```

- [ ] **Step 4: Commit**

```bash
git add docs/Security_Rules_Reference_zh.md
git commit -m "docs(security-rules): full ZH retranslation aligned to EN section structure"
```

### Task 35: Translate README.md → README_zh.md

**Files:**
- Modify: `README_zh.md`

- [ ] **Step 1: Translate**

Same procedure. The README is shorter; aim for full mirror including the Quickstart code block (commands unchanged, surrounding prose translated).

- [ ] **Step 2: Heading parity + ratio**

Run:
```bash
diff <(grep -E '^#{1,6} ' README.md    | sed -E 's/^(#+) .*/\1/') \
     <(grep -E '^#{1,6} ' README_zh.md | sed -E 's/^(#+) .*/\1/')
en=$(wc -l < README.md); zh=$(wc -l < README_zh.md)
python3 -c "en=$en; zh=$zh; ratio=zh/en; assert 0.85<=ratio<=1.15, f'ratio {ratio:.2f}'; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add README_zh.md
git commit -m "docs(readme): full ZH retranslation aligned to EN structure"
```

---

## Phase F — Acceptance Gate

Run the 9-point acceptance checklist from the spec. If anything fails, return to the relevant phase.

### Task 36: Acceptance G1 — All 10 files exist with non-empty content

- [ ] **Step 1: Existence + size check**

Run:
```bash
for f in README.md README_zh.md Status.md Task.md \
         docs/User_Manual.md docs/User_Manual_zh.md \
         docs/Architecture.md docs/Architecture_zh.md \
         docs/Security_Rules_Reference.md docs/Security_Rules_Reference_zh.md; do
  if [ ! -f "$f" ]; then echo "MISSING $f"; continue; fi
  lines=$(wc -l < "$f")
  echo "$lines  $f"
done
```
Expected: every line shows ≥ 100 (≥ 30 acceptable for `Status.md` / `Task.md` only); no `MISSING`.

### Task 37: Acceptance G2 — Line-count floors

- [ ] **Step 1: Per-file floors**

Run:
```bash
python3 - <<'PY'
floors = {
  "docs/User_Manual.md": 1700,
  "docs/Architecture.md": 800,
  "docs/Security_Rules_Reference.md": 700,
  "README.md": 100,
}
fail = False
for path, floor in floors.items():
    n = sum(1 for _ in open(path, encoding="utf-8"))
    flag = "OK" if n >= floor else "LOW"
    if flag == "LOW": fail = True
    print(f"{flag}  {n:>5} / {floor:>5}  {path}")
import sys; sys.exit(1 if fail else 0)
PY
```
Expected: every line is `OK`. If `LOW`, expand the under-sized doc.

- [ ] **Step 2: ZH/EN ratio per pair**

Run:
```bash
python3 - <<'PY'
pairs = [
  ("README.md", "README_zh.md"),
  ("docs/User_Manual.md", "docs/User_Manual_zh.md"),
  ("docs/Architecture.md", "docs/Architecture_zh.md"),
  ("docs/Security_Rules_Reference.md", "docs/Security_Rules_Reference_zh.md"),
]
fail = False
for en, zh in pairs:
    a = sum(1 for _ in open(en, encoding="utf-8"))
    b = sum(1 for _ in open(zh, encoding="utf-8"))
    r = b/a if a else 0
    flag = "OK" if 0.85 <= r <= 1.15 else "DRIFT"
    if flag == "DRIFT": fail = True
    print(f"{flag}  ratio={r:.2f}  {en}={a}  {zh}={b}")
import sys; sys.exit(1 if fail else 0)
PY
```
Expected: every line `OK`.

- [ ] **Step 3: Total ≥ 6,500 lines**

Run:
```bash
total=$(cat README.md README_zh.md Status.md Task.md docs/*.md 2>/dev/null | wc -l)
echo "TOTAL=$total"
[ "$total" -ge 6500 ] && echo OK || { echo LOW; exit 1; }
```

### Task 38: Acceptance G3 — Heading-structure parity

- [ ] **Step 1: Run parity diff for every pair**

Run:
```bash
for pair in "README.md README_zh.md" \
            "docs/User_Manual.md docs/User_Manual_zh.md" \
            "docs/Architecture.md docs/Architecture_zh.md" \
            "docs/Security_Rules_Reference.md docs/Security_Rules_Reference_zh.md"; do
  set -- $pair
  d=$(diff <(grep -E '^#{1,6} ' "$1" | sed -E 's/^(#+) .*/\1/') \
            <(grep -E '^#{1,6} ' "$2" | sed -E 's/^(#+) .*/\1/'))
  if [ -n "$d" ]; then echo "DRIFT $1 vs $2"; echo "$d"; else echo "OK $1 vs $2"; fi
done
```
Expected: every pair `OK`.

### Task 39: Acceptance G4 — Coverage script

- [ ] **Step 1: Run coverage check**

Run: `scripts/check_doc_coverage.sh`
Expected: `OK — all required terms present in docs/User_Manual.md`.

### Task 40: Acceptance G5 — Documentation Map present

- [ ] **Step 1: Verify**

Run:
```bash
grep -L "BEGIN:doc-map" README.md README_zh.md docs/User_Manual.md docs/User_Manual_zh.md docs/Architecture.md docs/Architecture_zh.md docs/Security_Rules_Reference.md docs/Security_Rules_Reference_zh.md
```
Expected: empty output.

### Task 41: Acceptance G6 — Link checker

- [ ] **Step 1: Run**

Run: `python3 scripts/check_doc_links.py`
Expected: `OK — all local links resolve`.

### Task 42: Acceptance G7 — i18n guardrails unaffected

- [ ] **Step 1: Run i18n audit**

Run: `python3 scripts/audit_i18n_usage.py`
Expected: exit 0.

- [ ] **Step 2: Run i18n tests**

Run: `python3 -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py -q`
Expected: 0 failures.

### Task 43: Acceptance G8 — _notebooklm_excerpts not in commit

- [ ] **Step 1: Verify**

Run:
```bash
git log --all -- 'docs/_notebooklm_excerpts/*' | head
git diff HEAD~30..HEAD --stat | grep _notebooklm_excerpts || echo "OK — no excerpts staged"
```
Expected: `OK — no excerpts staged`.

### Task 44: Acceptance G9 — Status.md and Task.md updated

**Files:**
- Modify: `Status.md`
- Modify: `Task.md`

- [ ] **Step 1: Capture rebuild commit hash**

Run: `git log --oneline | head -1`
Note the most recent commit hash; it will be referenced in the next step.

- [ ] **Step 2: Append a completion note to Status.md**

Append to `Status.md`:
```markdown

---

## 2026-04-28 — Documentation rebuild complete

- Rebuilt 10 user-facing files (README × 2, User_Manual × 2, Architecture × 2, Security_Rules_Reference × 2, Status, Task) to v3.20.0.
- EN/ZH parity verified at the heading level (`scripts/check_doc_links.py` + per-pair diff).
- Coverage gates passed (`scripts/check_doc_coverage.sh`, `scripts/check_doc_links.py`, i18n audit/tests).
- Plan: `docs/superpowers/plans/2026-04-28-documentation-rebuild.md`
- Spec: `docs/superpowers/specs/2026-04-28-documentation-rebuild-design.md`
```

- [ ] **Step 3: Update Task.md to reflect closure**

Replace the "Active task" block added in Task 9 with:
```markdown

---

## Closed task — Documentation rebuild (2026-04-28)

Plan and spec at `docs/superpowers/{plans,specs}/2026-04-28-documentation-rebuild*.md`. Acceptance gates G1–G9 all passed.
```

- [ ] **Step 4: Commit**

```bash
git add Status.md Task.md
git commit -m "docs: mark documentation rebuild complete in Status.md and Task.md"
```

### Task 45: Final summary log

- [ ] **Step 1: Print rebuild summary**

Run:
```bash
echo "=== Documentation rebuild — final summary ==="
echo
echo "Files:"
for f in README.md README_zh.md Status.md Task.md docs/User_Manual.md docs/User_Manual_zh.md docs/Architecture.md docs/Architecture_zh.md docs/Security_Rules_Reference.md docs/Security_Rules_Reference_zh.md; do
  printf '  %5d lines  %s\n' "$(wc -l < $f)" "$f"
done
echo
echo "Commits added by this rebuild:"
git log --oneline ed20df0..HEAD -- README.md README_zh.md Status.md Task.md 'docs/*.md' scripts/check_doc_links.py scripts/check_doc_coverage.sh
```
This summary is the closing artefact of the rebuild — record it in the Telegram channel or paste it into the final agent reply.
