"""Static guard: an area mount must register its S2 teardown before it awaits.

Task 12d F6 found the overview leaking two route-scoped palette commands into
every other area whenever its mount ended on the XC-10 error card: the commands
were registered synchronously, but the teardown that drops them again was
registered inside the render callback, which a failed mount never reaches.
A sweep for the same shape found it in nine more places (reports.mjs and all
eight system.mjs sub-routes), each with the same consequence for its own
registrations.

Nothing failed when this was wrong — the leak is only visible on a route the
operator has already left — so the shape needs a gate rather than a habit.

The rule this encodes, in the form the leak actually takes:

  in every file that defines installTeardown(), every `async function mount*`
  calls it, at the mount's own top level (two-space indentation), before that
  mount's first `await`.

"Before the first await" is the substantive half: after an await the mount may
already have lost the race to a newer navigation, and a failed load never gets
there at all. "At the top level" is what keeps it out of a render callback,
which is exactly where all ten instances had drifted to. investigate.mjs,
alerting.mjs and automation.mjs were already written this way and are what the
other three were brought in line with.

This reads the source as text on purpose: the thing under test is where a call
sits in the file, which no runtime assertion can see.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREAS = ROOT / "src" / "static" / "js" / "v2" / "areas"

MOUNT_RE = re.compile(r"^(?:export )?async function (mount\w*)\s*\(")
CALL_RE = re.compile(r"^(\s*)installTeardown\(")
AWAIT_RE = re.compile(r"\bawait\b")


def _area_files() -> list[Path]:
    """The area modules that own a teardown — the ones this rule is about."""
    files = [
        p for p in sorted(AREAS.glob("*.mjs"))
        if "function installTeardown(" in p.read_text(encoding="utf-8")
    ]
    assert files, f"no area module defines installTeardown() under {AREAS}"
    return files


def _is_comment(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*")


def _mounts(text: str) -> list[tuple[str, int, list[tuple[int, str]]]]:
    """[(mount_name, decl_line_no, [(line_no, line), ...]), ...].

    A top-level function ends at the first column-0 "}" — the whole v2
    frontend is written that way (no top-level indentation, no minification).
    """
    lines = text.splitlines()
    out: list[tuple[str, int, list[tuple[int, str]]]] = []
    i = 0
    while i < len(lines):
        m = MOUNT_RE.match(lines[i])
        if not m:
            i += 1
            continue
        body: list[tuple[int, str]] = []
        j = i + 1
        while j < len(lines) and not lines[j].startswith("}"):
            body.append((j + 1, lines[j]))
            j += 1
        out.append((m.group(1), i + 1, body))
        i = j + 1
    return out


def test_every_area_mount_registers_a_teardown():
    """A mount with no teardown at all leaks everything it registers."""
    missing = []
    for path in _area_files():
        text = path.read_text(encoding="utf-8")
        mounts = _mounts(text)
        assert mounts, f"{path.name}: no `async function mount*` found — has the file been restructured?"
        for name, decl, body in mounts:
            if not any(CALL_RE.match(line) for _, line in body):
                missing.append(f"{path.name}:{decl} {name}()")
    assert missing == [], (
        "these mounts register no teardown, so their palette commands / audit "
        f"openers outlive the area: {missing}"
    )


def test_teardown_is_registered_at_mount_top_level_before_the_first_await():
    problems = []
    for path in _area_files():
        text = path.read_text(encoding="utf-8")
        for name, decl, body in _mounts(text):
            calls = [(n, m.group(1)) for n, line in body
                     if (m := CALL_RE.match(line)) is not None]
            if not calls:
                continue  # the other test owns this case
            first_await = next(
                (n for n, line in body if not _is_comment(line) and AWAIT_RE.search(line)),
                None,
            )
            for lineno, indent in calls:
                where = f"{path.name}:{lineno} ({name})"
                if len(indent) != 2:
                    problems.append(
                        f"{where}: installTeardown() is nested {len(indent)} spaces deep — "
                        "it belongs at the mount's own top level, not inside a callback, "
                        "or a mount that never reaches that callback registers none"
                    )
                if first_await is not None and lineno > first_await:
                    problems.append(
                        f"{where}: installTeardown() runs after this mount's first await "
                        f"(line {first_await}) — a failed or superseded load never gets there"
                    )
    assert problems == [], "teardown registered too late:\n  " + "\n  ".join(problems)
