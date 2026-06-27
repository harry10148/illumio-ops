---
title: Release Process
audience: [developer]
last_verified: 2026-06-26
verified_against:
  - CHANGELOG.md
  - deploy/
  - scripts/setup-prod-git.sh
  - README.md
  - commit d9b8389
related_docs:
  - dev-setup.md
  - ../getting-started.md
  - i18n-workflow.md
  - ../user-guide/tls-and-certificates.md
---

> **[English](release-process.md)** | **[繁體中文](release-process_zh.md)**
> 📍 [INDEX](../INDEX.md) › Contributing › Release Process
> 🔍 Last verified **2026-05-15** against commit `d9b8389` — see frontmatter for sources

# Release Process

---

## Versioning scheme

illumio-ops uses plain **semantic versioning** (`<major>.<minor>.<patch>`, e.g. `4.1.0`).
The `-<topic-slug>` codename scheme used before v4.0.0 has been retired —
`scripts/bump_version.sh` **rejects** any version that is not a bare `X.Y.Z`.

The version source of truth is `__version__` in `src/__init__.py`.

**Bump rules:**

- `patch` — bug fixes, documentation, dependency pins; no new behaviour.
- `minor` — new features or non-breaking API additions; backward compatible.
- `major` — breaking changes to config schema, CLI flags, or API contracts.

**README version badge** is a plain `v<X.Y.Z>` shield:

```markdown
![Version](https://img.shields.io/badge/Version-v4.1.0-blue?style=flat-square)
```

`scripts/bump_version.sh` rewrites this badge in **both** `README.md` and `README_zh.md`
automatically — you do not edit it by hand.

---

## Pre-release checklist

Run all of the following before tagging. Do not skip items because the
change "looks small" — each catches a distinct class of regression.

- [ ] **Tests pass** — `pytest -q` exits 0 on the current branch.
- [ ] **Lint clean** — `ruff check .` or `flake8` shows no errors.
- [ ] **Type-check passes** — `mypy src/` shows no new errors.
- [ ] **i18n audit clean** — run the i18n pre-release audit; see
  [i18n Workflow](i18n-workflow.md) for the exact command.
  Every key used in code must appear in both `en` and `zh_TW` bundles.
- [ ] **CHANGELOG updated** — add a new `## [<version>] — <YYYY-MM-DD>` section
  with user-visible changes. Follow the "Keep a Changelog" format already used.
- [ ] **Version bump in README badge** — update the `![Version]` shield in
  `README.md` (and `README_zh.md`) to the new tag.
- [ ] **Offline bundle ready (if applicable)** — `requirements-offline.txt`
  and `wheels/` are regenerated if any dependency changed.
- [ ] **Migration script drafted (if needed)** — breaking config changes require
  a script under `scripts/migrate_*.py`. See CHANGELOG v3.26.0 for an example
  (`migrate_rules_to_keys.py`).

---

## Tagging & version bump

Use the canonical bump script — it updates `src/__init__.py` (`__version__`), inserts a
new `CHANGELOG.md` section, rewrites the Version badge in `README.md` + `README_zh.md`,
then commits and creates the annotated tag:

```bash
# from a clean working tree, on the release branch
pytest -q                          # tests must pass first
scripts/bump_version.sh 4.1.1      # bare semver only — codenames are rejected
git push origin main
git push origin v4.1.1             # push the tag the script created
```

To stage the file edits without committing/tagging (e.g. to fill in the CHANGELOG by
hand first), use `--no-tag`:

```bash
scripts/bump_version.sh 4.1.1 --no-tag   # edits src/__init__.py + CHANGELOG only
# ...edit CHANGELOG.md, then commit + tag by hand...
```

> **Note:** Annotated tags (`-a`) are preferred over lightweight tags because
> they carry a tagger identity and timestamp visible in `git log --tags`.

---

## Deployment to prod / lab

The standard upgrade path for an already-installed deployment box:

```bash
# On the deployment box (as the service user or with sudo)
cd /opt/illumio-ops

git pull                                              # fetch + fast-forward
pip install -r requirements.txt                       # sync Python deps
sudo systemctl restart illumio-ops.service            # apply new code
```

If the deployment uses the **offline bundle** (no internet access):

```bash
pip install --no-index --find-links wheels -r requirements-offline.txt
sudo systemctl restart illumio-ops.service
```

For the full operator-facing upgrade SOP (including Windows / NSSM and config
preservation details) see [Getting Started — Upgrade section](../getting-started.md).

**Offline-bundle installer (`scripts/install.sh`)**: detects an existing install
by checking for `<INSTALL_ROOT>/config/config.json` and sets `IS_UPGRADE=true`.
The internal pip invocation it runs is:

```bash
"$INSTALL_ROOT/python/bin/python3" -m pip install \
    --no-index --find-links "$SRC/wheels" \
    -r requirements-offline.txt
```

After the dependency refresh, the installer restarts `illumio-ops.service` only
when `IS_UPGRADE=true` — fresh installs leave the service stopped so the
operator can review settings first.

---

## Per-version migration scripts

Some releases ship a one-shot migration that rewrites operator-owned state
(`config/alerts.json`, `config/rule_schedules.json`, etc.). Scripts live in
`scripts/migrate_*.py` and are **idempotent** — safe to re-run.

Run AFTER the upgrade installer completes, but BEFORE relying on the new
schema in production.

### v3.26.0 — alerts.json keys

3.26.0 moved rule description/recommendation text into `desc_key` / `rec_key`
so language switching is instant. Existing rules without keys keep working
(loader falls back to a `[MISSING:*]` marker until migrated). Run once:

```bash
# Linux (offline-bundle install)
sudo -u illumio-ops /opt/illumio-ops/python/bin/python3 \
    /opt/illumio-ops/scripts/migrate_rules_to_keys.py \
    --config /opt/illumio-ops/config/config.json --write

# Source / development install
python3 scripts/migrate_rules_to_keys.py --config config/config.json --write
```

```powershell
# Windows (NSSM install)
& C:\illumio-ops\python\python.exe `
    C:\illumio-ops\scripts\migrate_rules_to_keys.py `
    --config C:\illumio-ops\config\config.json -Write
```

Re-running once all rules are converted is a no-op.

### Other versions

No mandatory migrations.

---

## Production git setup

Run **once** on every new deployment box, immediately after the initial clone:

```bash
bash scripts/setup-prod-git.sh
```

**Why:** `git pull` on a deployment box frequently aborts with
_"would be overwritten by merge"_ when a tracked file (e.g.
`deploy/install_service.ps1`, `scripts/install.sh`,
`src/pce_cache/ingestor_events.py`) has been edited in place.

The script enables `merge.autoStash = true` and `rebase.autoStash = true`
on the local repo. With autoStash, `git pull` stashes local edits →
fast-forwards → pops the stash, instead of aborting.

The setting is **local-only** — it does not affect the upstream repo or any
other clone. The script is idempotent; re-running it is harmless.

_Source: commit `2f173d0`, `scripts/setup-prod-git.sh`._

---

## Rollback

```bash
# 1. Stop the service
sudo systemctl stop illumio-ops.service

# 2. Check out the previous release tag
git checkout "v<previous-tag>"
# OR restore python/ and src/ from the offline tarball of the previous version

# 3. Reinstall dependencies for the previous version
pip install --no-index --find-links wheels -r requirements-offline.txt

# 4. Restart the service
sudo systemctl start illumio-ops.service
```

**Config compatibility note:** `config/config.json` is **not** rolled back.
The older code safely ignores unknown config keys added by newer versions.
Do not restore `config/` from backup unless the new version corrupted it.

**Migration scripts:** If a migration script ran (e.g. `migrate_rules_to_keys.py`),
the edited `config/alerts.json` is forward-compatible — older code reads
`desc_key`/`rec_key` via a fallback path and continues to work without
reverting the migration.

---

## Post-release verification

After the service restarts, verify the deployment is healthy:

1. **Health endpoint** — `GET /api/status` should return HTTP 200.
   > Note: `/health` does **not** exist; the correct endpoint is `/api/status`
   > (confirmed during B1.3 audit).

   ```bash
   curl -s http://localhost:<port>/api/status | python3 -m json.tool
   ```

2. **Dashboard smoke-test** — open the web GUI, verify the dashboard loads
   without JS console errors and displays current PCE data.

3. **Report generation** — trigger at least one report type and confirm it
   renders without errors in the UI and in `logs/`.

4. **Monitor logs** — watch `journalctl -u illumio-ops.service -f` for 2–3
   minutes; there should be no `ERROR` or `CRITICAL` lines after startup
   stabilises.

5. **Version badge** — confirm the `/api/status` response (or the GUI footer)
   reflects the new version string.

> **TODO:** Add a `scripts/smoke_test.sh` that automates steps 1 and 3 for
> CI/CD pipelines.

---

## Related Docs

- [Dev Setup](dev-setup.md) — local environment before tagging
- [Getting Started (operator upgrade)](../getting-started.md) — what end-users do
- [i18n Workflow](i18n-workflow.md) — pre-release i18n audit
- [Operations Manual](../operations-manual_zh.md) — TLS cert rotation (§8.6) and day-2 operations (繁體中文)
