#!/usr/bin/env bash
# Go back from a v6 upgrade to the v6 version it replaced.
#
#   sudo /opt/illumio-ops/restore-previous.sh
#
# install.sh, upgrading an installed v6, left the replaced version in PREFIX/previous: its program, its settings file,
# and a copy of each database the new version migrates at its first start (the previous version refuses a newer
# schema). This stops the service, puts the previous program and settings back, puts those database copies back,
# and starts the service if it was running. What the new version changed is moved aside, not deleted: the settings
# file and each restored database stay next to the originals as *.from-<version>-<time>. Settings changed and data
# collected in a restored database since the upgrade are what goes back; other data stays as it is.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREV="$HERE/previous"
die() { echo "restore-previous.sh: $*" >&2; exit 1; }

[[ -f "$PREV/previous.env" ]] || die "$PREV/previous.env is missing: there is no previous version to go back to"
PREFIX="" SERVICE="" NO_SYSTEMD=0 OLD_VERSION="" NEW_VERSION="" COPIES=""
# shellcheck source=/dev/null
source "$PREV/previous.env"  # PREFIX SERVICE NO_SYSTEMD OLD_VERSION NEW_VERSION COPIES (install.sh, %q-quoted)
[[ "$PREFIX" == "$HERE" ]] || die "previous.env names $PREFIX, but this script is in $HERE"
for need in illumio_ops python settings.json; do
    [[ -e "$PREV/$need" ]] || die "$PREV/$need is missing; nothing was changed"
done
for f in $COPIES; do
    [[ -f "$PREV/data/$f" ]] || die "$PREV/data/$f is missing; nothing was changed"
done

WAS_ACTIVE=0
if (( ! NO_SYSTEMD )); then
    [[ $(id -u) -eq 0 ]] || die "run as root"
    if systemctl is-active --quiet "$SERVICE"; then
        WAS_ACTIVE=1
    fi
    echo "==> Stopping $SERVICE"
    systemctl stop "$SERVICE" || die "could not stop $SERVICE; nothing else was changed"
    if systemctl is-active --quiet "$SERVICE"; then
        die "$SERVICE is still running; nothing else was changed"
    fi
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
echo "==> Putting $OLD_VERSION back in place of ${NEW_VERSION:-the new version}"
rm -rf "$PREFIX/illumio_ops" "$PREFIX/python"  # the new version's program: the bundle has it
mv "$PREV/illumio_ops" "$PREFIX/illumio_ops"
mv "$PREV/python" "$PREFIX/python"
mv "$PREFIX/config/settings.json" "$PREFIX/config/settings.json.from-$NEW_VERSION-$STAMP"
cp -p "$PREV/settings.json" "$PREFIX/config/settings.json"
for f in $COPIES; do
    for suffix in "" -wal -shm; do
        if [[ -e "$PREFIX/data/$f$suffix" ]]; then
            mv "$PREFIX/data/$f$suffix" "$PREFIX/data/$f.from-$NEW_VERSION-$STAMP$suffix"
        fi
        if [[ -e "$PREV/data/$f$suffix" ]]; then
            mv "$PREV/data/$f$suffix" "$PREFIX/data/$f$suffix"
        fi
    done
done
rm -rf "$PREV" "$PREFIX/restore-previous.sh"

if (( ! NO_SYSTEMD && WAS_ACTIVE )); then
    echo "==> Starting $SERVICE"
    systemctl start "$SERVICE"
fi
echo "==> Back on $OLD_VERSION. What ${NEW_VERSION:-the new version} changed is kept as *.from-$NEW_VERSION-$STAMP in config/ and data/."
