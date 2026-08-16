"""Guard: every `detail` string check_enablement() can produce must be
recognized by the reports.mjs RHC panel's translation logic, not silently
shown as raw English in zh_TW.

Task 12c's first pass mapped the two fixed detail strings from
check_enablement()'s main branches and the two "missing: X" partial-state
strings, but missed that the `unsupported` branch (404 on the report
template endpoint) actually produces THREE distinct detail shapes, not one:
a fixed string, and two that interpolate a live PCE version (and, for one of
them, the version-floor constants). Only the fixed one got mapped; the other
two kept printing raw English. A human review caught it by reading the
source side by side — this test makes that comparison automatic.

Approach: statically extract every string/f-string expression the function
can assign to `detail`, structurally (via `ast`), not by hand-enumerating
branches — so a *new* branch added later is picked up here without anyone
remembering to update this file. Concrete example strings are built from
these shapes (module-level constants and small closed-form local variables
like `missing` are resolved to their real value(s); anything that comes from
a live call, like `version_str`, is rendered as an opaque placeholder — the
frontend's job is to route by shape, not to validate the substituted value).

Those example strings are then run through reports.mjs's *actual* matching
logic — the RHC_DETAIL_KEYS map and the two floor regexes — extracted
directly from its source text (not hand-copied into this file), so drift in
either file shows up here rather than needing another manual side-by-side
read.
"""
from __future__ import annotations

import ast
import itertools
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_PATH = ROOT / "src" / "report" / "rule_hit_count_enablement.py"
JS_PATH = ROOT / "src" / "static" / "js" / "v2" / "areas" / "reports.mjs"


# ---------------------------------------------------------------------------
# Backend side: structurally enumerate every string check_enablement() can
# assign to `detail`.
# ---------------------------------------------------------------------------

def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    consts = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            consts[node.targets[0].id] = node.value.value
    return consts


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found in {PY_PATH}")


def _local_assign_values(func: ast.FunctionDef, name: str) -> list[ast.expr]:
    """Every RHS expression assigned to a bare-name or tuple-unpacked `name`
    inside func (regardless of which if/elif/else branch it's in — we want
    every possible value, not just one control-flow path)."""
    out: list[ast.expr] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                out.append(node.value)
            elif isinstance(target, ast.Tuple):
                for i, el in enumerate(target.elts):
                    if (
                        isinstance(el, ast.Name)
                        and el.id == name
                        and isinstance(node.value, ast.Tuple)
                        and len(node.value.elts) == len(target.elts)
                    ):
                        out.append(node.value.elts[i])
    return out


def _resolve_expr(node: ast.expr, module_consts: dict[str, str], func: ast.FunctionDef, depth: int) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _resolve_expr(node.body, module_consts, func, depth + 1) + _resolve_expr(
            node.orelse, module_consts, func, depth + 1
        )
    if isinstance(node, ast.Name):
        return _resolve_name(node.id, module_consts, func, depth + 1)
    # A call, attribute access, etc. — genuinely runtime data (e.g. a PCE
    # version string fetched over the network). Any distinct placeholder is
    # fine: the frontend routes by sentence *shape*, not by this value.
    return ["<opaque>"]


def _resolve_name(name_id: str, module_consts: dict[str, str], func: ast.FunctionDef, depth: int) -> list[str]:
    if name_id in module_consts:
        return [module_consts[name_id]]
    if depth > 4:
        return [f"<{name_id}>"]
    assigns = _local_assign_values(func, name_id)
    if not assigns:
        return [f"<{name_id}>"]
    out: list[str] = []
    for value_node in assigns:
        out.extend(_resolve_expr(value_node, module_consts, func, depth))
    return out or [f"<{name_id}>"]


def _render_joinedstr(node: ast.JoinedStr, module_consts: dict[str, str], func: ast.FunctionDef) -> list[str]:
    segment_options: list[list[str]] = []
    for value in node.values:
        if isinstance(value, ast.Constant):
            segment_options.append([str(value.value)])
        elif isinstance(value, ast.FormattedValue):
            inner = value.value
            if isinstance(inner, ast.Name):
                segment_options.append(_resolve_name(inner.id, module_consts, func, 0))
            else:
                segment_options.append(["<opaque>"])
        else:  # pragma: no cover - JoinedStr only ever holds these two node types
            segment_options.append(["?"])
    return ["".join(combo) for combo in itertools.product(*segment_options)]


def backend_detail_shapes() -> list[str]:
    """Every concrete string check_enablement() can assign to `detail`."""
    tree = ast.parse(PY_PATH.read_text(encoding="utf-8"))
    module_consts = _module_string_constants(tree)
    func = _find_function(tree, "check_enablement")

    detail_value_nodes: list[ast.expr] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "detail":
                detail_value_nodes.append(node.value)
            elif isinstance(target, ast.Tuple):
                for i, el in enumerate(target.elts):
                    if (
                        isinstance(el, ast.Name)
                        and el.id == "detail"
                        and isinstance(node.value, ast.Tuple)
                        and len(node.value.elts) == len(target.elts)
                    ):
                        detail_value_nodes.append(node.value.elts[i])

    shapes: list[str] = []
    for value_node in detail_value_nodes:
        if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
            shapes.append(value_node.value)
        elif isinstance(value_node, ast.JoinedStr):
            shapes.extend(_render_joinedstr(value_node, module_consts, func))
        else:  # pragma: no cover - would mean detail is built some new way
            raise AssertionError(
                "check_enablement() assigns `detail` from an expression this test "
                f"doesn't know how to enumerate: {ast.dump(value_node)[:200]} — "
                "extend backend_detail_shapes() to cover it, then make sure "
                "reports.mjs's RHC_DETAIL_KEYS/regexes handle the new shape too."
            )
    return shapes


# ---------------------------------------------------------------------------
# Frontend side: extract the actual matching logic from reports.mjs (not a
# hand-copied duplicate of it).
# ---------------------------------------------------------------------------

def frontend_classifier():
    js_src = JS_PATH.read_text(encoding="utf-8")

    keys_block = re.search(r"const RHC_DETAIL_KEYS = \{(.*?)\n\s*\};", js_src, re.S)
    assert keys_block, "RHC_DETAIL_KEYS not found in reports.mjs — did it get renamed?"
    detail_keys = dict(
        re.findall(r'"((?:[^"\\]|\\.)*)"\s*:\s*"(gui_[a-z0-9_]+)"', keys_block.group(1))
    )
    assert detail_keys, "RHC_DETAIL_KEYS parsed to an empty map — extraction regex is broken"

    below_m = re.search(r"const RHC_BELOW_FLOOR_RE = /(.*)/;", js_src)
    meets_m = re.search(r"const RHC_MEETS_FLOOR_RE = /(.*)/;", js_src)
    assert below_m and meets_m, "RHC_BELOW_FLOOR_RE / RHC_MEETS_FLOOR_RE not found in reports.mjs"
    below_re = re.compile(below_m.group(1))
    meets_re = re.compile(meets_m.group(1))

    def classify(raw: str) -> str | None:
        if raw in detail_keys:
            return detail_keys[raw]
        if below_re.match(raw):
            return "gui_rp_rhc_detail_below_floor"
        if meets_re.match(raw):
            return "gui_rp_rhc_detail_meets_floor"
        return None  # falls through to the raw-passthrough branch — untranslated

    return classify


def test_every_backend_detail_shape_is_recognized_by_the_frontend():
    shapes = backend_detail_shapes()
    # Sanity: if this drops to 0 or 1, the AST walk broke, not the feature.
    assert len(shapes) >= 5, f"only found {len(shapes)} detail shapes — extraction likely broken: {shapes}"

    classify = frontend_classifier()
    unrecognized = {s: classify(s) for s in shapes if classify(s) is None}
    assert not unrecognized, (
        "reports.mjs's RHC_DETAIL_KEYS/regexes do not recognize these detail "
        "strings that check_enablement() can actually produce — they will "
        f"print raw English in zh_TW: {sorted(unrecognized)}"
    )


def test_backend_detail_shape_count_is_pinned():
    """A pure count ratchet: if check_enablement() gains or loses a `detail`-
    producing branch, this changes even before anyone updates the frontend,
    so the change is visible in review instead of silently drifting."""
    shapes = backend_detail_shapes()
    assert len(shapes) == 7, (
        f"check_enablement() now produces {len(shapes)} detail shapes, was 7 "
        "— update reports.mjs's RHC panel to handle the new/removed shape, "
        "then update this pinned count"
    )
