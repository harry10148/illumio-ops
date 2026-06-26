# Install Root Rename: `illumio_ops` → `illumio-ops`

**Feature Name:** Standardise filesystem install root and system user to kebab-case
**Goal:** Match the already-renamed entry script (`illumio-ops.py`), GitHub repo (`illumio-ops`), and systemd unit name (`illumio-ops.service`) by also renaming the install root, system user, and bundle artefact filenames. After this change, no operator-facing path or identifier uses the underscore form.
**Architecture:** Forward-only changes for fresh installs in early phases; explicit upgrade-path migration for existing installs in a later phase. Strictly scoped to filesystem paths and system identities — does NOT touch in-code identifiers, log filenames, or SIEM source fields.
**Tech Stack:** bash, PowerShell, systemd, NSSM, sed (for doc rewrites)

---

## Scope

### In scope (this rename)

| # | Dimension | Old | New | Touch points |
|---|-----------|-----|-----|--------------|
| 1 | Linux install root | `/opt/illumio_ops` | `/opt/illumio-ops` | ~65 across docs / scripts / systemd unit |
| 2 | Windows install root | `C:\illumio_ops` | `C:\illumio-ops` | `scripts/install.ps1:22` default + 2 doc examples |
| 3 | System user | `illumio_ops` | `illumio-ops` | `deploy/illumio-ops.service:9-10` (`User=` / `Group=`), `scripts/install.sh` useradd, 2 doc references |
| 4 | Bundle archive filename | `illumio_ops-<v>-offline-{linux,windows}-x86_64.{tar.gz,zip}` | `illumio-ops-<v>-offline-…` | `scripts/build_offline_bundle.sh:5,6,67,107`, ~6 doc references |
| 5 | Extracted bundle directory | `illumio_ops-<v>/` | `illumio-ops-<v>/` | docs install steps |
| 6 | CLI `--help` examples | `python illumio_ops.py --gui` | `python illumio-ops.py --gui` | `src/main.py:482-486` (cosmetic, not behavioural) |

### Out of scope (deliberately NOT renamed)

These all match the underscore form today and **stay unchanged**, with reasoning recorded so future audits don't re-litigate:

| Identifier | Why kept |
|------------|----------|
| `logs/illumio_ops.log` | Customer log shippers (filebeat, rsyslog, journald regex rules) parse this exact filename; rename requires coordinated config update on every customer host |
| Splunk HEC `sourcetype: illumio_ops` (`src/siem/transports/splunk_hec.py:15`) | Customer Splunk searches and dashboards filter on this sourcetype; silent rename breaks alerting |
| `deploy/filebeat.illumio_ops.yml`, `logstash.illumio_ops.conf`, `rsyslog.illumio_ops.conf` | Sample SIEM configs paired with the log filename above; renaming would split the pair |
| Python module docstrings `"for illumio_ops"` | Internal identifier, not surfaced to operators |
| Python source tree `src/` package paths | snake_case is Python convention (PEP 8); cross-cutting refactor with no user benefit |
| `requirements.txt` comment | Cosmetic, no behavioural impact |
| Tests `tests/test_cli_compat_matrix.py` `["illumio_ops.py", …]` | Asserts CLI backwards-compat for the legacy script name; deliberately keeps the old name |

A future ticket may revisit the SIEM-related identifiers as a coordinated customer-facing change.

---

## Architecture & Sequencing

The rename runs in 5 batches with a verification gate between each. **Forward-only** changes (new installs use new paths) come first so they can ship and bake without affecting existing fleets. The risky **migration logic** (touching existing `/opt/illumio_ops` deployments) is isolated to the last code-touching batch.

```
Batch 1 — Bundle artefact filename            (forward-only, low risk)
       ↓ verify: build_offline_bundle.sh produces dist/illumio-ops-<v>-offline-*
Batch 2 — Install path defaults               (forward-only, fresh installs only)
       ↓ verify: clean Linux + Windows install lands at /opt/illumio-ops / C:\illumio-ops
Batch 3 — System user / group                 (forward-only, fresh installs only)
       ↓ verify: clean Linux install creates user `illumio-ops`; service runs under it
Batch 4 — Upgrade migration                   (touches existing installs — risky)
       ↓ verify: simulated upgrade from /opt/illumio_ops moves cleanly to /opt/illumio-ops
Batch 5 — Doc sweep + CLI help text + final grep verification
       ↓ verify: zero `/opt/illumio_ops` matches in user-facing docs / scripts (excl. migration code)
```

Verification gates are **mandatory pauses** for the user to manually test on a real host before proceeding. This matches the user's stated preference for batched subagent-driven execution with manual review per batch.

---

## Migration Strategy (Batch 4)

### Trigger conditions

`scripts/install.sh` and `scripts/install.ps1` already detect upgrade vs fresh install via `IS_UPGRADE = test_path config/config.json`. Migration runs when **all** of:
- `IS_UPGRADE=1`
- Old install root exists (`/opt/illumio_ops` on Linux, `C:\illumio_ops` on Windows)
- New install root does NOT exist
- Detected install was not yet migrated (no `MIGRATED_FROM` marker file)

### Linux migration sequence (atomic-ish)

```
1. systemctl stop illumio-ops
2. usermod -l illumio-ops illumio_ops          # rename user (UID preserved)
3. groupmod -n illumio-ops illumio_ops         # rename group (GID preserved)
4. mv /opt/illumio_ops /opt/illumio-ops
5. install systemd unit (now with WorkingDirectory=/opt/illumio-ops, User=illumio-ops)
6. systemctl daemon-reload
7. echo "/opt/illumio_ops" > /opt/illumio-ops/MIGRATED_FROM
8. systemctl start illumio-ops
```

Why this order: stop service first to release file locks; rename user before mv so any open file descriptors close cleanly; chown is unnecessary because `usermod -l` preserves UID and existing inodes still point at the same UID.

**Pre-flight checks before starting** (fail fast, do nothing destructive):
- Confirm `usermod` and `groupmod` exist (yes on every supported distro)
- Confirm no other user owns the name `illumio-ops` (would cause `usermod -l` to fail)
- Confirm `/opt/illumio-ops` does not already exist (would cause `mv` to fail)
- Confirm running as root

**Rollback on partial failure** (each step records a marker; on failure, reverse in order):
- If steps 2-3 succeeded but step 4 failed: `usermod -l illumio_ops illumio-ops` to undo
- If step 4 succeeded but step 5 failed: `mv /opt/illumio-ops /opt/illumio_ops` to undo
- After step 8 succeeds, MIGRATED_FROM is the durable record

### Windows migration sequence

```
1. Stop-Service IllumioOps
2. Move-Item C:\illumio_ops C:\illumio-ops
3. nssm set IllumioOps AppDirectory C:\illumio-ops
4. nssm set IllumioOps Application  C:\illumio-ops\python\python.exe
5. nssm set IllumioOps AppParameters "C:\illumio-ops\illumio-ops.py --monitor --interval 10"
6. nssm set IllumioOps AppStdout    C:\illumio-ops\logs\service_stdout.log
7. nssm set IllumioOps AppStderr    C:\illumio-ops\logs\service_stderr.log
8. New-Item -Type File C:\illumio-ops\MIGRATED_FROM -Value "C:\illumio_ops"
9. Start-Service IllumioOps
```

No system user rename on Windows (NSSM runs as LocalSystem by default in this project).

---

## Success Criteria

- Fresh Linux install lands at `/opt/illumio-ops`, runs as user `illumio-ops`, service stays in `Active (running)` for ≥1 minute
- Fresh Windows install lands at `C:\illumio-ops`, NSSM service `IllumioOps` reports `SERVICE_RUNNING`
- Existing `/opt/illumio_ops` install upgrades cleanly to `/opt/illumio-ops` with zero data loss; `MIGRATED_FROM` file documents the source path; service restarts and stays running
- `bash scripts/build_offline_bundle.sh` outputs `dist/illumio-ops-<v>-offline-{linux,windows}-x86_64.*` (kebab-case)
- Final grep across user-facing files (`docs/`, `README*`, `scripts/`, `deploy/`, excluding `docs/superpowers/`, the migration code itself, and the in-code identifiers listed in "Out of scope") returns **zero matches** for `illumio_ops` (underscore)
- All existing tests pass, including `tests/test_cli_compat_matrix.py` which intentionally references the legacy CLI name

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| `usermod -l` fails because `illumio_ops` user has running processes (e.g. crontab) | Stop systemd unit first; if other processes own files, document manual `ps -u illumio_ops` cleanup before re-running |
| `mv /opt/illumio_ops /opt/illumio-ops` fails (cross-device, permission, race) | Pre-flight `df` check that both paths are on the same filesystem; if not, fall back to `rsync -aHAX` + `rm -rf` (slower but cross-device safe) |
| Operator runs new installer on host that already migrated, expects another rename | `MIGRATED_FROM` marker file makes second-run a no-op |
| Doc-only references to `/opt/illumio_ops` linger and confuse operators | Batch 5 final grep is part of success criteria; CI lint can be added in a follow-up |
| External monitoring expects `/opt/illumio_ops` path string in alerts | Out of scope — surface as a release-note bullet in the version bumping that ships this rename |
| In-code identifiers diverge from filesystem identity (e.g. log file is `illumio_ops.log` but install dir is `illumio-ops`) | Documented as deliberate in "Out of scope"; operator-visible inconsistency, but functionally harmless and SIEM-stable |

---

## Non-goals

- Renaming the SIEM source/sourcetype field — defer to a coordinated customer-facing release
- Renaming the log filename — same reason
- Touching Python source identifiers / module names — snake_case is correct Python style
- Adding CI lint for `illumio_ops` — separate hardening ticket
