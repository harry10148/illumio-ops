#!/usr/bin/env bash
# Install or upgrade the illumio_ops offline bundle.
# Run as root from the extracted bundle directory.
# Usage:
#   sudo ./install.sh                              # install / upgrade
#   sudo ./install.sh --install-root /opt/custom   # custom path
set -euo pipefail

INSTALL_ROOT="/opt/illumio-ops"
ALLOW_DOWNGRADE=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --install-root) INSTALL_ROOT="$2"; shift 2 ;;
        --allow-downgrade) ALLOW_DOWNGRADE=true; shift ;;
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

# --- Upgrade guards ---------------------------------------------------------
if [ "$IS_UPGRADE" = true ]; then
    # Downgrade guard: db schema migrations are forward-only (PRAGMA
    # user_version); installing an older bundle over a newer install is
    # unsupported. Compare base versions (strip +hash dev suffix).
    BUNDLE_BASE="$(cat "$SRC/VERSION" 2>/dev/null || echo unknown)"
    BUNDLE_BASE="${BUNDLE_BASE%%+*}"
    INSTALLED_VERSION=$(sed -n 's/^__version__ *= *["'"'"']\([^"'"'"']*\)["'"'"'].*/\1/p' \
        "$INSTALL_ROOT/src/__init__.py" 2>/dev/null || true)
    if [ -n "$INSTALLED_VERSION" ] && [ -n "$BUNDLE_BASE" ] && [ "$BUNDLE_BASE" != "unknown" ] \
       && [ "$BUNDLE_BASE" != "$INSTALLED_VERSION" ] \
       && [ "$(printf '%s\n%s\n' "$BUNDLE_BASE" "$INSTALLED_VERSION" | sort -V | tail -1)" = "$INSTALLED_VERSION" ]; then
        if [ "$ALLOW_DOWNGRADE" != true ]; then
            echo "ERROR: bundle version $BUNDLE_BASE is older than installed $INSTALLED_VERSION." >&2
            echo "       Downgrade is unsupported (db schema migrations are forward-only)." >&2
            echo "       Re-run with --allow-downgrade to proceed anyway." >&2
            exit 1
        fi
        echo "WARNING: downgrading $INSTALLED_VERSION -> $BUNDLE_BASE (--allow-downgrade given)."
    fi
    # Fallback downgrade guard: a non-purge uninstall deletes src/ but keeps
    # config/ + data/, so on reinstall INSTALLED_VERSION above is unreadable
    # and the version-string comparison is skipped. Detect a newer-than-bundle
    # DB directly: compare the DB's PRAGMA user_version against the highest
    # migration this bundle's schema.py knows (_MIGRATION_AGG_BUCKET_DAY).
    DB_FILE="$INSTALL_ROOT/data/pce_cache.sqlite"
    if [ -z "$INSTALLED_VERSION" ] && [ -f "$DB_FILE" ] && [ -x "$SRC/python/bin/python3" ]; then
        BUNDLE_MAX_UV=$(sed -n 's/^_MIGRATION_AGG_BUCKET_DAY = \([0-9][0-9]*\).*/\1/p' \
            "$SRC/app/src/pce_cache/schema.py" 2>/dev/null || true)
        DB_UV=$("$SRC/python/bin/python3" -c "
import sqlite3, sys
conn = sqlite3.connect(f'file:{sys.argv[1]}?mode=ro', uri=True)
print(conn.execute('PRAGMA user_version').fetchone()[0])
" "$DB_FILE" 2>/dev/null || true)
        if [ -n "$BUNDLE_MAX_UV" ] && [ -n "$DB_UV" ] && [ "$DB_UV" -gt "$BUNDLE_MAX_UV" ] 2>/dev/null; then
            if [ "$ALLOW_DOWNGRADE" != true ]; then
                echo "ERROR: existing cache DB user_version=$DB_UV is newer than this bundle understands (max $BUNDLE_MAX_UV)." >&2
                echo "       The DB was migrated by newer code; installing an older bundle over it is unsupported." >&2
                echo "       Re-run with --allow-downgrade to proceed anyway." >&2
                exit 1
            fi
            echo "WARNING: proceeding over newer cache DB (user_version=$DB_UV > max $BUNDLE_MAX_UV) (--allow-downgrade given)."
        fi
    fi
    # Service guard: upgrading files under a running service risks a torn
    # state (old process, new site-packages). Stop it; operator restarts
    # after reviewing the install output (docs already instruct this).
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        echo "==> Stopping running service for upgrade"
        systemctl stop "$SERVICE_NAME" || {
            echo "ERROR: failed to stop $SERVICE_NAME; stop it manually and re-run." >&2
            exit 1
        }
        echo "    NOTE: restart after install: sudo systemctl restart $SERVICE_NAME"
    fi
fi

echo "==> Installing to $INSTALL_ROOT (upgrade=$IS_UPGRADE)"
mkdir -p "$INSTALL_ROOT"
# Ensure all runtime dirs exist — ProtectSystem=strict requires them before service startup
mkdir -p "$INSTALL_ROOT/logs" "$INSTALL_ROOT/data" "$INSTALL_ROOT/reports" \
         "$INSTALL_ROOT/config" "$INSTALL_ROOT/config/tls"

# --delete restores a pristine bundled runtime each install/upgrade. This is
# what makes the dependency refresh deterministic: site-packages is reset to
# the bundle's baseline, then pip below installs exactly the bundled wheels.
# Without it, range specs in requirements-offline.txt let pip keep stale
# already-satisfied versions, and removed dependencies linger forever.
rsync -a --delete "$SRC/python/" "$INSTALL_ROOT/python/"

if [ "$IS_UPGRADE" = true ]; then
    # Preserve all of config/ on upgrade — never overwrite operator-owned files.
    # --delete removes app files that no longer exist in the new release:
    # renamed/deleted src modules would otherwise linger as importable zombie
    # .py files. Operator/runtime dirs are excluded from deletion.
    # Excludes are anchored (leading /) to the transfer root: unanchored
    # patterns match at any depth and would freeze app-tree dirs like
    # src/i18n/data/ out of the upgrade sync.
    rsync -a --delete \
        --exclude='/config/' --exclude='/data/' --exclude='/logs/' \
        --exclude='/reports/' --exclude='/python/' \
        --exclude='/MIGRATED_FROM' --exclude='/uninstall.sh' \
        "$SRC/app/" "$INSTALL_ROOT/"
    # Only update *.example templates so operators can diff for new config keys
    rsync -a --include='*.example' --exclude='*' \
        "$SRC/app/config/" "$INSTALL_ROOT/config/" 2>/dev/null || true
else
    rsync -a "$SRC/app/" "$INSTALL_ROOT/"
    cp "$INSTALL_ROOT/config/config.json.example" "$INSTALL_ROOT/config/config.json"
fi

# site-packages was reset by the python/ rsync above, so this installs the
# bundle's exact wheel set (deterministic; no --upgrade needed).
"$INSTALL_ROOT/python/bin/python3" -m pip install \
    --no-index --find-links "$SRC/wheels" \
    -r "$INSTALL_ROOT/requirements-offline.txt" --quiet

# Migrate deprecated config fields on upgrade
if [ "$IS_UPGRADE" = true ] && [ -f "$INSTALL_ROOT/config/config.json" ]; then
    "$INSTALL_ROOT/python/bin/python3" -c "
import json, sys
p = sys.argv[1]
try:
    with open(p) as f: cfg = json.load(f)
    changed = []
    tls = cfg.get('web_gui', {}).get('tls', {})
    if 'http_redirect_port' in tls:
        del tls['http_redirect_port']
        changed.append('web_gui.tls.http_redirect_port')
    if changed:
        with open(p, 'w') as f: json.dump(cfg, f, indent=2)
        print('    Config migration: removed deprecated field(s):', ', '.join(changed))
except Exception as e:
    print('    Config migration warning:', e, file=sys.stderr)
" "$INSTALL_ROOT/config/config.json" || true
fi

# --- Post-install verification -----------------------------------------------
echo "==> Verifying installed dependencies"
"$INSTALL_ROOT/python/bin/python3" "$INSTALL_ROOT/scripts/verify_deps.py" --offline-bundle || {
    echo "ERROR: dependency verification failed — installation is incomplete." >&2
    exit 1
}
(cd "$INSTALL_ROOT" && ./python/bin/python3 illumio-ops.py --help >/dev/null) || {
    echo "ERROR: app smoke check failed (illumio-ops.py --help)." >&2
    exit 1
}
echo "    Dependency and smoke checks passed."

if ! id illumio-ops &>/dev/null; then
    useradd --system --no-create-home --shell /sbin/nologin illumio-ops
fi
cp "$SRC/uninstall.sh" "$INSTALL_ROOT/uninstall.sh"
chmod +x "$INSTALL_ROOT/uninstall.sh"
chown -R illumio-ops:illumio-ops "$INSTALL_ROOT"
chmod 600 "$INSTALL_ROOT/config/config.json" 2>/dev/null || true
chmod 600 "$INSTALL_ROOT/config/alerts.json" 2>/dev/null || true

# Fine-grained permissions: secrets 0600, configs 0640, sensitive dirs 0750
find "$INSTALL_ROOT/config" -type f -name "*.json" -exec chmod 0600 {} \; 2>/dev/null || true
find "$INSTALL_ROOT/config" -type f -name "*.yaml" -exec chmod 0640 {} \; 2>/dev/null || true
find "$INSTALL_ROOT/config/tls" -type f -name "*key*.pem" -exec chmod 0600 {} \; 2>/dev/null || true
find "$INSTALL_ROOT/config/tls" -type f -name "*.pem" ! -name "*key*" -exec chmod 0640 {} \; 2>/dev/null || true
chmod 0750 "$INSTALL_ROOT/logs" "$INSTALL_ROOT/config" 2>/dev/null || true

sed "s|/opt/illumio-ops|$INSTALL_ROOT|g" "$SRC/deploy/illumio-ops.service" > "$SERVICE_FILE"
chmod 0644 "$SERVICE_FILE"
systemctl daemon-reload

# CLI wrapper: give operators a stable `illumio-ops` command that always uses
# the bundled Python. Running the app with the system python3 breaks on old
# distros (system SQLite < 3.35 lacks INSERT ... RETURNING).
WRAPPER=/usr/local/bin/illumio-ops
cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash
# cd first: relative paths from config (data/, logs/, reports/) resolve
# against the process cwd, not the app root.
cd "$INSTALL_ROOT" || exit 1
exec "$INSTALL_ROOT/python/bin/python3" "$INSTALL_ROOT/illumio-ops.py" "\$@"
EOF
chmod 0755 "$WRAPPER"

if [ "$IS_UPGRADE" = true ]; then
    echo "==> Upgrade complete."
    echo "    Check for new config keys: diff $INSTALL_ROOT/config/config.json.example $INSTALL_ROOT/config/config.json"
    echo "    Restart service          : sudo systemctl restart $SERVICE_NAME"
    echo "    CLI usage    : illumio-ops --help   (wrapper installed at /usr/local/bin/illumio-ops)"
else
    echo "==> Installation complete."
    echo "    Edit config : nano $INSTALL_ROOT/config/config.json"
    echo "    Start service: sudo systemctl enable --now $SERVICE_NAME"
    echo "    CLI usage    : illumio-ops --help   (wrapper installed at /usr/local/bin/illumio-ops)"
    echo "    Uninstall    : sudo $INSTALL_ROOT/uninstall.sh"
    echo "    Purge all    : sudo $INSTALL_ROOT/uninstall.sh --purge"
fi
