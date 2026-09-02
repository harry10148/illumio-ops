#!/usr/bin/env bash
# Build illumio-ops offline bundles for Linux.
# Requires: curl, tar, git, any Linux x86_64 with Python 3.10+.
# Output:
#   dist/illumio-ops-<version>-offline-linux-x86_64.tar.gz
set -euo pipefail

# Keep the bundled interpreter's pip off the build host's user site-packages
# (see the note at the top of scripts/install.sh).
export PYTHONNOUSERSITE=1

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"

VERSION="$("$SCRIPT_DIR/resolve_version.sh")"

# python-build-standalone release — update these lines when upgrading Python.
# After bumping PBS_TAG / PBS_PYTHON, refresh the SHA256 pin below from a
# GPG / Sigstore-verified source (NOT the same release origin) and commit
# PBS_TAG, PBS_PYTHON, and PBS_SHA256_LINUX_X86_64 together in the same patch.
PBS_TAG="20241016"
PBS_PYTHON="3.12.7"

PBS_LINUX_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/cpython-${PBS_PYTHON}+${PBS_TAG}-x86_64-unknown-linux-gnu-install_only.tar.gz"

# L-10: hard-coded SHA256 pins — verified against the GitHub release sidecar
# (https://github.com/astral-sh/python-build-standalone/releases/tag/20241016)
# at commit time. Pinning the hash in-tree breaks the same-origin TOFU loop
# from the original sidecar-on-download approach: a future MITM that swaps
# both the tarball AND the published .sha256 will still mismatch this in-tree
# pin. For higher-assurance environments, swap verify_sha256 for a GPG / cosign
# bundle check (astral-sh publishes both).
PBS_SHA256_LINUX_X86_64="43576f7db1033dd57b900307f09c2e86f371152ac8a2607133afa51cbfc36064"

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

# ── Gate: the wheel lock must exist and match its source spec ─────────────────
# 離線 bundle 的 wheels 過去是照 requirements-offline.txt 的「範圍」即時解析下載
# 的：同一版原始碼在不同日子建置會裝到不同的套件版本，而且沒有任何雜湊驗證，
# 被掉包的 wheel 會靜靜地裝進每一台離線機器。改成一律從 requirements-offline.lock
# （--generate-hashes 逐檔釘選）下載，並在這裡確認鎖檔沒有落後於來源規格。
# 新鮮度用鎖檔尾端的 sha256 標記判定；標記由產生鎖檔的第二道指令寫入，忘了跑
# 就等同「鎖檔可能過期」，一律擋下（fail closed）。
LOCK_FILE="$REPO_ROOT/requirements-offline.lock"
require_fresh_lock() {
    local src="$REPO_ROOT/requirements-offline.txt" expected actual
    if [[ ! -f "$LOCK_FILE" ]]; then
        echo "ERROR: requirements-offline.lock is missing — the offline bundle must" >&2
        echo "  install hash-pinned wheels, not a live range resolution." >&2
        echo "  Generate it (see the header of requirements-offline.txt)." >&2
        exit 1
    fi
    expected=$(sha256sum "$src" | awk '{print $1}')
    actual=$(sed -n 's/^# requirements-offline\.txt sha256: *//p' "$LOCK_FILE" | tail -n 1)
    if [[ -z "$actual" ]]; then
        echo "ERROR: requirements-offline.lock has no source sha256 marker — cannot" >&2
        echo "  prove it matches requirements-offline.txt. Regenerate it (see the" >&2
        echo "  header of requirements-offline.txt)." >&2
        exit 1
    fi
    if [[ "$expected" != "$actual" ]]; then
        echo "ERROR: requirements-offline.lock is stale — it was generated from a" >&2
        echo "  different requirements-offline.txt." >&2
        echo "  requirements-offline.txt: $expected" >&2
        echo "  lock marker:              $actual" >&2
        echo "  Regenerate it (see the header of requirements-offline.txt)." >&2
        exit 1
    fi
    echo "==> requirements-offline.lock is in sync with requirements-offline.txt"
}

# ── Shared helper: assert no secrets were staged ──────────────────────────────
# The excludes in stage_app are the control; this is the gate that proves they
# held. The build host normally runs the app, so config/ accumulates real
# secrets (config.json with the PCE api key/secret, alerts.json, and the
# runtime-generated TLS private key under config/tls/). Anything that slips
# through lands in a customer-distributed archive, so fail the build loudly
# rather than shipping it.
assert_no_secrets_staged() {
    local dest="$1" bad
    bad=$(find "$dest/app/config" -type f \
            \( -name '*.pem' -o -name '*.key' -o -name '*.p12' -o -name '*.pfx' \
               -o -name '*.crt' -o -name '*.csr' -o -name '*.json' \) 2>/dev/null || true)
    if [[ -n "$bad" ]] || [[ -d "$dest/app/config/tls" ]]; then
        echo "ERROR: key material or operator-owned files staged into the bundle:" >&2
        [[ -n "$bad" ]] && echo "$bad" >&2
        [[ -d "$dest/app/config/tls" ]] && echo "$dest/app/config/tls" >&2
        echo "  Only *.example templates and report_config.yaml belong in the bundle's" >&2
        echo "  config/. Update the excludes in stage_app() before re-running." >&2
        exit 1
    fi
}

# ── Shared helper: stage app files (no credentials) ───────────────────────────
stage_app() {
    local dest="$1"
    mkdir -p "$dest/app"
    rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
        "$REPO_ROOT/illumio-ops.py" \
        "$REPO_ROOT/src" \
        "$dest/app/"
    # config templates only — NEVER bundle config.json (API credentials),
    # alerts.json (operator rules + previously LINE/webhook secrets), runtime
    # data, or key material.
    # config/tls/ is runtime-generated on the BUILD host (self_signed.pem +
    # self_signed_key.pem, csr_key.pem, ca_signed.pem). Bundling it would ship
    # one private key to every customer, and each install would then serve
    # HTTPS with that shared key instead of minting its own — the fresh-install
    # path in _generate_self_signed_cert() (src/gui/_helpers.py) short-circuits
    # whenever both PEMs already exist. config/limiter/ is rate-limiter state.
    rsync -a \
        --exclude='config.json' \
        --exclude='alerts.json' \
        --exclude='rule_schedules.json' \
        --exclude='tls/' \
        --exclude='limiter/' \
        --exclude='*.pem' \
        --exclude='*.key' \
        --exclude='*.p12' \
        --exclude='*.pfx' \
        "$REPO_ROOT/config/" "$dest/app/config/"
    assert_no_secrets_staged "$dest"
    rsync -a "$REPO_ROOT/scripts/" "$dest/app/scripts/"
    cp "$REPO_ROOT/requirements-offline.txt" "$dest/app/"
    # 鎖檔一定要進 bundle：install.sh 就是拿它配 --require-hashes 安裝。
    cp "$LOCK_FILE" "$dest/app/"
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
# Linux), plus the Tcl/Tk GUI stack and dev-only stdlib. None are needed at
# runtime for this web/CLI app (matplotlib uses the Agg backend, so no Tkinter).
# Stripping + pruning cuts the Linux bundle ~50%. ensurepip is KEPT (venv-based
# deploys need it).
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

    echo "==> [Linux] Downloading manylinux_2_28_x86_64 wheels"
    mkdir -p "$BUILD/wheels"
    # --platform 是精確標籤比對，不是「這個版本以上」：只給 manylinux_2_28 時，
    # 仍只發舊標籤的套件（例如 cffi 只發 manylinux_2_17）會直接 "No matching
    # distribution found"。舊標籤在 glibc 2.28 上本來就裝得起來，所以把可接受的
    # 標籤全部列出——順序不代表偏好，pip 會挑最合適的那個。
    "$BUILD/python/bin/python3" -m pip download \
        --only-binary=:all: \
        --platform manylinux_2_28_x86_64 \
        --platform manylinux_2_17_x86_64 \
        --platform manylinux2014_x86_64 \
        --python-version 3.12 \
        --implementation cp \
        --require-hashes \
        -d "$BUILD/wheels" \
        -r "$LOCK_FILE"

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

require_fresh_lock
build_linux

echo ""
echo "==> Bundle ready in dist/:"
ls -lh "$DIST_DIR"/illumio-ops-"${VERSION}"-offline-*.tar.gz 2>/dev/null || true
