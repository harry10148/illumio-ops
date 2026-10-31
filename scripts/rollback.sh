#!/usr/bin/env bash
# Go back from an upgraded illumio-ops v6 to the 5.x installation it replaced (spec §7 "可回退").
#
#   sudo /opt/illumio-ops/rollback.sh
#
# install.sh --upgrade-from left this script and rollback/rollback.env in the v6 prefix. It stops and
# disables v6, moves the v6 directory aside (kept, named *.v6-rolled-back-<time>, so a later upgrade starts
# clean), puts the 5.x directory back where it ran, restores its unit and command wrapper, and starts 5.x.
# 5.x continues from where it stopped: what v6 sent to SIEM or alerted on meanwhile may be sent again.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$HERE/rollback/rollback.env"
die() { echo "rollback.sh: $*" >&2; exit 1; }

[[ -f "$ENV_FILE" ]] || die "$ENV_FILE is missing: this directory was not made by an upgrade"
# shellcheck source=/dev/null
OLD_UNIT=""
source "$ENV_FILE"   # PREFIX SERVICE OLD_SERVICE OLD_UNIT V5_NOW V5_ORIGINAL NO_SYSTEMD (install.sh, %q-quoted)
[[ "$PREFIX" == "$HERE" ]] || die "rollback.env names $PREFIX, but this script is in $HERE"
[[ -d "$V5_NOW" ]] || die "the 5.x installation is no longer at $V5_NOW"
if [[ "$V5_NOW" != "$V5_ORIGINAL" && -e "$V5_ORIGINAL" && "$V5_ORIGINAL" != "$PREFIX" ]]; then
    die "$V5_ORIGINAL exists: move it away before going back to 5.x"
fi
if (( ! NO_SYSTEMD )); then
    [[ $(id -u) -eq 0 ]] || die "run as root"
fi

AWAY="${PREFIX}.v6-rolled-back-$(date +%Y%m%d-%H%M%S)"
KEEP="$(mktemp -d)"
cp -a "$HERE/rollback/." "$KEEP/" || die "could not read the backups in $HERE/rollback; nothing was changed"

if (( ! NO_SYSTEMD )); then
    echo "==> Stopping and disabling v6 ($SERVICE)"
    systemctl stop "$SERVICE" || die "could not stop $SERVICE; nothing else was changed"
    if systemctl is-active --quiet "$SERVICE"; then
        die "$SERVICE is still running; nothing else was changed"
    fi
    systemctl disable "$SERVICE" 2>/dev/null || true
fi
echo "==> Moving v6 aside to $AWAY"
mv "$PREFIX" "$AWAY"
if [[ "$V5_NOW" != "$V5_ORIGINAL" ]]; then
    echo "==> Putting 5.x back at $V5_ORIGINAL"
    mv "$V5_NOW" "$V5_ORIGINAL"
fi
if (( ! NO_SYSTEMD )); then
    rm -f "/etc/systemd/system/${SERVICE}.service"   # v6's unit; the 5.x one goes back where systemd had it
    if [[ -n "$OLD_SERVICE" && -f "$KEEP/old.service" ]]; then
        cp -p "$KEEP/old.service" "${OLD_UNIT:-/etc/systemd/system/${OLD_SERVICE}.service}"
    fi
    if [[ -f "$KEEP/illumio-ops.wrapper" ]]; then
        cp -p "$KEEP/illumio-ops.wrapper" /usr/local/bin/illumio-ops
    fi
    systemctl daemon-reload
    if [[ -n "$OLD_SERVICE" ]]; then
        echo "==> Starting 5.x ($OLD_SERVICE)"
        systemctl enable --now "$OLD_SERVICE"
    fi
fi
rm -rf "$KEEP"
echo "==> Back on 5.x. v6 is kept at $AWAY (its settings, data and the migration report)."
echo "    5.x continues from where it stopped; what v6 sent or alerted on meanwhile may be sent again."
