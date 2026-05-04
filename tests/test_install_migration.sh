#!/usr/bin/env bash
# Integration tests for migrate_from_underscore_root() in scripts/install.sh.
#
# Sources only the function body (per the plan in
# docs/superpowers/plans/2026-05-03-install-root-rename.md, Task 4.3) and
# exercises six scenarios (T1–T6). Runs as a non-root user.
#
# Usage: bash tests/test_install_migration.sh
#
# Notes:
# - We deliberately use `set -u` (NOT `set -e`) because several scenarios
#   intentionally trigger non-zero exits from the function-under-test, and we
#   need to capture those exit codes via `||` patterns.
# - Each test isolates state in a fresh mktemp dir so reruns are hermetic.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_SH="$REPO_ROOT/scripts/install.sh"
STUBS_DIR="$REPO_ROOT/tests/migration_test_helpers"

if [[ ! -f "$INSTALL_SH" ]]; then
    echo "ERROR: cannot find $INSTALL_SH" >&2
    exit 1
fi
if [[ ! -d "$STUBS_DIR" ]]; then
    echo "ERROR: cannot find stubs dir $STUBS_DIR" >&2
    exit 1
fi

# --- Shared setup ----------------------------------------------------------

# Source only the migrate_from_underscore_root function body. The function is
# self-contained (no calls into other parts of install.sh), so this is safe.
# shellcheck disable=SC1090
source <(sed -n '/^migrate_from_underscore_root()/,/^}/p' "$INSTALL_SH")

if ! declare -f migrate_from_underscore_root > /dev/null; then
    echo "ERROR: failed to source migrate_from_underscore_root from $INSTALL_SH" >&2
    exit 1
fi

# Prepend stubs to PATH so `id`, `systemctl`, `chown` are intercepted.
export PATH="$STUBS_DIR:$PATH"

PASS_COUNT=0
FAIL_COUNT=0
TOTAL=6

pass() {
    echo "PASS: $1"
    PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
    echo "FAIL: $1 — $2" >&2
    if [[ -n "${3-}" ]]; then
        echo "----- captured output -----" >&2
        echo "$3" >&2
        echo "----- end output -----" >&2
    fi
    FAIL_COUNT=$((FAIL_COUNT + 1))
    exit 1
}

# Helper: build a fresh test environment for a scenario.
# Sets TEST_DIR, OLD_ROOT, NEW_ROOT and exports them along with the user/group
# overrides. Caller is responsible for staging actual files inside.
new_test_env() {
    TEST_DIR="$(mktemp -d)"
    # Both paths share the same parent so the cross-filesystem check passes.
    export OLD_ROOT="$TEST_DIR/illumio_ops"
    export NEW_ROOT="$TEST_DIR/illumio-ops"
    export OLD_USER="illumio_ops"
    export NEW_USER="illumio-ops"
    export MIGRATE_SERVICE_NAME="illumio-ops"
    # Use `:` (the no-op shell builtin) for user/group rename; tests don't need
    # real mutation, only that the function reaches and "succeeds at" this step.
    export USERMOD_CMD=":"
    export GROUPMOD_CMD=":"
    # Default: only the old user exists (so happy path can rename it).
    export MIGRATION_TEST_USERS="illumio_ops"
}

cleanup_test_env() {
    if [[ -n "${TEST_DIR-}" && -d "$TEST_DIR" ]]; then
        rm -rf "$TEST_DIR"
    fi
    unset TEST_DIR OLD_ROOT NEW_ROOT OLD_USER NEW_USER MIGRATE_SERVICE_NAME
    unset USERMOD_CMD GROUPMOD_CMD MIGRATION_TEST_USERS
}

echo "==> Running migrate_from_underscore_root() integration tests (T1–T6)"
echo

# --- T1: Happy path --------------------------------------------------------

t1_happy_path() {
    new_test_env
    mkdir -p "$OLD_ROOT/config"
    echo '{"sentinel":"t1"}' > "$OLD_ROOT/config/config.json"

    local out exit_code
    out="$(migrate_from_underscore_root 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T1 happy path" "non-zero exit ($exit_code)" "$out"
    fi
    if [[ ! -d "$NEW_ROOT" ]]; then
        fail "T1 happy path" "new root missing" "$out"
    fi
    if [[ -d "$OLD_ROOT" ]]; then
        fail "T1 happy path" "old root still exists" "$out"
    fi
    if [[ ! -f "$NEW_ROOT/MIGRATED_FROM" ]]; then
        fail "T1 happy path" "MIGRATED_FROM marker missing" "$out"
    fi
    local marker
    marker="$(cat "$NEW_ROOT/MIGRATED_FROM")"
    if [[ "$marker" != "$OLD_ROOT" ]]; then
        fail "T1 happy path" "marker contents wrong (got '$marker', want '$OLD_ROOT')" "$out"
    fi
    if [[ "$(cat "$NEW_ROOT/config/config.json")" != '{"sentinel":"t1"}' ]]; then
        fail "T1 happy path" "config.json content not preserved" "$out"
    fi

    pass "T1 happy path"
    cleanup_test_env
}

# --- T2: Idempotency -------------------------------------------------------

t2_idempotent_rerun() {
    new_test_env
    # Stage a finished migration: only NEW_ROOT exists with marker.
    mkdir -p "$NEW_ROOT/config"
    echo '{"sentinel":"t2"}' > "$NEW_ROOT/config/config.json"
    echo "$OLD_ROOT" > "$NEW_ROOT/MIGRATED_FROM"
    local marker_mtime_before
    marker_mtime_before="$(stat -c %Y "$NEW_ROOT/MIGRATED_FROM")"

    # Sleep 1 second so we can detect any rewrite via mtime.
    sleep 1

    local out exit_code
    out="$(migrate_from_underscore_root 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T2 idempotent rerun" "non-zero exit ($exit_code)" "$out"
    fi
    local marker_mtime_after
    marker_mtime_after="$(stat -c %Y "$NEW_ROOT/MIGRATED_FROM")"
    if [[ "$marker_mtime_before" != "$marker_mtime_after" ]]; then
        fail "T2 idempotent rerun" "marker was rewritten (mtime changed)" "$out"
    fi
    if [[ -n "$out" ]]; then
        # No-op should be silent; any output means we entered the migration body.
        fail "T2 idempotent rerun" "expected silent no-op, got output" "$out"
    fi

    pass "T2 idempotent rerun"
    cleanup_test_env
}

# --- T3: OLD_ROOT absent ---------------------------------------------------

t3_old_root_absent() {
    new_test_env
    # Don't create anything: OLD_ROOT and NEW_ROOT both missing.

    local out exit_code
    out="$(migrate_from_underscore_root 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T3 old root absent" "non-zero exit ($exit_code)" "$out"
    fi
    if [[ -n "$out" ]]; then
        fail "T3 old root absent" "expected silent no-op, got output" "$out"
    fi
    if [[ -d "$NEW_ROOT" ]]; then
        fail "T3 old root absent" "new root was created (should be no-op)" "$out"
    fi

    pass "T3 old root absent"
    cleanup_test_env
}

# --- T4: Dual-existence (no marker) ----------------------------------------

t4_dual_existence_no_marker() {
    new_test_env
    mkdir -p "$OLD_ROOT/config"
    mkdir -p "$NEW_ROOT/config"
    # No MIGRATED_FROM marker — install.sh must refuse to proceed.

    local out exit_code
    out="$(migrate_from_underscore_root 2>&1)"
    exit_code=$?

    if [[ $exit_code -eq 0 ]]; then
        fail "T4 dual existence" "expected non-zero exit, got 0" "$out"
    fi
    if ! grep -q "Both .* exist" <<< "$out"; then
        fail "T4 dual existence" "expected 'Both ... exist' message" "$out"
    fi

    pass "T4 dual existence"
    cleanup_test_env
}

# --- T5: Already-migrated marker present -----------------------------------

t5_already_migrated_marker() {
    new_test_env
    mkdir -p "$NEW_ROOT/config"
    echo "$OLD_ROOT" > "$NEW_ROOT/MIGRATED_FROM"
    # OLD_ROOT does NOT exist (already cleaned up).

    local out exit_code
    out="$(migrate_from_underscore_root 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T5 already-migrated marker" "non-zero exit ($exit_code)" "$out"
    fi
    if [[ -n "$out" ]]; then
        fail "T5 already-migrated marker" "expected silent no-op, got output" "$out"
    fi

    pass "T5 already-migrated marker"
    cleanup_test_env
}

# --- T6: Pre-flight ordering — partial migration scenario A ----------------
# Regression test for ab353d6: the C1 partial-migration check must fire BEFORE
# the I3 missing-old-user check. State: OLD_ROOT exists, NEW_USER exists,
# OLD_USER does NOT exist. Expected: C1 message ("Partial migration detected")
# fires; we must NOT see the I3 message ("user 'illumio_ops' does not").

t6_partial_migration_ordering() {
    new_test_env
    mkdir -p "$OLD_ROOT/config"
    # Override default user state: only the NEW user exists; OLD user was
    # already renamed away in a prior partial migration run.
    export MIGRATION_TEST_USERS="illumio-ops"

    local out exit_code
    out="$(migrate_from_underscore_root 2>&1)"
    exit_code=$?

    if [[ $exit_code -eq 0 ]]; then
        fail "T6 partial migration ordering" "expected non-zero exit, got 0" "$out"
    fi
    if ! grep -q "Partial migration detected" <<< "$out"; then
        fail "T6 partial migration ordering" "expected C1 'Partial migration detected' message" "$out"
    fi
    if grep -q "user 'illumio_ops' does not" <<< "$out"; then
        fail "T6 partial migration ordering" "saw forbidden I3 message — C1/I3 ordering broken" "$out"
    fi

    pass "T6 partial migration ordering"
    cleanup_test_env
}

# --- Run all ---------------------------------------------------------------

t1_happy_path
t2_idempotent_rerun
t3_old_root_absent
t4_dual_existence_no_marker
t5_already_migrated_marker
t6_partial_migration_ordering

echo
echo "$PASS_COUNT/$TOTAL passed"
if [[ $FAIL_COUNT -ne 0 ]]; then
    exit 1
fi
exit 0
