#!/usr/bin/env bash
# Check this host and this bundle before install.sh. Reads only; changes nothing.
#
#   ./preflight.sh [--prefix DIR] [--port N]
#
# Says what install.sh would do in DIR (a fresh install, an upgrade of 5.x, or of an installed v6) and checks what
# that needs. Exit 0: every check passed or only warned; 1: at least one failed (install.sh would fail or the
# service would not run).
set -uo pipefail

PREFIX=/opt/illumio-ops
PORT=""
BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix) PREFIX="${2:?}"; shift 2 ;;
        --port) PORT="${2:?}"; shift 2 ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) echo "preflight.sh: unknown option: $1" >&2; exit 2 ;;
    esac
done
PREFIX="${PREFIX%/}"

FAILED=0
pass() { echo "  PASS  $1"; }
warn() { echo "  WARN  $1"; }
fail() { echo "  FAIL  $1"; FAILED=$((FAILED + 1)); }

echo "illumio-ops preflight for $PREFIX"

# --- what install.sh would do -----------------------------------------------------------------------------------
BUNDLE_VERSION="$(grep -oP '^__version__ = "\K[0-9.]+' "$BUNDLE_DIR/illumio_ops/__init__.py" 2>/dev/null || true)"
if [[ -e "$PREFIX/illumio-ops.py" ]]; then
    pass "$PREFIX holds 5.x: install.sh upgrades it to v6 ${BUNDLE_VERSION} (the migration report comes first)"
elif [[ -e "$PREFIX/illumio_ops" || -e "$PREFIX/config/settings.json" ]]; then
    INSTALLED="$(grep -oP '^__version__ = "\K[0-9.]+' "$PREFIX/illumio_ops/__init__.py" 2>/dev/null || true)"
    if [[ -z "$INSTALLED" || ! -f "$PREFIX/config/settings.json" ]]; then
        fail "$PREFIX holds only part of a v6 installation: install.sh refuses it"
    elif [[ "$(printf '%s\n%s\n' "$INSTALLED" "$BUNDLE_VERSION" | sort -V | tail -1)" != "$BUNDLE_VERSION" ]]; then
        fail "$PREFIX runs $INSTALLED, newer than this bundle ($BUNDLE_VERSION): an older version is not installed over it"
    else
        pass "$PREFIX holds v6 $INSTALLED: install.sh upgrades it to $BUNDLE_VERSION in place (settings and data stay)"
    fi
else
    pass "$PREFIX is free: install.sh makes a fresh installation of $BUNDLE_VERSION"
fi

# --- host --------------------------------------------------------------------------------------------------------
ARCH="$(uname -m)"
[[ "$ARCH" == x86_64 ]] && pass "architecture $ARCH" || fail "architecture $ARCH: the bundle is built for x86_64"

GLIBC="$({ ldd --version 2>&1 || true; } | head -1 | grep -oP '[0-9]+\.[0-9]+$' || echo 0.0)"
if [[ "$(printf '%s\n2.28\n' "$GLIBC" | sort -V | head -1)" == 2.28 ]]; then
    pass "glibc $GLIBC"
else
    fail "glibc $GLIBC: the bundled wheels need 2.28 or newer (RHEL/Rocky 8+, Ubuntu 20.04+, Debian 11+)"
fi

if command -v systemctl >/dev/null && [[ -d /run/systemd/system ]]; then
    pass "systemd"
else
    fail "systemd is not running: install.sh registers a systemd service (only --no-systemd works without it)"
fi
for cmd in useradd runuser getent df du; do
    command -v "$cmd" >/dev/null || fail "$cmd not found: install.sh uses it"
done

DIR="$PREFIX"
while [[ ! -d "$DIR" ]]; do DIR="$(dirname "$DIR")"; done
AVAIL_MB=$(( $(df --output=avail -B1 "$DIR" | tail -1 | tr -d ' ') / 1048576 ))
if (( AVAIL_MB >= 2048 )); then
    pass "disk: ${AVAIL_MB} MB free at $DIR"
else
    fail "disk: ${AVAIL_MB} MB free at $DIR; need at least 2048 MB (program about 500 MB, the rest for data and reports)"
fi

# --- bundle ------------------------------------------------------------------------------------------------------
for need in install.sh rollback.sh restore-previous.sh uninstall.sh illumio-ops.service.in requirements.lock \
            illumio_ops/__init__.py; do
    [[ -e "$BUNDLE_DIR/$need" ]] || fail "bundle: $need is missing (the bundle is incomplete or damaged)"
done
WHEELS=$(find "$BUNDLE_DIR/wheels" -maxdepth 1 -name '*.whl' 2>/dev/null | wc -l)
(( WHEELS >= 20 )) && pass "bundle: $WHEELS wheels" || fail "bundle: $WHEELS wheels; expected at least 20"
PY="$BUNDLE_DIR/python/bin/python3"
if [[ -x "$PY" ]] && SQLITE="$("$PY" -I -c 'import sqlite3, ssl; print(sqlite3.sqlite_version)' 2>/dev/null)"; then
    if [[ "$(printf '%s\n3.51.3\n' "$SQLITE" | sort -V | head -1)" == 3.51.3 ]]; then
        pass "bundled Python runs (SQLite $SQLITE)"
    else
        fail "bundled SQLite $SQLITE: needs 3.51.3 or newer"
    fi
else
    fail "the bundled Python does not run on this host"
fi

# --- port --------------------------------------------------------------------------------------------------------
if [[ -z "$PORT" ]]; then
    PORT="$(grep -oP '"port":\s*\K[0-9]+' "$PREFIX/config/settings.json" 2>/dev/null | head -1)"
    PORT="${PORT:-5001}"
fi
if command -v ss >/dev/null && ss -Htln "sport = :$PORT" 2>/dev/null | grep -q .; then
    if [[ -e "$PREFIX/config/settings.json" ]]; then
        pass "port $PORT is in use (the installed service, which the upgrade restarts)"
    else
        warn "port $PORT is in use: pass install.sh --port with a free one"
    fi
else
    pass "port $PORT is free"
fi

echo
if (( FAILED )); then
    echo "PREFLIGHT FAILED: $FAILED check(s). Resolve them before install.sh."
    exit 1
fi
echo "Preflight passed."
