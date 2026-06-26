# Install Root Rename: `illumio_ops` → `illumio-ops` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Each batch ends with a verification gate that requires manual review on a real host before the next batch starts** — do not chain batches.

**Goal:** Standardise filesystem install root and system user to kebab-case so no operator-facing path or identifier uses the underscore form. See spec `docs/superpowers/specs/2026-05-03-install-root-rename-design.md` for scope, out-of-scope items, and migration design.

**Architecture:** Forward-only changes for fresh installs in batches 1-3; explicit upgrade-path migration in batch 4; final doc sweep + verification in batch 5.

**Tech Stack:** bash, PowerShell, systemd, NSSM, sed.

---

## Batch 1 — Bundle artefact filename (forward-only)

Renames the produced bundle archive and the directory it extracts into. No effect on existing installs.

### Task 1.1: Rename build script outputs

**Files:** `scripts/build_offline_bundle.sh`

- [ ] **Step 1: Update header comment**

```bash
sed -i 's|dist/illumio_ops-<version>-offline-linux|dist/illumio-ops-<version>-offline-linux|' scripts/build_offline_bundle.sh
sed -i 's|dist/illumio_ops-<version>-offline-windows|dist/illumio-ops-<version>-offline-windows|' scripts/build_offline_bundle.sh
```

- [ ] **Step 2: Update `local ARCHIVE=` lines** (lines ~67, ~107)

```bash
sed -i 's|illumio_ops-${VERSION}-offline-linux-x86_64.tar.gz|illumio-ops-${VERSION}-offline-linux-x86_64.tar.gz|' scripts/build_offline_bundle.sh
sed -i 's|illumio_ops-${VERSION}-offline-windows-x86_64.zip|illumio-ops-${VERSION}-offline-windows-x86_64.zip|' scripts/build_offline_bundle.sh
```

- [ ] **Step 3: Update final `ls` glob in epilogue**

```bash
sed -i 's|illumio_ops-"\${VERSION}"-offline-|illumio-ops-"${VERSION}"-offline-|' scripts/build_offline_bundle.sh
```

- [ ] **Step 4: Sanity check**

```bash
bash -n scripts/build_offline_bundle.sh
grep -n 'illumio_ops-' scripts/build_offline_bundle.sh   # expect zero hits
```

### Task 1.2: Update doc references to extracted directory

**Files:** `docs/Installation.md`, `docs/Installation_zh.md`, `docs/User_Manual.md`, `docs/User_Manual_zh.md`, `README.md`, `README_zh.md`

- [ ] **Step 1: Mass-replace archive filename and extracted dir in docs**

```bash
for f in docs/Installation.md docs/Installation_zh.md docs/User_Manual.md docs/User_Manual_zh.md README.md README_zh.md; do
    sed -i \
        -e 's|illumio_ops-<version>-offline-linux|illumio-ops-<version>-offline-linux|g' \
        -e 's|illumio_ops-<version>-offline-windows|illumio-ops-<version>-offline-windows|g' \
        -e 's|illumio_ops-<new-version>|illumio-ops-<new-version>|g' \
        -e 's|cd illumio_ops-<version>|cd illumio-ops-<version>|g' \
        -e 's|cd illumio_ops-<new-version>|cd illumio-ops-<new-version>|g' \
        "$f"
done
```

- [ ] **Step 2: Verify**

```bash
grep -rn 'illumio_ops-' docs/ README*.md | grep -v 'docs/superpowers/'   # expect zero hits
```

### 🛂 Verification gate — Batch 1

- [ ] Run a clean build: `bash scripts/build_offline_bundle.sh`
- [ ] Confirm `ls dist/` shows `illumio-ops-<v>-offline-linux-x86_64.tar.gz` and `illumio-ops-<v>-offline-windows-x86_64.zip`
- [ ] Manually inspect that the extracted Linux tarball still contains `app/`, `python/`, `wheels/`, `deploy/`, `install.sh` etc.
- [ ] **PAUSE for manual user review before Batch 2.**

---

## Batch 2 — Install path defaults (forward-only)

Changes the install root used by `install.sh`, `install.ps1`, the systemd unit template, preflight, and uninstall. Existing `/opt/illumio_ops` installs are NOT touched in this batch (Batch 4 handles that).

### Task 2.0: Fix tar root directory name to match docs (added 2026-05-03 from Batch 1 final review)

**Files:** `scripts/build_offline_bundle.sh`

**Background:** Batch 1 final review surfaced a pre-existing inconsistency: the build script packages the Linux tarball with root directory `offline-linux/` (because `BUILD="$REPO_ROOT/build/offline-linux"` and the `tar` invocation uses `$(basename "$BUILD")`), but the install docs tell operators `cd illumio-ops-<version>` after extraction. Operators following the docs hit `cd: No such file or directory`. Same for Windows ZIP. This task fixes the build script so the archive root matches what docs already promise.

- [ ] **Step 1:** Change `build_linux()` and `build_windows()` to use a versioned BUILD dir name that matches `<archive-name-without-extension>`.

The simplest approach: stage the build into a versioned name from the start. In `build_linux()` (around line 65) change:

```bash
local BUILD="$REPO_ROOT/build/offline-linux"
```

to:

```bash
local STAGE_NAME="illumio-ops-${VERSION}-offline-linux-x86_64"
local BUILD="$REPO_ROOT/build/$STAGE_NAME"
```

Same pattern in `build_windows()` (around line 105) with `windows-x86_64` suffix.

The existing `tar czf "$DIST_DIR/$ARCHIVE" -C "$(dirname "$BUILD")" "$(basename "$BUILD")"` then automatically uses the new versioned name as the archive root. Same for the Windows `zip -r` invocation.

- [ ] **Step 2:** Verify the produced archive's root directory name matches what docs say:

```bash
bash scripts/build_offline_bundle.sh
tar tzf dist/illumio-ops-*-offline-linux-x86_64.tar.gz | head -1
# Expect: illumio-ops-<v>-offline-linux-x86_64/
unzip -l dist/illumio-ops-*-offline-windows-x86_64.zip | head -5 | tail -1
# Expect: illumio-ops-<v>-offline-windows-x86_64/
```

- [ ] **Step 3:** Confirm docs' `cd illumio-ops-<version>` instruction now works in practice (not just a string):

```bash
cd /tmp && tar xzf /path/to/dist/illumio-ops-<v>-offline-linux-x86_64.tar.gz
test -d "illumio-ops-<v>-offline-linux-x86_64"   # Should exist
```

Note: the docs currently say `cd illumio-ops-<version>` (without the `-offline-linux-x86_64` suffix). After this fix, the archive root will be `illumio-ops-<v>-offline-linux-x86_64/`. Either:
(a) update the docs to `cd illumio-ops-<version>-offline-linux-x86_64` (more accurate to what extraction actually produces), or
(b) inside the build script, stage to `build/illumio-ops-<v>` (shorter) and rely on `tar`'s root being `illumio-ops-<v>/`.

Option (a) is more honest — the archive name and extracted root match. Pick (a) when implementing this task and update Installation.md / _zh.md / User_Manual.md / _zh.md `cd` instructions to use the long form. The change is small (4 docs, ~6 lines each).

### Task 2.1: Update Linux install root default

**Files:** `scripts/install.sh`, `scripts/uninstall.sh`, `scripts/preflight.sh`

- [ ] **Step 1:** Identify every literal `/opt/illumio_ops` in the three scripts and change to `/opt/illumio-ops`. Do **not** change references in migration logic (which doesn't exist yet — added in Batch 4).

```bash
sed -i 's|/opt/illumio_ops|/opt/illumio-ops|g' scripts/install.sh scripts/uninstall.sh scripts/preflight.sh
```

- [ ] **Step 2: Verify**

```bash
grep -n '/opt/illumio_ops\|/opt/illumio-ops' scripts/install.sh scripts/uninstall.sh scripts/preflight.sh
# Expect: every line shows /opt/illumio-ops (kebab); zero /opt/illumio_ops
```

- [ ] **Step 3: Sanity check syntax**

```bash
bash -n scripts/install.sh scripts/uninstall.sh scripts/preflight.sh
```

### Task 2.2: Update Windows install root default

**Files:** `scripts/install.ps1`

- [ ] **Step 1:** Update default `$InstallRoot` and the two `D:\illumio_ops` doc-comment examples.

Open `scripts/install.ps1` and change:
- Line ~16: `.\install.ps1 -InstallRoot D:\illumio_ops` → `.\install.ps1 -InstallRoot D:\illumio-ops`
- Line ~17: `.\install.ps1 -Action uninstall -InstallRoot D:\illumio_ops` → `… D:\illumio-ops`
- Line ~22: `[string]$InstallRoot = "C:\illumio_ops"` → `[string]$InstallRoot = "C:\illumio-ops"`

- [ ] **Step 2: Verify**

```bash
grep -n 'illumio_ops\|illumio-ops' scripts/install.ps1
# Expect: zero illumio_ops; only illumio-ops appears.
```

### Task 2.3: Update systemd unit

**Files:** `deploy/illumio-ops.service`

- [ ] **Step 1:** Change `WorkingDirectory=`, `ReadWritePaths=`, and `ExecStart=` paths.

```bash
sed -i 's|/opt/illumio_ops|/opt/illumio-ops|g' deploy/illumio-ops.service
```

- [ ] **Step 2:** Confirm `User=` / `Group=` are NOT touched yet (Batch 3 handles those).

```bash
grep -n 'illumio_ops\|illumio-ops' deploy/illumio-ops.service
# Expect: User=illumio_ops, Group=illumio_ops still underscore (Batch 3 changes these);
# all path occurrences are now kebab-case.
```

### Task 2.4: Update build script sed-replacement source pattern

**Files:** `scripts/build_offline_bundle.sh`

- [ ] **Step 1:** The script currently does `sed "s|/opt/illumio_ops|$INSTALL_ROOT|g"` to template the systemd unit at install time. Now that the unit ships with `/opt/illumio-ops`, change the sed source pattern.

```bash
sed -i 's|sed "s|/opt/illumio_ops|\$INSTALL_ROOT|g"|sed "s|/opt/illumio-ops|\$INSTALL_ROOT|g"|' scripts/install.sh
```

(The literal sed pattern lives in `scripts/install.sh`, not `build_offline_bundle.sh` — locate the exact line by `grep -n 'sed.*illumio_ops' scripts/install.sh`.)

- [ ] **Step 2: Verify**

```bash
grep -n 'sed.*illumio' scripts/install.sh
# Expect: source pattern is /opt/illumio-ops (kebab).
```

### Task 2.5: Mass-replace `/opt/illumio_ops` in user-facing docs

**Files:** all `docs/*.md` (excluding `docs/superpowers/`), `README.md`, `README_zh.md`

- [ ] **Step 1: Replace path references**

```bash
find docs/ -maxdepth 1 -name '*.md' -exec sed -i 's|/opt/illumio_ops|/opt/illumio-ops|g' {} +
sed -i 's|/opt/illumio_ops|/opt/illumio-ops|g' README.md README_zh.md
```

- [ ] **Step 2: Replace Windows `C:\illumio_ops` and `D:\illumio_ops` references**

```bash
find docs/ -maxdepth 1 -name '*.md' -exec sed -i \
    -e 's|C:\\illumio_ops|C:\\illumio-ops|g' \
    -e 's|D:\\illumio_ops|D:\\illumio-ops|g' {} +
```

(Bash escaping: each `\\` represents one backslash in the resulting file content.)

- [ ] **Step 3: Verify**

```bash
grep -rn 'illumio_ops' docs/*.md README*.md 2>/dev/null | grep -v 'docs/superpowers/'
# Expect: only references that match the "Out of scope" identifiers in the spec
# (e.g., `logs/illumio_ops.log`, SIEM sample config filenames). Path references = zero.
```

### 🛂 Verification gate — Batch 2

On a **clean Linux VM** (no prior install):
- [ ] Build: `bash scripts/build_offline_bundle.sh`
- [ ] Transfer + extract bundle, run `bash ./preflight.sh` — should PASS
- [ ] Run `sudo ./install.sh` — confirm install lands at `/opt/illumio-ops`
- [ ] `sudo systemctl status illumio-ops` — confirm running
- [ ] `cat /etc/systemd/system/illumio-ops.service | grep -E 'WorkingDirectory|ReadWritePaths'` — confirm kebab path

On a **clean Windows VM**:
- [ ] Run `.\preflight.ps1` — should PASS
- [ ] Run `.\install.ps1` — confirm install lands at `C:\illumio-ops`
- [ ] `Get-Service IllumioOps` — confirm Running
- [ ] `nssm get IllumioOps AppDirectory` — confirm `C:\illumio-ops`

- [ ] **PAUSE for manual user review before Batch 3.**

---

## Batch 3 — System user / group rename (Linux only)

NSSM on Windows runs as `LocalSystem` by default, so this batch is Linux-only.

### Task 3.1: Update systemd unit User / Group

**Files:** `deploy/illumio-ops.service`

- [ ] **Step 1:**

```bash
sed -i 's|User=illumio_ops|User=illumio-ops|;s|Group=illumio_ops|Group=illumio-ops|' deploy/illumio-ops.service
```

- [ ] **Step 2: Verify**

```bash
grep -E '^User=|^Group=' deploy/illumio-ops.service
# Expect: User=illumio-ops, Group=illumio-ops
```

### Task 3.2: Update install.sh useradd/groupadd

**Files:** `scripts/install.sh`

- [ ] **Step 1:** Locate the `useradd` / `groupadd` lines (search `grep -n 'useradd\|groupadd' scripts/install.sh`) and change literal `illumio_ops` to `illumio-ops`.

- [ ] **Step 2: Verify**

```bash
grep -n 'useradd\|groupadd\|chown' scripts/install.sh
# Expect: every line uses illumio-ops (kebab).
```

### Task 3.3: Update doc references to system user

**Files:** `docs/Troubleshooting.md`, `docs/Installation.md`, ZH counterparts

- [ ] **Step 1:** Two known references mention the system user by name:
  - `docs/Troubleshooting.md`: `Confirm the illumio_ops system user owns /opt/...`
  - `docs/Installation.md`: `delete the illumio_ops system user`

```bash
sed -i \
    -e 's|`illumio_ops` system user|`illumio-ops` system user|g' \
    -e 's|delete the `illumio_ops` system user|delete the `illumio-ops` system user|g' \
    docs/Troubleshooting.md docs/Troubleshooting_zh.md docs/Installation.md docs/Installation_zh.md
```

(Adjust patterns to match actual ZH wording if direct `sed` doesn't catch them.)

- [ ] **Step 2: Verify**

```bash
grep -rn 'illumio_ops' docs/*.md | grep -E 'system user|系統' | grep -v 'docs/superpowers/'
# Expect: zero hits.
```

### 🛂 Verification gate — Batch 3

On a **clean Linux VM**:
- [ ] Run `sudo ./install.sh`
- [ ] `id illumio-ops` — confirm user exists with kebab name
- [ ] `getent group illumio-ops` — confirm group exists
- [ ] `ps -u illumio-ops` — confirm `illumio-ops.py` process runs under new user
- [ ] `ls -l /opt/illumio-ops/` — confirm files owned by `illumio-ops:illumio-ops`

- [ ] **PAUSE for manual user review before Batch 4.**

---

## Batch 4 — Upgrade migration (RISKY — touches existing installs)

Adds migration logic so existing `/opt/illumio_ops` deployments upgrade cleanly. This is the only batch that mutates existing installs.

### Task 4.1: Add Linux migration function

**Files:** `scripts/install.sh`

- [ ] **Step 1: Add `migrate_from_underscore_root()` function**

Add this function near the top of `install.sh`, after the `IS_UPGRADE` detection:

```bash
migrate_from_underscore_root() {
    local OLD_ROOT="/opt/illumio_ops"
    local NEW_ROOT="/opt/illumio-ops"

    # Only migrate when old exists and new doesn't (and we haven't migrated already)
    if [[ ! -d "$OLD_ROOT" ]]; then return 0; fi
    if [[ -d "$NEW_ROOT" && -f "$NEW_ROOT/MIGRATED_FROM" ]]; then return 0; fi
    if [[ -d "$NEW_ROOT" ]]; then
        echo "ERROR: Both $OLD_ROOT and $NEW_ROOT exist. Manual cleanup required." >&2
        exit 1
    fi

    echo "==> Migrating $OLD_ROOT → $NEW_ROOT"

    # Pre-flight
    if id illumio-ops &>/dev/null; then
        echo "ERROR: User 'illumio-ops' already exists; cannot rename illumio_ops." >&2
        exit 1
    fi
    if [[ "$(stat -c %d "$OLD_ROOT")" != "$(stat -c %d "$(dirname $NEW_ROOT)")" ]]; then
        echo "ERROR: $OLD_ROOT and $NEW_ROOT parent are on different filesystems." >&2
        echo "       Run 'rsync -aHAX $OLD_ROOT/ $NEW_ROOT/ && rm -rf $OLD_ROOT' manually." >&2
        exit 1
    fi

    systemctl stop illumio-ops 2>/dev/null || true
    usermod -l illumio-ops illumio_ops || { echo "FAIL: usermod"; exit 1; }
    groupmod -n illumio-ops illumio_ops || { echo "FAIL: groupmod"; usermod -l illumio_ops illumio-ops; exit 1; }
    mv "$OLD_ROOT" "$NEW_ROOT" || {
        echo "FAIL: mv — rolling back user/group rename"
        usermod -l illumio_ops illumio-ops
        groupmod -n illumio_ops illumio-ops
        exit 1
    }
    echo "$OLD_ROOT" > "$NEW_ROOT/MIGRATED_FROM"
    chown illumio-ops:illumio-ops "$NEW_ROOT/MIGRATED_FROM"
    echo "==> Migration complete; $NEW_ROOT/MIGRATED_FROM records source path."
}
```

- [ ] **Step 2: Call `migrate_from_underscore_root` early in install.sh, before the install logic runs.**

- [ ] **Step 3: Sanity check syntax**

```bash
bash -n scripts/install.sh
```

### Task 4.2: Add Windows migration function

**Files:** `scripts/install.ps1`

- [ ] **Step 1: Add `Invoke-MigrateFromUnderscoreRoot` function**

```powershell
function Invoke-MigrateFromUnderscoreRoot {
    $OldRoot = "C:\illumio_ops"
    $NewRoot = "C:\illumio-ops"
    if (-not (Test-Path $OldRoot)) { return }
    if ((Test-Path $NewRoot) -and (Test-Path "$NewRoot\MIGRATED_FROM")) { return }
    if (Test-Path $NewRoot) {
        Write-Host "ERROR: Both $OldRoot and $NewRoot exist; manual cleanup required." -ForegroundColor Red
        exit 1
    }
    Write-Host "==> Migrating $OldRoot to $NewRoot" -ForegroundColor Cyan
    Stop-Service IllumioOps -ErrorAction SilentlyContinue
    Move-Item $OldRoot $NewRoot
    & nssm set IllumioOps AppDirectory  $NewRoot
    & nssm set IllumioOps Application   "$NewRoot\python\python.exe"
    & nssm set IllumioOps AppParameters "$NewRoot\illumio-ops.py --monitor --interval 10"
    & nssm set IllumioOps AppStdout     "$NewRoot\logs\service_stdout.log"
    & nssm set IllumioOps AppStderr     "$NewRoot\logs\service_stderr.log"
    Set-Content "$NewRoot\MIGRATED_FROM" $OldRoot
    Write-Host "==> Migration complete; $NewRoot\MIGRATED_FROM records source path." -ForegroundColor Green
}
```

- [ ] **Step 2:** Call `Invoke-MigrateFromUnderscoreRoot` at the top of the install action (before `Test-Path config\config.json` check).

### Task 4.3: Add migration tests (option A — refactor for testability)

**Decision (2026-05-03 handoff):** The plan's original sketch assumed `OLD_ROOT`/`NEW_ROOT` could be overridden by sourcing — but `migrate_from_underscore_root()` hardcodes both paths inside the function body. Plus the function calls `usermod -l` / `groupmod -n` which require real system mutations. To make the function testable in CI without touching real users, **refactor the function to accept overrides**:

- Allow `OLD_ROOT`, `NEW_ROOT`, and `SERVICE_NAME` to be set via environment variables (default to `/opt/illumio_ops`, `/opt/illumio-ops`, `illumio-ops`)
- Optionally accept a `MIGRATE_USER_CMD` env var (default `usermod -l`) so tests can stub it with `:` (no-op) or a fake script that records calls
- Same for `MIGRATE_GROUP_CMD`

**Files (this task):**
- `scripts/install.sh` — refactor `migrate_from_underscore_root()` to support env-var overrides; default behavior unchanged
- `tests/test_install_migration.sh` (new — bash integration test) OR `tests/test_install_migration.py` (Python wrapper invoking bash)
- `tests/migration_test_helpers/` (optional) — stub `usermod` / `groupmod` scripts that just `echo` and exit 0

**Test scenarios to cover:**

- [ ] **T1: Happy path** — pre-create fake old root with `config/config.json`; invoke migrate; assert new root exists with same content, old root gone, `MIGRATED_FROM` marker present and contains old path.
- [ ] **T2: Idempotency** — re-run migrate after T1 succeeded; assert no-op (early return, no error, no double-write of marker).
- [ ] **T3: OLD_ROOT absent** — invoke migrate with no old root present; assert no-op (early return).
- [ ] **T4: Dual-existence** — pre-create both old root and new root (no marker); assert exit 1 with "Both ... exist" error.
- [ ] **T5: Already-migrated marker** — pre-create new root with marker, no old root; assert no-op.
- [ ] **T6: Pre-flight ordering — partial-migration scenario A** — pre-create old root + new user (`illumio-ops`) but no old user (`illumio_ops`); assert C1 message (partial migration detected) fires, NOT I3 message (which would tell operator to delete data). This is the regression test for the `ab353d6` Critical fix.

**Out of scope for tests:**
- usermod/groupmod actual mutation (use stubs)
- systemctl operations (use stubs or skip)
- Cross-filesystem detection (hard to test without two real filesystems; rely on manual test)
- Windows `Invoke-MigrateFromUnderscoreRoot` (PowerShell — document manual test plan instead, see below)

**Test invocation pattern:**

```bash
# tests/test_install_migration.sh
TEST_DIR=$(mktemp -d)
export OLD_ROOT="$TEST_DIR/old"
export NEW_ROOT="$TEST_DIR/new"
export PATH="$REPO_ROOT/tests/migration_test_helpers:$PATH"  # stub usermod/groupmod

# Setup fake old install
mkdir -p "$OLD_ROOT/config"
echo '{}' > "$OLD_ROOT/config/config.json"

# Source install.sh (function only) and invoke
source <(sed -n '/^migrate_from_underscore_root()/,/^}/p' "$REPO_ROOT/scripts/install.sh")
migrate_from_underscore_root

# Assert
test -d "$NEW_ROOT" || { echo "FAIL: new root missing"; exit 1; }
test ! -d "$OLD_ROOT" || { echo "FAIL: old root still exists"; exit 1; }
test -f "$NEW_ROOT/MIGRATED_FROM" || { echo "FAIL: marker missing"; exit 1; }
echo "PASS: T1 happy path"
```

**Refactor pattern for `install.sh`:**

```bash
migrate_from_underscore_root() {
    local OLD_ROOT="${OLD_ROOT:-/opt/illumio_ops}"
    local NEW_ROOT="${NEW_ROOT:-/opt/illumio-ops}"
    local USERMOD_CMD="${USERMOD_CMD:-usermod -l}"
    local GROUPMOD_CMD="${GROUPMOD_CMD:-groupmod -n}"
    # ... rest of function unchanged, just substitute $USERMOD_CMD where usermod was
}
```

**Windows manual test plan (no automation):**

Document in `docs/superpowers/plans/manual-tests/2026-05-03-windows-migration-manual-test.md`:
- Setup: clean Windows VM, install previous bundle to `C:\illumio_ops`
- Scenario 1: full migration (clean kill at end)
- Scenario 2: SIGKILL between Move-Item and nssm sets — verify partial-resume on next install.ps1 run
- Scenario 3: SIGKILL between nssm sets and marker — verify marker-only resume

### 🛂 Verification gate — Batch 4

### 🛂 Verification gate — Batch 4

This is the most critical gate. On a **fresh VM with a simulated old install**:

```bash
# Setup: install the previous version (commit before this batch) at /opt/illumio_ops
sudo /tmp/old-bundle/install.sh
sudo systemctl status illumio-ops  # confirm running at old path

# Run the new installer
sudo /tmp/new-bundle/install.sh

# Verify
test -d /opt/illumio-ops && echo "new path exists"
test ! -d /opt/illumio_ops && echo "old path gone"
cat /opt/illumio-ops/MIGRATED_FROM  # should print /opt/illumio_ops
id illumio-ops                       # should exist
sudo systemctl status illumio-ops    # should be Active (running)
```

- [ ] All assertions above pass on Linux
- [ ] Equivalent test passes on Windows (manual)
- [ ] **Re-run installer**: confirm migration is a no-op (`MIGRATED_FROM` already present, no errors)
- [ ] **PAUSE for manual user review before Batch 5.**

---

## Batch 5 — CLI help text + final verification

### Task 5.1: Fix CLI `--help` examples

**Files:** `src/main.py`

- [ ] **Step 1:** Replace `python illumio_ops.py` with `python illumio-ops.py` in lines 482-486 (the `--help` epilog examples).

```bash
sed -i 's|python illumio_ops\.py|python illumio-ops.py|g' src/main.py
```

- [ ] **Step 2: Verify**

```bash
grep -n 'python illumio' src/main.py
# Expect: only kebab-case examples remain.
```

### Task 5.2: Final repo-wide grep verification

- [ ] **Step 1: Confirm zero out-of-scope `illumio_ops` matches**

```bash
grep -rn 'illumio_ops' \
    --include='*.md' --include='*.sh' --include='*.ps1' --include='*.py' \
    --include='*.service' --include='*.json' --include='*.yaml' \
    /home/harry/rd/illumio-ops/ 2>/dev/null \
    | grep -v 'docs/superpowers/' \
    | grep -v '/build/' \
    | grep -v '/logs/' \
    | grep -v '/data/' \
    | grep -v '/.git/' \
    | grep -v 'logs/illumio_ops.log' \
    | grep -v 'sourcetype.*illumio_ops' \
    | grep -v 'filebeat.illumio_ops.yml' \
    | grep -v 'logstash.illumio_ops.conf' \
    | grep -v 'rsyslog.illumio_ops.conf' \
    | grep -v 'tests/test_cli_compat_matrix.py' \
    | grep -v 'tests/test_cli_report_commands.py' \
    | grep -v 'tests/test_siem_samples_parse.py' \
    | grep -v 'src/.*"""' \
    | grep -v 'migrate_from_underscore_root\|Invoke-MigrateFromUnderscoreRoot\|MIGRATED_FROM' \
    | grep -v 'OLD_ROOT.*illumio_ops' \
    > /tmp/illumio_ops_remaining.txt

wc -l /tmp/illumio_ops_remaining.txt    # expect 0
cat /tmp/illumio_ops_remaining.txt      # expect empty
```

If non-zero, inspect each line and either move to "Out of scope" in the spec or fix it.

### Task 5.3: CHANGELOG entry

**Files:** `CHANGELOG.md`

- [ ] **Step 1:** Add an entry under the next unreleased version (or current dev version) describing:
  - Install root rename: `/opt/illumio_ops` → `/opt/illumio-ops` (Linux), `C:\illumio_ops` → `C:\illumio-ops` (Windows)
  - System user rename: `illumio_ops` → `illumio-ops` (Linux)
  - Bundle filename: `illumio_ops-<v>-offline-*` → `illumio-ops-<v>-offline-*`
  - Auto-migration: `install.sh` / `install.ps1` detect existing `/opt/illumio_ops` (or `C:\illumio_ops`) and migrate atomically; the marker file `MIGRATED_FROM` records the source path
  - Out-of-scope items (log filename, SIEM sourcetype) deliberately retained — see release notes

### 🛂 Verification gate — Batch 5

- [ ] CLI: `python illumio-ops.py --help` shows kebab-case examples
- [ ] Final grep returns zero unexpected matches
- [ ] Full test suite passes: `pytest`
- [ ] CHANGELOG has the rename entry
- [ ] **PAUSE for manual user review before merging to main.**

---

## Out-of-scope reminder

These are intentionally NOT renamed in this plan (see spec for full reasoning):

- `logs/illumio_ops.log` — log shipper compat
- Splunk HEC `sourcetype: illumio_ops` — customer Splunk searches
- `deploy/{filebeat,logstash,rsyslog}.illumio_ops.{yml,conf}` — paired with log filename
- `src/` Python module identifiers — snake_case is Python convention
- `tests/test_cli_compat_matrix.py` — intentionally tests legacy CLI name
- `requirements.txt` comment string

A future ticket may revisit the SIEM-related items as a coordinated customer release.
