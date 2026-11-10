#!/usr/bin/env bash
# illumio-ops v6 installer: a fresh install, an upgrade of a 5.x installation (spec §7), or of an installed v6.
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
#   --report-only    show the migration report (or, over v6, the upgrade plan) and change nothing
#   --accept-report  upgrade without asking (non-interactive)
#
# When the prefix already holds v6, this bundle's version replaces the installed one in place: settings, data,
# reports, logs and certificates stay. An older bundle is refused over a newer installation, and so are settings or
# databases this version would not start with. The service is stopped for the swap and started again if it was
# running. The replaced version is kept in PREFIX/previous (with a copy of each database this version migrates at
# its first start) and PREFIX/restore-previous.sh puts it back.
#   --old-service    the 5.x unit (default: the one whose WorkingDirectory is the 5.x directory)
set -euo pipefail

PREFIX=/opt/illumio-ops
SERVICE=illumio-ops
PORT=5001
PORT_GIVEN=0
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
        --port) PORT="${2:?}"; PORT_GIVEN=1; shift 2 ;;
        --no-systemd) NO_SYSTEMD=1; shift ;;
        --print-unit) PRINT_UNIT=1; shift ;;
        --upgrade-from) UPGRADE_FROM="${2:?}"; shift 2 ;;
        --report-only) REPORT_ONLY=1; shift ;;
        --accept-report) ACCEPT=1; shift ;;
        --lang) REPORT_LANG="${2:?}"; shift 2 ;;
        --old-service) OLD_SERVICE="${2:?}"; shift 2 ;;
        -h|--help) sed -n '2,29p' "$0"; exit 0 ;;
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
V6_UPGRADE=0
KEPT=0
if [[ -z "$UPGRADE_FROM" && -f "$PREFIX/config/settings.json" && ! -e "$PREFIX/illumio_ops" ]]; then
    KEPT=1  # the settings and data uninstall.sh kept: a fresh install of the program that uses them
elif [[ -z "$UPGRADE_FROM" && ( -e "$PREFIX/illumio_ops" || -e "$PREFIX/config/settings.json" ) ]]; then
    [[ -f "$PREFIX/illumio_ops/__init__.py" && -f "$PREFIX/config/settings.json" ]] \
        || die "$PREFIX holds only part of a v6 installation (illumio_ops/ and config/settings.json go together): not a complete installation; nothing was changed"
    V6_UPGRADE=1  # the prefix holds v6: this bundle's version replaces it
fi
if [[ -n "$UPGRADE_FROM" ]]; then
    [[ "$UPGRADE_FROM" == /* ]] || die "--upgrade-from must be an absolute path"
    UPGRADE_FROM="${UPGRADE_FROM%/}"
    [[ -f "$UPGRADE_FROM/illumio-ops.py" && -f "$UPGRADE_FROM/config/config.json" ]] \
        || die "$UPGRADE_FROM is not an illumio-ops 5.x installation (no illumio-ops.py and config/config.json)"
elif (( ! V6_UPGRADE && ! KEPT && (REPORT_ONLY || ACCEPT) )); then
    die "--report-only and --accept-report are for an upgrade (--upgrade-from, or a prefix that holds v6)"
fi
if [[ -n "$UPGRADE_FROM" && "$PREFIX" != "$UPGRADE_FROM" && ( -e "$PREFIX/illumio_ops" || -e "$PREFIX/config/settings.json" ) ]]; then
    die "$PREFIX already holds an illumio-ops v6 installation; nothing was changed"
fi
# The address to open, with the port the settings in PREFIX hold: settings that were already there keep theirs,
# whatever --port said.
say_url() {
    local port
    port="$("$PREFIX/python/bin/python3" -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["web"]["port"])' \
        "$PREFIX/config/settings.json" 2>/dev/null)" || port=""
    if [[ -z "$port" ]]; then
        echo "    then open https://<this host>:<the port in $PREFIX/config/settings.json>/"
        return 0
    fi
    echo "    then open https://<this host>:${port}/"
    if (( PORT_GIVEN )) && [[ "$port" != "$PORT" ]]; then
        echo "    (--port $PORT was not applied: the settings in $PREFIX were already there and keep port $port)"
    fi
}

for need in python wheels illumio_ops requirements.lock illumio-ops.service.in rollback.sh restore-previous.sh uninstall.sh; do
    [[ -e "$BUNDLE_DIR/$need" ]] || die "bundle is incomplete: $need is missing next to install.sh"
done

SITE=""
# The bundle's program, its dependencies in a scratch directory: it reads the installation before anything changes.
bundle_program() {
    if [[ -z "$SITE" ]]; then
        SITE="$(mktemp -d)"
        trap 'rm -rf "$SITE"' EXIT
        "$BUNDLE_DIR/python/bin/python3" -I -m pip install --quiet --no-index --no-warn-script-location --root-user-action=ignore \
            --require-hashes --find-links "$BUNDLE_DIR/wheels" --target "$SITE" -r "$BUNDLE_DIR/requirements.lock"
    fi
    (cd "$SITE" && env "PYTHONPATH=$BUNDLE_DIR:$SITE" PYTHONNOUSERSITE=1 "$BUNDLE_DIR/python/bin/python3" -P "$@")
}

# Copy without the archive's owner; as root, the code and the interpreter must be root's
# (the service account only writes config/data/logs/reports).
install_program() {
    mkdir -p "$PREFIX"
    cp -R --preserve=mode,timestamps "$BUNDLE_DIR/python" "$PREFIX/python"
    cp -R --preserve=mode,timestamps "$BUNDLE_DIR/illumio_ops" "$PREFIX/illumio_ops"
    if (( ! NO_SYSTEMD )); then
        chown root:root "$PREFIX"
        chmod 755 "$PREFIX"
        chown -R root:root "$PREFIX/python" "$PREFIX/illumio_ops"
    fi
    chmod -R go-w "$PREFIX/python" "$PREFIX/illumio_ops"
    cp "$BUNDLE_DIR/uninstall.sh" "$PREFIX/uninstall.sh" && chmod 755 "$PREFIX/uninstall.sh"
    cd "$PREFIX"  # a directory we own: never let python -m pick modules up from the caller's cwd
    echo "==> Installing locked dependencies (hash-checked, offline)"
    "$PREFIX/python/bin/python3" -I -m pip install --quiet --no-index --no-warn-script-location --root-user-action=ignore \
        --require-hashes --find-links "$BUNDLE_DIR/wheels" -r "$BUNDLE_DIR/requirements.lock"
}

if (( KEPT )); then
    # The kept settings and databases must be ones this version starts with (not written by a newer one).
    bundle_program -m illumio_ops.migrate.v6 --root "$PREFIX" \
        || die "the settings and data kept in $PREFIX cannot be used by this bundle (above); nothing was changed"
    (( REPORT_ONLY )) && exit 0
fi
if (( V6_UPGRADE )); then
    PLAN="$(mktemp)"
    set +e
    bundle_program -m illumio_ops.migrate.v6 --root "$PREFIX" --env "$PLAN"
    rc=$?
    set -e
    if (( rc != 0 )); then
        rm -f "$PLAN"
        die "$PREFIX cannot be upgraded with this bundle (above)"
    fi
    OLD_VERSION="" NEW_VERSION="" APP_PENDING=0 FLOW_PENDING=0
    # shellcheck source=/dev/null
    source "$PLAN"  # OLD_VERSION NEW_VERSION APP_PENDING FLOW_PENDING, %q-quoted by the program
    rm -f "$PLAN"
    (( REPORT_ONLY )) && exit 0
    if (( ! ACCEPT )); then
        [[ -t 0 ]] || die "not a terminal: pass --accept-report to upgrade with this plan; nothing was changed"
        read -r -p "Upgrade $PREFIX from $OLD_VERSION to $NEW_VERSION? Type yes: " answer
        [[ "$answer" == yes ]] || die "cancelled; nothing was changed"
    fi

    DATA="$PREFIX/data"
    PREV="$PREFIX/previous"
    COPIES=()  # the databases this version migrates at its first start: the previous version could not open them
    (( APP_PENDING > 0 )) && [[ -f "$DATA/app.sqlite" ]] && COPIES+=(app.sqlite)
    (( FLOW_PENDING > 0 )) && [[ -f "$DATA/flows.sqlite" ]] && COPIES+=(flows.sqlite)
    if (( ${#COPIES[@]} )); then
        need=0
        for f in "${COPIES[@]}"; do
            need=$(( need + $(du -cb "$DATA/$f"* | tail -1 | cut -f1) ))
        done
        avail=$(df --output=avail -B1 "$DATA" | tail -1 | tr -d ' ')
        (( avail > need + need / 10 )) || die "the copies of ${COPIES[*]} need $(( need / 1048576 )) MB in $DATA and $(( avail / 1048576 )) MB are free; nothing was changed"
    fi
    WAS_ACTIVE=0
    if (( ! NO_SYSTEMD )); then
        [[ $(id -u) -eq 0 ]] || die "run as root (or use --no-systemd for a user-level installation)"
        command -v systemctl >/dev/null || die "systemctl not found (use --no-systemd)"
        UNIT="/etc/systemd/system/${SERVICE}.service"
        if ! grep -qF -- "-m illumio_ops serve --root $PREFIX" "$UNIT" 2>/dev/null; then
            UNIT=""
            for u in /etc/systemd/system/*.service; do
                if [[ -f "$u" ]] && grep -qF -- "-m illumio_ops serve --root $PREFIX" "$u"; then
                    UNIT="$u"
                    break
                fi
            done
            [[ -n "$UNIT" ]] || die "no systemd unit in /etc/systemd/system runs $PREFIX: pass --service-name NAME; nothing was changed"
            SERVICE="$(basename "$UNIT" .service)"
        fi
        if systemctl is-active --quiet "$SERVICE"; then
            WAS_ACTIVE=1
        fi
        echo "==> Stopping $SERVICE"
        systemctl stop "$SERVICE" || die "could not stop $SERVICE; nothing else was changed"
        if systemctl is-active --quiet "$SERVICE"; then
            die "$SERVICE is still running; nothing else was changed"
        fi
    fi
    BACK="$OLD_VERSION is stopped and unchanged in $PREFIX"
    (( WAS_ACTIVE )) && BACK="$BACK; to start it again: systemctl start $SERVICE"
    echo "==> Keeping $OLD_VERSION in $PREV"
    rm -rf "$PREV"  # one previous version is kept: the one this upgrade replaces
    mkdir -p "$PREV/data" && chmod 700 "$PREV" || die "could not make $PREV; $BACK"
    # config/ and data/ belong to the service account: only regular files are copied, never a link planted there.
    [[ -f "$PREFIX/config/settings.json" && ! -L "$PREFIX/config/settings.json" ]] \
        || die "$PREFIX/config/settings.json is not a regular file; $BACK"
    cp -p "$PREFIX/config/settings.json" "$PREV/settings.json" || die "could not copy the settings to $PREV; $BACK"
    for f in "${COPIES[@]}"; do
        for g in "$DATA/$f" "$DATA/$f-wal" "$DATA/$f-shm"; do
            [[ -L "$g" ]] && die "$g is a symbolic link; $BACK"
            if [[ -f "$g" ]]; then
                cp -p "$g" "$PREV/data/" || die "could not copy $g to $PREV; $BACK"
            fi
        done
    done
    printf 'PREFIX=%q\nSERVICE=%q\nNO_SYSTEMD=%q\nOLD_VERSION=%q\nNEW_VERSION=%q\nCOPIES=%q\n' \
        "$PREFIX" "$SERVICE" "$NO_SYSTEMD" "$OLD_VERSION" "$NEW_VERSION" "${COPIES[*]}" > "$PREV/previous.env"
    cp "$BUNDLE_DIR/restore-previous.sh" "$PREFIX/restore-previous.sh" && chmod 755 "$PREFIX/restore-previous.sh" \
        || die "could not write $PREFIX/restore-previous.sh; $BACK"
    mv "$PREFIX/illumio_ops" "$PREV/illumio_ops" && mv "$PREFIX/python" "$PREV/python" \
        || die "could not move $OLD_VERSION into $PREV; $PREFIX/restore-previous.sh puts it back"
    echo "==> If anything below fails: $PREFIX/restore-previous.sh brings $OLD_VERSION back"

    echo "==> Installing illumio-ops $NEW_VERSION into $PREFIX"
    install_program
    if (( NO_SYSTEMD )); then
        echo "==> Upgraded to $NEW_VERSION (no systemd)."
        say_url
        exit 0
    fi
    render_unit > "$UNIT"  # the unit of this version (its directives may have changed)
    chmod 644 "$UNIT"
    systemctl daemon-reload
    if (( ! WAS_ACTIVE )); then
        echo "==> Upgraded to $NEW_VERSION. The service was not running and is NOT started: systemctl start $SERVICE"
        exit 0
    fi
    echo "==> Starting $SERVICE"
    systemctl start "$SERVICE" || die "$SERVICE did not start; journalctl -u $SERVICE says why, and $PREFIX/restore-previous.sh brings $OLD_VERSION back"
    sleep 5
    systemctl is-active --quiet "$SERVICE" \
        || die "$SERVICE stopped after starting; journalctl -u $SERVICE says why, and $PREFIX/restore-previous.sh brings $OLD_VERSION back"
    echo "==> Upgraded to $NEW_VERSION and running. $OLD_VERSION is kept in $PREV until the next upgrade."
    exit 0
fi
if [[ -n "$UPGRADE_FROM" ]]; then
    # The report first, from the bundle, before anything changes.
    set +e
    bundle_program -m illumio_ops.migrate --from "$UPGRADE_FROM" --report-only --lang "$REPORT_LANG"
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
        # The 5.x unit: the one running the 5.x directory, wherever systemd keeps it.
        for unit in /etc/systemd/system/*.service /usr/lib/systemd/system/*.service /lib/systemd/system/*.service; do
            if [[ -f "$unit" ]] && grep -qx "WorkingDirectory=$UPGRADE_FROM" "$unit"; then
                OLD_SERVICE="$(basename "$unit" .service)"
                break
            fi
        done
        if [[ -z "$OLD_SERVICE" ]] && systemctl cat illumio-ops 2>/dev/null | grep -qF "$UPGRADE_FROM"; then
            OLD_SERVICE=illumio-ops
        fi
        [[ -n "$OLD_SERVICE" ]] || die "no systemd unit runs $UPGRADE_FROM: pass --old-service NAME, or --old-service none when 5.x does not run as a service; nothing was changed"
    fi
    [[ "$OLD_SERVICE" == none ]] && OLD_SERVICE=""
    if [[ -e "/etc/systemd/system/${SERVICE}.service" && "$SERVICE" != "$OLD_SERVICE" ]]; then
        die "/etc/systemd/system/${SERVICE}.service already exists"
    fi
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
V5_NOW="$UPGRADE_FROM"
OLD_UNIT=""
if [[ -n "$UPGRADE_FROM" ]]; then
    # Back up first, before anything changes: a backup that could not be made stops the upgrade here.
    BACKUP="$(mktemp -d)"
    WRAPPER=/usr/local/bin/illumio-ops
    if (( ! NO_SYSTEMD )) && [[ -n "$OLD_SERVICE" ]]; then
        OLD_UNIT="$(systemctl show -p FragmentPath --value "$OLD_SERVICE")"
        [[ -f "$OLD_UNIT" ]] || die "cannot find the unit file of $OLD_SERVICE; nothing was changed"
        cp -p "$OLD_UNIT" "$BACKUP/old.service" || die "could not back up $OLD_UNIT; nothing was changed"
    fi
    # The 5.x command wrapper, only when it is this installation's (it runs "$UPGRADE_FROM/illumio-ops.py").
    TAKE_WRAPPER=0
    if (( ! NO_SYSTEMD )) && [[ -f "$WRAPPER" ]] && grep -qF "$UPGRADE_FROM/illumio-ops.py" "$WRAPPER"; then
        cp -p "$WRAPPER" "$BACKUP/illumio-ops.wrapper" || die "could not back up $WRAPPER; nothing was changed"
        TAKE_WRAPPER=1
    fi
    # 5.x stops before its progress is read, so what it sent and evaluated no longer moves; a stop that did not
    # take ends the upgrade (5.x writing on while its directory moves would corrupt both).
    if (( ! NO_SYSTEMD )) && [[ -n "$OLD_SERVICE" ]]; then
        echo "==> Stopping and disabling the 5.x service $OLD_SERVICE"
        systemctl stop "$OLD_SERVICE" || die "could not stop $OLD_SERVICE; nothing else was changed"
        if systemctl is-active --quiet "$OLD_SERVICE"; then
            die "$OLD_SERVICE is still running; nothing else was changed"
        fi
        systemctl disable "$OLD_SERVICE" 2>/dev/null || echo "    (could not disable $OLD_SERVICE; rollback.sh enables it again anyway)"
    fi
    (( TAKE_WRAPPER )) && rm -f "$WRAPPER"  # v6 has no command line
    BACK="5.x is stopped; to start it again: systemctl enable --now ${OLD_SERVICE:-<its service>}"
    if [[ "$PREFIX" == "$UPGRADE_FROM" ]]; then
        V5_NOW="${UPGRADE_FROM}.5x-${STAMP}"
        echo "==> Moving the 5.x installation aside to $V5_NOW"
        mv "$UPGRADE_FROM" "$V5_NOW" || die "could not move $UPGRADE_FROM aside; $BACK (backups in $BACKUP)"
        BACK="5.x is stopped and at $V5_NOW; move it back to $UPGRADE_FROM, then: systemctl enable --now ${OLD_SERVICE:-<its service>}"
    fi
    mkdir -p "$PREFIX/rollback" && chmod 700 "$PREFIX/rollback" && cp -a "$BACKUP/." "$PREFIX/rollback/" \
        || die "could not keep the backups in $PREFIX/rollback; $BACK (backups in $BACKUP)"
    rm -rf "$BACKUP"
    {
        printf 'PREFIX=%q\nSERVICE=%q\nOLD_SERVICE=%q\nOLD_UNIT=%q\nV5_NOW=%q\nV5_ORIGINAL=%q\nNO_SYSTEMD=%q\n' \
            "$PREFIX" "$SERVICE" "$OLD_SERVICE" "$OLD_UNIT" "$V5_NOW" "$UPGRADE_FROM" "$NO_SYSTEMD"
    } > "$PREFIX/rollback/rollback.env"
    cp "$BUNDLE_DIR/rollback.sh" "$PREFIX/rollback.sh"
    chmod 755 "$PREFIX/rollback.sh"
    echo "==> If anything below fails: $PREFIX/rollback.sh brings 5.x back"
fi

echo "==> Installing illumio-ops v6 into $PREFIX"
install_program

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
    "${PY[@]}" -m illumio_ops.migrate --from "$V5_NOW" --write --root "$PREFIX" --lang "$REPORT_LANG" \
        --port "$PORT" "${MOVED[@]}" \
        || die "the upgrade did not complete; $PREFIX/rollback.sh brings 5.x back"
    RUN=()
elif (( KEPT )); then
    echo "==> Using the settings and data kept in $PREFIX"
    RUN=()
else
    RUN=("${PY[@]}" -m illumio_ops.rescue init --root "$PREFIX" --port "$PORT")
fi
if (( NO_SYSTEMD )); then
    (( ${#RUN[@]} )) && "${RUN[@]}"
    echo "==> Done (no systemd). Run: env PYTHONPATH=$PREFIX $PREFIX/python/bin/python3 -m illumio_ops serve --root $PREFIX"
    say_url
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
say_url
