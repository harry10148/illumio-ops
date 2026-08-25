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

# Source only the check_pce_profile_contamination function body. Self-contained
# per the same convention as migrate_from_underscore_root above.
# shellcheck disable=SC1090
source <(sed -n '/^check_pce_profile_contamination()/,/^}/p' "$INSTALL_SH")

if ! declare -f check_pce_profile_contamination > /dev/null; then
    echo "ERROR: failed to source check_pce_profile_contamination from $INSTALL_SH" >&2
    exit 1
fi

# Prepend stubs to PATH so `id`, `systemctl`, `chown` are intercepted.
export PATH="$STUBS_DIR:$PATH"

# Python interpreter for check_pce_profile_contamination's inline script.
# Test config roots have no src/ tree, so the function's `from src.pce_target
# import ...` always falls back to the local normalize functions — that's
# intentional and exercised by T10 below.
PY_BIN="$REPO_ROOT/venv/bin/python3"
if [[ ! -x "$PY_BIN" ]]; then
    PY_BIN="$(command -v python3)"
fi

PASS_COUNT=0
FAIL_COUNT=0
TOTAL=21

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

# --- check_pce_profile_contamination() integration tests (T7-T10) ---------

echo
echo "==> Running check_pce_profile_contamination() integration tests (T7-T10)"
echo

new_contamination_env() {
    CTEST_DIR="$(mktemp -d)"
    export CFG_ROOT="$CTEST_DIR/root"
    mkdir -p "$CFG_ROOT/config"
}

cleanup_contamination_env() {
    if [[ -n "${CTEST_DIR-}" && -d "$CTEST_DIR" ]]; then
        rm -rf "$CTEST_DIR"
    fi
    unset CTEST_DIR CFG_ROOT
}

MARKER_REL="config/.pce-profile-migration.json"

# Stages a real copy of src/pce_target.py (+ its package __init__.py) under
# CFG_ROOT/src, so `from src.pce_target import ...` inside the heredoc
# succeeds via the function's own `sys.path.insert(0, root)` — deliberately,
# not by accident. check_pce_profile_contamination invokes python with -P
# (no cwd on sys.path), so without this staging there is no other way for
# the real module to be found: any test that needs real-normalizer behavior
# (case-folding, or urlsplit raising on a malformed url) must call this.
stage_real_pce_target() {
    mkdir -p "$CFG_ROOT/src"
    cp "$REPO_ROOT/src/pce_target.py" "$CFG_ROOT/src/pce_target.py"
    cp "$REPO_ROOT/src/__init__.py" "$CFG_ROOT/src/__init__.py"
}

# --- T7: two distinct (url, org_id) profiles -> contamination warning ------

t7_two_distinct_profiles() {
    new_contamination_env
    cat > "$CFG_ROOT/config/config.json" <<'JSON'
{
  "api": {"url": "https://pce1.example.com", "org_id": "1"},
  "pce_profiles": [
    {"url": "https://pce1.example.com", "org_id": "1"},
    {"url": "https://pce2.example.com", "org_id": "2"}
  ]
}
JSON

    local out exit_code
    out="$(check_pce_profile_contamination "$CFG_ROOT" "$PY_BIN" 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T7 two distinct profiles" "non-zero exit ($exit_code)" "$out"
    fi
    if ! grep -qi "WARNING" <<< "$out"; then
        fail "T7 two distinct profiles" "expected WARNING keyword" "$out"
    fi
    if ! grep -q "pce1.example.com" <<< "$out"; then
        fail "T7 two distinct profiles" "expected pce1 url in output" "$out"
    fi
    if ! grep -q "pce2.example.com" <<< "$out"; then
        fail "T7 two distinct profiles" "expected pce2 url in output" "$out"
    fi
    if ! grep -q "cache flush" <<< "$out"; then
        fail "T7 two distinct profiles" "expected 'cache flush' remediation command" "$out"
    fi
    if ! grep -q "sudo -u illumio-ops" <<< "$out"; then
        fail "T7 two distinct profiles" "expected 'sudo -u illumio-ops' in output" "$out"
    fi
    if [[ ! -f "$CFG_ROOT/$MARKER_REL" ]]; then
        fail "T7 two distinct profiles" "marker file not created" "$out"
    fi
    if ! "$PY_BIN" -m json.tool "$CFG_ROOT/$MARKER_REL" > /dev/null 2>&1; then
        fail "T7 two distinct profiles" "marker file is not valid JSON" "$out"
    fi

    pass "T7 two distinct profiles"
    cleanup_contamination_env
}

# --- T8: a single profile -> plain notice, no warning ----------------------

t8_single_profile() {
    new_contamination_env
    cat > "$CFG_ROOT/config/config.json" <<'JSON'
{
  "api": {"url": "https://pce1.example.com", "org_id": "1"},
  "pce_profiles": [
    {"url": "https://pce1.example.com", "org_id": "1"}
  ]
}
JSON

    local out exit_code
    out="$(check_pce_profile_contamination "$CFG_ROOT" "$PY_BIN" 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T8 single profile" "non-zero exit ($exit_code)" "$out"
    fi
    if grep -qi "WARNING" <<< "$out"; then
        fail "T8 single profile" "did not expect WARNING keyword" "$out"
    fi
    if [[ -z "$out" ]]; then
        fail "T8 single profile" "expected a notice, got no output" "$out"
    fi
    # Pin the exact branch: this must be the single-profile NOTE, not the
    # "cannot be determined" (no pce_profiles key) branch or the malformed-
    # shape branch — all three satisfy "no WARNING, non-empty output" alone.
    if ! grep -q "credentials stay in config.json until the next save" <<< "$out"; then
        fail "T8 single profile" "expected the single-profile NOTE text" "$out"
    fi
    if grep -qi "cannot be determined" <<< "$out"; then
        fail "T8 single profile" "unexpectedly hit the 'cannot be determined' branch" "$out"
    fi
    if [[ ! -f "$CFG_ROOT/$MARKER_REL" ]]; then
        fail "T8 single profile" "marker file not created" "$out"
    fi
    if ! "$PY_BIN" -m json.tool "$CFG_ROOT/$MARKER_REL" > /dev/null 2>&1; then
        fail "T8 single profile" "marker file is not valid JSON" "$out"
    fi

    pass "T8 single profile"
    cleanup_contamination_env
}

# --- T9: no pce_profiles key and no prior marker -> "cannot determine" -----

t9_no_profiles_no_marker() {
    new_contamination_env
    cat > "$CFG_ROOT/config/config.json" <<'JSON'
{
  "api": {"url": "https://pce1.example.com", "org_id": "1"}
}
JSON

    local out exit_code
    out="$(check_pce_profile_contamination "$CFG_ROOT" "$PY_BIN" 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T9 no profiles, no marker" "non-zero exit ($exit_code)" "$out"
    fi
    if ! grep -qi "cannot be determined" <<< "$out"; then
        fail "T9 no profiles, no marker" "expected 'cannot be determined' notice" "$out"
    fi
    # No marker is written here (round 2 / P1-1 fix): there was nothing
    # readable to observe, so recording "0 targets" would be a false
    # negative that silences every future upgrade on this appliance forever.
    # Leaving no marker means the next upgrade honestly says "cannot be
    # determined" again instead of going silent.
    if [[ -f "$CFG_ROOT/$MARKER_REL" ]]; then
        fail "T9 no profiles, no marker" "marker file was created despite nothing observable — future upgrades would go silent" "$out"
    fi

    pass "T9 no profiles, no marker"
    cleanup_contamination_env
}

# --- T10: two profile urls differing only by trailing slash -> same PCE ----

t10_trailing_slash_same_pce() {
    new_contamination_env
    cat > "$CFG_ROOT/config/config.json" <<'JSON'
{
  "api": {"url": "https://pce1.example.com", "org_id": "1"},
  "pce_profiles": [
    {"url": "https://pce1.example.com", "org_id": "1"},
    {"url": "https://pce1.example.com/", "org_id": "1"}
  ]
}
JSON

    local out exit_code
    out="$(check_pce_profile_contamination "$CFG_ROOT" "$PY_BIN" 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T10 trailing-slash-only difference" "non-zero exit ($exit_code)" "$out"
    fi
    if grep -qi "WARNING" <<< "$out"; then
        fail "T10 trailing-slash-only difference" "url differing only by trailing slash treated as distinct PCE" "$out"
    fi
    if [[ ! -f "$CFG_ROOT/$MARKER_REL" ]]; then
        fail "T10 trailing-slash-only difference" "marker file not created" "$out"
    fi
    if ! "$PY_BIN" -m json.tool "$CFG_ROOT/$MARKER_REL" > /dev/null 2>&1; then
        fail "T10 trailing-slash-only difference" "marker file is not valid JSON" "$out"
    fi

    pass "T10 trailing-slash-only difference"
    cleanup_contamination_env
}

# --- T11: malformed `api` must not abort the caller under set -e -----------
# Regression test: check_pce_profile_contamination runs under install.sh's
# `set -euo pipefail`. A `pce_profiles` list combined with a non-dict `api`
# value used to raise AttributeError from the heredoc's python, which killed
# the calling script before its own `return 0` was reached. This must fail
# against d2b1b321 (the AttributeError propagates and the subshell below
# exits non-zero, "AFTER_CALL_MARKER" is never printed).

t11_malformed_api_survives_set_e() {
    new_contamination_env
    cat > "$CFG_ROOT/config/config.json" <<'JSON'
{
  "api": "not-a-dict",
  "pce_profiles": [
    {"url": "https://pce1.example.com", "org_id": "1"},
    {"url": "https://pce2.example.com", "org_id": "2"}
  ]
}
JSON

    # Reproduce install.sh's own `set -euo pipefail` context: an exception in
    # the heredoc must not kill this subshell before AFTER_CALL_MARKER prints,
    # and the subshell itself must exit 0 (real caller relies on that).
    local out exit_code
    out="$(bash -c '
        set -euo pipefail
        source <(sed -n "/^check_pce_profile_contamination()/,/^}/p" "$1")
        check_pce_profile_contamination "$2" "$3"
        echo "AFTER_CALL_MARKER"
    ' _ "$INSTALL_SH" "$CFG_ROOT" "$PY_BIN" 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T11 malformed api survives set -e" "non-zero exit ($exit_code) — the caller was aborted" "$out"
    fi
    if ! grep -q "AFTER_CALL_MARKER" <<< "$out"; then
        fail "T11 malformed api survives set -e" "caller never reached the line after the call" "$out"
    fi
    if grep -q "Traceback" <<< "$out"; then
        fail "T11 malformed api survives set -e" "python raised instead of falling through" "$out"
    fi
    if ! grep -qi "WARNING" <<< "$out"; then
        fail "T11 malformed api survives set -e" "expected the contamination warning to still fire" "$out"
    fi
    if [[ ! -f "$CFG_ROOT/$MARKER_REL" ]]; then
        fail "T11 malformed api survives set -e" "marker file not created" "$out"
    fi
    if ! "$PY_BIN" -m json.tool "$CFG_ROOT/$MARKER_REL" > /dev/null 2>&1; then
        fail "T11 malformed api survives set -e" "marker file is not valid JSON" "$out"
    fi

    pass "T11 malformed api survives set -e"
    cleanup_contamination_env
}

# --- T12: exercises the real src.pce_target import, not the fallback -------
# check_pce_profile_contamination invokes python with -P (no cwd on
# sys.path), so the only way `from src.pce_target import ...` succeeds is a
# real src/ tree under CFG_ROOT itself — never incidentally, via wherever
# this suite happens to be invoked from. T7-T11, T13-T15, T17, T20 and T21
# don't stage one, so they deterministically exercise the inline fallback
# normalizers. This test stages a real src/pce_target.py under CFG_ROOT and
# uses a behavior only the real normalize_pce_url has (scheme/host case
# folding) to prove the import path — not the fallback — ran.

t12_real_normalizer_import() {
    new_contamination_env
    stage_real_pce_target
    cat > "$CFG_ROOT/config/config.json" <<'JSON'
{
  "api": {"url": "https://pce1.example.com", "org_id": "1"},
  "pce_profiles": [
    {"url": "HTTPS://PCE1.EXAMPLE.COM", "org_id": "1"},
    {"url": "https://pce1.example.com", "org_id": "1"}
  ]
}
JSON

    local out exit_code
    out="$(check_pce_profile_contamination "$CFG_ROOT" "$PY_BIN" 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T12 real normalizer import" "non-zero exit ($exit_code)" "$out"
    fi
    # The fallback's normalize_pce_url does NOT lowercase scheme/host, so if
    # the import silently fell back, these two URLs would stay distinct and
    # WARNING would fire. Its absence pins that the real import ran.
    if grep -qi "WARNING" <<< "$out"; then
        fail "T12 real normalizer import" "scheme/host case was not folded — real src.pce_target import did not run" "$out"
    fi
    if ! grep -q "credentials stay in config.json until the next save" <<< "$out"; then
        fail "T12 real normalizer import" "expected the single-profile NOTE (URLs should have normalized to one target)" "$out"
    fi
    if [[ ! -f "$CFG_ROOT/$MARKER_REL" ]]; then
        fail "T12 real normalizer import" "marker file not created" "$out"
    fi
    if ! "$PY_BIN" -m json.tool "$CFG_ROOT/$MARKER_REL" > /dev/null 2>&1; then
        fail "T12 real normalizer import" "marker file is not valid JSON" "$out"
    fi
    if ! grep -q '"distinct_pce_targets": 1' "$CFG_ROOT/$MARKER_REL"; then
        fail "T12 real normalizer import" "expected distinct_pce_targets=1 in marker" "$out"
    fi

    pass "T12 real normalizer import"
    cleanup_contamination_env
}

# --- T13: pce_profiles present but not a list -> "could not be read" -------
# Regression test: this used to fall through to the "were removed in a newer
# version" text, which is false when the key is right there, just unreadable.

t13_malformed_profiles_not_a_list() {
    new_contamination_env
    cat > "$CFG_ROOT/config/config.json" <<'JSON'
{
  "api": {"url": "https://pce1.example.com", "org_id": "1"},
  "pce_profiles": "not-a-list"
}
JSON

    local out exit_code
    out="$(check_pce_profile_contamination "$CFG_ROOT" "$PY_BIN" 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T13 malformed pce_profiles" "non-zero exit ($exit_code)" "$out"
    fi
    if grep -qi "were removed in a newer version" <<< "$out"; then
        fail "T13 malformed pce_profiles" "false claim: profiles are present, not removed" "$out"
    fi
    if ! grep -qi "could not be read" <<< "$out"; then
        fail "T13 malformed pce_profiles" "expected an unreadable-shape notice" "$out"
    fi
    if [[ ! -f "$CFG_ROOT/$MARKER_REL" ]]; then
        fail "T13 malformed pce_profiles" "marker file not created" "$out"
    fi
    if ! "$PY_BIN" -m json.tool "$CFG_ROOT/$MARKER_REL" > /dev/null 2>&1; then
        fail "T13 malformed pce_profiles" "marker file is not valid JSON" "$out"
    fi

    pass "T13 malformed pce_profiles"
    cleanup_contamination_env
}

# --- T14: marker recording >1 targets must NOT be silenced once the key ----
# vanishes. Regression for P1-1: `if profiles is None and marker exists: exit
# silently` ignored what the marker actually recorded. An appliance warned
# about two PCEs, never cleaned, then had pce_profiles stripped by a routine
# ConfigManager.save() must still warn on every subsequent upgrade.

t14_marker_recorded_contamination_not_silenced() {
    new_contamination_env
    cat > "$CFG_ROOT/config/config.json" <<'JSON'
{
  "api": {"url": "https://pce1.example.com", "org_id": "1"}
}
JSON
    cat > "$CFG_ROOT/$MARKER_REL" <<'JSON'
{
  "checked_at": "2026-08-18T00:00:00+00:00",
  "distinct_pce_targets": 2
}
JSON

    local out exit_code
    out="$(check_pce_profile_contamination "$CFG_ROOT" "$PY_BIN" 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T14 marker contamination not silenced" "non-zero exit ($exit_code)" "$out"
    fi
    if [[ -z "$out" ]]; then
        fail "T14 marker contamination not silenced" "check went silent despite a marker recording 2 distinct PCE targets" "$out"
    fi
    if ! grep -qi "WARNING" <<< "$out"; then
        fail "T14 marker contamination not silenced" "expected a warning to still fire" "$out"
    fi
    if ! grep -q "cache flush --confirm" <<< "$out"; then
        fail "T14 marker contamination not silenced" "expected the cache-flush remediation command" "$out"
    fi

    pass "T14 marker contamination not silenced"
    cleanup_contamination_env
}

# --- T15: a PCE URL carrying credentials must never reach the terminal -----
# Regression for P1-2: normalize_pce_url deliberately preserves userinfo (a
# legacy https://user:pass@host profile is possible from a reverse-proxy
# arrangement). The comparison must still use the full value; the printed
# value must be masked to scheme + host + port only.

t15_credential_url_is_masked_in_output() {
    new_contamination_env
    cat > "$CFG_ROOT/config/config.json" <<'JSON'
{
  "api": {"url": "https://someuser:supersecretpw@pce1.example.com:8443", "org_id": "1"},
  "pce_profiles": [
    {"url": "https://someuser:supersecretpw@pce1.example.com:8443", "org_id": "1"},
    {"url": "https://pce2.example.com", "org_id": "2"}
  ]
}
JSON

    local out exit_code
    out="$(check_pce_profile_contamination "$CFG_ROOT" "$PY_BIN" 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T15 credential URL masked" "non-zero exit ($exit_code)" "$out"
    fi
    if ! grep -qi "WARNING" <<< "$out"; then
        fail "T15 credential URL masked" "expected the contamination warning to fire" "$out"
    fi
    # This is the assertion that matters: the password must never appear.
    if grep -q "supersecretpw" <<< "$out"; then
        fail "T15 credential URL masked" "password leaked into installer output" "$out"
    fi
    if grep -q "someuser" <<< "$out"; then
        fail "T15 credential URL masked" "username leaked into installer output" "$out"
    fi
    if ! grep -q "https://pce1.example.com:8443" <<< "$out"; then
        fail "T15 credential URL masked" "expected the masked scheme+host+port form in output" "$out"
    fi
    if ! grep -q "pce2.example.com" <<< "$out"; then
        fail "T15 credential URL masked" "expected the second PCE's url in output" "$out"
    fi

    pass "T15 credential URL masked"
    cleanup_contamination_env
}

# --- T16: one unparseable profile URL must not blank out the whole check ---
# Regression for P2-3: urlsplit('https://[broken') raises ValueError inside
# normalize_pce_url. The old code let that exception propagate out of the
# per-entry loop, so the ONLY thing that ran was the outer `|| true` guard —
# no warning, no marker, for a config that has two perfectly good profiles.
# Needs the REAL normalizer staged: the fallback never calls urlsplit, so it
# would treat "https://[broken" as just another opaque string and never
# raise at all — the test would misreport this fix as working when only the
# fallback ran (this depended on cwd, incidentally, before the -P fix).

t16_one_bad_url_does_not_blank_the_check() {
    new_contamination_env
    stage_real_pce_target
    cat > "$CFG_ROOT/config/config.json" <<'JSON'
{
  "api": {"url": "https://pce1.example.com", "org_id": "1"},
  "pce_profiles": [
    {"url": "https://pce1.example.com", "org_id": "1"},
    {"url": "https://pce2.example.com", "org_id": "2"},
    {"url": "https://[broken", "org_id": "3"}
  ]
}
JSON

    local out exit_code
    out="$(check_pce_profile_contamination "$CFG_ROOT" "$PY_BIN" 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T16 one bad url does not blank check" "non-zero exit ($exit_code)" "$out"
    fi
    if grep -q "Traceback" <<< "$out"; then
        fail "T16 one bad url does not blank check" "python raised instead of skipping the bad entry" "$out"
    fi
    if ! grep -qi "WARNING" <<< "$out"; then
        fail "T16 one bad url does not blank check" "expected the two good profiles to still trigger a warning" "$out"
    fi
    if ! grep -q "pce1.example.com" <<< "$out"; then
        fail "T16 one bad url does not blank check" "expected pce1 in output" "$out"
    fi
    if ! grep -q "pce2.example.com" <<< "$out"; then
        fail "T16 one bad url does not blank check" "expected pce2 in output" "$out"
    fi
    if [[ ! -f "$CFG_ROOT/$MARKER_REL" ]]; then
        fail "T16 one bad url does not blank check" "marker file not created" "$out"
    fi
    if ! "$PY_BIN" -m json.tool "$CFG_ROOT/$MARKER_REL" > /dev/null 2>&1; then
        fail "T16 one bad url does not blank check" "marker file is not valid JSON" "$out"
    fi
    if ! grep -q '"distinct_pce_targets": 2' "$CFG_ROOT/$MARKER_REL"; then
        fail "T16 one bad url does not blank check" "expected distinct_pce_targets=2 (only the readable entries)" "$out"
    fi

    pass "T16 one bad url does not blank check"
    cleanup_contamination_env
}

# --- T17: archive advice must be an actual, pasteable command --------------
# Regression for P2-4: the old text said "MOVE (do not delete)" with no path
# and no command, leaving an operator with a non-default archive_dir unable
# to act on it.

t17_archive_advice_is_actionable() {
    new_contamination_env
    cat > "$CFG_ROOT/config/config.json" <<'JSON'
{
  "api": {"url": "https://pce1.example.com", "org_id": "1"},
  "pce_cache": {"archive_dir": "custom/archive/path"},
  "pce_profiles": [
    {"url": "https://pce1.example.com", "org_id": "1"},
    {"url": "https://pce2.example.com", "org_id": "2"}
  ]
}
JSON

    local out exit_code
    out="$(check_pce_profile_contamination "$CFG_ROOT" "$PY_BIN" 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T17 archive advice actionable" "non-zero exit ($exit_code)" "$out"
    fi
    if ! grep -qi "WARNING" <<< "$out"; then
        fail "T17 archive advice actionable" "expected the contamination warning to fire" "$out"
    fi
    if ! grep -q "do not delete" <<< "$out"; then
        fail "T17 archive advice actionable" "expected the move-not-delete reasoning to survive" "$out"
    fi
    if ! grep -q "mv $CFG_ROOT/custom/archive/path" <<< "$out"; then
        fail "T17 archive advice actionable" "expected a pasteable mv command with the configured archive_dir resolved" "$out"
    fi

    pass "T17 archive advice actionable"
    cleanup_contamination_env
}

# --- T18: F1 — two profiles, one unparseable url, degraded marker ----------
# Regression: with the surviving readable count at exactly one, the marker
# used to record `distinct_pce_targets: 1` as if that were a confirmed fact.
# Since this appliance's pce_profiles had TWO entries, the dropped one could
# just as easily have been a second distinct PCE — the marker must not claim
# otherwise, and this run must not print the false "were removed" NOTE
# either. Needs the real normalizer staged (see T16's comment) so the broken
# url actually raises instead of being silently accepted by the fallback.

t18_two_profiles_one_bad_degrades_not_confirms() {
    new_contamination_env
    stage_real_pce_target
    cat > "$CFG_ROOT/config/config.json" <<'JSON'
{
  "api": {"url": "https://pce1.example.com", "org_id": "1"},
  "pce_profiles": [
    {"url": "https://pce1.example.com", "org_id": "1"},
    {"url": "https://[broken", "org_id": "9"}
  ]
}
JSON

    local out exit_code
    out="$(check_pce_profile_contamination "$CFG_ROOT" "$PY_BIN" 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T18 two-profile-one-bad degrades" "non-zero exit ($exit_code)" "$out"
    fi
    if grep -q "Traceback" <<< "$out"; then
        fail "T18 two-profile-one-bad degrades" "python raised instead of skipping the bad entry" "$out"
    fi
    # This run must not claim the profiles were removed — they are present,
    # just partly unreadable, and there genuinely were two of them.
    if grep -qi "were removed in a newer version" <<< "$out"; then
        fail "T18 two-profile-one-bad degrades" "false claim: profiles are present and there were two of them" "$out"
    fi
    if ! grep -qi "WARNING" <<< "$out"; then
        fail "T18 two-profile-one-bad degrades" "expected a warning this run — two profiles, one unreadable, is not confirmed-safe" "$out"
    fi
    if ! grep -q "pce1.example.com" <<< "$out"; then
        fail "T18 two-profile-one-bad degrades" "expected the one readable PCE in output" "$out"
    fi
    if [[ ! -f "$CFG_ROOT/$MARKER_REL" ]]; then
        fail "T18 two-profile-one-bad degrades" "marker file not created" "$out"
    fi
    if ! "$PY_BIN" -m json.tool "$CFG_ROOT/$MARKER_REL" > /dev/null 2>&1; then
        fail "T18 two-profile-one-bad degrades" "marker file is not valid JSON" "$out"
    fi
    # The bug: this used to write `"distinct_pce_targets": 1`, which a later
    # run (once pce_profiles is stripped by a routine save) reads as
    # confirmed-safe and goes silent forever.
    if grep -q '"distinct_pce_targets": 1' "$CFG_ROOT/$MARKER_REL"; then
        fail "T18 two-profile-one-bad degrades" "marker recorded a confirmed count of 1 — that was never confirmed" "$out"
    fi

    # Phase 2: simulate a routine ConfigManager.save() stripping pce_profiles
    # after this. A later upgrade must still say SOMETHING — never silence.
    cat > "$CFG_ROOT/config/config.json" <<'JSON'
{
  "api": {"url": "https://pce1.example.com", "org_id": "1"}
}
JSON
    local out2 exit_code2
    out2="$(check_pce_profile_contamination "$CFG_ROOT" "$PY_BIN" 2>&1)"
    exit_code2=$?
    if [[ $exit_code2 -ne 0 ]]; then
        fail "T18 two-profile-one-bad degrades" "phase 2: non-zero exit ($exit_code2)" "$out2"
    fi
    if [[ -z "$out2" ]]; then
        fail "T18 two-profile-one-bad degrades" "phase 2: went silent after pce_profiles was stripped — the degraded marker was read as safe" "$out2"
    fi

    pass "T18 two-profile-one-bad degrades"
    cleanup_contamination_env
}

# --- T19: F1 variant — a wholly malformed pce_profiles shape degrades too --
# Same defect, different path: `pce_profiles` not shaped as a list at all
# used to record `distinct_pce_targets: 0` — also a confirmed-safe claim
# that was never actually confirmed.

t19_malformed_shape_degrades_not_confirms() {
    new_contamination_env
    cat > "$CFG_ROOT/config/config.json" <<'JSON'
{
  "api": {"url": "https://pce1.example.com", "org_id": "1"},
  "pce_profiles": "not-a-list"
}
JSON

    local out exit_code
    out="$(check_pce_profile_contamination "$CFG_ROOT" "$PY_BIN" 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T19 malformed shape degrades" "non-zero exit ($exit_code)" "$out"
    fi
    if [[ ! -f "$CFG_ROOT/$MARKER_REL" ]]; then
        fail "T19 malformed shape degrades" "marker file not created" "$out"
    fi
    if ! "$PY_BIN" -m json.tool "$CFG_ROOT/$MARKER_REL" > /dev/null 2>&1; then
        fail "T19 malformed shape degrades" "marker file is not valid JSON" "$out"
    fi
    if grep -q '"distinct_pce_targets": 0' "$CFG_ROOT/$MARKER_REL"; then
        fail "T19 malformed shape degrades" "marker recorded a confirmed count of 0 — nothing was actually readable" "$out"
    fi

    # Phase 2: pce_profiles stripped afterward — must not go silent.
    cat > "$CFG_ROOT/config/config.json" <<'JSON'
{
  "api": {"url": "https://pce1.example.com", "org_id": "1"}
}
JSON
    local out2 exit_code2
    out2="$(check_pce_profile_contamination "$CFG_ROOT" "$PY_BIN" 2>&1)"
    exit_code2=$?
    if [[ $exit_code2 -ne 0 ]]; then
        fail "T19 malformed shape degrades" "phase 2: non-zero exit ($exit_code2)" "$out2"
    fi
    if [[ -z "$out2" ]]; then
        fail "T19 malformed shape degrades" "phase 2: went silent after pce_profiles was stripped — the degraded marker was read as safe" "$out2"
    fi

    pass "T19 malformed shape degrades"
    cleanup_contamination_env
}

# --- T20: F2 — masked-collapse ambiguity resolved by an ordinal ------------
# Two distinct profiles that both mask to the same placeholder (no scheme,
# and nothing left to show once any '@'-prefixed userinfo is stripped) used
# to render as two textually identical lines — the operator couldn't tell
# there even are two PCEs, let alone which. Same org on both so the org
# field doesn't accidentally disambiguate them either.

t20_masked_collapse_stays_distinguishable() {
    new_contamination_env
    cat > "$CFG_ROOT/config/config.json" <<'JSON'
{
  "api": {"url": "https://real-pce.example.com", "org_id": "9"},
  "pce_profiles": [
    {"url": "userA@", "org_id": "1"},
    {"url": "userB@", "org_id": "1"}
  ]
}
JSON

    local out exit_code
    out="$(check_pce_profile_contamination "$CFG_ROOT" "$PY_BIN" 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T20 masked collapse distinguishable" "non-zero exit ($exit_code)" "$out"
    fi
    if ! grep -qi "WARNING" <<< "$out"; then
        fail "T20 masked collapse distinguishable" "expected the contamination warning to fire" "$out"
    fi
    if ! grep -q "1) <url unavailable> (org 1)" <<< "$out"; then
        fail "T20 masked collapse distinguishable" "expected an ordinal-numbered first entry" "$out"
    fi
    if ! grep -q "2) <url unavailable> (org 1)" <<< "$out"; then
        fail "T20 masked collapse distinguishable" "expected an ordinal-numbered second, distinguishable entry" "$out"
    fi

    pass "T20 masked collapse distinguishable"
    cleanup_contamination_env
}

# --- T21: F3 — a boolean marker value must not pass as a safe int count ----
# bool is a subclass of int in Python: isinstance(True, int) is True, and
# True <= 1 is also True. A marker with `"distinct_pce_targets": true` used
# to silence the check exactly like a legitimately recorded 0 or 1 would.

t21_bool_marker_value_rejected() {
    new_contamination_env
    cat > "$CFG_ROOT/config/config.json" <<'JSON'
{
  "api": {"url": "https://pce1.example.com", "org_id": "1"}
}
JSON
    cat > "$CFG_ROOT/$MARKER_REL" <<'JSON'
{
  "checked_at": "2026-08-18T00:00:00+00:00",
  "distinct_pce_targets": true
}
JSON

    local out exit_code
    out="$(check_pce_profile_contamination "$CFG_ROOT" "$PY_BIN" 2>&1)"
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        fail "T21 bool marker rejected" "non-zero exit ($exit_code)" "$out"
    fi
    if [[ -z "$out" ]]; then
        fail "T21 bool marker rejected" "went silent — a boolean marker value was accepted as a safe int count" "$out"
    fi

    pass "T21 bool marker rejected"
    cleanup_contamination_env
}

# --- Run all ---------------------------------------------------------------

t1_happy_path
t2_idempotent_rerun
t3_old_root_absent
t4_dual_existence_no_marker
t5_already_migrated_marker
t6_partial_migration_ordering
t7_two_distinct_profiles
t8_single_profile
t9_no_profiles_no_marker
t10_trailing_slash_same_pce
t11_malformed_api_survives_set_e
t12_real_normalizer_import
t13_malformed_profiles_not_a_list
t14_marker_recorded_contamination_not_silenced
t15_credential_url_is_masked_in_output
t16_one_bad_url_does_not_blank_the_check
t17_archive_advice_is_actionable
t18_two_profiles_one_bad_degrades_not_confirms
t19_malformed_shape_degrades_not_confirms
t20_masked_collapse_stays_distinguishable
t21_bool_marker_value_rejected

echo
echo "$PASS_COUNT/$TOTAL passed"
if [[ $FAIL_COUNT -ne 0 ]]; then
    exit 1
fi
exit 0
