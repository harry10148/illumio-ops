#!/usr/bin/env bash
# Verify user docs cover the operator-facing surface.
# Exits non-zero with a list of missing terms.
#
# Families:
#   subcommand -> docs/reference/cli.md      (CLI reference)
#   script     -> docs/getting-started.md    (install/upgrade/uninstall SOP)
#
# Analysis-module filename coverage (mod*.py / pu_*.py -> Report_Modules.md)
# was dropped 2026-07-12: the split docs describe reports chapter-by-chapter
# and internal module filenames are not an operator-facing surface.
set -euo pipefail

declare -A DOC_FOR_FAMILY=(
  ["subcommand"]="docs/reference/cli.md"
  ["script"]="docs/getting-started.md"
)

for d in "${DOC_FOR_FAMILY[@]}"; do
  [ -f "$d" ] || { echo "FATAL: $d not found"; exit 2; }
done

missing=()

doc=${DOC_FOR_FAMILY[subcommand]}
for sub in cache monitor gui report rule siem workload config status version; do
  grep -qE "(\`|\b)${sub}(\`|\b)" "$doc" || missing+=("subcommand:$sub (in $doc)")
done

doc=${DOC_FOR_FAMILY[script]}
for s in build_offline_bundle.sh preflight.sh install.sh uninstall.sh \
         preflight.ps1 install.ps1; do
  grep -q -- "$s" "$doc" || missing+=("script:$s (in $doc)")
done

if [ ${#missing[@]} -ne 0 ]; then
  printf 'MISSING:\n'
  printf '  %s\n' "${missing[@]}"
  exit 1
fi

echo "OK — all required terms present in their target docs"
