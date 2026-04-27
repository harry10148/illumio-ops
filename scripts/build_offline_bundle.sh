#!/usr/bin/env bash
# Build illumio_ops offline bundles for Linux and Windows.
# Requires: curl, tar, zip, git, any Linux x86_64 with Python 3.10+.
# Output:
#   dist/illumio_ops-<version>-offline-linux-x86_64.tar.gz
#   dist/illumio_ops-<version>-offline-windows-x86_64.zip
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"

VERSION="${VERSION:-$(cd "$REPO_ROOT" && git describe --tags --always 2>/dev/null || echo "dev")}"

# python-build-standalone release — update these two lines when upgrading Python
PBS_TAG="20241016"
PBS_PYTHON="3.12.7"

PBS_LINUX_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/cpython-${PBS_PYTHON}+${PBS_TAG}-x86_64-unknown-linux-gnu-install_only.tar.gz"
PBS_WIN_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/cpython-${PBS_PYTHON}+${PBS_TAG}-x86_64-pc-windows-msvc-install_only.tar.gz"

mkdir -p "$DIST_DIR"

# ── Shared helper: stage app files (no credentials) ───────────────────────────
stage_app() {
    local dest="$1"
    mkdir -p "$dest/app"
    rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
        "$REPO_ROOT/illumio_ops.py" \
        "$REPO_ROOT/src" \
        "$dest/app/"
    # config templates only — NEVER bundle config.json (API credentials) or runtime data
    rsync -a \
        --exclude='config.json' \
        --exclude='rule_schedules.json' \
        "$REPO_ROOT/config/" "$dest/app/config/"
    rsync -a "$REPO_ROOT/scripts/" "$dest/app/scripts/"
    cp "$REPO_ROOT/requirements-offline.txt" "$dest/app/"
    echo "$VERSION" > "$dest/VERSION"
}

# ── Linux bundle ──────────────────────────────────────────────────────────────
build_linux() {
    local BUILD="$REPO_ROOT/build/offline-linux"
    local ARCHIVE="illumio_ops-${VERSION}-offline-linux-x86_64.tar.gz"
    echo "==> [Linux] Cleaning build dir"
    rm -rf "$BUILD" && mkdir -p "$BUILD"

    echo "==> [Linux] Downloading PBS ${PBS_PYTHON}"
    curl -fL "$PBS_LINUX_URL" | tar xz -C "$BUILD"

    echo "==> [Linux] Downloading manylinux_2_17_x86_64 wheels"
    mkdir -p "$BUILD/wheels"
    "$BUILD/python/bin/python3" -m pip download \
        --only-binary=:all: \
        --platform manylinux_2_17_x86_64 \
        --python-version 3.12 \
        --implementation cp \
        -d "$BUILD/wheels" \
        -r "$REPO_ROOT/requirements-offline.txt"

    stage_app "$BUILD"

    mkdir -p "$BUILD/deploy"
    cp "$REPO_ROOT/deploy/illumio-ops.service" "$BUILD/deploy/"
    cp "$REPO_ROOT/scripts/preflight.sh" "$BUILD/"
    chmod +x "$BUILD/preflight.sh"
    cp "$REPO_ROOT/scripts/install.sh" "$BUILD/"
    chmod +x "$BUILD/install.sh"
    cp "$REPO_ROOT/scripts/uninstall.sh" "$BUILD/"
    chmod +x "$BUILD/uninstall.sh"

    echo "==> [Linux] Creating $ARCHIVE"
    tar czf "$DIST_DIR/$ARCHIVE" -C "$(dirname "$BUILD")" "$(basename "$BUILD")"
    echo "    Size: $(du -sh "$DIST_DIR/$ARCHIVE" | cut -f1)"
}

# ── Windows bundle ─────────────────────────────────────────────────────────────
build_windows() {
    local BUILD="$REPO_ROOT/build/offline-windows"
    local ARCHIVE="illumio_ops-${VERSION}-offline-windows-x86_64.zip"
    local LINUX_PYTHON="$REPO_ROOT/build/offline-linux/python/bin/python3"

    [[ -x "$LINUX_PYTHON" ]] || \
        { echo "ERROR: Linux PBS Python not found — run build_linux first (required for cross-platform wheel download)"; exit 1; }

    echo "==> [Windows] Cleaning build dir"
    rm -rf "$BUILD" && mkdir -p "$BUILD"

    echo "==> [Windows] Downloading PBS ${PBS_PYTHON} for Windows"
    curl -fL "$PBS_WIN_URL" | tar xz -C "$BUILD"

    echo "==> [Windows] Downloading win_amd64 wheels"
    mkdir -p "$BUILD/wheels"
    # Use the local Linux PBS pip to download Windows wheels (cross-platform download)
    "$LINUX_PYTHON" -m pip download \
        --only-binary=:all: \
        --platform win_amd64 \
        --python-version 3.12 \
        --implementation cp \
        -d "$BUILD/wheels" \
        -r "$REPO_ROOT/requirements-offline.txt"

    stage_app "$BUILD"

    mkdir -p "$BUILD/deploy"
    cp "$REPO_ROOT/deploy/install_service.ps1" "$BUILD/deploy/"
    cp "$REPO_ROOT/scripts/preflight.ps1" "$BUILD/"
    cp "$REPO_ROOT/scripts/install.ps1" "$BUILD/"

    echo "==> [Windows] Creating $ARCHIVE"
    (cd "$(dirname "$BUILD")" && zip -r "$DIST_DIR/$ARCHIVE" "$(basename "$BUILD")" -x "*.pyc" -x "__pycache__/*")
    echo "    Size: $(du -sh "$DIST_DIR/$ARCHIVE" | cut -f1)"
}

build_linux
build_windows

echo ""
echo "==> All bundles ready in dist/:"
ls -lh "$DIST_DIR"/illumio_ops-"${VERSION}"-offline-*.{tar.gz,zip} 2>/dev/null || true
