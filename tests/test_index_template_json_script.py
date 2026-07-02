from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_translations_use_json_script_tag():
    template = (_ROOT / "src" / "templates" / "index.html").read_text()
    assert 'type="application/json"' in template or "type='application/json'" in template, \
        "index.html should embed translations via <script type=application/json>"
    # Task D1 (CSP hardening) externalized the inline bootstrap <script> that
    # used to call JSON.parse(...) directly in index.html into
    # static/js/_init_bootstrap.js (script-src no longer allows inline
    # scripts). The safety property — translations are read via JSON.parse,
    # never interpolated directly into a JS string literal — now lives there.
    bootstrap_js = (_ROOT / "src" / "static" / "js" / "_init_bootstrap.js").read_text()
    assert "JSON.parse" in bootstrap_js, \
        "_init_bootstrap.js should use JSON.parse(...) to read translations"
