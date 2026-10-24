"""Gate: the two dictionaries agree, every referenced key exists, no key is dead,
and no code builds a key name at runtime (which would hide it from this gate).

What counts as a reference:
  TS      t("key") and message_key: "key"
  Python  a keyword argument named in I18N_KWARGS with a string literal; the 3rd positional
          argument (message key) of api_error(...) / ApiFailure(...); the values of a
          module-level dict whose name ends in _KEYS.
"No dead keys" is broader: a key is alive if it appears as a string literal anywhere
in illumio_ops/**/*.py or web/src/**/*.ts(x).
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from tests_v6.gates._scan import PKG_ROOT, REPO_ROOT, iter_modules

DICT_DIR = PKG_ROOT / "i18n"
WEB_SRC = REPO_ROOT / "web" / "src"
_MSG_POSITIONAL = {"api_error", "ApiFailure"}
# Keyword arguments that carry an i18n key. An allowlist, not "*_key": settings fields
# such as api_key / secret_key are not dictionary keys.
I18N_KWARGS = frozenset({"message_key", "detail_key", "reason_key", "label_key", "hint_key"})
_TS_T = re.compile(r"""\bt\(\s*["']([A-Za-z0-9_.]+)["']""")
_TS_MSG = re.compile(r"""\bmessage_key\s*:\s*["']([A-Za-z0-9_.]+)["']""")
_TS_DYNAMIC = re.compile(r"""\bt\(\s*`""")
_TS_LITERAL = re.compile(r"""["'`]([A-Za-z0-9_.]+)["'`]""")


def load(lang: str, d: Path = DICT_DIR) -> dict[str, str]:
    data: dict[str, str] = json.loads((d / f"{lang}.json").read_text(encoding="utf-8"))
    return data


def _ts_files(web_src: Path) -> list[Path]:
    return [p for p in sorted(web_src.rglob("*.ts*")) if p.name != "generated.ts"] if web_src.exists() else []


def _call_name(node: ast.Call) -> str:
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def python_refs(pkg: Path) -> tuple[set[str], list[str]]:
    refs: set[str] = set()
    dynamic: list[str] = []
    for _name, tree, path in iter_modules(pkg):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg in I18N_KWARGS:
                        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            refs.add(kw.value.value)
                        elif isinstance(kw.value, (ast.JoinedStr, ast.BinOp)):
                            dynamic.append(f"{path}:{node.lineno}")
                if _call_name(node) in _MSG_POSITIONAL and len(node.args) >= 3:
                    a = node.args[2]
                    if isinstance(a, ast.Constant) and isinstance(a.value, str):
                        refs.add(a.value)
                    elif isinstance(a, (ast.JoinedStr, ast.BinOp)):
                        dynamic.append(f"{path}:{node.lineno}")
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target] if isinstance(node, ast.AnnAssign) else [])
            for t in targets:
                if isinstance(t, ast.Name) and t.id.endswith("_KEYS") and isinstance(node.value, ast.Dict):
                    refs.update(v.value for v in node.value.values
                                if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return refs, dynamic


def ts_refs(web_src: Path) -> tuple[set[str], list[str]]:
    refs: set[str] = set()
    dynamic: list[str] = []
    for p in _ts_files(web_src):
        text = p.read_text(encoding="utf-8")
        refs.update(_TS_T.findall(text))
        refs.update(_TS_MSG.findall(text))
        dynamic += [f"{p}" for _ in _TS_DYNAMIC.finditer(text)]
    return refs, dynamic


def all_literals(pkg: Path, web_src: Path) -> set[str]:
    out: set[str] = set()
    for _name, tree, _path in iter_modules(pkg):
        out.update(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str))
    for p in _ts_files(web_src):
        out.update(_TS_LITERAL.findall(p.read_text(encoding="utf-8")))
    return out


def missing_keys(pkg: Path, web_src: Path, keys: set[str]) -> list[str]:
    return sorted((python_refs(pkg)[0] | ts_refs(web_src)[0]) - keys)


def dead_keys(pkg: Path, web_src: Path, keys: set[str]) -> list[str]:
    return sorted(keys - all_literals(pkg, web_src))


def dynamic_keys(pkg: Path, web_src: Path) -> list[str]:
    return python_refs(pkg)[1] + ts_refs(web_src)[1]


# ── the gate ─────────────────────────────────────────────────────────────

def test_same_keys_in_both_languages():
    en, zh = load("en"), load("zh_TW")
    assert sorted(set(en) ^ set(zh)) == []
    assert all(v.strip() for v in [*en.values(), *zh.values()])


def test_every_referenced_key_exists():
    assert missing_keys(PKG_ROOT, WEB_SRC, set(load("en"))) == []


def test_no_dead_keys():
    assert dead_keys(PKG_ROOT, WEB_SRC, set(load("en"))) == []


def test_no_dynamic_keys():
    assert dynamic_keys(PKG_ROOT, WEB_SRC) == []


def test_placeholders_match_between_languages():
    en, zh = load("en"), load("zh_TW")
    ph = re.compile(r"\{(\w+)\}")
    assert [k for k in en if set(ph.findall(en[k])) != set(ph.findall(zh.get(k, "")))] == []


# ── self-tests: each rule must go red on an injected violation ───────────

def _tree(tmp_path: Path, py: str, ts: str) -> tuple[Path, Path]:
    pkg = tmp_path / "illumio_ops"
    pkg.mkdir()
    (pkg / "__init__.py").touch()
    (pkg / "m.py").write_text(py)
    web = tmp_path / "web" / "src"
    web.mkdir(parents=True)
    (web / "a.tsx").write_text(ts)
    return pkg, web


def test_selftest_missing_key_from_detail_key(tmp_path):
    pkg, web = _tree(tmp_path, 'R(detail_key="x_unused")\n', "")
    assert missing_keys(pkg, web, set()) == ["x_unused"]


def test_selftest_missing_key_from_ts_and_api_error(tmp_path):
    pkg, web = _tree(tmp_path, 'api_error(400, "c", "err_c")\n', 't("ui_title")\n')
    assert missing_keys(pkg, web, {"ui_title"}) == ["err_c"]


def test_selftest_key_referenced_only_by_reason_key_is_alive(tmp_path):
    pkg, web = _tree(tmp_path, 'Item(reason_key="y")\n', "")
    assert dead_keys(pkg, web, {"y"}) == [] and dead_keys(pkg, web, {"y", "z"}) == ["z"]


def test_selftest_keys_dict_counts(tmp_path):
    pkg, web = _tree(tmp_path, 'DETAIL_KEYS = {"ok": "probe_ok"}\n', "")
    assert missing_keys(pkg, web, set()) == ["probe_ok"]


def test_selftest_settings_fields_named_key_are_not_i18n(tmp_path):
    pkg, web = _tree(tmp_path, 'PceSettings(api_key="", secret_key="abc")\n', "")
    assert missing_keys(pkg, web, set()) == []


def test_selftest_dynamic_keys_are_caught(tmp_path):
    pkg, web = _tree(tmp_path, 'Item(reason_key=f"a_{n}")\n', "t(`a_${n}`)\n")
    assert len(dynamic_keys(pkg, web)) == 2
