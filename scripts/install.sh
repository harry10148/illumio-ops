#!/usr/bin/env bash
# Install or uninstall the illumio_ops offline bundle.
# Run as root from the extracted bundle directory.
# Usage:
#   sudo ./install.sh                              # install / upgrade
#   sudo ./install.sh --action uninstall           # remove everything
#   sudo ./install.sh --install-root /opt/custom   # custom path
set -euo pipefail

ACTION="install"
INSTALL_ROOT="/opt/illumio_ops"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --action)       ACTION="$2";       shift 2 ;;
        --install-root) INSTALL_ROOT="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

SERVICE_NAME="illumio-ops"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# ── Uninstall ─────────────────────────────────────────────────────────────────
if [ "$ACTION" = "uninstall" ]; then
    echo "==> Stopping and disabling service"
    systemctl stop    "$SERVICE_NAME" 2>/dev/null || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload
    echo "==> Removing $INSTALL_ROOT"
    [[ -n "$INSTALL_ROOT" && "$INSTALL_ROOT" != "/" ]] || \
        { echo "ERROR: Refusing to remove dangerous path: '$INSTALL_ROOT'"; exit 1; }
    rm -rf "$INSTALL_ROOT"
    if id illumio_ops &>/dev/null; then
        userdel illumio_ops
        echo "==> User illumio_ops removed"
    fi
    echo "==> Uninstall complete."
    exit 0
fi

# ── Install / Upgrade ─────────────────────────────────────────────────────────
SRC="$(cd "$(dirname "$0")" && pwd)"
IS_UPGRADE=false
[ -f "$INSTALL_ROOT/config/config.json" ] && IS_UPGRADE=true

echo "==> Installing to $INSTALL_ROOT (upgrade=$IS_UPGRADE)"
mkdir -p "$INSTALL_ROOT"

rsync -a "$SRC/python/" "$INSTALL_ROOT/python/"

# Preserve operator-owned files on upgrade
rsync -a \
    --exclude='config/config.json' \
    --exclude='config/rule_schedules.json' \
    "$SRC/app/" "$INSTALL_ROOT/"

if [ "$IS_UPGRADE" = false ]; then
    cp "$INSTALL_ROOT/config/config.json.example" "$INSTALL_ROOT/config/config.json"
fi

"$INSTALL_ROOT/python/bin/python3" -m pip install \
    --no-index --find-links "$SRC/wheels" \
    -r "$INSTALL_ROOT/requirements-offline.txt" --quiet

if ! id illumio_ops &>/dev/null; then
    useradd --system --no-create-home --shell /sbin/nologin illumio_ops
fi
cp "$SRC/uninstall.sh" "$INSTALL_ROOT/uninstall.sh"
chmod +x "$INSTALL_ROOT/uninstall.sh"
chown -R illumio_ops:illumio_ops "$INSTALL_ROOT"

sed "s|/opt/illumio_ops|$INSTALL_ROOT|g" "$SRC/deploy/illumio-ops.service" > "$SERVICE_FILE"
chmod 0644 "$SERVICE_FILE"
systemctl daemon-reload

if [ "$IS_UPGRADE" = true ]; then
    echo "==> Upgrade complete. Run: sudo systemctl restart $SERVICE_NAME"
else
    echo "==> Installation complete."
    echo "    Edit config : nano $INSTALL_ROOT/config/config.json"
    echo "    Start service: sudo systemctl enable --now $SERVICE_NAME"
    echo "    Uninstall    : sudo $INSTALL_ROOT/uninstall.sh"
fi
