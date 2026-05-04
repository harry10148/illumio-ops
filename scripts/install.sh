#!/usr/bin/env bash
# Install or upgrade the illumio_ops offline bundle.
# Run as root from the extracted bundle directory.
# Usage:
#   sudo ./install.sh                              # install / upgrade
#   sudo ./install.sh --install-root /opt/custom   # custom path
set -euo pipefail

INSTALL_ROOT="/opt/illumio-ops"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --install-root) INSTALL_ROOT="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

SERVICE_NAME="illumio-ops"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SRC="$(cd "$(dirname "$0")" && pwd)"

migrate_from_underscore_root() {
    # All identifiers below are env-var overridable so tests/test_install_migration.sh
    # can exercise the function without touching real system users or paths.
    # Defaults reproduce the original production behavior byte-for-byte.
    local OLD_ROOT="${OLD_ROOT:-/opt/illumio_ops}"
    local NEW_ROOT="${NEW_ROOT:-/opt/illumio-ops}"
    local OLD_USER="${OLD_USER:-illumio_ops}"
    local NEW_USER="${NEW_USER:-illumio-ops}"
    local MIGRATE_SERVICE_NAME="${MIGRATE_SERVICE_NAME:-illumio-ops}"
    # NOTE: USERMOD_CMD/GROUPMOD_CMD are invoked unquoted to allow the default
    # "usermod -l" / "groupmod -n" to word-split into command + flag. Do not
    # override with a value whose path contains whitespace.
    local USERMOD_CMD="${USERMOD_CMD:-usermod -l}"
    local GROUPMOD_CMD="${GROUPMOD_CMD:-groupmod -n}"

    # Fix 5 (M1): root check must be first — all mutation steps require root.
    # Skip the EUID check only when both OLD_ROOT and NEW_ROOT are overridden
    # (test mode). Production never sets these env vars and so always trips the
    # check. A partial override (one default, one custom) still requires root —
    # that prevents accidental privilege bypass when an operator points the
    # installer at a custom path.
    if [[ "$OLD_ROOT" == "/opt/illumio_ops" || "$NEW_ROOT" == "/opt/illumio-ops" ]]; then
        if [[ $EUID -ne 0 ]]; then
            echo "ERROR: migration requires root (run install.sh with sudo)." >&2
            exit 1
        fi
    fi

    # Only migrate when old exists and new doesn't (and we haven't migrated already)
    if [[ ! -d "$OLD_ROOT" ]]; then return 0; fi
    if [[ -d "$NEW_ROOT" && -f "$NEW_ROOT/MIGRATED_FROM" ]]; then return 0; fi
    if [[ -d "$NEW_ROOT" ]]; then
        echo "ERROR: Both $OLD_ROOT and $NEW_ROOT exist. Manual cleanup required." >&2
        exit 1
    fi

    echo "==> Migrating $OLD_ROOT → $NEW_ROOT"

    # Pre-flight: cross-filesystem check
    if [[ "$(stat -c %d "$OLD_ROOT")" != "$(stat -c %d "$(dirname "$NEW_ROOT")")" ]]; then
        echo "ERROR: $OLD_ROOT and $NEW_ROOT parent are on different filesystems." >&2
        echo "       Run 'rsync -aHAX $OLD_ROOT/ $NEW_ROOT/ && rm -rf $OLD_ROOT' manually." >&2
        exit 1
    fi

    # Fix 1 (C1): detect partial-migration (usermod completed, mv did not).
    if id "$NEW_USER" &>/dev/null; then
        if [[ -d "$OLD_ROOT" ]]; then
            # Partial migration: usermod succeeded, but mv hasn't completed.
            # We can't safely auto-resume because we don't know which step failed.
            echo "ERROR: Partial migration detected: user '$NEW_USER' exists but $OLD_ROOT also still exists." >&2
            echo "       The previous install.sh run was interrupted between user rename and directory move." >&2
            echo "       Resume manually:" >&2
            echo "         groupmod -n $NEW_USER $OLD_USER 2>/dev/null || true   # safe if already renamed" >&2
            echo "         mv $OLD_ROOT $NEW_ROOT" >&2
            echo "         echo $OLD_ROOT > $NEW_ROOT/MIGRATED_FROM" >&2
            echo "         chown $NEW_USER:$NEW_USER $NEW_ROOT/MIGRATED_FROM" >&2
            echo "       Then re-run install.sh." >&2
        else
            echo "ERROR: User '$NEW_USER' already exists; cannot rename $OLD_USER." >&2
        fi
        exit 1
    fi

    # Fix 4 (I3): if OLD_ROOT exists but illumio_ops user has been manually deleted,
    # usermod -l would fail cryptically — detect and surface it now.
    if ! id "$OLD_USER" &>/dev/null; then
        echo "ERROR: Directory $OLD_ROOT exists but user '$OLD_USER' does not." >&2
        echo "       Manual cleanup required: rename or remove $OLD_ROOT, then re-run." >&2
        exit 1
    fi

    # Fix 2 (I1): stop service only if running; fail loudly if stop fails.
    if systemctl is-active --quiet "$MIGRATE_SERVICE_NAME" 2>/dev/null; then
        systemctl stop "$MIGRATE_SERVICE_NAME" || {
            echo "ERROR: Failed to stop $MIGRATE_SERVICE_NAME service; cannot rename user while it has running processes." >&2
            echo "       Diagnose: systemctl status $MIGRATE_SERVICE_NAME" >&2
            exit 1
        }
    fi

    $USERMOD_CMD "$NEW_USER" "$OLD_USER" || { echo "FAIL: usermod"; exit 1; }
    $GROUPMOD_CMD "$NEW_USER" "$OLD_USER" || { echo "FAIL: groupmod"; $USERMOD_CMD "$OLD_USER" "$NEW_USER"; exit 1; }
    mv "$OLD_ROOT" "$NEW_ROOT" || {
        echo "FAIL: mv — rolling back user/group rename"
        $USERMOD_CMD "$OLD_USER" "$NEW_USER"
        $GROUPMOD_CMD "$OLD_USER" "$NEW_USER"
        exit 1
    }
    echo "$OLD_ROOT" > "$NEW_ROOT/MIGRATED_FROM"
    chown "$NEW_USER:$NEW_USER" "$NEW_ROOT/MIGRATED_FROM"

    # Fix 3 (I2): warn operator that service is left stopped.
    echo "==> Migration complete; $NEW_ROOT/MIGRATED_FROM records source path."
    echo "    NOTE: service was stopped for migration. The rest of install.sh will"
    echo "    finish the upgrade flow; restart with 'sudo systemctl start illumio-ops' afterwards."
}

# Run migration only for the default install root (custom paths bypass migration).
if [[ "$INSTALL_ROOT" == "/opt/illumio-ops" ]]; then
    migrate_from_underscore_root
fi

IS_UPGRADE=false
[ -f "$INSTALL_ROOT/config/config.json" ] && IS_UPGRADE=true

echo "==> Installing to $INSTALL_ROOT (upgrade=$IS_UPGRADE)"
mkdir -p "$INSTALL_ROOT"

rsync -a "$SRC/python/" "$INSTALL_ROOT/python/"

if [ "$IS_UPGRADE" = true ]; then
    # Preserve all of config/ on upgrade — never overwrite operator-owned files
    rsync -a --exclude='config/' "$SRC/app/" "$INSTALL_ROOT/"
    # Only update *.example templates so operators can diff for new config keys
    rsync -a --include='*.example' --exclude='*' \
        "$SRC/app/config/" "$INSTALL_ROOT/config/" 2>/dev/null || true
else
    rsync -a "$SRC/app/" "$INSTALL_ROOT/"
    cp "$INSTALL_ROOT/config/config.json.example" "$INSTALL_ROOT/config/config.json"
fi

"$INSTALL_ROOT/python/bin/python3" -m pip install \
    --no-index --find-links "$SRC/wheels" \
    -r "$INSTALL_ROOT/requirements-offline.txt" --quiet

if ! id illumio-ops &>/dev/null; then
    useradd --system --no-create-home --shell /sbin/nologin illumio-ops
fi
cp "$SRC/uninstall.sh" "$INSTALL_ROOT/uninstall.sh"
chmod +x "$INSTALL_ROOT/uninstall.sh"
chown -R illumio-ops:illumio-ops "$INSTALL_ROOT"
chmod 600 "$INSTALL_ROOT/config/config.json" 2>/dev/null || true
chmod 600 "$INSTALL_ROOT/config/alerts.json" 2>/dev/null || true

sed "s|/opt/illumio-ops|$INSTALL_ROOT|g" "$SRC/deploy/illumio-ops.service" > "$SERVICE_FILE"
chmod 0644 "$SERVICE_FILE"
systemctl daemon-reload

if [ "$IS_UPGRADE" = true ]; then
    echo "==> Upgrade complete."
    echo "    Check for new config keys: diff $INSTALL_ROOT/config/config.json.example $INSTALL_ROOT/config/config.json"
    echo "    Restart service          : sudo systemctl restart $SERVICE_NAME"
else
    echo "==> Installation complete."
    echo "    Edit config : nano $INSTALL_ROOT/config/config.json"
    echo "    Start service: sudo systemctl enable --now $SERVICE_NAME"
    echo "    Uninstall    : sudo $INSTALL_ROOT/uninstall.sh"
    echo "    Purge all    : sudo $INSTALL_ROOT/uninstall.sh --purge"
fi
