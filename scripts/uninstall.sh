#!/usr/bin/env bash
# Uninstall illumio_ops from this machine.
# Run as root:
#   sudo /opt/illumio_ops/uninstall.sh           # from installed location (auto-detects root)
#   sudo ./uninstall.sh                          # from bundle (defaults to /opt/illumio_ops)
#   sudo ./uninstall.sh --install-root /custom   # override install root
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# When running from inside the installed directory, illumio_ops.py is a sibling
if [[ -f "$SCRIPT_DIR/illumio_ops.py" ]]; then
    INSTALL_ROOT="$SCRIPT_DIR"
else
    INSTALL_ROOT="/opt/illumio_ops"
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install-root) INSTALL_ROOT="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

SERVICE_NAME="illumio-ops"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

[[ $EUID -eq 0 ]] || { echo "ERROR: Run as root (sudo $0)"; exit 1; }
[[ -n "$INSTALL_ROOT" && "$INSTALL_ROOT" != "/" ]] || \
    { echo "ERROR: Refusing to remove dangerous path: '$INSTALL_ROOT'"; exit 1; }

echo "==> Stopping and disabling service"
systemctl stop    "$SERVICE_NAME" 2>/dev/null || true
systemctl disable "$SERVICE_NAME" 2>/dev/null || true
rm -f "$SERVICE_FILE"
systemctl daemon-reload

echo "==> Removing $INSTALL_ROOT"
rm -rf "$INSTALL_ROOT"

if id illumio_ops &>/dev/null; then
    userdel illumio_ops
    echo "==> User illumio_ops removed"
fi

echo "==> Uninstall complete."
