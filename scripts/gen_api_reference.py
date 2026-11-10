"""Write docs/reference/v6-rest-api.md from the API contracts, so the page cannot drift from the routes.

Run: python scripts/gen_api_reference.py   (tests/gates/test_docs.py fails when the page is stale)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from illumio_ops.web.app import PASSWORD_CHANGE_OPS, PUBLIC_OPS
from illumio_ops.web.contract import REGISTRY

OUT = REPO / "docs" / "reference" / "v6-rest-api.md"

HEAD = """---
title: v6 REST API 參考
verified_against:
  - illumio_ops/web/contract.py
  - illumio_ops/web/app.py
  - web/src/api/contracts.json
---

# v6 REST API 參考

> 本頁由 `scripts/gen_api_reference.py` 從 API 契約產生，請勿手改。新增或修改操作後重新執行該腳本。

這些是網頁介面自己使用的 API，共 {count} 個操作。每個操作的請求與回應欄位（JSON Schema）在
`web/src/api/contracts.json`，以下只列操作、方法、路徑與模型名稱。

## 共通規則

- 路徑都在 `/api/` 底下，走與網頁介面相同的 HTTPS port。
- 登入：`POST /api/auth/login` 成功後以 session cookie 識別。未登入時回 401 `auth_required`。
  不需登入的操作：{public}。
- 寫入（GET 以外）要帶 CSRF 權杖：先 `GET /api/auth/csrf` 取得，放在 `X-CSRFToken` 標頭。登入不需要。
- 設定檔標記為必須改密碼時，除了 {change} 之外的操作都回 423 `password_change_required`。
- 回應一律是同一個封套：

```
{{"ok": true,  "data": <回應模型>, "error": null, "meta": {{"partial": false, "truncated": false, "notes": []}}}}
{{"ok": false, "data": null, "error": {{"code": "...", "message_key": "...", "params": {{}}, "field": null}}, "meta": {{...}}}}
```

- `error.message_key` 是介面字典的鍵，文字由 `GET /api/i18n/<語系>` 取得。
- 請求欄位不符合模型時回 400；`error.field` 指出是哪一欄。
"""


def render() -> str:
    def ids(ops: frozenset[str]) -> str:
        return "、".join(f"`{o}`" for o in sorted(ops))

    out = [HEAD.format(count=len(REGISTRY), public=ids(PUBLIC_OPS), change=ids(PASSWORD_CHANGE_OPS))]
    groups: dict[str, list[str]] = {}
    for op_id in sorted(REGISTRY):
        groups.setdefault(op_id.split(".", 1)[0], []).append(op_id)
    for group, op_ids in groups.items():
        out.append(f"\n## {group}\n\n| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |\n|---|---|---|---|---|\n")
        for op_id in op_ids:
            op = REGISTRY[op_id]
            req = f"`{op.request.__name__}`" if op.request else "—"
            out.append(f"| `{op_id}` | {op.method} | `{op.path}` | {req} | `{op.response.__name__}` |\n")
    return "".join(out)


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({len(REGISTRY)} operations)")
