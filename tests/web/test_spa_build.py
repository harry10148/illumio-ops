import re

from illumio_ops.web.app import DEFAULT_STATIC_DIR


def test_built_index_references_hashed_assets():
    index = DEFAULT_STATIC_DIR / "index.html"
    assert index.is_file(), "run the frontend build (see the plan's 前端建置 command) first"
    html = index.read_text(encoding="utf-8")
    scripts = re.findall(r'src="(/assets/[^"]+\.js)"', html)
    assert scripts, html[:200]
    for s in scripts:
        assert (DEFAULT_STATIC_DIR / s.lstrip("/")).is_file()
