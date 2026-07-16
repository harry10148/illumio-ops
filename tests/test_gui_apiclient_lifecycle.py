"""Task 5（API layer hardening）：GUI 路由 ApiClient 生命週期守門測試。

背景：src/gui/routes/*.py 過去有多處 `ApiClient(cm)` 建構後從未 close()，
每個 request 洩漏一個 requests.Session 連線池。本檔案有兩個測試：

1. test_apiclient_context_manager：確認 ApiClient 的 `with` 協定本身正確
   （離開 with 區塊後 _session 必須是 None）。
2. test_routes_no_bare_apiclient：靜態掃描 src/gui/routes/*.py 原始碼，
   對每個 `ApiClient(` 呼叫點要求二選一：
     (a) 是某個 `with ApiClient(...) as x:` 的 context expression，或
     (b) 呼叫點所在函式內存在 `try/finally` 且 finally 區塊有 `.close()` 呼叫
         （背景 thread 站點：建構與 close 都在同一個 thread target 函式內）。
   這是通用不變量守門——未來新增站點忘記關閉連線會直接讓這個測試變紅，
   不需要為每個新站點手動補測試案例。
"""
from __future__ import annotations

import ast
import glob
import os

_ROUTES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src", "gui", "routes",
)


def _make_cm():
    from unittest.mock import MagicMock
    cm = MagicMock()
    cm.config = {
        "api": {
            "url": "https://localhost",
            "org_id": "1",
            "key": "k",
            "secret": "s",
            "verify_ssl": False,
            "profile": "dev",
        }
    }
    return cm


def test_apiclient_context_manager():
    """`with ApiClient(cm) as api:` 離開後 _session 必須是 None（連線池已釋放）。"""
    from src.api_client import ApiClient
    with ApiClient(_make_cm()) as api:
        assert api._session is not None
    assert api._session is None


# ─────────────────────────────────────────────────────────────────────────
# 靜態守門：src/gui/routes/*.py 不得有裸 ApiClient( 建構
# ─────────────────────────────────────────────────────────────────────────

def _is_apiclient_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ApiClient"
    )


def _parent_map(tree: ast.AST) -> dict:
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    return parent


def _enclosing_function(node: ast.AST, parent: dict):
    """回傳最內層 def/async def（可能是巢狀在 blueprint factory 或 thread target 內）。"""
    cur = parent.get(node)
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur
        cur = parent.get(cur)
    return None


def _collect_with_guarded_call_ids(tree: ast.AST) -> set:
    """回傳所有『是某個 with 語句 context_expr』的 ApiClient( 呼叫節點 id 集合。"""
    guarded = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if _is_apiclient_call(item.context_expr):
                    guarded.add(id(item.context_expr))
    return guarded


def _stmt_has_close_call(stmt: ast.AST) -> bool:
    """stmt（通常是 finally 區塊裡的一條敘述）底下是否存在 `<something>.close()`。"""
    for n in ast.walk(stmt):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "close"
        ):
            return True
    return False


def _function_has_try_finally_close(func_node) -> bool:
    """函式（不跨進巢狀函式邊界）內是否存在 try 且 finally 區塊呼叫 .close()。"""
    found = False

    def visit(node, is_top):
        nonlocal found
        if found:
            return
        if not is_top and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return  # 不跨進巢狀函式（例如 thread target 裡面又定義的 helper）
        if isinstance(node, ast.Try) and node.finalbody:
            for stmt in node.finalbody:
                if _stmt_has_close_call(stmt):
                    found = True
                    return
        for child in ast.iter_child_nodes(node):
            visit(child, False)

    visit(func_node, True)
    return found


def _find_bare_apiclient_sites(file_path: str) -> list[int]:
    with open(file_path, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source, filename=file_path)
    parent_map = _parent_map(tree)
    guarded_ids = _collect_with_guarded_call_ids(tree)

    bare_lines = []
    for node in ast.walk(tree):
        if not _is_apiclient_call(node):
            continue
        if id(node) in guarded_ids:
            continue
        func = _enclosing_function(node, parent_map)
        if func is not None and _function_has_try_finally_close(func):
            continue
        bare_lines.append(node.lineno)
    return bare_lines


def test_routes_no_bare_apiclient():
    """每個 src/gui/routes/*.py 裡的 ApiClient( 呼叫點都必須是 with-guarded
    或所在函式內有 try/finally+close()——通用不變量，未來新站點忘記關閉
    連線會直接讓這個測試變紅。"""
    route_files = sorted(glob.glob(os.path.join(_ROUTES_DIR, "*.py")))
    assert route_files, f"no route files found under {_ROUTES_DIR}"

    violations = {}
    for path in route_files:
        bare_lines = _find_bare_apiclient_sites(path)
        if bare_lines:
            violations[os.path.relpath(path, _ROUTES_DIR)] = bare_lines

    assert not violations, (
        "bare ApiClient( construction found (no `with` / no try-finally-close "
        f"in the same function): {violations}"
    )
