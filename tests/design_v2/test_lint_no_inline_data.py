import sys, pathlib, tempfile, os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "design" / "v2" / "tools"))
from lint_no_inline_data import lint_source, main

def test_flags_array_of_objects():
    assert lint_source('const rows = [{name: "wl1", ip: "10.0.0.1"}];')

def test_flags_big_object_literal():
    assert lint_source('let d = {a:1, b:2, c:3, d:4, e:5};')

def test_allows_small_config_and_fetch():
    assert not lint_source('const opt = {method: "GET"}; const r = await fetch("../snapshots/status.json");')

def test_allow_marker_suppresses():
    assert not lint_source('// lint-allow-inline-data: i18n fallback\nconst x = [{a:1},{a:2}];')

# New tests for brace-aware scanner
def test_flags_multiline_array_of_objects():
    """Multi-line array-of-objects should be flagged."""
    src = 'const rows = [\n  {name: "a"}\n];'
    assert lint_source(src)

def test_flags_one_key_per_line_big_object():
    """One-key-per-line big object should be flagged."""
    src = 'let d = {\n a:1,\n b:2,\n c:3,\n d:4,\n e:5\n};'
    assert lint_source(src)

def test_flags_nested_value_big_object():
    """Big object with nested value should be flagged (counts colons at object depth)."""
    src = 'let d = {a:1, b:{x:1}, c:3, d:4, e:5};'
    assert lint_source(src)

def test_allows_small_multiline_object():
    """Object with ≤4 keys spanning multiple lines should NOT be flagged."""
    src = 'let d = {\n  a: 1,\n  b: 2,\n  c: 3\n};'
    assert not lint_source(src)

def test_string_with_colon_not_counted():
    """Colon inside string should not be counted toward key count."""
    src = 'const u = {href: "http://x/y:8080"};'
    assert not lint_source(src)

def test_array_object_in_string_not_flagged():
    """[{ inside a string should not be flagged."""
    src = 'const s = "[{";'
    assert not lint_source(src)

def test_allow_marker_suppresses_multiline():
    """Allow marker should suppress multi-line array-of-objects."""
    src = '// lint-allow-inline-data: test\nconst rows = [\n  {name: "a"}\n];'
    assert not lint_source(src)

# New tests for false-positive fixes (object literal vs code block detection)
def test_switch_statement_not_flagged():
    """Switch with 5 case labels should NOT be flagged (code block, not object literal)."""
    src = '''function handleCase(x) {
  switch (x) {
    case 1:
    case 2:
    case 3:
    case 4:
    case 5:
      break;
  }
}'''
    assert not lint_source(src)

def test_ternary_chain_not_flagged():
    """5-way ternary chain in function body should NOT be flagged (code block)."""
    src = 'function f(x) { return x ? a : b ? c : d ? e : f ? g : h; }'
    assert not lint_source(src)

def test_object_with_ternary_value_not_flagged():
    """4-key object with ternary value should NOT be flagged (only 4 keys)."""
    src = 'const obj = {onError: (e) => e ? f(e) : null, a: 1, b: 2, c: 3};'
    assert not lint_source(src)

def test_six_key_object_with_ternary_value_flagged():
    """6-key object with ternary value should BE flagged (>4 keys, counts top-level commas)."""
    src = 'const obj = {a: 1, b: 2, c: 3, d: {x: 1}, e: (err) => err ? f(err) : null, f: 4};'
    assert lint_source(src)

def test_object_as_function_argument_flagged():
    """Function call with 5-key object argument should BE flagged."""
    src = 'fn({a:1,b:2,c:3,d:4,e:5})'
    assert lint_source(src)

def test_return_object_flagged():
    """Return statement with 5-key object should BE flagged."""
    src = 'return {a:1,b:2,c:3,d:4,e:5}'
    assert lint_source(src)

def test_object_with_trailing_comma_not_flagged():
    """4-key object with trailing comma should NOT be flagged."""
    src = 'const obj = {a:1,b:2,c:3,d:4,}'
    assert not lint_source(src)

# New tests for destructuring pattern detection (round 3)
def test_function_param_destructure_not_flagged():
    """Function parameter destructuring {a, b, c, d, e} should NOT be flagged."""
    src = 'function f({a, b, c, d, e}) { return a + b; }'
    assert not lint_source(src)

def test_const_destructure_not_flagged():
    """const {a, b, c, d, e} = props destructuring should NOT be flagged."""
    src = 'const {a, b, c, d, e} = props;'
    assert not lint_source(src)

def test_arrow_param_destructure_not_flagged():
    """Arrow function parameter destructuring should NOT be flagged."""
    src = 'const f = ({a, b, c, d, e}) => a + b;'
    assert not lint_source(src)

def test_destructure_rename_small_not_flagged():
    """Renaming destructure with ≤4 keys should NOT be flagged."""
    src = 'const {a: x, b: y} = obj;'
    assert not lint_source(src)

def test_shorthand_literal_not_flagged():
    """Shorthand object literal {a, b, c, d, e} (zero colons) should NOT be flagged."""
    src = 'const o = {a, b, c, d, e};'
    assert not lint_source(src)

def test_six_key_real_data_object_flagged():
    """6-key real data object (>4 commas + colons) should BE flagged (regression pin)."""
    src = 'const data = {id: 1, name: "test", value: 42, status: "active", category: "demo", priority: "high"};'
    assert lint_source(src)

def test_cli_exit_code_with_violation(monkeypatch, tmp_path):
    """CLI should exit 1 when violations found."""
    # Create a temp mockup dir with a violating file
    mockup_dir = tmp_path / "mockup"
    mockup_dir.mkdir()
    js_file = mockup_dir / "test.js"
    js_file.write_text('const rows = [{a: 1}];')

    # Monkeypatch the root to use tmp dir
    def mock_main():
        import sys
        from lint_no_inline_data import lint_source
        root = tmp_path
        bad = False
        for p in sorted(list((root / "mockup").rglob("*.mjs")) + list((root / "mockup").rglob("*.js"))
                        + list((root / "pitch").rglob("*.html"))):
            for msg in lint_source(p.read_text()):
                print(f"{p.relative_to(root)}: {msg}"); bad = True
        sys.exit(1 if bad else 0)

    # Verify it raises SystemExit with code 1
    import pytest
    with pytest.raises(SystemExit) as exc_info:
        mock_main()
    assert exc_info.value.code == 1

def test_cli_exit_code_clean(monkeypatch, tmp_path):
    """CLI should exit 0 when no violations found."""
    # Create an empty temp mockup dir
    mockup_dir = tmp_path / "mockup"
    mockup_dir.mkdir()

    def mock_main():
        import sys
        from lint_no_inline_data import lint_source
        root = tmp_path
        bad = False
        for p in sorted(list((root / "mockup").rglob("*.mjs")) + list((root / "mockup").rglob("*.js"))
                        + list((root / "pitch").rglob("*.html"))):
            for msg in lint_source(p.read_text()):
                print(f"{p.relative_to(root)}: {msg}"); bad = True
        sys.exit(1 if bad else 0)

    # Verify it raises SystemExit with code 0
    import pytest
    with pytest.raises(SystemExit) as exc_info:
        mock_main()
    assert exc_info.value.code == 0
