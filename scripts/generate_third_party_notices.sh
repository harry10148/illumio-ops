#!/usr/bin/env bash
# Regenerate THIRD_PARTY_NOTICES.md from installed Python packages.
# Run from repo root with the project venv activated.
set -euo pipefail

if ! command -v pip-licenses &>/dev/null; then
    echo "Installing pip-licenses..." >&2
    pip install pip-licenses
fi

pip-licenses --from=mixed --format=markdown --with-license-file --no-license-path \
    > THIRD_PARTY_NOTICES.md

echo "Generated THIRD_PARTY_NOTICES.md ($(wc -l < THIRD_PARTY_NOTICES.md) lines)"
