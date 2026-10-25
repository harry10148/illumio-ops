#!/usr/bin/env bash
# The single entry point for generated API types: backend contracts -> JSON -> TypeScript.
# PYTHON defaults to python3 (CI: setup-python 3.12); locally: PYTHON=.venv/bin/python.
set -euo pipefail
cd "$(dirname "$0")/../.."
"${PYTHON:-python3}" scripts/v6/export_contracts.py
if [ -f web/package.json ] && grep -q '"gen:ts"' web/package.json; then
    npm --prefix web run --silent gen:ts
fi
