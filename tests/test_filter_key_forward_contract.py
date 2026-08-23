"""Contract: FilterBar keys must appear in every endpoint forward whitelist.

Whitelist misses are SILENT drops (the analyzer never sees the key) — the
seventh..ninth incidents of this class. This is a static source contract:
each (file, anchor) surface below must name every key in KEYS.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (label, file, anchor-substring-that-identifies-the-dict)
FORWARD_SURFACES = (
    ("reports.report_filters", "src/gui/routes/reports.py", "report_filters = {"),
    ("dashboard._fb_keys", "src/gui/routes/dashboard.py", "_fb_keys = ("),
    ("dashboard.top10_params", "src/gui/routes/dashboard.py", '"src_ip_in": d.get("src_ip_in")'),
)

PILL_KEYS = ("ports", "ex_ports", "services", "ex_services")

NAME_KEYS = ("process_name", "ex_process_name",
             "windows_service_name", "ex_windows_service_name")

TRANSMISSION_KEYS = ("transmission", "ex_transmission")

FORWARD_SURFACES_ALL = FORWARD_SURFACES + (
    ("rules.whitelist", "src/gui/routes/rules.py", "src_labels"),
)

# actions.py 有兩份轉發白名單（archive 分支的 query_filters、live 分支的
# params），固定字元窗口定位不到它們：2026-08-23 archive 分支加入後，
# 'src_labels' 首次出現落在 query_filters 尾端，往後的窗口看不到更早的
# 'ports'，閘門因此變紅、卻沒有任何 key 真的被丟掉。改以 AST 取出每一份
# dict 的**完整原始碼片段**（含 key 與 value，因為有些 key 是改名轉發的，
# 例如 ex_transmission -> transmission_excludes），兩份各自驗。
# 不要改回放大窗口：窗口一旦同時罩住兩份，其中一份缺 key 會被另一份遮住。
ACTIONS_FORWARD_DICTS = ("query_filters", "params")


def _surface_text(path: str, anchor: str, span: int = 4000) -> str:
    text = (ROOT / path).read_text()
    idx = text.find(anchor)
    assert idx >= 0, f"anchor not found in {path}: {anchor}"
    return text[idx : idx + span]


def _actions_surfaces() -> list[tuple[str, str]]:
    """(label, source-segment) for each forward whitelist dict in actions.py."""
    src = (ROOT / "src/gui/routes/actions.py").read_text()
    tree = ast.parse(src)
    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        if not node.value.keys:
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id in ACTIONS_FORWARD_DICTS:
                seg = ast.get_source_segment(src, node.value)
                assert seg, f"could not extract source for actions.{tgt.id}"
                out.append((f"actions.{tgt.id}", seg))
    found = {label.split(".", 1)[1] for label, _ in out}
    missing = [n for n in ACTIONS_FORWARD_DICTS if n not in found]
    assert not missing, f"forward whitelist dict(s) not found in actions.py: {missing}"
    return out


def _assert_keys_forwarded(keys: tuple[str, ...]) -> None:
    surfaces = [(label, _surface_text(path, anchor))
                for label, path, anchor in FORWARD_SURFACES_ALL]
    surfaces += _actions_surfaces()
    for label, seg in surfaces:
        missing = [k for k in keys if f"'{k}'" not in seg and f'"{k}"' not in seg]
        assert not missing, f"{label} missing keys: {missing}"


def test_pill_port_service_keys_forwarded_everywhere():
    _assert_keys_forwarded(PILL_KEYS)


def test_name_keys_forwarded_everywhere():
    _assert_keys_forwarded(NAME_KEYS)


def test_transmission_keys_forwarded_everywhere():
    _assert_keys_forwarded(TRANSMISSION_KEYS)
