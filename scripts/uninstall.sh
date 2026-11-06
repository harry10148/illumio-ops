#!/usr/bin/env bash
# Remove illumio-ops v6 from this host.
#
#   sudo /opt/illumio-ops/uninstall.sh [--purge] [--yes] [--prefix DIR] [--service-name NAME] [--no-systemd]
#
# Stops and removes the service and the program. config/, data/ and reports/ are kept (owned by root, mode 0700:
# the service account is deleted and its user id may be given to another program later); a later install.sh in the
# same directory installs the program again with them (unless they were written by a newer version). --purge removes
# the whole directory, settings and data included. Asks before removing anything unless --yes.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX=""
SERVICE=""
PURGE=0
YES=0
NO_SYSTEMD=0
SERVICE_USER=illumio-ops
die() { echo "uninstall.sh: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix) PREFIX="${2:?}"; shift 2 ;;
        --service-name) SERVICE="${2:?}"; shift 2 ;;
        --purge) PURGE=1; shift ;;
        --yes) YES=1; shift ;;
        --no-systemd) NO_SYSTEMD=1; shift ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done
if [[ -z "$PREFIX" ]]; then
    [[ -d "$HERE/illumio_ops" ]] && PREFIX="$HERE" || PREFIX=/opt/illumio-ops
fi
[[ "$PREFIX" == /* ]] || die "--prefix must be an absolute path"
PREFIX="$(cd "$PREFIX" 2>/dev/null && pwd -P)" || die "$PREFIX does not exist"
[[ "$PREFIX" != / && "$PREFIX" != /opt && "$PREFIX" != /usr && "$PREFIX" != /home ]] || die "refusing to remove $PREFIX"
[[ -d "$PREFIX/illumio_ops" || -f "$PREFIX/config/settings.json" ]] \
    || die "$PREFIX is not an illumio-ops v6 installation (no illumio_ops/ or config/settings.json); nothing was changed"

UNIT=""
if (( ! NO_SYSTEMD )); then
    [[ $(id -u) -eq 0 ]] || die "run as root (or --no-systemd for a user-level installation)"
    if [[ -n "$SERVICE" ]]; then
        UNIT="/etc/systemd/system/${SERVICE}.service"
        [[ -f "$UNIT" ]] || die "$UNIT does not exist; nothing was changed"
    else
        for u in /etc/systemd/system/*.service; do
            if [[ -f "$u" ]] && grep -qF -- "-m illumio_ops serve --root $PREFIX" "$u"; then
                UNIT="$u"
                SERVICE="$(basename "$u" .service)"
                break
            fi
        done
    fi
fi

if (( PURGE )); then
    WHAT="the service ${SERVICE:-(none found)} and all of $PREFIX, settings, data and reports included"
else
    WHAT="the service ${SERVICE:-(none found)} and the program in $PREFIX; config/, data/ and reports/ are kept"
fi
if (( ! YES )); then
    [[ -t 0 ]] || die "not a terminal: pass --yes to remove $WHAT; nothing was changed"
    read -r -p "Remove $WHAT? Type yes: " answer
    [[ "$answer" == yes ]] || die "cancelled; nothing was changed"
fi

if [[ -n "$UNIT" ]]; then
    echo "==> Stopping and removing $SERVICE"
    systemctl stop "$SERVICE" || die "could not stop $SERVICE; nothing else was changed"
    if systemctl is-active --quiet "$SERVICE"; then
        die "$SERVICE is still running; nothing else was changed"
    fi
    systemctl disable "$SERVICE" 2>/dev/null || true
    rm -f "$UNIT"
    systemctl daemon-reload
fi

if (( PURGE )); then
    echo "==> Removing $PREFIX"
    rm -rf --one-file-system "$PREFIX"
else
    echo "==> Removing the program from $PREFIX"
    find "$PREFIX" -mindepth 1 -maxdepth 1 ! -name config ! -name data ! -name reports -exec rm -rf --one-file-system {} +
    if (( ! NO_SYSTEMD )); then
        # The service account goes below: these must not stay owned by a user id that may be handed out again.
        for d in config data reports; do
            if [[ -d "$PREFIX/$d" ]]; then
                chown -R root:root "$PREFIX/$d"
                chmod 700 "$PREFIX/$d"
            fi
        done
    fi
    echo "    Kept: $PREFIX/config, $PREFIX/data, $PREFIX/reports. To remove them too: sudo rm -rf $PREFIX"
fi

if (( ! NO_SYSTEMD )) && getent passwd "$SERVICE_USER" >/dev/null; then
    if grep -lqx "User=$SERVICE_USER" /etc/systemd/system/*.service 2>/dev/null; then
        echo "==> Keeping the account $SERVICE_USER: another illumio-ops service on this host runs as it"
    else
        userdel "$SERVICE_USER"
        echo "==> Removed the account $SERVICE_USER"
    fi
fi
echo "==> illumio-ops is removed."
