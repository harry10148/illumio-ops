#!/usr/bin/env bash
# illumio-ops v6 installer (fresh installs only; upgrading a 5.x installation arrives in P6).
#
#   ./install.sh [--prefix DIR] [--service-name NAME] [--port N] [--no-systemd] [--print-unit]
#
# Copies the bundled Python and the illumio_ops package to the prefix, installs the locked
# wheels with hash checking, creates the first settings file through
# `python -m illumio_ops.rescue init` (this script never writes settings itself), renders the
# systemd unit, and stops there: it does not start the service.
#   --no-systemd  copy, pip install and init as the current user only (verification runs)
#   --print-unit  print the rendered unit and exit
set -euo pipefail

PREFIX=/opt/illumio-ops
SERVICE=illumio-ops
PORT=5001
NO_SYSTEMD=0
PRINT_UNIT=0
SERVICE_USER=illumio-ops
BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die() { echo "install.sh: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix) PREFIX="${2:?}"; shift 2 ;;
        --service-name) SERVICE="${2:?}"; shift 2 ;;
        --port) PORT="${2:?}"; shift 2 ;;
        --no-systemd) NO_SYSTEMD=1; shift ;;
        --print-unit) PRINT_UNIT=1; shift ;;
        -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

[[ "$PREFIX" == /* ]] || die "--prefix must be an absolute path"
[[ "$SERVICE" =~ ^[A-Za-z0-9_.@-]+$ ]] || die "--service-name may only contain letters, digits, _ . @ -"
[[ "$PORT" =~ ^[0-9]+$ ]] && (( PORT >= 1 && PORT <= 65535 )) || die "--port must be 1-65535"
PREFIX="${PREFIX%/}"

render_unit() {
    sed -e "s#@PREFIX@#${PREFIX}#g" -e "s#@SERVICE_NAME@#${SERVICE}#g" "$BUNDLE_DIR/illumio-ops.service.in"
}

if (( PRINT_UNIT )); then
    render_unit
    exit 0
fi

if [[ -e "$PREFIX/illumio-ops.py" ]]; then
    die "$PREFIX holds an illumio-ops 5.x installation; upgrading it is not supported by this version"
fi
if [[ -e "$PREFIX/illumio_ops" || -e "$PREFIX/config/settings.json" ]]; then
    die "$PREFIX already holds an illumio-ops v6 installation; nothing was changed"
fi
for need in python wheels illumio_ops requirements-v6.lock illumio-ops.service.in; do
    [[ -e "$BUNDLE_DIR/$need" ]] || die "bundle is incomplete: $need is missing next to install.sh"
done
if (( ! NO_SYSTEMD )); then
    [[ $(id -u) -eq 0 ]] || die "run as root (or use --no-systemd for a user-level verification install)"
    command -v systemctl >/dev/null || die "systemctl not found (use --no-systemd)"
    [[ ! -e "/etc/systemd/system/${SERVICE}.service" ]] || die "/etc/systemd/system/${SERVICE}.service already exists"
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
RUN=(env "PYTHONPATH=$PREFIX" PYTHONNOUSERSITE=1 "$PREFIX/python/bin/python3" -P -m illumio_ops.rescue
     init --root "$PREFIX" --port "$PORT")
if (( NO_SYSTEMD )); then
    "${RUN[@]}"
    echo "==> Done (no systemd). Run: env PYTHONPATH=$PREFIX $PREFIX/python/bin/python3 -m illumio_ops serve --root $PREFIX"
    exit 0
fi

if ! getent passwd "$SERVICE_USER" >/dev/null; then
    useradd --system --no-create-home --shell /sbin/nologin "$SERVICE_USER"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$PREFIX/config" "$PREFIX/data" "$PREFIX/logs" "$PREFIX/reports"
runuser -u "$SERVICE_USER" -- "${RUN[@]}"

render_unit > "/etc/systemd/system/${SERVICE}.service"
chmod 644 "/etc/systemd/system/${SERVICE}.service"
systemctl daemon-reload
echo "==> Installed. The service is NOT started. Start it with:"
echo "    systemctl enable --now ${SERVICE}"
echo "    then open https://<this host>:${PORT}/"
