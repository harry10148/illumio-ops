#!/usr/bin/env bash
# Verify each doc covers its expected terms after the Option 1 split.
# Exits non-zero with a list of missing terms.
set -euo pipefail

declare -A DOC_FOR_FAMILY=(
  ["module"]="docs/Report_Modules.md"
  ["pu_module"]="docs/Report_Modules.md"
  ["subcommand"]="docs/User_Manual.md"
  ["script"]="docs/Installation.md"
)

for d in "${DOC_FOR_FAMILY[@]}"; do
  [ -f "$d" ] || { echo "FATAL: $d not found"; exit 2; }
done

missing=()

while IFS= read -r path; do
  mod=$(basename "$path" .py)
  doc=${DOC_FOR_FAMILY[module]}
  grep -q -- "$mod" "$doc" || missing+=("module:$mod (in $doc)")
done < <(find src/report/analysis -maxdepth 1 -name 'mod*.py' -not -name '__init__.py')

while IFS= read -r path; do
  mod=$(basename "$path" .py)
  doc=${DOC_FOR_FAMILY[pu_module]}
  grep -q -- "$mod" "$doc" || missing+=("pu_module:$mod (in $doc)")
done < <(find src/report/analysis/policy_usage -maxdepth 1 -name 'pu_*.py')

doc=${DOC_FOR_FAMILY[subcommand]}
for sub in cache monitor gui report rule siem workload config status version; do
  grep -qE "(\`|\b)${sub}(\`|\b)" "$doc" || missing+=("subcommand:$sub (in $doc)")
done

doc=${DOC_FOR_FAMILY[script]}
for s in build_offline_bundle.sh install.sh uninstall.sh; do
  grep -q -- "$s" "$doc" || missing+=("script:$s (in $doc)")
done

if [ ${#missing[@]} -ne 0 ]; then
  printf 'MISSING:\n'
  printf '  %s\n' "${missing[@]}"
  exit 1
fi

echo "OK — all required terms present in their target docs"
