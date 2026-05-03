#!/usr/bin/env bash
# Pre-install environment check for illumio_ops offline bundle.
# Run BEFORE install.sh or setup.sh to validate the target host.
# Usage: bash preflight.sh
# Exit: 0 = all PASS/WARN, 1 = at least one FAIL
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "$0")" && pwd)"
RED='\033[0;31m'; YEL='\033[1;33m'; GRN='\033[0;32m'; NC='\033[0m'
FAIL_COUNT=0

pass() { echo -e "  ${GRN}PASS${NC}  $1"; }
warn() { echo -e "  ${YEL}WARN${NC}  $1"; }
fail() { echo -e "  ${RED}FAIL${NC}  $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); }

echo "illumio-ops pre-install check"
echo "=============================="

# 1. Architecture
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then pass "Architecture: $ARCH"
else fail "Architecture: $ARCH — bundle requires x86_64"; fi

# 2. glibc >= 2.17 (required by manylinux_2_17 wheels)
GLIBC_VER=$(ldd --version 2>&1 | head -1 | grep -oP '\d+\.\d+' | head -1 || echo "0.0")
GLIBC_MAJOR=$(echo "$GLIBC_VER" | cut -d. -f1)
GLIBC_MINOR=$(echo "$GLIBC_VER" | cut -d. -f2)
if [ "$GLIBC_MAJOR" -gt 2 ] || { [ "$GLIBC_MAJOR" -eq 2 ] && [ "$GLIBC_MINOR" -ge 17 ]; }; then
    pass "glibc: $GLIBC_VER (>= 2.17 required)"
else
    fail "glibc: $GLIBC_VER — requires >= 2.17 (RHEL 7+)"
fi

# 3. systemd
if systemctl --version &>/dev/null; then pass "systemd: available"
else fail "systemd: not found — required for service registration"; fi

# 4. Disk space >= 2 GB at /opt
# Bundle ~150 MB + extracted PBS runtime ~250 MB + site-packages ~415 MB +
# logs/cache/reports headroom for 24/7 operation → 2 GB minimum.
AVAIL_KB=$(df /opt 2>/dev/null | tail -1 | awk '{print $4}' || echo 0)
AVAIL_MB=$((AVAIL_KB / 1024))
if [ "$AVAIL_MB" -ge 2048 ]; then pass "Disk at /opt: ${AVAIL_MB} MB (>= 2048 MB required)"
else fail "Disk at /opt: ${AVAIL_MB} MB — need >= 2048 MB"; fi

# 5. rsync (used by install.sh)
if command -v rsync &>/dev/null; then pass "rsync: available"
else fail "rsync: not found — install with: dnf install rsync"; fi

# 6. Bundle integrity
if [ -f "$BUNDLE_DIR/VERSION" ]; then pass "Bundle VERSION: $(cat "$BUNDLE_DIR/VERSION")"
else fail "Bundle VERSION file missing — bundle may be corrupt"; fi

for dir in python wheels app deploy; do
    if [ -d "$BUNDLE_DIR/$dir" ]; then pass "Bundle dir: $dir/"
    else fail "Bundle dir missing: $dir/ — bundle may be corrupt"; fi
done

WHEEL_COUNT=$(find "$BUNDLE_DIR/wheels" -name "*.whl" 2>/dev/null | wc -l)
if [ "$WHEEL_COUNT" -ge 20 ]; then pass "Wheels: $WHEEL_COUNT .whl files (>= 20 required)"
else fail "Wheels: only $WHEEL_COUNT .whl files — expected >= 20"; fi

BUNDLED_PY="$BUNDLE_DIR/python/bin/python3"
if [ -x "$BUNDLED_PY" ]; then pass "Bundled Python: $("$BUNDLED_PY" --version 2>&1)"
else fail "Bundled Python not executable: $BUNDLED_PY"; fi

# 7. Upgrade detection (informational)
INSTALL_ROOT="/opt/illumio-ops"
if [ -f "$INSTALL_ROOT/config/config.json" ]; then
    warn "Existing installation at $INSTALL_ROOT — this is an UPGRADE"
    warn "config.json and rule_schedules.json will be preserved"
else
    pass "No existing installation at $INSTALL_ROOT — fresh install"
fi

# 8. Port 5000
if ss -tlnp 2>/dev/null | grep -q ':5000 ' || netstat -tlnp 2>/dev/null | grep -q ':5000 '; then
    warn "Port 5000 is already in use — web UI may not start"
else
    pass "Port 5000: available"
fi

echo ""
echo "=============================="
if [ "$FAIL_COUNT" -gt 0 ]; then
    echo -e "${RED}PREFLIGHT FAILED: $FAIL_COUNT check(s) failed. Resolve before installing.${NC}"
    exit 1
else
    echo -e "${GRN}PREFLIGHT PASSED: Host is ready for installation.${NC}"
    exit 0
fi
