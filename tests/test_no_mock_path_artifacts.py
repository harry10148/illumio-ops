"""No test may leave a file named after a Mock in the repository root.

A test double whose `db_path` is a bare `MagicMock` stringifies to its repr, and
anything that opens `sqlite:///{db_path}` then creates a real 172KB database
called `<MagicMock name='mock.models.pce_cache.db_path' id='...'>` next to the
source. Three of them were nearly committed; they were caught only by reading
what `git add -A` had staged.

This is a guard rather than a fix because the writer is not one place: eleven
call sites open the cache engine from `cfg.db_path`, and any of them reached with
a Mock config produces the same litter. Naming the symptom catches whichever one
does it next, including one added later.

Deliberately not `tmp_path`-scoped: the point is the *repository*, which is where
the files landed and where they are dangerous.
"""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_no_mock_named_files_in_the_repo_root():
    litter = sorted(n for n in os.listdir(ROOT) if n.startswith("<") or "MagicMock" in n)
    assert not litter, (
        "a test opened a database using a Mock as its path and left these behind:\n  "
        + "\n  ".join(litter)
        + "\nFind the caller (grep for `_get_cache_engine(` / `sqlite:///`) and give "
          "that test a real tmp_path, or guard the opener against a non-existent file."
    )
