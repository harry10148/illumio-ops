#!/usr/bin/env bash
# illumio-ops v6 installer: a fresh install, or an upgrade of a 5.x installation (spec §7).
#
#   ./install.sh [--prefix DIR] [--service-name NAME] [--port N] [--no-systemd] [--print-unit]
#                [--upgrade-from DIR] [--report-only] [--accept-report] [--lang en|zh_TW] [--old-service NAME]
#
# Copies the bundled Python and the illumio_ops package to the prefix, installs the locked
# wheels with hash checking, creates the settings (fresh: `python -m illumio_ops.rescue init`;
# upgrade: `python -m illumio_ops.migrate --write`; this script never writes settings itself),
# renders the systemd unit, and stops there: it does not start the service.
#   --no-systemd     copy, pip install and init as the current user only (verification runs)
#   --print-unit     print the rendered unit and exit
#   --upgrade-from   the 5.x installation to upgrade (found automatically when the prefix holds one).
#                    The migration report is shown first; the upgrade stops and disables the 5.x
#                    service, keeps its unit and wrapper, moves the 5.x directory aside only when v6
#                    takes the same directory, and leaves PREFIX/rollback.sh to go back.
#   --report-only    show the migration report and change nothing
#   --accept-report  upgrade without asking (non-interactive)
#   --old-service    the 5.x unit (default: the one whose WorkingDirectory is the 5.x directory)
set -euo pipefail

PREFIX=/opt/illumio-ops
SERVICE=illumio-ops
PORT=5001
NO_SYSTEMD=0
PRINT_UNIT=0
SERVICE_USER=illumio-ops
UPGRADE_FROM=""
REPORT_ONLY=0
ACCEPT=0
REPORT_LANG=en
OLD_SERVICE=""
BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die() { echo "install.sh: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix) PREFIX="${2:?}"; shift 2 ;;
        --service-name) SERVICE="${2:?}"; shift 2 ;;
        --port) PORT="${2:?}"; shift 2 ;;
        --no-systemd) NO_SYSTEMD=1; shift ;;
        --print-unit) PRINT_UNIT=1; shift ;;
        --upgrade-from) UPGRADE_FROM="${2:?}"; shift 2 ;;
        --report-only) REPORT_ONLY=1; shift ;;
        --accept-report) ACCEPT=1; shift ;;
        --lang) REPORT_LANG="${2:?}"; shift 2 ;;
        --old-service) OLD_SERVICE="${2:?}"; shift 2 ;;
        -h|--help) sed -n '2,23p' "$0"; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

[[ "$PREFIX" == /* ]] || die "--prefix must be an absolute path"
[[ "$SERVICE" =~ ^[A-Za-z0-9_.@-]+$ ]] || die "--service-name may only contain letters, digits, _ . @ -"
[[ "$PORT" =~ ^[0-9]+$ ]] && (( PORT >= 1 && PORT <= 65535 )) || die "--port must be 1-65535"
[[ "$REPORT_LANG" == en || "$REPORT_LANG" == zh_TW ]] || die "--lang must be en or zh_TW"
[[ -z "$OLD_SERVICE" || "$OLD_SERVICE" =~ ^[A-Za-z0-9_.@-]+$ ]] || die "--old-service may only contain letters, digits, _ . @ -"
PREFIX="${PREFIX%/}"

render_unit() {
    sed -e "s#@PREFIX@#${PREFIX}#g" -e "s#@SERVICE_NAME@#${SERVICE}#g" "$BUNDLE_DIR/illumio-ops.service.in"
}

if (( PRINT_UNIT )); then
    render_unit
    exit 0
fi

if [[ -z "$UPGRADE_FROM" && -e "$PREFIX/illumio-ops.py" ]]; then
    UPGRADE_FROM="$PREFIX"  # the prefix holds 5.x: this is an upgrade
fi
if [[ -n "$UPGRADE_FROM" ]]; then
    [[ "$UPGRADE_FROM" == /* ]] || die "--upgrade-from must be an absolute path"
    UPGRADE_FROM="${UPGRADE_FROM%/}"
    [[ -f "$UPGRADE_FROM/illumio-ops.py" && -f "$UPGRADE_FROM/config/config.json" ]] \
        || die "$UPGRADE_FROM is not an illumio-ops 5.x installation (no illumio-ops.py and config/config.json)"
elif (( REPORT_ONLY || ACCEPT )); then
    die "--report-only and --accept-report are for an upgrade (--upgrade-from)"
fi
if [[ "$PREFIX" != "$UPGRADE_FROM" && ( -e "$PREFIX/illumio_ops" || -e "$PREFIX/config/settings.json" ) ]]; then
    die "$PREFIX already holds an illumio-ops v6 installation; nothing was changed"
fi
for need in python wheels illumio_ops requirements-v6.lock illumio-ops.service.in rollback.sh; do
    [[ -e "$BUNDLE_DIR/$need" ]] || die "bundle is incomplete: $need is missing next to install.sh"
done

if [[ -n "$UPGRADE_FROM" ]]; then
    # The report first, from the bundle (dependencies into a scratch directory), before anything changes.
    SITE="$(mktemp -d)"
    trap 'rm -rf "$SITE"' EXIT
    "$BUNDLE_DIR/python/bin/python3" -I -m pip install --quiet --no-index --no-warn-script-location \
        --require-hashes --find-links "$BUNDLE_DIR/wheels" --target "$SITE" -r "$BUNDLE_DIR/requirements-v6.lock"
    set +e
    (cd "$SITE" && env "PYTHONPATH=$BUNDLE_DIR:$SITE" PYTHONNOUSERSITE=1 "$BUNDLE_DIR/python/bin/python3" -P \
        -m illumio_ops.migrate --from "$UPGRADE_FROM" --report-only --lang "$REPORT_LANG")
    rc=$?
    set -e
    (( rc == 0 )) || die "the 5.x settings cannot be upgraded as they are (above); nothing was changed"
    if (( REPORT_ONLY )); then
        exit 0
    fi
    if (( ! ACCEPT )); then
        [[ -t 0 ]] || die "not a terminal: pass --accept-report to upgrade with this report; nothing was changed"
        read -r -p "Upgrade $UPGRADE_FROM to v6 in $PREFIX with this report? Type yes: " answer
        [[ "$answer" == yes ]] || die "cancelled; nothing was changed"
    fi
fi

if (( ! NO_SYSTEMD )); then
    [[ $(id -u) -eq 0 ]] || die "run as root (or use --no-systemd for a user-level verification install)"
    command -v systemctl >/dev/null || die "systemctl not found (use --no-systemd)"
    if [[ -n "$UPGRADE_FROM" && -z "$OLD_SERVICE" ]]; then
        for unit in /etc/systemd/system/*.service; do
            if grep -qx "WorkingDirectory=$UPGRADE_FROM" "$unit" 2>/dev/null; then
                OLD_SERVICE="$(basename "$unit" .service)"
                break
            fi
        done
    fi
    if [[ -e "/etc/systemd/system/${SERVICE}.service" && "$SERVICE" != "$OLD_SERVICE" ]]; then
        die "/etc/systemd/system/${SERVICE}.service already exists"
    fi
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
V5_NOW="$UPGRADE_FROM"
if [[ -n "$UPGRADE_FROM" ]]; then
    # 5.x stops before its progress is read, so what it sent and evaluated no longer moves.
    BACKUP="$(mktemp -d)"
    WRAPPER=/usr/local/bin/illumio-ops
    if (( ! NO_SYSTEMD )) && [[ -n "$OLD_SERVICE" ]]; then
        echo "==> Stopping and disabling the 5.x service $OLD_SERVICE"
        systemctl stop "$OLD_SERVICE" || true
        systemctl disable "$OLD_SERVICE" 2>/dev/null || true
        [[ -f "/etc/systemd/system/${OLD_SERVICE}.service" ]] && cp -p "/etc/systemd/system/${OLD_SERVICE}.service" "$BACKUP/old.service"
    fi
    if (( ! NO_SYSTEMD )) && [[ -e "$WRAPPER" ]]; then
        cp -p "$WRAPPER" "$BACKUP/illumio-ops.wrapper"
        rm -f "$WRAPPER"  # v6 has no command line
    fi
    if [[ "$PREFIX" == "$UPGRADE_FROM" ]]; then
        V5_NOW="${UPGRADE_FROM}.5x-${STAMP}"
        echo "==> Moving the 5.x installation aside to $V5_NOW"
        mv "$UPGRADE_FROM" "$V5_NOW"
    fi
    mkdir -p "$PREFIX/rollback"
    chmod 700 "$PREFIX/rollback"
    cp -p "$BACKUP"/* "$PREFIX/rollback/" 2>/dev/null || true
    rm -rf "$BACKUP"
    {
        printf 'PREFIX=%q\nSERVICE=%q\nOLD_SERVICE=%q\nV5_NOW=%q\nV5_ORIGINAL=%q\nNO_SYSTEMD=%q\n' \
            "$PREFIX" "$SERVICE" "$OLD_SERVICE" "$V5_NOW" "$UPGRADE_FROM" "$NO_SYSTEMD"
    } > "$PREFIX/rollback/rollback.env"
    cp "$BUNDLE_DIR/rollback.sh" "$PREFIX/rollback.sh"
    chmod 755 "$PREFIX/rollback.sh"
    echo "==> If anything below fails: $PREFIX/rollback.sh brings 5.x back"
fi

echo "==> Installing illumio-ops v6 into $PREFIX"
mkdir -p "$PREFIX"
# Copy without the archive's owner; as root, the code and the interpreter must be root's
# (the service account only writes config/data/logs/reports).
cp -R --preserve=mode,timestamps "$BUNDLE_DIR/python" "$PREFIX/python"
cp -R --preserve=mode,timestamps "$BUNDLE_DIR/illumio_ops" "$PREFIX/illumio_ops"
if (( ! NO_SYSTEMD )); then
    chown root:root "$PREFIX"
    chmod 755 "$PREFIX"
    chown -R root:root "$PREFIX/python" "$PREFIX/illumio_ops"
fi
chmod -R go-w "$PREFIX/python" "$PREFIX/illumio_ops"
cd "$PREFIX"  # a directory we own: never let python -m pick modules up from the caller's cwd

echo "==> Installing locked dependencies (hash-checked, offline)"
"$PREFIX/python/bin/python3" -I -m pip install --quiet --no-index --no-warn-script-location \
    --require-hashes --find-links "$BUNDLE_DIR/wheels" -r "$BUNDLE_DIR/requirements-v6.lock"

for d in config data logs reports; do
    mkdir -p "$PREFIX/$d"
    chmod 700 "$PREFIX/$d"
done

# -P: do not put the current directory on sys.path; the package comes from PYTHONPATH only.
PY=(env "PYTHONPATH=$PREFIX" PYTHONNOUSERSITE=1 "$PREFIX/python/bin/python3" -P)
if [[ -n "$UPGRADE_FROM" ]]; then
    # As the installing user (root): the 5.x directory may be one the service account cannot read.
    MOVED=()
    [[ "$V5_NOW" != "$UPGRADE_FROM" ]] && MOVED=(--original-root "$UPGRADE_FROM")
    echo "==> Writing the v6 settings and continuing where 5.x stopped"
    "${PY[@]}" -m illumio_ops.migrate --from "$V5_NOW" --write --root "$PREFIX" --lang "$REPORT_LANG" "${MOVED[@]}" \
        || die "the upgrade did not complete; $PREFIX/rollback.sh brings 5.x back"
    RUN=()
else
    RUN=("${PY[@]}" -m illumio_ops.rescue init --root "$PREFIX" --port "$PORT")
fi
if (( NO_SYSTEMD )); then
    (( ${#RUN[@]} )) && "${RUN[@]}"
    echo "==> Done (no systemd). Run: env PYTHONPATH=$PREFIX $PREFIX/python/bin/python3 -m illumio_ops serve --root $PREFIX"
    exit 0
fi

if ! getent passwd "$SERVICE_USER" >/dev/null; then
    useradd --system --no-create-home --shell /sbin/nologin "$SERVICE_USER"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$PREFIX/config" "$PREFIX/data" "$PREFIX/logs" "$PREFIX/reports"
(( ${#RUN[@]} )) && runuser -u "$SERVICE_USER" -- "${RUN[@]}"

render_unit > "/etc/systemd/system/${SERVICE}.service"
chmod 644 "/etc/systemd/system/${SERVICE}.service"
systemctl daemon-reload
echo "==> Installed. The service is NOT started. Start it with:"
echo "    systemctl enable --now ${SERVICE}"
echo "    then open https://<this host>:${PORT}/"
