#!/usr/bin/env python3
"""Write THIRD_PARTY_NOTICES for the offline bundle (scripts/build_bundle.sh): the licence of everything the bundle
ships that illumio-ops did not write.

- every wheel in --wheels (the locked requirements): name, version, the licence its metadata declares
  (License-Expression, License, or the License :: classifiers) and every licence file the wheel carries;
- every production package of the web interface (package-lock.json entries not marked dev, read from
  <web>/node_modules), built into illumio_ops/web/static: its declared licence and its LICENSE/NOTICE files;
- each --extra NAME=FILE (the fonts' OFL, the bundled CPython's licence): the file as it is.

A package that declares no licence and carries no licence file stops the build (exit 1): a notice is never left out
silently. Standard library only (it runs with the build's Python before anything is installed).

usage: third_party_notices.py --wheels DIR --web DIR [--extra NAME=FILE ...] --title TEXT --out FILE
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from dataclasses import dataclass, field
from email.parser import HeaderParser
from pathlib import Path, PurePosixPath

LICENSE_STEMS = ("license", "licence", "copying", "notice", "authors")
RULE = "=" * 79
SUB = "-" * 79


@dataclass
class Notice:
    name: str
    version: str
    declared: str  # the licence as the package states it ("" when it states none)
    texts: list[tuple[str, str]] = field(default_factory=list)  # (file name, text)


class MissingLicense(Exception):
    pass


def _is_license_file(name: str) -> bool:
    stem = PurePosixPath(name).name.lower()
    return any(stem.startswith(s) for s in LICENSE_STEMS)


def _declared(meta: dict[str, list[str]]) -> str:
    if meta.get("license-expression"):
        return meta["license-expression"][0].strip()
    text = (meta.get("license") or [""])[0].strip()
    if text and "\n" not in text and len(text) <= 120:  # a name; a whole licence pasted here is shown as a text below
        return text
    classifiers = [c.split("::")[-1].strip() for c in meta.get("classifier", []) if c.startswith("License ::")]
    return ", ".join(classifiers)


def wheel_notice(path: Path) -> Notice:
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        meta_name = next((n for n in names if n.count("/") == 1 and n.endswith(".dist-info/METADATA")), None)
        if meta_name is None:
            raise MissingLicense(f"{path.name}: no .dist-info/METADATA")
        msg = HeaderParser().parsestr(zf.read(meta_name).decode("utf-8", errors="replace"))
        meta: dict[str, list[str]] = {}
        for key, value in msg.items():
            meta.setdefault(key.lower(), []).append(value)
        dist_info = meta_name.rsplit("/", 1)[0]
        texts = [(PurePosixPath(n).name, zf.read(n).decode("utf-8", errors="replace"))
                 for n in sorted(names) if n.startswith(dist_info + "/") and not n.endswith("/")
                 and _is_license_file(n)]
    notice = Notice(name=(meta.get("name") or [path.name])[0], version=(meta.get("version") or [""])[0],
                    declared=_declared(meta), texts=texts)
    long_license = (meta.get("license") or [""])[0].strip()
    if not texts and long_license and ("\n" in long_license or len(long_license) > 120):
        notice.texts.append(("METADATA License", long_license))
    if not notice.declared and not notice.texts:
        raise MissingLicense(f"{path.name}: declares no licence and carries no licence file")
    return notice


def web_notices(web: Path) -> list[Notice]:
    lock = json.loads((web / "package-lock.json").read_text(encoding="utf-8"))
    out = []
    for key, entry in sorted(lock.get("packages", {}).items()):
        if not key or entry.get("dev"):
            continue
        pkg_dir = web / key
        manifest = json.loads((pkg_dir / "package.json").read_text(encoding="utf-8"))
        lic = manifest.get("license") or entry.get("license") or ""
        declared = lic if isinstance(lic, str) else str(lic.get("type", "")) if isinstance(lic, dict) else ""
        texts = [(p.name, p.read_text(encoding="utf-8", errors="replace"))
                 for p in sorted(pkg_dir.iterdir()) if p.is_file() and _is_license_file(p.name)]
        name = key.removeprefix("node_modules/").replace("/node_modules/", " > ")
        if not declared and not texts:
            raise MissingLicense(f"{name}: declares no licence and carries no licence file")
        out.append(Notice(name=name, version=str(manifest.get("version") or entry.get("version") or ""),
                          declared=declared, texts=texts))
    return out


def _section(title: str, notices: list[Notice]) -> list[str]:
    lines = [RULE, title, RULE, ""]
    for n in notices:
        lines += [SUB, f"{n.name} {n.version}".rstrip(), f"License: {n.declared or 'see the text below'}", SUB]
        if not n.texts:
            lines.append("(the package carries no licence file; its declared licence is above)")
        for fname, text in n.texts:
            lines += [f"[{fname}]", text.rstrip(), ""]
        lines.append("")
    return lines


def render(title: str, wheels: list[Notice], web: list[Notice], extras: list[tuple[str, str]]) -> str:
    lines = [title, "", "This bundle includes the third-party software listed below, under the licences stated.", ""]
    lines += _section(f"Python packages ({len(wheels)}, in wheels/)", wheels)
    lines += _section(f"Web interface packages ({len(web)}, built into illumio_ops/web/static)", web)
    if extras:
        lines += [RULE, "Fonts and runtime", RULE, ""]
        for name, text in extras:
            lines += [SUB, name, SUB, text.rstrip(), "", ""]
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--wheels", type=Path, required=True)
    ap.add_argument("--web", type=Path, required=True)
    ap.add_argument("--extra", action="append", default=[], metavar="NAME=FILE")
    ap.add_argument("--title", default="THIRD-PARTY NOTICES")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        wheels = [wheel_notice(p) for p in sorted(args.wheels.glob("*.whl"))]
        if not wheels:
            raise MissingLicense(f"no wheels in {args.wheels}")
        web = web_notices(args.web)
        extras = []
        for spec in args.extra:
            name, sep, file = spec.partition("=")
            if not sep or not Path(file).is_file():
                raise MissingLicense(f"--extra {spec}: not NAME=FILE of an existing file")
            extras.append((name, Path(file).read_text(encoding="utf-8", errors="replace")))
    except MissingLicense as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1
    args.out.write_text(render(args.title, wheels, web, extras), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
