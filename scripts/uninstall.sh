#!/usr/bin/env bash
# Uninstall illumio_ops from this machine.
# Run as root:
#   sudo /opt/illumio-ops/uninstall.sh           # preserve config (default)
#   sudo /opt/illumio-ops/uninstall.sh --purge   # remove everything including config
#   sudo ./uninstall.sh                          # from bundle (defaults to /opt/illumio-ops)
#   sudo ./uninstall.sh --install-root /custom   # override install root
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# When running from inside the installed directory, illumio-ops.py is a sibling
if [[ -f "$SCRIPT_DIR/illumio-ops.py" ]]; then
    INSTALL_ROOT="$SCRIPT_DIR"
else
    INSTALL_ROOT="/opt/illumio-ops"
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
rm -f /usr/local/bin/illumio-ops
systemctl daemon-reload

if [ "$PURGE" = true ]; then
    echo "==> Removing $INSTALL_ROOT (--purge: config and data (cache DB) will be deleted)"
    rm -rf "$INSTALL_ROOT"
else
    echo "==> Removing $INSTALL_ROOT (preserving config/ and data/)"
    find "$INSTALL_ROOT" -mindepth 1 -maxdepth 1 ! -name 'config' ! -name 'data' -exec rm -rf {} +
    # The illumio-ops account is deleted below, which would leave these files
    # owned by an unallocated UID/GID. useradd --system reuses freed IDs, so the
    # next system daemon packaged on this host could inherit the UID and read
    # config.json (PCE api key/secret, SMTP password, LINE/Telegram tokens,
    # web_gui.secret_key) and config/tls/*key*.pem. Re-home the survivors to
    # root and take the group bit off the directories before that can happen.
    chown -R root:root "$INSTALL_ROOT/config" "$INSTALL_ROOT/data" 2>/dev/null || true
    chmod 0700 "$INSTALL_ROOT/config" "$INSTALL_ROOT/data" 2>/dev/null || true
    echo "    Config preserved at: $INSTALL_ROOT/config/  (now root-owned, mode 0700)"
    echo "    Data preserved at:   $INSTALL_ROOT/data/  (cache DB; reinstall picks it up)"
    echo "    To fully remove:     sudo rm -rf $INSTALL_ROOT"
fi

if id illumio-ops &>/dev/null; then
    userdel illumio-ops
    echo "==> User illumio-ops removed"
fi

echo "==> Uninstall complete."
