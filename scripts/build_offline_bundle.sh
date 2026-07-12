#!/usr/bin/env bash
# Build illumio-ops offline bundles for Linux and Windows.
# Requires: curl, tar, zip, git, any Linux x86_64 with Python 3.10+.
# Output:
#   dist/illumio-ops-<version>-offline-linux-x86_64.tar.gz
#   dist/illumio-ops-<version>-offline-windows-x86_64.zip
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"

VERSION="$("$SCRIPT_DIR/resolve_version.sh")"

# python-build-standalone release — update these lines when upgrading Python.
# After bumping PBS_TAG / PBS_PYTHON, refresh the SHA256 pins below from a
# GPG / Sigstore-verified source (NOT the same release origin) and commit
# all four fields together in the same patch.
PBS_TAG="20241016"
PBS_PYTHON="3.12.7"

PBS_LINUX_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/cpython-${PBS_PYTHON}+${PBS_TAG}-x86_64-unknown-linux-gnu-install_only.tar.gz"
PBS_WIN_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/cpython-${PBS_PYTHON}+${PBS_TAG}-x86_64-pc-windows-msvc-install_only.tar.gz"

# L-10: hard-coded SHA256 pins — verified against the GitHub release sidecar
# (https://github.com/astral-sh/python-build-standalone/releases/tag/20241016)
# at commit time. Pinning the hash in-tree breaks the same-origin TOFU loop
# from the original sidecar-on-download approach: a future MITM that swaps
# both the tarball AND the published .sha256 will still mismatch this in-tree
# pin. For higher-assurance environments, swap verify_sha256 for a GPG / cosign
# bundle check (astral-sh publishes both).
PBS_SHA256_LINUX_X86_64="43576f7db1033dd57b900307f09c2e86f371152ac8a2607133afa51cbfc36064"
PBS_SHA256_WIN_X86_64="f05531bff16fa77b53be0776587b97b466070e768e6d5920894de988bdcd547a"

verify_sha256() {
    local file="$1" expected="$2"
    echo "==> Verifying SHA256 for $(basename "$file")"
    local actual
    actual=$(sha256sum "$file" | awk '{print $1}')
    if [[ "$expected" != "$actual" ]]; then
        echo "ERROR: SHA256 mismatch for $(basename "$file")" >&2
        echo "  expected: $expected (in-tree pin)" >&2
        echo "  actual:   $actual" >&2
        exit 1
    fi
    echo "    OK ($expected)"
}

mkdir -p "$DIST_DIR"

# ── Shared helper: stage app files (no credentials) ───────────────────────────
stage_app() {
    local dest="$1"
    mkdir -p "$dest/app"
    rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
        "$REPO_ROOT/illumio-ops.py" \
        "$REPO_ROOT/src" \
        "$dest/app/"
    # config templates only — NEVER bundle config.json (API credentials),
    # alerts.json (operator rules + previously LINE/webhook secrets), or runtime data
    rsync -a \
        --exclude='config.json' \
        --exclude='alerts.json' \
        --exclude='rule_schedules.json' \
        "$REPO_ROOT/config/" "$dest/app/config/"
    rsync -a "$REPO_ROOT/scripts/" "$dest/app/scripts/"
    cp "$REPO_ROOT/requirements-offline.txt" "$dest/app/"
    # Runtime data read from outside src/: src/events/reference.py loads
    # docs/_meta/illumio-event-reference.json (path resolved relative to repo
    # root). It MUST be bundled or the Event Viewer 500s with FileNotFoundError
    # on a fresh install.
    mkdir -p "$dest/app/docs/_meta"
    cp "$REPO_ROOT/docs/_meta/illumio-event-reference.json" "$dest/app/docs/_meta/"
    echo "$VERSION" > "$dest/VERSION"
}

# ── Shared helper: slim the bundled Python ────────────────────────────────────
# python-build-standalone ships an UNSTRIPPED libpython (~206M of debug_info on
# Linux) and full .pdb debug files on Windows, plus the Tcl/Tk GUI stack and
# dev-only stdlib. None are needed at runtime for this web/CLI app (matplotlib
# uses the Agg backend, so no Tkinter). Stripping + pruning cuts the Linux
# bundle ~50% and Windows ~30%. ensurepip is KEPT (venv-based deploys need it).
# Call AFTER all pip downloads complete (the bundled python is still usable).
slim_python() {
    local py="$1/python" platform="$2"
    echo "==> [$platform] Slimming bundled Python (strip debug + prune GUI/dev stdlib)"
    if [[ "$platform" == "linux" ]]; then
        local f
        for f in "$py"/lib/libpython3.*.so.* "$py"/bin/python3.[0-9]*; do
            [[ -f "$f" ]] && strip --strip-debug "$f" 2>/dev/null || true
        done
        rm -rf "$py"/lib/tcl8* "$py"/lib/tk8* "$py"/lib/Tix* "$py"/lib/itcl* \
               "$py"/lib/thread2* "$py"/include
        rm -rf "$py"/lib/python3.*/tkinter "$py"/lib/python3.*/idlelib \
               "$py"/lib/python3.*/lib2to3 "$py"/lib/python3.*/pydoc_data \
               "$py"/lib/python3.*/test "$py"/lib/python3.*/config-3.*
        find "$py"/lib -name '*.a' -delete 2>/dev/null || true
    else  # windows
        find "$py" -name '*.pdb' -delete 2>/dev/null || true
        rm -rf "$py"/tcl "$py"/include "$py"/libs \
               "$py"/Lib/tkinter "$py"/Lib/idlelib "$py"/Lib/lib2to3 \
               "$py"/Lib/pydoc_data "$py"/Lib/test
        rm -f "$py"/DLLs/_tkinter.pyd "$py"/DLLs/tcl*.dll "$py"/DLLs/tk*.dll
    fi
}

# ── Linux bundle ──────────────────────────────────────────────────────────────
build_linux() {
    local STAGE_NAME="illumio-ops-${VERSION}-offline-linux-x86_64"
    local BUILD="$REPO_ROOT/build/$STAGE_NAME"
    local ARCHIVE="illumio-ops-${VERSION}-offline-linux-x86_64.tar.gz"
    echo "==> [Linux] Cleaning build dir"
    rm -rf "$BUILD" && mkdir -p "$BUILD"

    echo "==> [Linux] Downloading PBS ${PBS_PYTHON}"
    local PBS_TAR="$BUILD/pbs-linux.tar.gz"
    curl -fL "$PBS_LINUX_URL" -o "$PBS_TAR"
    verify_sha256 "$PBS_TAR" "$PBS_SHA256_LINUX_X86_64"
    tar xzf "$PBS_TAR" -C "$BUILD"
    rm -f "$PBS_TAR"

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

    slim_python "$BUILD" linux

    echo "==> [Linux] Creating $ARCHIVE"
    tar czf "$DIST_DIR/$ARCHIVE" -C "$(dirname "$BUILD")" "$(basename "$BUILD")"
    echo "    Size: $(du -sh "$DIST_DIR/$ARCHIVE" | cut -f1)"
}

# ── Windows bundle ─────────────────────────────────────────────────────────────
build_windows() {
    local STAGE_NAME="illumio-ops-${VERSION}-offline-windows-x86_64"
    local BUILD="$REPO_ROOT/build/$STAGE_NAME"
    local ARCHIVE="illumio-ops-${VERSION}-offline-windows-x86_64.zip"
    local LINUX_PYTHON="$REPO_ROOT/build/illumio-ops-${VERSION}-offline-linux-x86_64/python/bin/python3"

    [[ -x "$LINUX_PYTHON" ]] || \
        { echo "ERROR: Linux PBS Python not found — run build_linux first (required for cross-platform wheel download)"; exit 1; }

    echo "==> [Windows] Cleaning build dir"
    rm -rf "$BUILD" && mkdir -p "$BUILD"

    echo "==> [Windows] Downloading PBS ${PBS_PYTHON} for Windows"
    local PBS_TAR="$BUILD/pbs-win.tar.gz"
    curl -fL "$PBS_WIN_URL" -o "$PBS_TAR"
    verify_sha256 "$PBS_TAR" "$PBS_SHA256_WIN_X86_64"
    tar xzf "$PBS_TAR" -C "$BUILD"
    rm -f "$PBS_TAR"

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

    # Cross-platform marker guard: pip download evaluates environment markers
    # on this (Linux) host, so Windows-only wheels vanish silently if they
    # ever drop out of requirements-offline.txt. Fail the build instead.
    for w in colorama win32_setctime; do
        ls "$BUILD/wheels/${w}"-*.whl >/dev/null 2>&1 || {
            echo "ERROR: missing Windows-only wheel: $w (see requirements-offline.txt)" >&2
            exit 1
        }
    done

    stage_app "$BUILD"

    mkdir -p "$BUILD/deploy"
    cp "$REPO_ROOT/deploy/install_service.ps1" "$BUILD/deploy/"
    cp "$REPO_ROOT/scripts/preflight.ps1" "$BUILD/"
    cp "$REPO_ROOT/scripts/install.ps1" "$BUILD/"

    # NSSM (Windows service manager) — bundled so air-gapped hosts don't need
    # to fetch nssm.exe from nssm.cc separately. install_service.ps1 picks it
    # up automatically from $PSScriptRoot/nssm.exe (i.e. deploy/nssm.exe).
    echo "==> [Windows] Bundling NSSM"
    unzip -j -o "$REPO_ROOT/vendor/windows/nssm-2.24.zip" \
        "nssm-2.24/win64/nssm.exe" -d "$BUILD/deploy/" >/dev/null

    slim_python "$BUILD" windows

    echo "==> [Windows] Creating $ARCHIVE"
    (cd "$(dirname "$BUILD")" && zip -r "$DIST_DIR/$ARCHIVE" "$(basename "$BUILD")" -x "*.pyc" -x "__pycache__/*")
    echo "    Size: $(du -sh "$DIST_DIR/$ARCHIVE" | cut -f1)"
}

build_linux
build_windows

echo ""
echo "==> All bundles ready in dist/:"
ls -lh "$DIST_DIR"/illumio-ops-"${VERSION}"-offline-*.{tar.gz,zip} 2>/dev/null || true
