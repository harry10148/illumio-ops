#!/usr/bin/env bash
# Build the v6 offline bundle: dist/illumio-ops-<version>-offline-linux-x86_64.tar.gz
#
#   illumio-ops-<version>/
#     python/                 python-build-standalone CPython 3.12.7 (SHA256-pinned)
#     wheels/                 every wheel requirements-v6.lock names
#     requirements-v6.lock
#     illumio_ops/            the package, including the built web UI
#     install.sh
#     illumio-ops.service.in
#
# PYTHON (default python3) must have pip-tools for the lock freshness check.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
PYTHON="${PYTHON:-python3}"
LOCK=requirements-v6.lock

# Same pins as 5.x scripts/build_offline_bundle.sh; bump all three together.
PBS_TAG="20241016"
PBS_PYTHON="3.12.7"
PBS_SHA256_LINUX_X86_64="43576f7db1033dd57b900307f09c2e86f371152ac8a2607133afa51cbfc36064"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/cpython-${PBS_PYTHON}+${PBS_TAG}-x86_64-unknown-linux-gnu-install_only.tar.gz"

VERSION="$("$PYTHON" -c 'import re,sys; print(re.search(r"__version__ = \"([^\"]+)\"", open("illumio_ops/__init__.py").read()).group(1))')"
NAME="illumio-ops-${VERSION}"
STAGE="$REPO_ROOT/build/v6/$NAME"
ARCHIVE="$REPO_ROOT/dist/${NAME}-offline-linux-x86_64.tar.gz"

echo "==> Lock freshness: $LOCK must equal a fresh compile of requirements-v6.in"
FRESH="$(mktemp)"
trap 'rm -f "$FRESH"' EXIT
"$PYTHON" -m piptools compile --quiet --generate-hashes --strip-extras --no-header \
    --output-file="$FRESH" requirements-v6.in
pins() { grep -E '^[A-Za-z0-9_.-]+==' "$1" | sed 's/ .*//' | sort; }
if ! diff <(pins "$LOCK") <(pins "$FRESH") >/dev/null; then
    diff <(pins "$LOCK") <(pins "$FRESH") || true
    echo "ERROR: $LOCK is stale; re-run pip-compile (see the header of requirements-v6.in)" >&2
    exit 1
fi

echo "==> Frontend: contracts current, typecheck, build"
npm ci --prefix web --no-audit --no-fund
PYTHON="$PYTHON" bash scripts/v6/gen_contracts.sh
git diff --exit-code web/src/api/contracts.json web/src/api/generated.ts \
    || { echo "ERROR: generated API files are not committed" >&2; exit 1; }
npm --prefix web run typecheck
npm --prefix web run build
[[ -f illumio_ops/web/static/index.html ]] || { echo "ERROR: web build produced no index.html" >&2; exit 1; }

echo "==> Staging $STAGE"
rm -rf "$STAGE" && mkdir -p "$STAGE/wheels" "$REPO_ROOT/dist"
PBS_TAR="$STAGE/../pbs.tar.gz"
curl -fL --retry 3 "$PBS_URL" -o "$PBS_TAR"
echo "$PBS_SHA256_LINUX_X86_64  $PBS_TAR" | sha256sum -c -
tar xzf "$PBS_TAR" -C "$STAGE"
rm -f "$PBS_TAR"

echo "==> Wheels (all manylinux tags: some packages only publish older ones, e.g. cffi)"
"$STAGE/python/bin/python3" -m pip download --quiet \
    --only-binary=:all: \
    --platform manylinux_2_28_x86_64 \
    --platform manylinux_2_17_x86_64 \
    --platform manylinux2014_x86_64 \
    --python-version 3.12 \
    --implementation cp \
    --require-hashes \
    -d "$STAGE/wheels" \
    -r "$LOCK"

rsync -a --exclude '__pycache__' --exclude '*.pyc' illumio_ops/ "$STAGE/illumio_ops/"
cp "$LOCK" scripts/v6/install.sh scripts/v6/illumio-ops.service.in "$STAGE/"
chmod +x "$STAGE/install.sh"

echo "==> Slimming the bundled Python"
py="$STAGE/python"
for f in "$py"/lib/libpython3.*.so.* "$py"/bin/python3.[0-9]*; do
    [[ -f "$f" ]] && strip --strip-debug "$f" 2>/dev/null || true
done
rm -rf "$py"/lib/tcl8* "$py"/lib/tk8* "$py"/lib/Tix* "$py"/lib/itcl* "$py"/lib/thread2* "$py"/include
rm -rf "$py"/lib/python3.*/tkinter "$py"/lib/python3.*/idlelib "$py"/lib/python3.*/lib2to3 \
       "$py"/lib/python3.*/pydoc_data "$py"/lib/python3.*/test "$py"/lib/python3.*/config-3.*
find "$py"/lib -name '*.a' -delete 2>/dev/null || true

tar czf "$ARCHIVE" -C "$REPO_ROOT/build/v6" "$NAME"
(cd "$(dirname "$ARCHIVE")" && sha256sum "$(basename "$ARCHIVE")") | tee "$ARCHIVE.sha256"  # relative name: checkable anywhere
echo "==> Built $ARCHIVE"
