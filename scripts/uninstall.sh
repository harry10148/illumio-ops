#!/usr/bin/env bash
# Uninstall illumio_ops from this machine.
# Run as root:
#   sudo /opt/illumio_ops/uninstall.sh           # preserve config (default)
#   sudo /opt/illumio_ops/uninstall.sh --purge   # remove everything including config
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
PURGE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install-root) INSTALL_ROOT="$2"; shift 2 ;;
        --purge)        PURGE=true;        shift   ;;
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

if [ "$PURGE" = true ]; then
    echo "==> Removing $INSTALL_ROOT (--purge: config will be deleted)"
    rm -rf "$INSTALL_ROOT"
else
    echo "==> Removing $INSTALL_ROOT (preserving config/)"
    find "$INSTALL_ROOT" -mindepth 1 -maxdepth 1 ! -name 'config' -exec rm -rf {} +
    echo "    Config preserved at: $INSTALL_ROOT/config/"
    echo "    To fully remove:     sudo rm -rf $INSTALL_ROOT"
fi

if id illumio_ops &>/dev/null; then
    userdel illumio_ops
    echo "==> User illumio_ops removed"
fi

echo "==> Uninstall complete."
