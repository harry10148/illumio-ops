"""The offline bundle ships THIRD_PARTY_NOTICES (parity 2026-11-06: 5.x and v6 shipped no third-party licence
notices): generated from the locked wheels' metadata, the web interface's production packages and the fonts' and
CPython's licence files by scripts/build_bundle.sh. The full bundle build is not run here."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BUILD = REPO / "scripts" / "build_bundle.sh"
_spec = importlib.util.spec_from_file_location("third_party_notices", REPO / "scripts" / "third_party_notices.py")
assert _spec is not None and _spec.loader is not None
tpn = importlib.util.module_from_spec(_spec)
sys.modules["third_party_notices"] = tpn  # dataclasses look their module up while the class is made
_spec.loader.exec_module(tpn)


def _wheel(d: Path, name: str, *, meta: str, files: dict[str, str] | None = None) -> None:
    info = f"{name}-1.0.dist-info"
    with zipfile.ZipFile(d / f"{name}-1.0-py3-none-any.whl", "w") as zf:
        zf.writestr(f"{name}/__init__.py", "")
        zf.writestr(f"{info}/METADATA", f"Metadata-Version: 2.4\nName: {name}\nVersion: 1.0\n{meta}\n")
        for fname, text in (files or {}).items():
            zf.writestr(f"{info}/{fname}", text)


def _web(d: Path, packages: dict[str, dict]) -> Path:
    web = d / "web"
    lock = {"packages": {"": {"name": "illumio-ops-web"}}}
    for name, spec in packages.items():
        lock["packages"][f"node_modules/{name}"] = {"version": "2.0.0", **({"dev": True} if spec.get("dev") else {})}
        pkg = web / "node_modules" / name
        pkg.mkdir(parents=True)
        manifest = {"name": name, "version": "2.0.0"} | ({"license": spec["license"]} if "license" in spec else {})
        (pkg / "package.json").write_text(json.dumps(manifest))
        for fname, text in spec.get("files", {}).items():
            (pkg / fname).write_text(text)
    (web / "package-lock.json").write_text(json.dumps(lock))
    return web


@pytest.fixture
def tree(tmp_path):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    _wheel(wheels, "alpha", meta="License-Expression: Apache-2.0", files={"licenses/LICENSE": "Apache text alpha"})
    _wheel(wheels, "beta", meta="Classifier: License :: OSI Approved :: MIT License")
    web = _web(tmp_path, {"react": {"license": "MIT", "files": {"LICENSE": "MIT text react"}},
                          "vite": {"license": "MIT", "dev": True, "files": {"LICENSE": "MIT text vite"}}})
    font = tmp_path / "OFL.txt"
    font.write_text("SIL OPEN FONT LICENSE Version 1.1")
    return tmp_path, wheels, web, font


def test_notices_list_every_wheel_and_production_web_package_with_their_texts(tree):
    tmp, wheels, web, font = tree
    out = tmp / "THIRD_PARTY_NOTICES"
    rc = tpn.main(["--wheels", str(wheels), "--web", str(web), "--extra", f"Montserrat font={font}",
                   "--title", "THIRD-PARTY NOTICES for illumio-ops 9.9.9", "--out", str(out)])
    text = out.read_text()
    assert rc == 0 and text.startswith("THIRD-PARTY NOTICES for illumio-ops 9.9.9")
    assert "alpha 1.0\nLicense: Apache-2.0" in text and "Apache text alpha" in text
    assert "beta 1.0\nLicense: MIT License" in text and "carries no licence file" in text  # said, not left out
    assert "react 2.0.0\nLicense: MIT" in text and "MIT text react" in text
    assert "vite" not in text  # a build tool, not shipped
    assert "Montserrat font" in text and "SIL OPEN FONT LICENSE" in text


def test_a_package_without_any_licence_stops_the_build(tree, capsys):
    tmp, wheels, web, _ = tree
    _wheel(wheels, "gamma", meta="Summary: nothing about a licence")
    assert tpn.main(["--wheels", str(wheels), "--web", str(web), "--out", str(tmp / "x")]) == 1
    assert "gamma" in capsys.readouterr().err and not (tmp / "x").exists()


def test_a_web_package_without_any_licence_stops_the_build(tmp_path, capsys):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    _wheel(wheels, "alpha", meta="License-Expression: MIT")
    web = _web(tmp_path, {"mystery": {}})
    assert tpn.main(["--wheels", str(wheels), "--web", str(web), "--out", str(tmp_path / "x")]) == 1
    assert "mystery" in capsys.readouterr().err


@pytest.mark.skipif(not (REPO / "web" / "node_modules" / "react").is_dir(), reason="web dependencies not installed")
def test_the_real_web_dependencies_all_state_a_licence():
    notices = tpn.web_notices(REPO / "web")
    names = {n.name for n in notices}
    assert {"react", "react-dom", "react-router-dom", "@fontsource-variable/jetbrains-mono"} <= names
    assert all(n.declared for n in notices) and all(n.texts for n in notices)
    assert not names & {"vite", "typescript"}


def test_the_bundle_build_writes_the_notices_into_the_bundle():
    script = BUILD.read_text()
    call = re.search(r'"\$PYTHON" -I scripts/third_party_notices\.py(.*?)--out "\$STAGE/THIRD_PARTY_NOTICES"',
                     script, re.DOTALL)
    assert call, "build_bundle.sh must generate $STAGE/THIRD_PARTY_NOTICES"
    args = call.group(1)
    assert '--wheels "$STAGE/wheels"' in args and "--web web" in args
    assert "web/src/styles/fonts/OFL-Montserrat.txt" in args and "$PY_LICENSE" in args
    assert (REPO / "web" / "src" / "styles" / "fonts" / "OFL-Montserrat.txt").is_file()
    # after the wheels are downloaded, before the archive is made
    assert script.index("pip download") < call.start() < script.index('tar --owner=0')
    assert "THIRD_PARTY_NOTICES" in script.split("set -euo pipefail")[0]  # listed in the bundle's layout
