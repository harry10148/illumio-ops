"""Write web/src/api/contracts.json: every API operation's schemas plus the value domains.

Run through scripts/v6/gen_contracts.sh, which also regenerates the TypeScript types.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import illumio_ops.web.app  # noqa: F401  - importing the app declares every operation
from illumio_ops.domain.values import export_value_domains
from illumio_ops.web.contract import REGISTRY


def build() -> dict[str, Any]:
    ops = {}
    for op_id in sorted(REGISTRY):
        op = REGISTRY[op_id]
        ops[op_id] = {
            "method": op.method,
            "path": op.path,
            "request_schema": op.request.model_json_schema() if op.request else None,
            "response_schema": op.response.model_json_schema(),
        }
    return {"operations": ops, "values": export_value_domains()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=REPO / "web" / "src" / "api" / "contracts.json")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(build(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
