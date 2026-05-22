#!/usr/bin/env bash
# Regenerate CycloneDX SBOM from installed Python packages.
set -euo pipefail

if ! command -v cyclonedx-py &>/dev/null; then
    echo "Installing cyclonedx-bom..." >&2
    pip install cyclonedx-bom
fi

cyclonedx-py environment -o sbom.cyclonedx.json --format json
echo "Generated sbom.cyclonedx.json ($(wc -c < sbom.cyclonedx.json) bytes)"
