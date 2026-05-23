#!/usr/bin/env bash
# Setup illumio_ops from a git clone (venv + pip + systemd service).
# Run as root from the repository root.
# Usage:
#   sudo bash scripts/setup.sh                          # install
#   sudo bash scripts/setup.sh --action uninstall       # remove service (keeps repo)
set -euo pipefail

ACTION="install"
INTERVAL=10
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="illumio-ops"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --action)   ACTION="$2";   shift 2 ;;
        --interval) INTERVAL="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [ "$ACTION" = "uninstall" ]; then
    echo "==> Stopping and disabling service"
    systemctl stop  "$SERVICE_NAME" 2>/dev/null || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload
    echo "==> Service removed. The git clone directory was NOT deleted."
    echo "    To fully remove, delete the repository directory manually."
    exit 0
fi

# ── Install ───────────────────────────────────────────────────────────────────
echo "==> Creating virtualenv"
python3 -m venv "$REPO_ROOT/venv"

echo "==> Installing Python packages"
"$REPO_ROOT/venv/bin/pip" install --require-hashes -r "$REPO_ROOT/requirements.lock" --quiet

# First run: initialise config
if [ ! -f "$REPO_ROOT/config/config.json" ]; then
    cp "$REPO_ROOT/config/config.json.example" "$REPO_ROOT/config/config.json"
    echo "==> config/config.json created. Fill in your PCE credentials before starting."
fi

VENV_PYTHON="$REPO_ROOT/venv/bin/python3"
SVC_USER="${SUDO_USER:-$(whoami)}"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Illumio PCE Ops
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SVC_USER
WorkingDirectory=$REPO_ROOT
ExecStart=$VENV_PYTHON $REPO_ROOT/illumio-ops.py --monitor --interval $INTERVAL
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=illumio-ops
# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$REPO_ROOT

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
echo "==> Setup complete."
echo "    Edit config : nano $REPO_ROOT/config/config.json"
echo "    Start service: sudo systemctl start $SERVICE_NAME"
