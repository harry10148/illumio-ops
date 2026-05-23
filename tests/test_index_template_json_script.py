from pathlib import Path


def test_translations_use_json_script_tag():
    template = (Path(__file__).resolve().parent.parent / "src" / "templates" / "index.html").read_text()
    assert 'type="application/json"' in template or "type='application/json'" in template, \
        "index.html should embed translations via <script type=application/json>"
    assert "JSON.parse" in template, \
        "index.html JS should use JSON.parse(...) to read translations"
