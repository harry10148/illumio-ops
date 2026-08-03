import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "design" / "v2" / "tools"))
from lint_no_inline_data import lint_source

def test_flags_array_of_objects():
    assert lint_source('const rows = [{name: "wl1", ip: "10.0.0.1"}];')

def test_flags_big_object_literal():
    assert lint_source('let d = {a:1, b:2, c:3, d:4, e:5};')

def test_allows_small_config_and_fetch():
    assert not lint_source('const opt = {method: "GET"}; const r = await fetch("../snapshots/status.json");')

def test_allow_marker_suppresses():
    assert not lint_source('// lint-allow-inline-data: i18n fallback\nconst x = [{a:1},{a:2}];')
